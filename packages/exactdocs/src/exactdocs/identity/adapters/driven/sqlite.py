from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, MetaData, Table, Text, exists, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.identity.models import Account, AccountId, Role, Username

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
        if row is None:
            return None
        return Account(
            id=AccountId(row.id),
            username=Username(row.username),
            password_hash=row.password_hash,
            role=Role(row.role),
            created_at=datetime.fromisoformat(row.created_at),
        )

    async def any_exists(self) -> bool:
        """Return whether at least one account exists."""
        async with self.engine.connect() as connection:
            return bool((await connection.execute(select(exists(select(accounts.c.id))))).scalar())
