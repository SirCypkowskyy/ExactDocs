from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    Table,
    Text,
    delete,
    exists,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.identity.models import Account, AccountId, Role, Session, Username

# The identity tables, prefixed `identity_`. The schema itself is created by an Alembic revision
# in `exactdocs.bootstrap`; this is only the adapter's query-side description of it.
metadata = MetaData()
accounts = Table(
    "identity_accounts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # ISO 8601 with offset
)
sessions = Table(
    "identity_sessions",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column(
        "account_id", Text, ForeignKey("identity_accounts.id", ondelete="CASCADE"), nullable=False
    ),
    Column("created_at", Text, nullable=False),  # see `_stamp`
    Column("last_used_at", Text, nullable=False),
)


def _stamp(moment: datetime) -> str:
    """UTC ISO 8601 with a fixed width, so comparing the text compares the instants."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class SqliteAccountRepository:
    """Implements ``ports.driven.AccountRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    async def add_first(self, account: Account) -> bool:
        """Store the account only if the table is empty, in one statement under a write lock."""
        values = {
            "id": account.id,
            "username": account.username.value,
            "password_hash": account.password_hash,
            "role": account.role.value,
            "created_at": account.created_at.isoformat(),
        }
        guarded = select(*(literal(v) for v in values.values())).where(
            ~exists(select(accounts.c.id))
        )
        statement = insert(accounts).from_select(list(values), guarded)
        # BEGIN IMMEDIATE: a concurrent writer waits, then sees the row and inserts nothing.
        async with self.engine.connect() as connection:
            await connection.execution_options(begin_immediate=True)
            async with connection.begin():
                result = await connection.execute(statement)
        return result.rowcount == 1

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``."""
        query = select(accounts).where(accounts.c.username == username.value)
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _account(row)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``."""
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(accounts).where(accounts.c.id == account_id))
            ).first()
        return None if row is None else _account(row)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash."""
        statement = (
            update(accounts).where(accounts.c.id == account_id).values(password_hash=password_hash)
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        async with self.engine.connect() as connection:
            return bool((await connection.execute(select(exists(select(accounts.c.id))))).scalar())


def _account(row: Row[Any]) -> Account:
    return Account(
        id=AccountId(row.id),
        username=Username(row.username),
        password_hash=row.password_hash,
        role=Role(row.role),
        created_at=datetime.fromisoformat(row.created_at),
    )


@dataclass(frozen=True, slots=True)
class SqliteSessionRepository:
    """Implements ``ports.driven.SessionRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    async def add(self, session: Session) -> None:
        """Store a new session."""
        values = {
            "token_hash": session.token_hash,
            "account_id": session.account_id,
            "created_at": _stamp(session.created_at),
            "last_used_at": _stamp(session.last_used_at),
        }
        async with self.engine.begin() as connection:
            await connection.execute(insert(sessions).values(values))

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``."""
        query = select(sessions).where(sessions.c.token_hash == token_hash)
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        if row is None:
            return None
        return Session(
            token_hash=row.token_hash,
            account_id=AccountId(row.account_id),
            created_at=datetime.fromisoformat(row.created_at),
            last_used_at=datetime.fromisoformat(row.last_used_at),
        )

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the session was used at ``at``."""
        statement = (
            update(sessions)
            .where(sessions.c.token_hash == token_hash)
            .values(last_used_at=_stamp(at))
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def delete(self, token_hash: str) -> None:
        """Remove the session."""
        async with self.engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account."""
        async with self.engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.account_id == account_id))

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``."""
        statement = delete(sessions).where(
            or_(
                sessions.c.last_used_at < _stamp(idle_before),
                sessions.c.created_at < _stamp(created_before),
            )
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)
