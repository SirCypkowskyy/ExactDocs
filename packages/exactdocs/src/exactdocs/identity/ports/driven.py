"""Driven (secondary) ports: what identity needs from infrastructure."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from exactdocs.identity.models import (
    Account,
    AccountId,
    ApiToken,
    FailedSignIns,
    Session,
    Username,
)


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

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account."""
        ...

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``."""
        ...


class FailedSignInLog(Protocol):
    """The sign-in throttle's state: attempt counts, and which address signed into which username.

    Counts are keyed by client address (``address:...``) or ``username:...``. The log may forget
    a record at any time (e.g. to stay within a memory bound): that only makes the throttle more
    lenient, never refuses anyone.
    """

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key, unless one of them must still wait.

        The check and the count are one atomic step, so attempts made at the same time cannot
        all pass the check before any is counted. Returns the longest wait; when it is above zero
        nothing was counted.
        """
        ...

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at`` (a right password).

        If no later attempt was charged since, the record goes back to how it was before that
        attempt, so the wait is not restarted; otherwise only the count goes down.
        """
        ...

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``."""
        ...

    async def forget(self, key: str) -> bool:
        """Drop the record under ``key`` (nothing happens when there is none).

        Returns:
            ``True`` once no record is left under ``key`` (dropped, or there was none);
            ``False`` when the log was too busy to take the key's turn and skipped it.
        """
        ...

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Note that the sign-in ``key`` (a username at an address) just succeeded."""
        ...

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR`` of ``now``."""
        ...


class PasswordHasher(Protocol):
    """A memory-hard, salted password KDF. Hashes are self-describing strings."""

    async def hash(self, password: str) -> str:
        """Return the encoded hash of ``password`` (a fresh salt every call)."""
        ...

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches the hash, in constant time."""
        ...
