import asyncio
import logging
import weakref
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    exists,
    insert,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Row
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.identity.constants import (
    _LOCK_NOT_AVAILABLE,
    _SIGN_IN_LOCKS,
    FORGET_FAILURES_AFTER,
    FORGOTTEN_SIGN_INS_PER_TURN,
    MAX_CONCURRENT_SIGN_IN_TURNS,
    REMEMBER_SIGN_INS_FOR,
    SIGN_IN_TURN_TIMEOUT,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ApiToken,
    FailedSignIns,
    Role,
    Session,
    Username,
    known_sign_ins_prefix,
)

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
api_tokens = Table(
    "identity_api_tokens",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "account_id", Text, ForeignKey("identity_accounts.id", ondelete="CASCADE"), nullable=False
    ),
    Column("name", Text, nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("prefix", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # see `_stamp`
    Column("expires_at", Text),
    Column("last_used_at", Text),
)

failed_sign_ins = Table(
    "identity_failed_sign_ins",
    metadata,
    Column("key", Text, primary_key=True),  # `address:...` or `username:...`
    Column("failures", Integer, nullable=False),
    Column("last_at", Text, nullable=False),  # see `_stamp`
    Column("previous_at", Text),
)
known_sign_ins = Table(
    "identity_known_sign_ins",
    metadata,
    Column("key", Text, primary_key=True),  # `<username>@address:...`
    Column("signed_in_at", Text, nullable=False),  # see `_stamp`
)
# One statement takes every key's lock, in the order of the lock ids (not of the keys: two keys
# whose `hashtext` collides share an id, and key order could then cross another attempt's).
# PostgreSQL evaluates a volatile function in the select list after the sort.
_lock_keys = text(
    "SELECT pg_advisory_xact_lock(:space, h) "
    "FROM (SELECT DISTINCT hashtext(k) AS h FROM unnest(CAST(:keys AS text[])) AS k) AS locks "
    "ORDER BY h"
)


def _stamp(moment: datetime) -> str:
    """UTC ISO 8601 with a fixed width, so comparing the text compares the instants.

    Args:
        moment: A timezone-aware time.

    Returns:
        The time as stored, e.g. ``2026-01-02T03:04:05.000000+00:00``.
    """
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteAccountRepository:
    """Implements ``ports.driven.AccountRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine
    """The database engine."""

    async def add_first(self, account: Account) -> bool:
        """Store the account only if the table is empty, in one statement under a write lock.

        Args:
            account: The first account.

        Returns:
            ``True`` when it was stored, ``False`` when an account already exists.
        """
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
        # preserve_rowcount: an INSERT's rowcount is only kept on request (psycopg reports -1).
        statement = (
            insert(accounts)
            .from_select(list(values), guarded)
            .execution_options(preserve_rowcount=True)
        )
        # BEGIN IMMEDIATE: a concurrent writer waits, then sees the row and inserts nothing.
        async with self.engine.connect() as connection:
            await connection.execution_options(begin_immediate=True)
            async with connection.begin():
                result = await connection.execute(statement)
        return result.rowcount == 1

    async def get(self, username: Username) -> Account | None:
        """Return the account with this username, or ``None``.

        Args:
            username: The normalized username.

        Returns:
            The account, or ``None``.
        """
        query = select(accounts).where(accounts.c.username == username.value)
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _account(row)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        """Return the account with this id, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The account, or ``None``.
        """
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(accounts).where(accounts.c.id == account_id))
            ).first()
        return None if row is None else _account(row)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        """Replace the account's password hash.

        Args:
            account_id: The account's id.
            password_hash: The new encoded hash.
        """
        statement = (
            update(accounts).where(accounts.c.id == account_id).values(password_hash=password_hash)
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def any_exists(self) -> bool:
        """Return whether at least one account exists.

        Returns:
            ``True`` once an account exists.
        """
        async with self.engine.connect() as connection:
            return bool((await connection.execute(select(exists(select(accounts.c.id))))).scalar())


def _account(row: Row[Any]) -> Account:
    """Map an ``accounts`` row to its entity.

    Args:
        row: The row.

    Returns:
        The account.
    """
    return Account(
        id=AccountId(row.id),
        username=Username(row.username),
        password_hash=row.password_hash,
        role=Role(row.role),
        created_at=datetime.fromisoformat(row.created_at),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteSessionRepository:
    """Implements ``ports.driven.SessionRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine
    """The database engine."""

    async def add(self, session: Session) -> None:
        """Store a new session.

        Args:
            session: The session.
        """
        values = {
            "token_hash": session.token_hash,
            "account_id": session.account_id,
            "created_at": _stamp(session.created_at),
            "last_used_at": _stamp(session.last_used_at),
        }
        async with self.engine.begin() as connection:
            await connection.execute(insert(sessions).values(values))

    async def get(self, token_hash: str) -> Session | None:
        """Return the session with this token hash, or ``None``.

        Args:
            token_hash: The hash of the session token.

        Returns:
            The session, or ``None``.
        """
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
        """Record that the session was used at ``at``.

        Args:
            token_hash: The hash of the session token.
            at: When it was used.
        """
        statement = (
            update(sessions)
            .where(sessions.c.token_hash == token_hash)
            .values(last_used_at=_stamp(at))
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def delete(self, token_hash: str) -> None:
        """Remove the session.

        Args:
            token_hash: The hash of the session token.
        """
        async with self.engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.token_hash == token_hash))

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every session of the account.

        Args:
            account_id: The account's id.
        """
        async with self.engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.account_id == account_id))

    async def delete_expired(self, *, idle_before: datetime, created_before: datetime) -> None:
        """Remove sessions last used before ``idle_before`` or created before ``created_before``.

        Args:
            idle_before: Idle deadline: sessions last used before it go.
            created_before: Absolute deadline: sessions created before it go.
        """
        statement = delete(sessions).where(
            or_(
                sessions.c.last_used_at < _stamp(idle_before),
                sessions.c.created_at < _stamp(created_before),
            )
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)


def _moment(value: str | None) -> datetime | None:
    """Read an optional stored time.

    Args:
        value: The stored ISO 8601 text, or ``None``.

    Returns:
        The time, or ``None``.
    """
    return None if value is None else datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteTokenRepository:
    """Implements ``ports.driven.TokenRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine
    """The database engine."""

    async def add(self, token: ApiToken) -> None:
        """Store a new token.

        Args:
            token: The token.
        """
        values = {
            "id": token.id,
            "account_id": token.account_id,
            "name": token.name,
            "token_hash": token.token_hash,
            "prefix": token.prefix,
            "created_at": _stamp(token.created_at),
            "expires_at": None if token.expires_at is None else _stamp(token.expires_at),
            "last_used_at": None if token.last_used_at is None else _stamp(token.last_used_at),
        }
        async with self.engine.begin() as connection:
            await connection.execute(insert(api_tokens).values(values))

    async def get(self, token_hash: str) -> ApiToken | None:
        """Return the token with this hash, or ``None``.

        Args:
            token_hash: The hash of the token's secret.

        Returns:
            The token, or ``None``.
        """
        query = select(api_tokens).where(api_tokens.c.token_hash == token_hash)
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _token(row)

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        """Return the account's tokens, newest first.

        Args:
            account_id: The account's id.

        Returns:
            The tokens, newest first.
        """
        query = (
            select(api_tokens)
            .where(api_tokens.c.account_id == account_id)
            .order_by(api_tokens.c.created_at.desc(), api_tokens.c.id.desc())
        )
        async with self.engine.connect() as connection:
            return [_token(row) for row in await connection.execute(query)]

    async def touch(self, token_hash: str, at: datetime) -> None:
        """Record that the token was used at ``at``.

        Args:
            token_hash: The hash of the token's secret.
            at: When it was used.
        """
        statement = (
            update(api_tokens)
            .where(api_tokens.c.token_hash == token_hash)
            .values(last_used_at=_stamp(at))
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        """Remove the account's token with this id; ``False`` when there is none.

        Args:
            account_id: The owner's id.
            token_id: The token's id.

        Returns:
            ``True`` when a token was removed, ``False`` when the account has none by this id.
        """
        statement = delete(api_tokens).where(
            api_tokens.c.id == token_id, api_tokens.c.account_id == account_id
        )
        async with self.engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount == 1

    async def delete_for_account(self, account_id: AccountId) -> None:
        """Remove every token of the account.

        Args:
            account_id: The account's id.
        """
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(api_tokens).where(api_tokens.c.account_id == account_id)
            )

    async def delete_expired(self, now: datetime) -> None:
        """Remove the tokens whose expiry is at or before ``now``.

        Args:
            now: The current time.
        """
        statement = delete(api_tokens).where(api_tokens.c.expires_at <= _stamp(now))
        async with self.engine.begin() as connection:
            await connection.execute(statement)


