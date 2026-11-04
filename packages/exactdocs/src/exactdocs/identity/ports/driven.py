"""Driven (secondary) ports: what identity needs from infrastructure."""

from typing import Protocol

from exactdocs.identity.models import Account, Username


class AccountRepository(Protocol):
    """Persistence for accounts."""

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet; ``False`` when one already does.

        Must be atomic: two concurrent calls store at most one account.
        """
        ...

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``."""
        ...

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        ...


class PasswordHasher(Protocol):
    """A memory-hard, salted password KDF. Hashes are self-describing strings."""

    async def hash(self, password: str) -> str:
        """Return the encoded hash of ``password`` (a fresh salt every call)."""
        ...

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches the hash, in constant time."""
        ...
