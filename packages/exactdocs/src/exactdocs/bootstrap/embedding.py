"""Glue between retrieval's AI providers and ingestion's ``embed`` jobs (RET-01).

Retrieval may not call ingestion (bridges point the other way), so the composition root queues
the embedding when something retrieval owns changes the embedding space.
"""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.bootstrap.cancellation import being_cancelled
from exactdocs.bootstrap.constants import (
    REQUEUE_JITTER_SECONDS,
    REQUEUE_LOCK_KEY,
    REQUEUE_TRY_LOCK,
    REQUEUE_UNLOCK,
    WINDOW_RESET_GRACE_SECONDS,
)
from exactdocs.bootstrap.database import is_postgres
from exactdocs.ingestion.dtos import QueueEmbeddingCommand
from exactdocs.ingestion.ports.driving import QueueEmbedding
from exactdocs.retrieval.dtos import ProviderOut, SaveProviderCommand
from exactdocs.retrieval.models import ModelRole, SpendWindow
from exactdocs.retrieval.ports.driving import SaveProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SaveProviderThenEmbed:
    """Implements retrieval's ``SaveProvider``, then queues the embedding when it may have to run.

    Saving the profile the embedding role points at (a new one, another kind, another endpoint)
    can make a new embedding space: every version not covered by it is queued at once, instead of
    at the next start or import. A profile no embedding role uses queues nothing.
    """

    save_provider: SaveProvider
    """Retrieval's use case."""
    queue_embedding: QueueEmbedding
    """Ingestion's: queues an ``embed`` job per version not fully embedded (none twice)."""

    async def __call__(self, command: SaveProviderCommand) -> ProviderOut:
        """Save the profile, then queue the embedding if the embedding role uses it.

        Args:
            command: The profile.

        Returns:
            The stored profile, as retrieval answered. A failure to queue is logged, never
            returned: the profile is saved, and the next start queues what is missing.
        """
        saved = await self.save_provider(command)
        if ModelRole.EMBEDDING in saved.roles:
            try:
                queued = await self.queue_embedding(QueueEmbeddingCommand())
            except Exception:
                logger.exception("could not queue the embedding after %s changed", saved.name)
            else:
                if queued.queued:
                    logger.info(
                        "AI provider %s changed: %d versions are being embedded again",
                        saved.name,
                        queued.queued,
                    )
        return saved


def seconds_to_next_window(now: datetime) -> float:
    """Count the seconds until just after the next UTC midnight, when spend windows reset.

    Args:
        now: An aware time.

    Returns:
        The wait, a little past midnight so the new window is surely the current one.
    """
    reset = SpendWindow.DAY.resets_at(now)
    return (reset - now).total_seconds() + WINDOW_RESET_GRACE_SECONDS


class LockSession(Protocol):
    """A database session that may hold the re-queue's lock."""

    async def holds_lock(self, *, held_before: bool) -> bool:
        """Take the lock if nobody holds it, and say whether this session holds it now.

        Args:
            held_before: This session held it at the last check.

        Returns:
            True when this session holds it, once.
        """
        ...

    async def close(self) -> None:
        """End the session; the database releases the lock with it."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresLockSession:
    """Implements ``LockSession`` with a PostgreSQL session advisory lock on one connection."""

    connection: AsyncConnection
    """The session; the lock lives and dies with it."""

    async def holds_lock(self, *, held_before: bool) -> bool:
        """Try the lock; for its holder the try succeeds again, so it is checked every night.

        A try that succeeds for a session that already held the lock takes it a second time:
        it is released once, so the session never holds it more than once.

        Args:
            held_before: This session held it at the last check.

        Returns:
            True when this session holds the lock.
        """
        key = {"key": REQUEUE_LOCK_KEY}
        held = bool((await self.connection.execute(text(REQUEUE_TRY_LOCK), key)).scalar())
        if held and held_before:
            await self.connection.execute(text(REQUEUE_UNLOCK), key)
        await self.connection.commit()  # the lock is the session's: no transaction stays open
        return held

    async def close(self) -> None:
        """Return the connection; PostgreSQL drops the lock if the session ends."""
        await self.connection.close()


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the open session
class RequeueLeader:
    """Whether this process leads the midnight re-queue, checked again every night.

    A session that failed (PostgreSQL restarted, a pooler or ``idle_session_timeout`` closed it)
    is dropped and a new one opened: the lock may have gone to another process meanwhile, so it
    is never assumed to be held.
    """

    open_session: Callable[[], Awaitable[LockSession]]
    """Opens a session (a connection) of its own."""
    session: LockSession | None = None
    """The session that holds, or tried, the lock."""
    leading: bool = False
    """The session held the lock at the last check."""

    async def leads(self) -> bool:
        """Check the lock, on the open session or, if it failed, on a new one.

        Returns:
            True when this process holds the lock now.
        """
        for attempt in range(2):
            try:
                if self.session is None:
                    self.session = await self.open_session()
                    self.leading = False
                self.leading = await self.session.holds_lock(held_before=self.leading)
            except Exception:
                await self.drop()
                if attempt:
                    raise
            else:
                return self.leading
        return False

    async def drop(self) -> None:
        """Close the session, whatever state it is in; the lock goes with it."""
        session, self.session, self.leading = self.session, None, False
        if session is not None:
            with suppress(Exception):
                await session.close()


async def requeue_daily(
    *,
    engine: AsyncEngine,
    queue: Callable[[], Awaitable[None]],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[], float] = lambda: secrets.SystemRandom().uniform(0, REQUEUE_JITTER_SECONDS),
) -> None:
    """Queue the missing embedding just after each UTC midnight, in one process only.

    On SQLite one process runs jobs, so it does. On PostgreSQL every server process runs this
    loop, but only the one holding a session advisory lock queues (``RequeueLeader``):
    ``EmbeddingQueue`` checks for a queued job and then inserts, so processes waking together
    would each queue every version. A random delay spreads the wake-ups.

    Args:
        engine: The database.
        queue: Queues the embedding of the versions not fully embedded.
        now: The current time (tests).
        sleep: Waits (tests).
        jitter: Seconds added after midnight (tests).
    """

    async def postgres_session() -> LockSession:
        """Open a connection of the re-queue's own.

        Returns:
            The session.
        """
        return PostgresLockSession(connection=await engine.connect())

    leader = None if not is_postgres(engine) else RequeueLeader(open_session=postgres_session)
    await requeue_nightly(leader=leader, queue=queue, now=now, sleep=sleep, jitter=jitter)


async def requeue_nightly(
    *,
    leader: RequeueLeader | None,
    queue: Callable[[], Awaitable[None]],
    now: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]],
    jitter: Callable[[], float],
) -> None:
    """Run the nights of the re-queue until cancelled; a failed night is logged, not fatal.

    Only cancellation ends it: an error (the database went away) would otherwise end the loop
    for good and be raised again when the server stops. An error that replaced the
    cancellation (raised while the cancelled night unwinds) ends it too (#308).

    Args:
        leader: Decides whether this process queues; ``None``: it always does (SQLite).
        queue: Queues the embedding of the versions not fully embedded.
        now: The current time.
        sleep: Waits.
        jitter: Seconds added after midnight.
    """
    try:
        while True:
            await sleep(seconds_to_next_window(now()) + jitter())
            try:
                if leader is None or await leader.leads():
                    await queue()
            except Exception:
                if being_cancelled():  # the error replaced the cancellation: the loop still ends
                    raise
                logger.exception(
                    "the midnight re-queue of embedding failed; it runs again tomorrow"
                )
    finally:
        if leader is not None:
            await leader.drop()
