"""`SlowDatabase`: a stall always ends, and a task cancelled in one ends cancelled (#304)."""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from slow_database import MAX_STALL_SECONDS, SlowDatabase

STALL_SECONDS = 2.0
"""How long the held statement runs."""
CANCEL_AFTER_SECONDS = 0.2
"""When the task is cancelled: well inside the stall."""
SLACK_SECONDS = 3.0
"""Scheduling slack on top of the stall."""


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A SQLite engine with one table, disposed at the end.

    Args:
        tmp_path: The test's temporary directory.

    Yields:
        The engine; ``SlowDatabase.on`` must still be called before its first connection.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'slow.db'}")
    yield engine
    await engine.dispose()


async def test_a_transaction_cancelled_during_a_stalled_statement_ends_cancelled(
    engine: AsyncEngine,
) -> None:
    # The hang of #304: the cancellation invalidates the connection, the rollback that follows
    # ran the fixture's listener, and its `connection.info` raised PendingRollbackError in place
    # of the CancelledError. A `except Exception` above (the nightly upkeep) then swallowed the
    # cancellation, and the app's shutdown waited for that task until midnight.
    slow = SlowDatabase.on(engine)

    async def transaction() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE IF NOT EXISTS t (x INTEGER)"))
            slow.stall(STALL_SECONDS)
            await connection.execute(text("INSERT INTO t VALUES (1)"))

    task = asyncio.create_task(transaction())
    await asyncio.sleep(CANCEL_AFTER_SECONDS)
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=STALL_SECONDS + SLACK_SECONDS)

    assert done, "the cancelled transaction is still running"
    assert task.cancelled(), task.exception()


async def test_release_ends_a_stall_at_once(engine: AsyncEngine) -> None:
    slow = SlowDatabase.on(engine)
    slow.stall(STALL_SECONDS)

    slow.release()

    assert slow.remaining() == 0
    started = time.monotonic()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    assert time.monotonic() - started < STALL_SECONDS


def test_a_stall_is_bounded() -> None:
    slow = SlowDatabase()

    with pytest.raises(ValueError, match="at most"):
        slow.stall(MAX_STALL_SECONDS + 1)
