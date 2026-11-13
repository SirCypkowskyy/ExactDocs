from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from exactdocs.identity.constants import (
    FREE_FAILURES,
    MAX_FAILED_SIGN_IN_KEYS,
    REMEMBER_SIGN_INS_FOR,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ApiToken,
    FailedSignIns,
    Session,
    Username,
    known_sign_ins_prefix,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryAccountRepository:
    """Implements ``ports.driven.AccountRepository``. For tests."""

    accounts: dict[Username, Account] = field(default_factory=dict)
    """The accounts, by username."""

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet.

        Args:
            account: The first account.

        Returns:
            ``True`` when it was stored, ``False`` when an account already exists.
        """
        if self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def add(self, account: Account) -> bool:
        """Store a further account, unless its username is taken.

        Args:
            account: The new account.

        Returns:
            ``True`` when it was stored, ``False`` when another account has the username.
        """
        if account.username in self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def list_all(self) -> list[Account]:
        """Return every account, oldest first (then by username).

        Returns:
            The accounts.
        """
        return sorted(self.accounts.values(), key=lambda a: (a.created_at, a.username.value))

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        """Disable or enable the account, never disabling the last enabled admin.

        Args:
            account_id: The account's id.
            disabled_at: When it was disabled, or ``None`` to enable it.

        Returns:
            ``False`` when disabling was refused to keep an enabled admin, else ``True``.
        """
        account = await self.get_by_id(account_id)
        if account is None:
            return True
        if disabled_at is not None and account.is_operator and not account.is_disabled:
            others = [
                a
                for a in self.accounts.values()
                if a.id != account_id and a.is_operator and not a.is_disabled
            ]
            if not others:
                return False
        self.accounts[account.username] = replace(account, disabled_at=disabled_at)
        return True

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``.

        Args:
            username: The normalized username.

        Returns:
            The account, or ``None``.
        """
        return self.accounts.get(username)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The account, or ``None``.
        """
        return next((a for a in self.accounts.values() if a.id == account_id), None)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash.

        Args:
            account_id: The account's id.
            password_hash: The new encoded hash.
        """
        account = await self.get_by_id(account_id)
        if account is not None:
            self.accounts[account.username] = replace(account, password_hash=password_hash)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists.

        Returns:
            ``True`` once an account exists.
        """
        return bool(self.accounts)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemorySessionRepository:
    """Implements ``ports.driven.SessionRepository``. For tests."""

    sessions: dict[str, Session] = field(default_factory=dict)
    """The sessions, by token hash."""

    async def add(self, session: Session) -> None:
        """Store a new session.

        Args:
            session: The session.
        """
        self.sessions[session.token_hash] = session

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``.

        Args:
            token_hash: The hash of the session token.

        Returns:
            The session, or ``None``.
        """
        return self.sessions.get(token_hash)

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``.

        Args:
            token_hash: The hash of the session token.
            at: When it was used.
        """
        if (session := self.sessions.get(token_hash)) is not None:
            self.sessions[token_hash] = replace(session, last_used_at=at)

    async def delete(self, token_hash: str) -> None:
        """Remove the session.

        Args:
            token_hash: The hash of the session token.
        """
        self.sessions.pop(token_hash, None)

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account.

        Args:
            account_id: The account's id.
        """
        for token_hash in [h for h, s in self.sessions.items() if s.account_id == account_id]:
            del self.sessions[token_hash]

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``.

        Args:
            idle_before: Idle deadline: sessions last used before it go.
            created_before: Absolute deadline: sessions created before it go.
        """
        for token_hash in [
            h
            for h, s in self.sessions.items()
            if s.last_used_at < idle_before or s.created_at < created_before
        ]:
            del self.sessions[token_hash]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryTokenRepository:
    """Implements ``ports.driven.TokenRepository``. For tests."""

    tokens: dict[str, ApiToken] = field(default_factory=dict)
    """The tokens, by the hash of their secret."""

    async def add(self, token: ApiToken) -> None:
        """Store a new token.

        Args:
            token: The token.
        """
        self.tokens[token.token_hash] = token

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``.

        Args:
            token_hash: The hash of the token's secret.

        Returns:
            The token, or ``None``.
        """
        return self.tokens.get(token_hash)

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first.

        Args:
            account_id: The account's id.

        Returns:
            The tokens, newest first.
        """
        own = [t for t in self.tokens.values() if t.account_id == account_id]
        return sorted(own, key=lambda t: (t.created_at, t.id), reverse=True)

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``.

        Args:
            token_hash: The hash of the token's secret.
            at: When it was used.
        """
        if (token := self.tokens.get(token_hash)) is not None:
            self.tokens[token_hash] = replace(token, last_used_at=at)

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none.

        Args:
            account_id: The owner's id.
            token_id: The token's id.

        Returns:
            ``True`` when a token was removed, ``False`` when the account has none by this id.
        """
        for token_hash, token in self.tokens.items():
            if token.id == token_id and token.account_id == account_id:
                del self.tokens[token_hash]
                return True
        return False

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account.

        Args:
            account_id: The account's id.
        """
        for token_hash in [h for h, t in self.tokens.items() if t.account_id == account_id]:
            del self.tokens[token_hash]

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``.

        Args:
            now: The current time.
        """
        for token_hash in [h for h, t in self.tokens.items() if t.is_expired(now)]:
            del self.tokens[token_hash]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryFailedSignInLog:
    """Implements ``ports.driven.FailedSignInLog`` in the process's memory. Used on SQLite.

    A restart forgets everything, and each process counts its own: on PostgreSQL, where several
    processes serve, ``SqliteFailedSignInLog`` shares the counts instead.
    ``charge`` never awaits, so on one event loop the check and the count cannot interleave
    with another attempt's. At most ``max_keys`` counts and ``max_keys`` remembered sign-ins are
    kept. Dict order is "least recently changed first", which is also oldest ``last_at`` first.
    When full, the oldest count that does not hold anyone back (under ``FREE_FAILURES``, or
    forgotten) is dropped, and only when every count does, the oldest of all: a flood of
    made-up usernames then pushes out its own records, not a live throttle on a real one.
    """

    max_keys: int = MAX_FAILED_SIGN_IN_KEYS
    """Most counts, and most remembered sign-ins, kept."""
    records: dict[str, FailedSignIns] = field(default_factory=dict)
    """The failure counts by throttle key, least recently changed first."""
    sign_ins: dict[str, datetime] = field(default_factory=dict)
    """When each sign-in key last succeeded, least recent first."""

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key unless one must wait; return the longest wait.

        Args:
            keys: The throttle keys of the attempt (its address and its username).
            now: When the attempt is made.

        Returns:
            The longest wait among the keys; zero when the attempt was counted and may go ahead.
        """
        records = {key: self.records.get(key) for key in keys}
        wait = max((r.wait(now) for r in records.values() if r), default=timedelta(0))
        if wait > timedelta(0):
            return wait
        for key, record in records.items():
            self._put(key, record.plus_one(now) if record else FailedSignIns(count=1, last_at=now))
        return timedelta(0)

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at``; its place stays.

        Args:
            key: The throttle key.
            charged_at: The ``now`` the attempt was charged with.
        """
        record = self.records.get(key)
        if record is None:
            return
        if (fewer := record.refunded(charged_at)) is None:
            del self.records[key]
        else:
            self.records[key] = fewer

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``.

        Args:
            key: The throttle key.

        Returns:
            The record, or ``None``.
        """
        return self.records.get(key)

    async def forget(self, key: str) -> bool:
        """Drop the record under ``key``.

        Args:
            key: The throttle key.

        Returns:
            Always ``True``: the process's memory is never busy.
        """
        self.records.pop(key, None)
        return True

    async def forget_remembered(self, username: str) -> bool:
        """Forget every address remembered for ``username``.

        Args:
            username: The username.

        Returns:
            Always ``True``: the process's memory is never busy.
        """
        prefix = known_sign_ins_prefix(username)
        for key in [k for k in self.sign_ins if k.startswith(prefix)]:
            del self.sign_ins[key]
        return True

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Remember the sign-in as the most recent one, dropping the oldest when full.

        Args:
            key: The sign-in key.
            now: When the sign-in succeeded.
        """
        self.sign_ins.pop(key, None)
        while len(self.sign_ins) >= self.max_keys:
            del self.sign_ins[next(iter(self.sign_ins))]
        self.sign_ins[key] = now

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR``.

        Args:
            key: The sign-in key.
            now: The current time.

        Returns:
            ``True`` when it did.
        """
        last = self.sign_ins.get(key)
        return last is not None and now - last < REMEMBER_SIGN_INS_FOR

    def _put(self, key: str, failures: FailedSignIns) -> None:
        """Store ``failures`` under ``key`` as the most recent record, making room when full.

        Args:
            key: The throttle key.
            failures: The new record.
        """
        self.records.pop(key, None)  # re-inserted below as the most recent
        if len(self.records) >= self.max_keys:
            del self.records[self._least_needed(failures.last_at)]
        self.records[key] = failures

    def _least_needed(self, now: datetime) -> str:
        """Pick the record to drop when the log is full.

        Args:
            now: The time of the attempt being stored.

        Returns:
            The key of the oldest record that holds no one back, else of the oldest record.
        """
        for key, record in self.records.items():
            if record.count < FREE_FAILURES or record.is_forgotten(now):
                return key
        return next(iter(self.records))
