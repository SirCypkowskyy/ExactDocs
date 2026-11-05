from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from exactdocs.identity.models import (
    FREE_FAILURES,
    REMEMBER_SIGN_INS_FOR,
    Account,
    AccountId,
    ApiToken,
    FailedSignIns,
    Session,
    Username,
)

# Enough for every address and username a busy instance sees in an hour, and small in memory
# (~200 bytes a record): a flood of made-up usernames cannot grow the log without bound.
MAX_FAILED_SIGN_IN_KEYS = 10_000


@dataclass(slots=True)
class InMemoryAccountRepository:
    """Implements ``ports.driven.AccountRepository``. For tests."""

    accounts: dict[Username, Account] = field(default_factory=dict)

    async def add_first(self, account: Account) -> bool:
        """Store the account only if no account exists yet."""
        if self.accounts:
            return False
        self.accounts[account.username] = account
        return True

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``."""
        return self.accounts.get(username)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``."""
        return next((a for a in self.accounts.values() if a.id == account_id), None)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash."""
        account = await self.get_by_id(account_id)
        if account is not None:
            self.accounts[account.username] = replace(account, password_hash=password_hash)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        return bool(self.accounts)


@dataclass(slots=True)
class InMemorySessionRepository:
    """Implements ``ports.driven.SessionRepository``. For tests."""

    sessions: dict[str, Session] = field(default_factory=dict)

    async def add(self, session: Session) -> None:
        """Store a new session."""
        self.sessions[session.token_hash] = session

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``."""
        return self.sessions.get(token_hash)

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``."""
        if (session := self.sessions.get(token_hash)) is not None:
            self.sessions[token_hash] = replace(session, last_used_at=at)

    async def delete(self, token_hash: str) -> None:
        """Remove the session."""
        self.sessions.pop(token_hash, None)

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account."""
        self.sessions = {h: s for h, s in self.sessions.items() if s.account_id != account_id}

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``."""
        self.sessions = {
            h: s
            for h, s in self.sessions.items()
            if s.last_used_at >= idle_before and s.created_at >= created_before
        }


@dataclass(slots=True)
class InMemoryTokenRepository:
    """Implements ``ports.driven.TokenRepository``. For tests."""

    tokens: dict[str, ApiToken] = field(default_factory=dict)

    async def add(self, token: ApiToken) -> None:
        """Store a new token."""
        self.tokens[token.token_hash] = token

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``."""
        return self.tokens.get(token_hash)

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first."""
        own = [t for t in self.tokens.values() if t.account_id == account_id]
        return sorted(own, key=lambda t: (t.created_at, t.id), reverse=True)

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``."""
        if (token := self.tokens.get(token_hash)) is not None:
            self.tokens[token_hash] = replace(token, last_used_at=at)

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none."""
        for token_hash, token in self.tokens.items():
            if token.id == token_id and token.account_id == account_id:
                del self.tokens[token_hash]
                return True
        return False

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account."""
        self.tokens = {h: t for h, t in self.tokens.items() if t.account_id != account_id}

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``."""
        self.tokens = {h: t for h, t in self.tokens.items() if not t.is_expired(now)}


@dataclass(slots=True)
class InMemoryFailedSignInLog:
    """Implements ``ports.driven.FailedSignInLog`` in the process's memory. Used in production.

    A restart forgets everything, and each process counts its own (TEAM-01 would share them).
    ``charge`` never awaits, so on one event loop the check and the count cannot interleave
    with another attempt's. At most ``max_keys`` counts and ``max_keys`` remembered sign-ins are
    kept. Dict order is "least recently changed first", which is also oldest ``last_at`` first.
    When full, the oldest count that does not hold anyone back (under ``FREE_FAILURES``, or
    forgotten) is dropped, and only when every count does, the oldest of all: a flood of
    made-up usernames then pushes out its own records, not a live throttle on a real one.
    """

    max_keys: int = MAX_FAILED_SIGN_IN_KEYS
    records: dict[str, FailedSignIns] = field(default_factory=dict)
    sign_ins: dict[str, datetime] = field(default_factory=dict)

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key unless one must wait; return the longest wait."""
        records = {key: self.records.get(key) for key in keys}
        wait = max((r.wait(now) for r in records.values() if r), default=timedelta(0))
        if wait > timedelta(0):
            return wait
        for key, record in records.items():
            self._put(key, record.plus_one(now) if record else FailedSignIns(count=1, last_at=now))
        return timedelta(0)

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at``; its place stays."""
        record = self.records.get(key)
        if record is None:
            return
        if (fewer := record.refunded(charged_at)) is None:
            del self.records[key]
        else:
            self.records[key] = fewer

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``."""
        return self.records.get(key)

    async def forget(self, key: str) -> None:
        """Drop the record under ``key``."""
        self.records.pop(key, None)

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Remember the sign-in as the most recent one, dropping the oldest when full."""
        self.sign_ins.pop(key, None)
        while len(self.sign_ins) >= self.max_keys:
            del self.sign_ins[next(iter(self.sign_ins))]
        self.sign_ins[key] = now

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR``."""
        last = self.sign_ins.get(key)
        return last is not None and now - last < REMEMBER_SIGN_INS_FOR

    def _put(self, key: str, failures: FailedSignIns) -> None:
        self.records.pop(key, None)  # re-inserted below as the most recent
        if len(self.records) >= self.max_keys:
            del self.records[self._least_needed(failures.last_at)]
        self.records[key] = failures

    def _least_needed(self, now: datetime) -> str:
        for key, record in self.records.items():
            if record.count < FREE_FAILURES or record.is_forgotten(now):
                return key
        return next(iter(self.records))
