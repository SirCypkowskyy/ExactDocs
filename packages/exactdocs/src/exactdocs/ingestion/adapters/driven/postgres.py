"""Ingestion's adapters that need PostgreSQL itself, beyond the portable SQL in ``sqlite.py``."""

import asyncio
import weakref
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.ingestion.constants._jobs import _LOCK_NAMESPACE

_lock = text("SELECT pg_advisory_lock(hashtextextended(:key, 0))")
_unlock = text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))")


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresLibraryLocks:
    """Implements ``ports.driven.LibraryLocks`` with a PostgreSQL advisory lock per library.

    Every process using the database waits for the same lock, so re-tags and an import's
    activation take turns across processes as ``TagLocks`` makes them within one. The lock is
    held by a connection of its own for as long as the work runs (the work uses others), and
    PostgreSQL releases it if that connection dies with its process. Waiters in this process
    queue on an ``asyncio.Lock`` first, so they do not each hold a connection while they wait.
    """

    engine: AsyncEngine
    """The PostgreSQL database the processes share."""
    purpose: str
    """What the locks order (``tags``, ``settings``): each purpose has its own keys."""
    _local: weakref.WeakValueDictionary[str, asyncio.Lock] = field(
        default_factory=weakref.WeakValueDictionary, init=False, repr=False
    )
    """This process's turn-taking before the database's, by library."""

    def of(self, library: str) -> AbstractAsyncContextManager[None]:
        """Return the lock of ``library`` (`/owner/repo`, any letter case).

        Args:
            library: The library's ID.

        Returns:
            An async context manager that holds the lock while it is entered.
        """
        return self._hold(library.lower())

    @asynccontextmanager
    async def _hold(self, library: str) -> AsyncGenerator[None]:
        """Hold this process's lock of the library, then the database's.

        Args:
            library: The library's ID, lower-case.

        Yields:
            Nothing, while both are held.
        """
        local = self._local.get(library)
        if local is None:
            local = self._local[library] = asyncio.Lock()
        key = {"key": _LOCK_NAMESPACE.format(purpose=self.purpose, library=library)}
        async with local, self.engine.connect() as connection:
            await connection.execute(_lock, key)
            await connection.commit()  # the lock is the session's: no transaction stays open
            try:
                yield
            finally:
                await connection.execute(_unlock, key)
                await connection.commit()
