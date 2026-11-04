"""Driven (secondary) ports: what identity needs from infrastructure."""

from datetime import datetime
from typing import Protocol

from exactdocs.identity.models import Account, AccountId, ApiToken, Session, Username


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

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``."""
        ...

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash."""
        ...

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        ...


class SessionRepository(Protocol):
    """Persistence for sessions, keyed by token hash."""

    async def add(self, session: Session) -> None:
        """Store a new session."""
        ...

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``."""
        ...

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``."""
        ...

    async def delete(self, token_hash: str) -> None:
        """Remove the session (nothing happens when it does not exist)."""
        ...

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account."""
        ...

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``."""
        ...


class TokenRepository(Protocol):
    """Persistence for API tokens, keyed by token hash."""

    async def add(self, token: ApiToken) -> None:
        """Store a new token."""
        ...

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``."""
        ...

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first."""
        ...

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``."""
        ...

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none."""
        ...


class PasswordHasher(Protocol):
    """A memory-hard, salted password KDF. Hashes are self-describing strings."""

    async def hash(self, password: str) -> str:
        """Return the encoded hash of ``password`` (a fresh salt every call)."""
        ...

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches the hash, in constant time."""
        ...