def _token(row: Row[Any]) -> ApiToken:
    """Map an ``api_tokens`` row to its entity.

    Args:
        row: The row.

    Returns:
        The token.
    """
    return ApiToken(
        id=row.id,
        account_id=AccountId(row.account_id),
        name=row.name,
        token_hash=row.token_hash,
        prefix=row.prefix,
        created_at=datetime.fromisoformat(row.created_at),
        expires_at=_moment(row.expires_at),
        last_used_at=_moment(row.last_used_at),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteFailedSignInLog:
    """Implements ``ports.driven.FailedSignInLog`` in the database, for every process at once.

    Used on PostgreSQL, where several processes serve one instance and must share the counts
    (on SQLite one process serves, and ``InMemoryFailedSignInLog`` is enough). Each
    read-then-write is one transaction that first takes its turn on the keys it touches: on
    PostgreSQL a transaction-level advisory lock per key (``_SIGN_IN_LOCKS``, taken in key order
    so two attempts cannot deadlock), on SQLite ``BEGIN IMMEDIATE``. Attempts on other keys do
    not wait, nor do the instance's other writers (it does not take their write turn).

    Before taking a connection, an attempt first waits its turn in the process: one
    ``asyncio.Lock`` per key, then one of ``max_concurrent`` slots. So a flood of attempts on one
    username holds one connection per process, not the whole pool, and the instance's other
    readers are not held up. Each wait (in the process, then PostgreSQL's ``lock_timeout``) lasts
    at most ``turn_timeout``. When it runs out, ``charge`` fails closed: the attempt is refused
    with ``turn_timeout`` as its wait and nothing is counted. ``refund``, ``forget`` and
    ``remember_sign_in`` only make the throttle more lenient, so they are skipped (and logged).
    ``forget_remembered`` makes it stricter, but runs after a password reset that is already
    done: it stops there too, and returns ``False`` so the reset can say so. It takes its keys'
    turns ``forgotten_per_turn`` at a time, so a username with many remembered addresses does not
    fill PostgreSQL's lock table in one transaction.

    Old rows are pruned when one is written, without a background job: a charge deletes the
    counts with no failure for ``FORGET_FAILURES_AFTER`` (they no longer hold anyone back), a
    remembered sign-in those older than ``REMEMBER_SIGN_INS_FOR``. On PostgreSQL the prune skips
    rows another attempt has locked, so it never waits for, nor deadlocks with, that attempt.
    """

    engine: AsyncEngine
    """The database every process of the instance uses."""
    max_concurrent: int = MAX_CONCURRENT_SIGN_IN_TURNS
    """Turns one process runs at once, each holding a connection."""
    turn_timeout: timedelta = SIGN_IN_TURN_TIMEOUT
    """Longest wait for a turn, in the process and then in the database."""
    forgotten_per_turn: int = FORGOTTEN_SIGN_INS_PER_TURN
    """Remembered sign-ins ``forget_remembered`` deletes in one turn."""
    _queues: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _TurnQueue] = field(
        default_factory=weakref.WeakKeyDictionary, init=False, repr=False
    )
    """One queue per event loop: asyncio's locks bind to the first loop they wait on, and the log
    may outlive a loop (tests, CLI), as the hasher's semaphores do."""

    async def charge(self, keys: Sequence[str], now: datetime) -> timedelta:
        """Count one attempt against every key unless one must wait; return the longest wait.

        Args:
            keys: The throttle keys the attempt counts against.
            now: When the attempt is made.

        Returns:
            The longest wait among the keys; when above zero nothing was counted.
        """
        if not keys:  # no address and no valid username: nothing to count against
            return timedelta(0)
        try:
            async with self._turn(keys) as connection:
                return await self._charge(connection, keys, now)
        except _TurnTimeoutError:
            return self.turn_timeout  # fail closed: refused, and nothing counted

    async def refund(self, key: str, charged_at: datetime) -> None:
        """Take back the attempt charged under ``key`` at ``charged_at``.

        Args:
            key: The throttle key.
            charged_at: When the attempt to take back was charged.
        """
        try:
            async with self._turn([key]) as connection:
                await self._refund(connection, key, charged_at)
        except _TurnTimeoutError:
            logger.warning("Sign-in throttle busy: an attempt was not refunded")

    async def get(self, key: str) -> FailedSignIns | None:
        """Return the record under ``key``, or ``None``.

        Args:
            key: The throttle key.

        Returns:
            The record, or ``None`` when there is none.
        """
        async with self.engine.connect() as connection:
            return (await self._records(connection, [key])).get(key)

    async def forget(self, key: str) -> bool:
        """Drop the record under ``key``.

        Args:
            key: The throttle key.

        Returns:
            ``True`` once no record is left (dropped, or there was none); ``False`` when the
            key's turn did not come within ``turn_timeout`` and the record was left as it was.
        """
        try:
            # In the key's turn: a charge reading the count meanwhile would write it back after.
            async with self._turn([key]) as connection:
                await connection.execute(
                    delete(failed_sign_ins).where(failed_sign_ins.c.key == key)
                )
        except _TurnTimeoutError:
            logger.warning("Sign-in throttle busy: a username's count was not reset")
            return False
        return True

    async def forget_remembered(self, username: str) -> bool:
        """Forget every address remembered for ``username``, in the turn of each one.

        The keys are read first, then deleted in key order, ``forgotten_per_turn`` at a time: each
        batch takes its keys' turns at once (as ``charge`` takes its keys') and deletes exactly
        those rows, so a ``remember_sign_in`` holding one of them finishes first and is deleted
        after. A sign-in remembered for a new address after the read stays: normally one made with
        the new password, as the reset set it before; one that checked the old password just
        before the reset and is still in flight could stay too, as the session it is about to
        start would.

        Args:
            username: The (normalised) username.

        Returns:
            ``True`` once none is left (dropped, or there was none); ``False`` when a batch's turn
            did not come within ``turn_timeout``. The batches before it stay forgotten, that one
            and the rest are kept, and running it again carries on.
        """
        prefix = known_sign_ins_prefix(username)
        query = select(known_sign_ins.c.key).where(
            known_sign_ins.c.key.startswith(prefix, autoescape=True)
        )
        async with self.engine.connect() as connection:
            keys = sorted((await connection.execute(query)).scalars())
        for start in range(0, len(keys), self.forgotten_per_turn):
            batch = keys[start : start + self.forgotten_per_turn]
            try:
                async with self._turn([f"known:{key}" for key in batch]) as connection:
                    await connection.execute(
                        delete(known_sign_ins).where(known_sign_ins.c.key.in_(batch))
                    )
            except _TurnTimeoutError:
                logger.warning("Sign-in throttle busy: a username's remembered sign-ins were kept")
                return False
        return True

    async def remember_sign_in(self, key: str, now: datetime) -> None:
        """Remember the sign-in at ``now``, pruning those too old to count.

        Args:
            key: The sign-in (a username at an address).
            now: When it succeeded.
        """
        try:
            async with self._turn([f"known:{key}"]) as connection:
                await connection.execute(delete(known_sign_ins).where(known_sign_ins.c.key == key))
                await connection.execute(
                    insert(known_sign_ins).values(key=key, signed_in_at=_stamp(now))
                )
                await _prune(connection, known_sign_ins.c.signed_in_at, now - REMEMBER_SIGN_INS_FOR)
        except _TurnTimeoutError:
            logger.warning("Sign-in throttle busy: a sign-in was not remembered")

    async def signed_in_before(self, key: str, now: datetime) -> bool:
        """Whether ``key`` succeeded within ``REMEMBER_SIGN_INS_FOR`` of ``now``.

        Args:
            key: The sign-in (a username at an address).
            now: The moment to look back from.

        Returns:
            ``True`` when it did.
        """
        query = select(known_sign_ins.c.signed_in_at).where(known_sign_ins.c.key == key)
        async with self.engine.connect() as connection:
            last = (await connection.execute(query)).scalar()
        return last is not None and now - datetime.fromisoformat(last) < REMEMBER_SIGN_INS_FOR

    async def _charge(
        self, connection: AsyncConnection, keys: Sequence[str], now: datetime
    ) -> timedelta:
        """``charge``'s read-then-write, in the transaction holding the turn on ``keys``.

        Args:
            connection: The connection, in that transaction.
            keys: The throttle keys the attempt counts against.
            now: When the attempt is made.

        Returns:
            The longest wait among the keys; when above zero nothing was counted.
        """
        records = await self._records(connection, keys)
        wait = max((r.wait(now) for r in records.values()), default=timedelta(0))
        if wait > timedelta(0):
            return wait
        counted = {
            key: (
                records[key].plus_one(now)
                if key in records
                else FailedSignIns(count=1, last_at=now)
            )
            for key in dict.fromkeys(keys)
        }
        await self._replace(connection, counted)
        await _prune(connection, failed_sign_ins.c.last_at, now - FORGET_FAILURES_AFTER)
        return timedelta(0)

    async def _refund(self, connection: AsyncConnection, key: str, charged_at: datetime) -> None:
        """``refund``'s read-then-write, in the transaction holding the turn on ``key``.

        Args:
            connection: The connection, in that transaction.
            key: The throttle key.
            charged_at: When the attempt to take back was charged.
        """
        record = (await self._records(connection, [key])).get(key)
        if record is None:
            return
        if (fewer := record.refunded(charged_at)) is None:
            await connection.execute(delete(failed_sign_ins).where(failed_sign_ins.c.key == key))
        else:
            await self._replace(connection, {key: fewer})

    @asynccontextmanager
    async def _turn(self, keys: Iterable[str]) -> AsyncGenerator[AsyncConnection]:
        """Begin a transaction that holds the turn on ``keys`` until it ends.

        Args:
            keys: What the transaction reads and then writes.

        Yields:
            The connection, in its transaction.

        Raises:
            _TurnTimeoutError: The turn did not come within ``turn_timeout``.
        """
        ordered = sorted(set(keys))
        queue = self._queue()
        async with AsyncExitStack() as held:
            try:
                async with asyncio.timeout(self.turn_timeout.total_seconds()):
                    for key in ordered:  # in key order, so two attempts cannot deadlock here
                        await held.enter_async_context(queue.lock(key))
                    await held.enter_async_context(queue.connections)
            except TimeoutError as error:
                raise _TurnTimeoutError from error
            async with self.engine.connect() as connection:
                postgres = connection.dialect.name == "postgresql"
                if not postgres:
                    await connection.execution_options(begin_immediate=True)
                async with connection.begin():
                    if postgres:
                        await self._lock(connection, ordered)
                    yield connection

    def _queue(self) -> _TurnQueue:
        """Return this event loop's queue, making it on first use.

        Returns:
            The queue.
        """
        loop = asyncio.get_running_loop()
        queue = self._queues.get(loop)
        if queue is None:
            queue = self._queues[loop] = _TurnQueue(
                connections=asyncio.Semaphore(self.max_concurrent)
            )
        return queue

    async def _lock(self, connection: AsyncConnection, keys: list[str]) -> None:
        """Take the PostgreSQL advisory lock of every key, waiting at most ``turn_timeout``.

        Args:
            connection: The connection, in the transaction the locks last for.
            keys: The throttle keys.

        Raises:
            _TurnTimeoutError: Another process held a lock for longer.
            OperationalError: The database failed for another reason.
        """
        milliseconds = int(self.turn_timeout.total_seconds() * 1000)
        await connection.execute(text(f"SET LOCAL lock_timeout = {milliseconds}"))
        try:
            await connection.execute(_lock_keys, {"space": _SIGN_IN_LOCKS, "keys": keys})
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            raise _TurnTimeoutError from error

    @staticmethod
    async def _records(
        connection: AsyncConnection, keys: Iterable[str]
    ) -> dict[str, FailedSignIns]:
        """Read the records under ``keys``.

        Args:
            connection: The connection to read with.
            keys: The throttle keys.

        Returns:
            The records found, by key.
        """
        query = select(failed_sign_ins).where(failed_sign_ins.c.key.in_(list(keys)))
        return {
            row.key: FailedSignIns(
                count=row.failures,
                last_at=datetime.fromisoformat(row.last_at),
                previous_at=_moment(row.previous_at),
            )
            for row in await connection.execute(query)
        }

    @staticmethod
    async def _replace(connection: AsyncConnection, records: dict[str, FailedSignIns]) -> None:
        """Store ``records`` in place of what their keys held.

        The caller holds the turn on those keys, so nobody else writes them meanwhile.

        Args:
            connection: The connection, in the transaction holding the turn.
            records: The records to store, by key.
        """
        await connection.execute(delete(failed_sign_ins).where(failed_sign_ins.c.key.in_(records)))
        await connection.execute(
            insert(failed_sign_ins),
            [
                {
                    "key": key,
                    "failures": record.count,
                    "last_at": _stamp(record.last_at),
                    "previous_at": None
                    if record.previous_at is None
                    else _stamp(record.previous_at),
                }
                for key, record in records.items()
            ],
        )


