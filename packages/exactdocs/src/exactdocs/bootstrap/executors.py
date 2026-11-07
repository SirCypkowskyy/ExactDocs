"""Executor IDs for the server processes that share a PostgreSQL database.

DBOS records which executor runs each workflow and, when it starts, resumes the pending workflows
of its own executor ID. Processes sharing the database therefore need IDs that are unique among
the live ones, yet reused after a restart so that a crashed process's jobs resume. A slot is a
PostgreSQL advisory lock held by a connection for the process's lifetime: a process takes the
lowest free slot ``n`` and runs as ``exactdocs-<n>``; when it dies, its connection closes, the
lock is released, and the next process to start takes that slot and resumes its workflows. The
worker adopts the workflows of slots nobody took again (``orphaned``).
"""

from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.bootstrap.constants import EXECUTOR_LOCKS, EXECUTOR_PREFIX, MAX_EXECUTORS
from exactdocs.bootstrap.database import StartupError

_try_lock = text("SELECT pg_try_advisory_lock(:space, :slot)")
_unlock = text("SELECT pg_advisory_unlock(:space, :slot)")


def _slot(executor_id: str) -> int | None:
    """Return the slot an executor ID names, or ``None`` for an ID that is not a slot's.

    Args:
        executor_id: An ID DBOS recorded.

    Returns:
        The slot number.
    """
    number = executor_id.removeprefix(EXECUTOR_PREFIX)
    if number == executor_id or not number.isdigit() or int(number) >= MAX_EXECUTORS:
        return None
    return int(number)


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresExecutorSlots:
    """Implements the job worker's ``ExecutorSlots`` with PostgreSQL advisory locks."""

    engine: AsyncEngine
    """The database the processes share."""

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        """Hold the lowest free slot for as long as the context runs.

        Yields:
            This process's executor ID.

        Raises:
            StartupError: Every slot is taken.
        """
        async with self.engine.connect() as connection:
            for slot in range(MAX_EXECUTORS):
                if await self._try(connection, slot):
                    try:
                        yield f"{EXECUTOR_PREFIX}{slot}"
                    finally:
                        await connection.execute(_unlock, {"space": EXECUTOR_LOCKS, "slot": slot})
                        await connection.commit()
                    return
        message = f"{MAX_EXECUTORS} ExactDocs processes already use this database."
        raise StartupError(message)

    @asynccontextmanager
    async def orphaned(self, executor_ids: Collection[str]) -> AsyncGenerator[Collection[str]]:
        """Hold the slots of those executors that no live process holds, while the context runs.

        Args:
            executor_ids: Executors with pending workflows.

        Yields:
            The IDs of the dead ones; no process can take their slots meanwhile.
        """
        slots = sorted({s for s in map(_slot, executor_ids) if s is not None})
        async with self.engine.connect() as connection:
            held = [slot for slot in slots if await self._try(connection, slot)]
            try:
                yield [f"{EXECUTOR_PREFIX}{slot}" for slot in held]
            finally:
                for slot in held:
                    await connection.execute(_unlock, {"space": EXECUTOR_LOCKS, "slot": slot})
                await connection.commit()

    @staticmethod
    async def _try(connection: AsyncConnection, slot: int) -> bool:
        """Take the slot's lock if it is free (the session keeps it; no transaction stays open).

        Args:
            connection: The connection that will hold it.
            slot: The slot.

        Returns:
            Whether it was free.
        """
        taken = await connection.scalar(_try_lock, {"space": EXECUTOR_LOCKS, "slot": slot})
        await connection.commit()
        return bool(taken)
