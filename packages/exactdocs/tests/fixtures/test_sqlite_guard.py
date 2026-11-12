"""`no_connection_left_open()`: a test that leaves a SQLite connection open fails itself (#300)."""

import sqlite3
import threading
from contextlib import ExitStack, closing
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sqlite_guard import is_open, no_connection_left_open


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