class _TurnTimeoutError(Exception):
    """A sign-in attempt waited ``turn_timeout`` for its turn on its keys without getting it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _TurnQueue:
    """Where one process's sign-in attempts wait for their turn before taking a connection."""

    connections: asyncio.Semaphore
    """Turns that may hold a connection at once."""
    keys: weakref.WeakValueDictionary[str, asyncio.Lock] = field(
        default_factory=weakref.WeakValueDictionary
    )
    """One lock per key, dropped once no attempt holds or awaits it."""

    def lock(self, key: str) -> asyncio.Lock:
        """Return the key's lock, making it if no attempt holds it.

        Args:
            key: The throttle key.

        Returns:
            The lock.
        """
        lock = self.keys.get(key)
        if lock is None:
            lock = self.keys[key] = asyncio.Lock()
        return lock


async def _prune(connection: AsyncConnection, moment: Column[str], before: datetime) -> None:
    """Delete the rows of ``moment``'s table whose ``moment`` is at or before ``before``.

    On PostgreSQL rows another transaction has locked are skipped (``SKIP LOCKED``), so the prune
    never waits: that transaction is writing them anyway. SQLite has no row locks (and renders no
    ``FOR UPDATE``); its writers take turns.

    Args:
        connection: The connection, in the writing transaction.
        moment: The time column the rows are aged by (its table has a ``key`` primary key).
        before: The oldest moment kept is just after this.
    """
    table = moment.table
    stale = select(table.c.key).where(moment <= _stamp(before)).with_for_update(skip_locked=True)
    await connection.execute(delete(table).where(table.c.key.in_(stale)))


logger = logging.getLogger(__name__)
