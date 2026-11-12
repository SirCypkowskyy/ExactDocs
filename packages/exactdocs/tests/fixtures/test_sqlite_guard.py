"""`no_connection_left_open()`: a test that leaves a SQLite connection open fails itself (#300)."""

import os
import sqlite3
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import threading
from contextlib import ExitStack, closing
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import sqlite_guard
from sqlite_guard import is_open, no_connection_left_open

GUARD_DIR = Path(sqlite_guard.__file__).parent


@pytest.fixture
def short_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the leak tests fast: they wait the whole grace before failing."""
    monkeypatch.setattr(sqlite_guard, "CLOSE_GRACE", 0.5)


pytestmark = pytest.mark.usefixtures("short_grace")


def watching() -> ExitStack:
    """Enter a guard by hand, so the test can leak inside it and then check its exit alone.

    Returns:
        The entered guard; ``close()`` runs the check.
    """
    guard = ExitStack()
    guard.enter_context(no_connection_left_open())
    return guard


def test_closed_connections_pass(tmp_path: Path) -> None:
    with no_connection_left_open(), closing(sqlite3.connect(tmp_path / "a.db")) as connection:
        connection.execute("SELECT 1")


def test_a_connection_left_open_fails_naming_its_database(tmp_path: Path) -> None:
    guard = watching()
    leaked = sqlite3.connect(tmp_path / "leaked.db")

    with pytest.raises(AssertionError, match=r"(?s)1 SQLite connection.*leaked\.db"):
        guard.close()
    leaked.close()


def test_with_connect_does_not_close_and_is_caught(tmp_path: Path) -> None:
    guard = watching()
    with sqlite3.connect(tmp_path / "a.db") as connection:
        connection.execute("SELECT 1")

    with pytest.raises(AssertionError, match="still open"):
        guard.close()
    connection.close()


def test_a_connection_opened_by_another_thread_is_caught(tmp_path: Path) -> None:
    opened: list[sqlite3.Connection] = []
    worker = threading.Thread(
        target=lambda: opened.append(sqlite3.connect(tmp_path / "a.db", check_same_thread=False)),
        name="worker",
    )
    guard = watching()
    worker.start()
    worker.join()

    with pytest.raises(AssertionError, match="opened in thread worker"):
        guard.close()
    opened[0].close()


def test_a_connection_closed_by_another_thread_passes(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "a.db", check_same_thread=False)
    with no_connection_left_open():
        opened = sqlite3.connect(tmp_path / "b.db", check_same_thread=False)
        closer = threading.Thread(target=opened.close)
        closer.start()
        closer.join()

    assert not is_open(opened)
    connection.close()


def test_a_connection_another_thread_closes_shortly_after_the_block_passes(tmp_path: Path) -> None:
    """DBOS's executor thread closes its system-DB connection a moment after ``DBOS.destroy``."""
    with no_connection_left_open():
        opened = sqlite3.connect(tmp_path / "a.db", check_same_thread=False)
        closer = threading.Timer(0.05, opened.close)
        closer.start()
        assert is_open(opened)

    closer.join()
    assert not is_open(opened)


LEAK_THEN_COLLECT = """
import gc
import sqlite3

import pytest

from sqlite_guard import no_connection_left_open


@pytest.fixture(autouse=True)
def guard():
    with no_connection_left_open():
        yield


def test_a_leaks(tmp_path):
    sqlite3.connect(tmp_path / "leak.db")


def test_b_only_collects_garbage():
    gc.collect()
"""


def test_a_reported_leak_does_not_fail_a_later_test(tmp_path: Path) -> None:
    """The guard drops its references before raising, so the leak is finalized in its own test."""
    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\nfilterwarnings = error\npythonpath = {GUARD_DIR}\n"
    )
    (tmp_path / "test_leak.py").write_text(LEAK_THEN_COLLECT)

    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "test_leak.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert "test_a_leaks ERROR" in run.stdout, run.stdout
    assert "test_b_only_collects_garbage PASSED" in run.stdout, run.stdout


def test_connections_opened_before_the_block_are_not_its_own(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "a.db")) as before, no_connection_left_open():
        before.execute("SELECT 1")


async def test_an_engine_nobody_disposes_is_caught(tmp_path: Path) -> None:
    """The leak of #300: an aiosqlite connection back in the pool of an engine never disposed."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    guard = watching()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    with pytest.raises(AssertionError, match=r"a\.db"):
        guard.close()
    await engine.dispose()


async def test_a_disposed_engine_passes(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    with no_connection_left_open():
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await engine.dispose()
