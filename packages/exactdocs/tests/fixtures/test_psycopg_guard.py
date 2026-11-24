"""`no_psycopg_connection_left_open()`: a test leaving a psycopg connection open fails (#333)."""

import gc
import threading
import traceback
import warnings
from collections.abc import Iterator
from contextlib import ExitStack

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

import integration
import psycopg_guard
from databases import PostgresDatabase, postgres_database
from psycopg_guard import _pick, no_psycopg_connection_left_open

pytestmark = [
    integration.POSTGRES,
    pytest.mark.usefixtures("short_grace"),
]


@pytest.fixture
def short_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the leak tests fast: they wait the whole grace before failing."""
    monkeypatch.setattr(psycopg_guard, "CLOSE_GRACE", 0.5)


@pytest.fixture
def database() -> Iterator[PostgresDatabase]:
    """A throwaway database, created and dropped outside the guard under test.

    Yields:
        The database.
    """
    with postgres_database() as created:
        yield created


def plain(database: PostgresDatabase) -> str:
    """Return the database's URL as libpq takes it."""
    return database.url.replace("postgresql+psycopg://", "postgresql://")


def watching() -> ExitStack:
    """Enter a guard by hand, so the test can leak inside it and then check its exit alone.

    Returns:
        The entered guard; ``close()`` runs the check.
    """
    guard = ExitStack()
    guard.enter_context(no_psycopg_connection_left_open())
    return guard


def test_closed_connections_pass(database: PostgresDatabase) -> None:
    with no_psycopg_connection_left_open(), psycopg.connect(plain(database)) as connection:
        connection.execute("SELECT 1")


def test_a_connection_left_open_fails_naming_its_database_and_where(
    database: PostgresDatabase,
) -> None:
    guard = watching()
    leaked = psycopg.connect(plain(database))

    with pytest.raises(
        AssertionError,
        match=rf"(?s)1 psycopg connection.*{database.name}.*"
        r"at .*test_psycopg_guard\.py:\d+ in test_a_connection_left_open",
    ):
        guard.close()
    leaked.close()


def test_a_connection_opened_by_another_thread_is_caught(database: PostgresDatabase) -> None:
    opened: list[psycopg.Connection] = []
    worker = threading.Thread(
        target=lambda: opened.append(psycopg.connect(plain(database))), name="worker"
    )
    guard = watching()
    worker.start()
    worker.join()

    with pytest.raises(AssertionError, match="opened in thread worker"):
        guard.close()
    opened[0].close()


def test_an_undisposed_sync_engine_is_caught(database: PostgresDatabase) -> None:
    guard = watching()
    engine = create_engine(database.url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    with pytest.raises(AssertionError, match="still open"):
        guard.close()
    engine.dispose()


async def test_an_undisposed_async_engine_is_caught(database: PostgresDatabase) -> None:
    guard = watching()
    engine = create_async_engine(database.url)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    with pytest.raises(AssertionError, match="still open"):
        guard.close()
    await engine.dispose()


def test_a_disposed_engine_passes(database: PostgresDatabase) -> None:
    with no_psycopg_connection_left_open():
        engine = create_engine(database.url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()


def test_a_connection_closed_during_the_grace_passes(database: PostgresDatabase) -> None:
    guard = watching()
    connection = psycopg.connect(plain(database))
    threading.Timer(0.1, connection.close).start()

    guard.close()

    assert connection.closed


def test_a_connection_opened_before_the_block_is_not_its_business(
    database: PostgresDatabase,
) -> None:
    with psycopg.connect(plain(database)) as before, no_psycopg_connection_left_open():
        before.execute("SELECT 1")


def test_a_failing_guard_leaves_no_warning_for_the_next_test(database: PostgresDatabase) -> None:
    held = {"record": None}  # like a pool record: keeps the leaked connection alive past the guard
    guard = watching()
    held["record"] = psycopg.connect(plain(database))

    with pytest.raises(AssertionError, match="still open"):
        guard.close()

    assert held["record"].closed
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        held.clear()  # what the next test's garbage collection would finalize
        gc.collect()
    assert not [each for each in caught if issubclass(each.category, ResourceWarning)]


async def test_a_failing_guard_closes_a_leaked_async_connection(database: PostgresDatabase) -> None:
    guard = watching()
    leaked = await psycopg.AsyncConnection.connect(plain(database))

    with pytest.raises(AssertionError, match="still open"):
        guard.close()

    assert leaked.closed


def frame(filename: str, name: str) -> traceback.FrameSummary:
    return traceback.FrameSummary(filename, 1, name, lookup_line=False)


def test_a_connection_a_library_thread_opened_names_the_library() -> None:
    site = "/venv/lib/python3.14/site-packages"
    stack = [
        frame("/usr/lib/python3.14/threading.py", "run"),
        frame(f"{site}/dbos/_scheduler.py", "dynamic_scheduler_loop"),
        frame(f"{site}/dbos/_sys_db.py", "get_workflows"),
        frame(f"{site}/sqlalchemy/engine/base.py", "connect"),
        frame(f"{site}/psycopg/connection.py", "connect"),
    ]

    assert _pick(stack) == (
        "dbos/_scheduler.py:1 in dynamic_scheduler_loop",
        "dbos/_sys_db.py:1 in get_workflows",
    )


def test_the_repository_frames_win_over_library_frames() -> None:
    site = "/venv/lib/python3.14/site-packages"
    stack = [frame(__file__, "open_it"), frame(f"{site}/dbos/_sys_db.py", "get_workflows")]

    assert _pick(stack) == ("packages/exactdocs/tests/fixtures/test_psycopg_guard.py:1 in open_it",)
