from dataclasses import dataclass, field, replace
from datetime import datetime

from exactdocs.identity.models import Account, AccountId, ApiToken, Session, Username


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
