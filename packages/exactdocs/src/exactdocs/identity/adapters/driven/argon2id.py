import asyncio
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError

MAX_CONCURRENT_HASHES = 4


class Kdf(Protocol):
    """The part of argon2-cffi's ``PasswordHasher`` used here (blocking calls)."""

    def hash(self, password: str, /) -> str:
        """Return the encoded hash."""
        ...

    def verify(self, encoded: str, password: str, /) -> bool:
        """Return ``True`` or raise ``VerificationError``."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Argon2idPasswordHasher:
    """Implements ``ports.driven.PasswordHasher`` with argon2id (argon2-cffi's defaults).

    The defaults are the RFC 9106 low-memory profile: 64 MiB, 3 passes, 4 lanes, random 16-byte
    salt. ``verify`` compares in constant time inside the library. The work runs in a thread so
    the event loop keeps serving while a hash is computed.

    At most ``max_concurrent`` hashes run at once (each takes 64 MiB and a core); more calls
    wait their turn, so a burst of sign-ins cannot exhaust the memory or the CPU.
    """

    argon2: Kdf = field(default_factory=Argon2)
    max_concurrent: int = MAX_CONCURRENT_HASHES
    # One semaphore per event loop: an asyncio.Semaphore binds to the first loop it waits on, so
    # a single one would fail when the hasher is reused across ``asyncio.run`` calls (tests, CLI).
    _slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = field(
        default_factory=weakref.WeakKeyDictionary, init=False, repr=False
    )

    async def hash(self, password: str) -> str:
        """Return the encoded argon2id hash (parameters and salt included)."""
        return await self._run(self.argon2.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches; a corrupt stored hash never matches."""
        try:
            return await self._run(self.argon2.verify, password_hash, password)
        except VerificationError, InvalidHashError:
            return False

    async def _run[T](self, work: Callable[..., T], *args: str) -> T:
        """Run ``work`` in a thread once a slot is free.

        Shielded: a cancelled caller (a dropped connection) returns at once, but its slot stays
        taken until the thread is done, so the bound holds for the threads, not just the callers.
        """
        loop = asyncio.get_running_loop()
        slots = self._slots.get(loop)
        if slots is None:
            slots = self._slots[loop] = asyncio.Semaphore(self.max_concurrent)

        async def in_a_slot() -> T:
            async with slots:
                return await asyncio.to_thread(work, *args)

        return await asyncio.shield(asyncio.ensure_future(in_a_slot()))
