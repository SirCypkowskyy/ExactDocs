"""SQL driven adapter of the usage domain: the daily counts (SQLite, libSQL and PostgreSQL)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Column, Index, Integer, MetaData, Table, Text, delete, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.usage.constants import COUNTS_PER_WRITE
from exactdocs.usage.models import Dimension, Operation, UsageKey, UsageSelection, UsageSum

metadata = MetaData()
daily_counts = Table(
    "usage_daily_counts",
    metadata,
    Column("day", Text, primary_key=True),  # the UTC day, ISO `YYYY-MM-DD`
    Column("account_id", Text, primary_key=True),  # `NO_ACCOUNT` ("") for no person
    Column("token_id", Text, primary_key=True),  # `NO_TOKEN` ("") for a session
    Column("library", Text, primary_key=True),  # lower-case; `NO_LIBRARY` ("") for several
    Column("operation", Text, primary_key=True),  # read, search, answer
    Column("requests", Integer, nullable=False),
    Index("ix_usage_daily_counts_account_day", "account_id", "day"),
)
key_columns = ("day", "account_id", "token_id", "library", "operation")  # the primary key


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteUsageCounts:
    """Implements ``ports.driven.UsageCounts`` (SQLite, libSQL and PostgreSQL).

    One row per day, account, token, library and operation, holding how many requests it
    counts: never a query, a path or any text of the docs.
    """

    engine: AsyncEngine
    """The database engine."""

    async def add(self, counts: Mapping[UsageKey, int]) -> None:
        """Add counts to the stored ones in one transaction (an upsert per counter).

        The counters are written in key order, so two processes adding to the same ones on
        PostgreSQL take their row locks in the same order and never deadlock.

        Args:
            counts: How many to add to each counter.
        """
        rows = sorted(
            (
                {
                    "day": key.day.isoformat(),
                    "account_id": key.account,
                    "token_id": key.token,
                    "library": key.library,
                    "operation": key.operation.value,
                    "requests": count,
                }
                for key, count in counts.items()
                if count
            ),
            key=lambda row: tuple(row[column] for column in key_columns),
        )
        if not rows:
            return
        async with self.engine.begin() as connection:
            insert = _conflict_insert(connection)
            statement = insert.on_conflict_do_update(
                index_elements=[daily_counts.c[column] for column in key_columns],
                set_={"requests": daily_counts.c.requests + insert.excluded.requests},
            )
            for start in range(0, len(rows), COUNTS_PER_WRITE):
                await connection.execute(statement, rows[start : start + COUNTS_PER_WRITE])

    async def sums(self, selection: UsageSelection) -> Sequence[UsageSum]:
        """Sum the stored counts of a range of days by the selected columns, in SQL.

        Args:
            selection: The days, the columns to sum by and the filters.

        Returns:
            One sum per distinct value of the selected columns that has counts.
        """
        grouped = [_column(dimension) for dimension in Dimension if dimension in selection.by]
        total = func.sum(daily_counts.c.requests).label("total")
        query = select(*grouped, total).where(
            daily_counts.c.day >= selection.first.isoformat(),
            daily_counts.c.day <= selection.last.isoformat(),
        )
        if selection.account is not None:
            query = query.where(daily_counts.c.account_id == selection.account)
        if selection.library is not None:
            query = query.where(daily_counts.c.library == selection.library)
        if selection.operation is not None:
            query = query.where(daily_counts.c.operation == selection.operation.value)
        if grouped:
            query = query.group_by(*grouped)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        found = []
        for row in rows:
            operation = row.get("operation")
            if not row["total"] or (operation is not None and operation not in Operation):
                continue  # nothing counted, or an operation a newer release counts
            found.append(
                UsageSum(
                    count=int(row["total"]),
                    day=None if row.get("day") is None else date.fromisoformat(row["day"]),
                    account=row.get("account_id"),
                    token=row.get("token_id"),
                    library=row.get("library"),
                    operation=None if operation is None else Operation(operation),
                )
            )
        return found

    async def prune(self, before: date) -> int:
        """Delete every count of a day before the given one.

        Args:
            before: The first day kept.

        Returns:
            How many counters were deleted.
        """
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(daily_counts).where(daily_counts.c.day < before.isoformat())
            )
        return result.rowcount or 0


def _column(dimension: Dimension) -> Column[Any]:
    """Return the column a dimension sums by.

    Args:
        dimension: The dimension.

    Returns:
        Its column.
    """
    match dimension:
        case Dimension.DAY:
            return daily_counts.c.day
        case Dimension.ACCOUNT:
            return daily_counts.c.account_id
        case Dimension.CREDENTIAL:
            return daily_counts.c.token_id
        case Dimension.LIBRARY:
            return daily_counts.c.library
        case Dimension.OPERATION:
            return daily_counts.c.operation


def _conflict_insert(connection: AsyncConnection) -> sqlite.Insert | postgresql.Insert:
    """Return an ``INSERT`` into the counts that takes ``ON CONFLICT``, in the database's dialect.

    Args:
        connection: Where the statement runs (SQLite, libSQL or PostgreSQL).

    Returns:
        The statement; both dialects spell ``on_conflict_do_update`` alike.
    """
    if connection.dialect.name == "postgresql":
        return postgres_insert(daily_counts)
    return sqlite_insert(daily_counts)
