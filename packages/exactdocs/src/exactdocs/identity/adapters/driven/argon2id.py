import asyncio
from dataclasses import dataclass, field

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError


@dataclass(frozen=True, slots=True)
class Argon2idPasswordHasher:
    """Implements ``ports.driven.PasswordHasher`` with argon2id (argon2-cffi's defaults).

    The defaults are the RFC 9106 low-memory profile: 64 MiB, 3 passes, 4 lanes, random 16-byte
    salt. ``verify`` compares in constant time inside the library. The work runs in a thread so
    the event loop keeps serving while a hash is computed.
    """

    argon2: Argon2 = field(default_factory=Argon2)

    async def hash(self, password: str) -> str:
        """Return the encoded argon2id hash (parameters and salt included)."""
        return await asyncio.to_thread(self.argon2.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches; a corrupt stored hash never matches."""
        try:
            return await asyncio.to_thread(self.argon2.verify, password_hash, password)
        except VerificationError, InvalidHashError:
            return False
