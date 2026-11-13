"""`no_psycopg_connection_left_open()`: a test leaving a psycopg connection open fails (#333)."""

import threading
from collections.abc import Iterator
from contextlib import ExitStack

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

import psycopg_guard
from databases import ADMIN_URL, PostgresDatabase, postgres_database
from psycopg_guard import no_psycopg_connection_left_open

pytestmark = [
    pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL"),
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
