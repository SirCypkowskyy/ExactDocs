"""Executor IDs for the server processes that share a PostgreSQL database.

DBOS records which executor runs each workflow and, when it starts, resumes the pending workflows
of its own executor ID. Processes sharing the database therefore need IDs that are unique among
the live ones, yet reused after a restart so that a crashed process's jobs resume. A slot is a
PostgreSQL advisory lock held by a connection for the process's lifetime: a process takes the
lowest free slot ``n`` and runs as ``exactdocs-<n>``; when it dies, its connection closes, the
lock is released, and the next process to start takes that slot and resumes its workflows. The
worker adopts the workflows of slots nobody took again (``orphaned``).
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

from sqlalchemy import NullPool, column, literal, select, table, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from exactdocs.bootstrap.constants import (
    EXECUTOR_LOCKS,
    EXECUTOR_PREFIX,
    MAX_EXECUTORS,
    SLOT_KEEPALIVES,
)
from exactdocs.bootstrap.database import StartupError
from exactdocs.ingestion.adapters.driving.dbos_worker import SlotState

log = logging.getLogger(__name__)

_try_lock = text("SELECT pg_try_advisory_lock(:space, :slot)")
_unlock = text("SELECT pg_advisory_unlock(:space, :slot)")
_holds = text(
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :space"
    " AND objid = :slot AND objsubid = 2 AND pid = pg_backend_pid() AND granted"
)


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


async def _release(connection: AsyncConnection, slot: int) -> None:
    """Unlock the slot and close the connection; a dead connection has released it already.

    Args:
        connection: The connection that holds the slot.
        slot: The slot.
    """
    with suppress(SQLAlchemyError, OSError):
        await connection.execute(_unlock, {"space": EXECUTOR_LOCKS, "slot": slot})
        await connection.commit()
    with suppress(SQLAlchemyError, OSError):
        await connection.close()


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresExecutorSlots:
    """Implements the job worker's ``ExecutorSlots`` with PostgreSQL advisory locks.

    The slot is held by a connection of its own (not the app's pool), with TCP keepalives so
    that a NAT or a load balancer does not drop it while it idles. The worker asks ``keep`` every
    few seconds whether it still holds it: a connection can die while the process lives (a
    server restart, a failover, ``idle_session_timeout``), and PostgreSQL then frees the slot.
    """

    engine: AsyncEngine
    """The database the processes share."""
    schema: str = "dbos"
    """DBOS's schema: ``claim`` looks there for the pending workflows of the slot it takes."""
    check_timeout: float = 1.5
    """Bound on one whole ``keep`` (both its round trips): the worker's ``slot_check_timeout``."""
    claim_grace: float = 15.0
    """How long ``claim`` waits before it returns a slot whose executor left pending workflows:
    a process that lost the slot but still runs them notices within this time and stops."""
    _held: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    """The slot held now, its connection and the engine that connection comes from."""

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        """Hold the lowest free slot for as long as the context runs.

        Yields:
            This process's executor ID.

        Raises:
            StartupError: Every slot is taken.
        """
        engine = create_async_engine(
            self.engine.url, poolclass=NullPool, connect_args=dict(SLOT_KEEPALIVES)
        )
        try:
            connection = await engine.connect()
            slot = None
            for candidate in range(MAX_EXECUTORS):
                if await self._try(connection, candidate):
                    slot = candidate
                    break
            if slot is None:
                await connection.close()
                message = f"{MAX_EXECUTORS} ExactDocs processes already use this database."
                raise StartupError(message)
            self._held.update(slot=slot, connection=connection, engine=engine)
            executor_id = f"{EXECUTOR_PREFIX}{slot}"
            try:
                if await self._left_work(executor_id):
                    log.warning(
                        "executor slot %s left pending jobs: waiting %.0f s before taking it"
                        " over, so a process that lost it can stop first",
                        executor_id,
                        self.claim_grace,
                    )
                    await asyncio.sleep(self.claim_grace)
                yield executor_id
            finally:
                held = self._held.pop("connection", connection)
                self._held.clear()
                if isinstance(held, AsyncConnection):
                    await _release(held, slot)
        finally:
            await engine.dispose()

    async def keep(self) -> SlotState:
        """Check that this process still holds its slot; take it again if it was freed.

        The whole check is bounded by ``check_timeout``: a connection to a host that no longer
        answers (a failover) must not hold the worker past its give-up time.

        Returns:
            ``held``; ``retaken`` when the slot was lost and taken again (the worker then checks
            nobody adopted its jobs meanwhile); ``lost`` when another process holds it now;
            ``unknown`` when the database cannot be reached to tell.
        """
        slot, connection, engine = (
            self._held.get("slot"),
            self._held.get("connection"),
            self._held.get("engine"),
        )
        if not isinstance(slot, int) or not isinstance(engine, AsyncEngine):
            return SlotState.LOST
        deadline = asyncio.get_running_loop().time() + self.check_timeout
        if isinstance(connection, AsyncConnection):
            try:
                async with asyncio.timeout_at(deadline):
                    held = await connection.scalar(_holds, {"space": EXECUTOR_LOCKS, "slot": slot})
                    await connection.commit()
            except DBAPIError, OSError, TimeoutError:
                held = None
            if held:
                return SlotState.HELD
            self._held.pop("connection", None)
            with suppress(SQLAlchemyError, OSError):
                await connection.invalidate()
        # Another process's `orphaned()` may hold this free slot for a moment while it lists
        # workflows; a retake that meets it reports `lost` and this process stops, though
        # nobody adopted anything. That errs on the safe side and is left as it is.
        try:
            async with asyncio.timeout_at(deadline):
                fresh = await engine.connect()
                taken = await self._try(fresh, slot)
        except DBAPIError, OSError, TimeoutError:
            log.warning("cannot reach the database to check executor slot %d", slot)
            return SlotState.UNKNOWN
        if not taken:
            with suppress(SQLAlchemyError, OSError):
                await fresh.close()
            return SlotState.LOST
        self._held["connection"] = fresh
        log.warning("executor slot %d was lost and is held again", slot)
        return SlotState.RETAKEN

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

    async def _left_work(self, executor_id: str) -> bool:
        """Tell whether the executor has pending workflows (``False`` before DBOS's tables exist).

        Args:
            executor_id: The executor whose slot was just taken.

        Returns:
            Whether a process that held the slot may still be running them.
        """
        statuses = table(
            "workflow_status", column("executor_id"), column("status"), schema=self.schema
        )
        query = (
            select(literal(1))
            .select_from(statuses)
            .where(statuses.c.executor_id == executor_id, statuses.c.status == "PENDING")
            .limit(1)
        )
        name = f'"{self.schema}".workflow_status'
        async with self.engine.connect() as connection:
            if await connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is None:
                return False  # the first start: DBOS has not created its tables yet
            return await connection.scalar(query) is not None

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
