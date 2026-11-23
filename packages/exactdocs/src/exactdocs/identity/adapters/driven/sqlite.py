import asyncio
import json
import logging
import weakref
from collections.abc import AsyncGenerator, Collection, Iterable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Column,
    Delete,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.identity.constants import (
    _LOCK_NOT_AVAILABLE,
    _SIGN_IN_LOCKS,
    FORGET_FAILURES_AFTER,
    FORGOTTEN_SIGN_INS_PER_TURN,
    MAX_CONCURRENT_SIGN_IN_TURNS,
    REMEMBER_SIGN_INS_FOR,
    SIGN_IN_TURN_TIMEOUT,
    TEXT_SCALES,
)
from exactdocs.identity.models import (
    AccessChange,
    AccessEvent,
    AccessLogFilter,
    Account,
    AccountId,
    ApiToken,
    Contrast,
    ExternalIdentity,
    FailedSignIns,
    Font,
    Language,
    LibraryGrant,
    LibraryRole,
    Motion,
    Preferences,
    Role,
    Session,
    SignInAttempt,
    SubjectKind,
    TextSpacing,
    Theme,
    Username,
    known_sign_ins_prefix,
)
from exactdocs.identity.ports.driven import LinkOutcome

# The identity tables, prefixed `identity_`. The schema itself is created by an Alembic revision
# in `exactdocs.bootstrap`; this is only the adapter's query-side description of it.
metadata = MetaData()
accounts = Table(
    "identity_accounts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text),  # NULL for an account of an identity provider
    Column("role", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # ISO 8601 with offset
    Column("disabled_at", Text),  # see `_stamp`; NULL while the account may sign in
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
    Column("library_ids", Text),
)

failed_sign_ins = Table(
    "identity_failed_sign_ins",
    metadata,
    Column("key", Text, primary_key=True),  # `address:...` or `username:...`
    Column("failures", Integer, nullable=False),
    Column("last_at", Text, nullable=False),  # see `_stamp`
    Column("previous_at", Text),
)
external_identities = Table(
    "identity_external_identities",
    metadata,
    Column("issuer", Text, primary_key=True),
    Column("subject", Text, primary_key=True),
    Column(
        "account_id",
        Text,
        ForeignKey("identity_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("provider", Text, nullable=False),
    Column("sealed_tokens", Text),  # the refresh token, sealed; NULL when there is none
    Column("signed_in_at", Text, nullable=False),  # see `_stamp`
    Column("checked_at", Text, nullable=False),
    Column("next_check_at", Text, nullable=False),
    Column("access_until", Text, nullable=False),
)
account_groups = Table(
    "identity_account_groups",
    metadata,
    Column(
        "account_id",
        Text,
        ForeignKey("identity_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("name", Text, primary_key=True),
)
library_grants = Table(
    "identity_library_grants",
    metadata,
    Column("library", Text, primary_key=True),  # `/owner/repo`, lower-case
    Column("kind", Text, primary_key=True),  # `user` or `group`
    Column("subject", Text, primary_key=True),  # an account ID, or a group name
    Column("role", Text, nullable=False),
)
sign_in_attempts = Table(
    "identity_sign_in_attempts",
    metadata,
    Column("binding_hash", Text, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("nonce", Text, nullable=False),
    Column("code_verifier", Text, nullable=False),
    Column("return_to", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # see `_stamp`
)
access_events = Table(
    "identity_access_events",
    metadata,
    Column("id", Text, primary_key=True),  # a UUIDv7: sorts in the order of recording
    Column("library", Text, nullable=False),  # `/owner/repo`, lower-case
    Column("at", Text, nullable=False),  # see `_stamp`
    Column("actor", Text),  # an account ID; NULL when the instance did it. No foreign key: the
    # log outlives what it names.
    Column("change", Text, nullable=False),
    Column("kind", Text),  # NULL for a deletion, like `subject` and `role`
    Column("subject", Text),
    Column("role", Text),
    Column("previous_role", Text),
)
known_sign_ins = Table(
    "identity_known_sign_ins",
    metadata,
    Column("key", Text, primary_key=True),  # `<username>@address:...`
    Column("signed_in_at", Text, nullable=False),  # see `_stamp`
)
account_preferences = Table(
    "identity_preferences",
    metadata,
    Column(
        "account_id",
        Text,
        ForeignKey("identity_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("preferences", Text, nullable=False),  # a JSON object, one key per preference
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

    async def add(self, account: Account) -> bool:
        """Store a further account; the unique username column refuses a taken name atomically.

        Args:
            account: The new account.

        Returns:
            ``True`` when it was stored, ``False`` when another account has the username.
        """
        try:
            async with self.engine.begin() as connection:
                await connection.execute(insert(accounts).values(_account_values(account)))
        except IntegrityError:
            return False
        return True

    async def list_all(self) -> list[Account]:
        """Return every account, oldest first (then by username).

        Returns:
            The accounts.
        """
        # `created_at` is ISO 8601 with its offset, as the account had it: sorted in Python, by
        # instant, not as text.
        async with self.engine.connect() as connection:
            rows = (await connection.execute(select(accounts))).all()
        return sorted(map(_account, rows), key=lambda a: (a.created_at, a.username.value))

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        """Disable or enable the account, never disabling the last enabled admin.

        A ``begin_immediate`` transaction (SQLite's write lock; on PostgreSQL the shared writers'
        lock) makes the check and the change one step, so concurrent disables cannot both pass.

        Args:
            account_id: The account's id.
            disabled_at: When it was disabled, or ``None`` to enable it.

        Returns:
            ``False`` when disabling was refused to keep an enabled admin, else ``True``.
        """
        stamp = None if disabled_at is None else _stamp(disabled_at)
        change = update(accounts).where(accounts.c.id == account_id).values(disabled_at=stamp)
        enabled_admins = select(accounts.c.id).where(
            accounts.c.role == Role.ADMIN.value, accounts.c.disabled_at.is_(None)
        )
        async with self.engine.execution_options(begin_immediate=True).begin() as connection:
            if disabled_at is not None:
                admins = set((await connection.execute(enabled_admins)).scalars())
                if admins == {account_id}:
                    return False
            await connection.execute(change)
        return True

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


def _account_values(account: Account) -> dict[str, Any]:
    """Return the ``accounts`` row of a further account.

    Args:
        account: The account.

    Returns:
        Its column values.
    """
    return {
        "id": account.id,
        "username": account.username.value,
        "password_hash": account.password_hash,
        "role": account.role.value,
        "created_at": account.created_at.isoformat(),
        "disabled_at": None if account.disabled_at is None else _stamp(account.disabled_at),
    }


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
        disabled_at=None if row.disabled_at is None else datetime.fromisoformat(row.disabled_at),
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
            "library_ids": None
            if token.library_ids is None
            else json.dumps(sorted(token.library_ids)),
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
        library_ids=None if row.library_ids is None else frozenset(json.loads(row.library_ids)),
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


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteSignInAttemptRepository:
    """Implements ``ports.driven.SignInAttemptRepository`` (SQLite and PostgreSQL).

    In the database, not in a process's memory: the callback may reach another process.
    """

    engine: AsyncEngine
    """The database engine."""

    async def add(self, attempt: SignInAttempt, *, expired_before: datetime) -> None:
        """Store a new attempt, pruning the expired ones in the same transaction.

        Args:
            attempt: The attempt.
            expired_before: Attempts started before this are deleted.
        """
        values = {
            "binding_hash": attempt.binding_hash,
            "provider": attempt.provider,
            "state": attempt.state,
            "nonce": attempt.nonce,
            "code_verifier": attempt.code_verifier,
            "return_to": attempt.return_to,
            "created_at": _stamp(attempt.created_at),
        }
        stale = delete(sign_in_attempts).where(
            sign_in_attempts.c.created_at < _stamp(expired_before)
        )
        async with self.engine.begin() as connection:
            await connection.execute(stale)
            await connection.execute(insert(sign_in_attempts).values(values))

    async def take(self, binding_hash: str) -> SignInAttempt | None:
        """Delete the attempt and return it, in one statement (``DELETE ... RETURNING``).

        Args:
            binding_hash: The hash of the browser's binding value.

        Returns:
            The attempt, or ``None`` when no row was deleted.
        """
        statement = (
            delete(sign_in_attempts)
            .where(sign_in_attempts.c.binding_hash == binding_hash)
            .returning(*sign_in_attempts.c)
        )
        async with self.engine.begin() as connection:
            row = (await connection.execute(statement)).first()
        if row is None:
            return None
        return SignInAttempt(
            binding_hash=row.binding_hash,
            provider=row.provider,
            state=row.state,
            nonce=row.nonce,
            code_verifier=row.code_verifier,
            return_to=row.return_to,
            created_at=datetime.fromisoformat(row.created_at),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteExternalIdentityRepository:
    """Implements ``ports.driven.ExternalIdentityRepository`` (SQLite and PostgreSQL)."""

    engine: AsyncEngine
    """The database engine."""

    async def get(self, issuer: str, subject: str) -> ExternalIdentity | None:
        """Return the link of this identity, or ``None``.

        Args:
            issuer: The provider's issuer.
            subject: The person's identifier at the issuer.

        Returns:
            The link, or ``None``.
        """
        query = select(external_identities).where(
            external_identities.c.issuer == issuer, external_identities.c.subject == subject
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _identity(row)

    async def get_for_account(self, account_id: AccountId) -> ExternalIdentity | None:
        """Return the link of this account, or ``None``.

        Args:
            account_id: The account's id.

        Returns:
            The link, or ``None``.
        """
        query = select(external_identities).where(external_identities.c.account_id == account_id)
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _identity(row)

    async def create_linked_account(
        self, account: Account, identity: ExternalIdentity, groups: frozenset[str]
    ) -> LinkOutcome:
        """Store the account, its link and its groups in one transaction.

        The unique username refuses a taken name, the primary key (issuer, subject) a second
        link of the identity; either rolls everything back. Which one it was is read again
        afterwards, so the answer holds whatever the dialect's error says.

        Args:
            account: The new account.
            identity: Its link.
            groups: Its groups.

        Returns:
            ``created``, ``username_taken`` or ``already_linked``.
        """
        try:
            async with self.engine.begin() as connection:
                await connection.execute(insert(accounts).values(_account_values(account)))
                await connection.execute(
                    insert(external_identities).values(_identity_values(identity))
                )
                await _replace_groups(connection, account.id, groups)
        except IntegrityError:
            if await self.get(identity.issuer, identity.subject) is not None:
                return "already_linked"
            return "username_taken"
        return "created"

    async def record_check(
        self, identity: ExternalIdentity, *, role: Role, groups: frozenset[str]
    ) -> None:
        """Store the link's new state, the account's role and its groups in one transaction.

        Args:
            identity: The link as it is now.
            role: The account's role now.
            groups: The account's groups now.
        """
        values = _identity_values(identity)
        del values["issuer"], values["subject"], values["account_id"]
        link = update(external_identities).where(
            external_identities.c.issuer == identity.issuer,
            external_identities.c.subject == identity.subject,
            external_identities.c.account_id == identity.account_id,
        )
        account = update(accounts).where(accounts.c.id == identity.account_id)
        async with self.engine.begin() as connection:
            await connection.execute(link.values(values))
            await connection.execute(account.values(role=role.value))
            await _replace_groups(connection, identity.account_id, groups)

    async def record_revalidation(
        self,
        claimed: ExternalIdentity,
        checked: ExternalIdentity,
        *,
        role: Role,
        groups: frozenset[str],
    ) -> bool:
        """Store a successful revalidation, unless the link changed since it was claimed.

        The link's ``UPDATE`` only matches while the row still holds the claimed tokens and
        sign-in, check and access times and the account is not disabled (a compare-and-set, so
        it holds on PostgreSQL under concurrent writers too: the row lock makes a concurrent
        sign-in or revocation either finish first, and the compare then fails, or wait). The
        role and the groups are written only when it matched, in the same transaction.

        Args:
            claimed: The link as ``claim_due`` returned it.
            checked: The link after the check.
            role: The account's role now.
            groups: The account's groups now.

        Returns:
            ``True`` when stored; ``False`` when the link had changed (nothing is stored).
        """
        values = _identity_values(checked)
        del values["issuer"], values["subject"], values["account_id"]
        enabled = (
            select(accounts.c.id)
            .where(accounts.c.id == claimed.account_id, accounts.c.disabled_at.is_(None))
            .exists()
        )
        link = update(external_identities).where(
            external_identities.c.issuer == claimed.issuer,
            external_identities.c.subject == claimed.subject,
            external_identities.c.account_id == claimed.account_id,
            # `==` against None renders `IS NULL`; claimed links hold a token anyway.
            external_identities.c.sealed_tokens == claimed.sealed_tokens,
            external_identities.c.signed_in_at == _stamp(claimed.signed_in_at),
            external_identities.c.checked_at == _stamp(claimed.checked_at),
            external_identities.c.access_until == _stamp(claimed.access_until),
            enabled,
        )
        account = update(accounts).where(accounts.c.id == claimed.account_id)
        async with self.engine.begin() as connection:
            if (await connection.execute(link.values(values))).rowcount != 1:
                return False
            await connection.execute(account.values(role=role.value))
            await _replace_groups(connection, claimed.account_id, groups)
        return True

    async def revoke(self, account_id: AccountId, now: datetime) -> None:
        """End the account's access now, dropping its sealed tokens and its groups.

        Args:
            account_id: The account.
            now: The current time.
        """
        statement = (
            update(external_identities)
            .where(external_identities.c.account_id == account_id)
            .values(access_until=_stamp(now), sealed_tokens=None)
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)
            await _replace_groups(connection, account_id, frozenset())

    async def forget_tokens(self, account_id: AccountId) -> None:
        """Drop the account's sealed tokens.

        Args:
            account_id: The account.
        """
        statement = (
            update(external_identities)
            .where(external_identities.c.account_id == account_id)
            .values(sealed_tokens=None)
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def claim_due(
        self, now: datetime, *, lease_until: datetime, limit: int
    ) -> list[ExternalIdentity]:
        """Claim due links that hold a token, leasing them until ``lease_until``.

        On PostgreSQL the rows are locked with ``FOR UPDATE SKIP LOCKED`` and leased in the same
        transaction, so concurrent processes claim disjoint links; SQLite has one writer at a
        time (``begin_immediate``).

        Args:
            now: The current time.
            lease_until: Until when the claimed links are not due again.
            limit: The most links to claim.

        Returns:
            The claimed links, as they were before the lease.
        """
        query = (
            select(external_identities)
            .where(
                external_identities.c.sealed_tokens.is_not(None),
                external_identities.c.next_check_at <= _stamp(now),
            )
            .order_by(external_identities.c.next_check_at)
            .limit(limit)
        )
        engine = self.engine
        if engine.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        else:
            engine = engine.execution_options(begin_immediate=True)
        async with engine.begin() as connection:
            rows = (await connection.execute(query)).all()
            for row in rows:
                await connection.execute(
                    update(external_identities)
                    .where(
                        external_identities.c.issuer == row.issuer,
                        external_identities.c.subject == row.subject,
                    )
                    .values(next_check_at=_stamp(lease_until))
                )
        return [_identity(row) for row in rows]

    async def groups_by_account(self) -> Mapping[AccountId, tuple[str, list[str]]]:
        """Return the provider and the groups of every linked account.

        Returns:
            For each linked account: its provider's name and its groups, sorted.
        """
        async with self.engine.connect() as connection:
            links = (
                await connection.execute(
                    select(external_identities.c.account_id, external_identities.c.provider)
                )
            ).all()
            groups = (
                await connection.execute(
                    select(account_groups.c.account_id, account_groups.c.name).order_by(
                        account_groups.c.account_id, account_groups.c.name
                    )
                )
            ).all()
        found: dict[AccountId, tuple[str, list[str]]] = {
            AccountId(row.account_id): (row.provider, []) for row in links
        }
        for row in groups:
            if (entry := found.get(AccountId(row.account_id))) is not None:
                entry[1].append(row.name)
        return found

    async def groups_of(self, account_id: AccountId) -> frozenset[str]:
        """Return the groups of one account (empty for a local account).

        Args:
            account_id: The account.

        Returns:
            Its groups.
        """
        query = select(account_groups.c.name).where(account_groups.c.account_id == account_id)
        async with self.engine.connect() as connection:
            return frozenset((await connection.execute(query)).scalars())


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteLibraryGrantRepository:
    """Implements ``ports.driven.LibraryGrantRepository`` (SQLite and PostgreSQL)."""

    engine: AsyncEngine
    """The database engine."""

    async def matching(
        self, libraries: Collection[str], *, account_id: AccountId, groups: frozenset[str]
    ) -> list[LibraryGrant]:
        """Return the grants on these libraries that apply to an account or one of its groups.

        Args:
            libraries: Library IDs, lower-case.
            account_id: The account.
            groups: The account's groups.

        Returns:
            The grants to the account itself and to each of its groups.
        """
        if not libraries:
            return []
        who = (library_grants.c.kind == SubjectKind.USER.value) & (
            library_grants.c.subject == account_id
        )
        if groups:
            who = or_(
                who,
                (library_grants.c.kind == SubjectKind.GROUP.value)
                & library_grants.c.subject.in_(sorted(groups)),
            )
        query = select(library_grants).where(library_grants.c.library.in_(sorted(libraries)), who)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [_grant(row) for row in rows]

    async def for_library(self, library: str) -> list[LibraryGrant]:
        """Return every grant on a library.

        Args:
            library: The library ID, lower-case.

        Returns:
            The grants, users first, each kind by subject.
        """
        query = (
            select(library_grants)
            .where(library_grants.c.library == library)
            .order_by(library_grants.c.kind.desc(), library_grants.c.subject)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [_grant(row) for row in rows]

    async def get(self, library: str, kind: SubjectKind, subject: str) -> LibraryGrant | None:
        """Return the grant of one user or group on a library, or ``None``.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            The grant, or ``None``.
        """
        query = select(library_grants).where(
            library_grants.c.library == library,
            library_grants.c.kind == kind.value,
            library_grants.c.subject == subject,
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).first()
        return None if row is None else _grant(row)

    async def put(self, grant: LibraryGrant) -> None:
        """Store a grant, replacing the role the subject had on the library.

        Args:
            grant: The grant.
        """
        async with self.engine.begin() as connection:
            await connection.execute(_delete_grant(grant.library, grant.kind, grant.subject))
            await connection.execute(insert(library_grants).values(_grant_values(grant)))

    async def remove(self, library: str, kind: SubjectKind, subject: str) -> bool:
        """Delete one grant.

        Args:
            library: The library ID, lower-case.
            kind: Whether ``subject`` is an account ID or a group name.
            subject: The account ID or the group name.

        Returns:
            ``False`` when there was no such grant.
        """
        async with self.engine.begin() as connection:
            result = await connection.execute(_delete_grant(library, kind, subject))
        return result.rowcount > 0

    async def claim(self, library: str, account_id: AccountId) -> None:
        """Replace every grant on a library by the creator's, in one transaction.

        Args:
            library: The library ID, lower-case.
            account_id: The creator.
        """
        creator = LibraryGrant(
            library=library, kind=SubjectKind.USER, subject=account_id, role=LibraryRole.CREATOR
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(library_grants).where(library_grants.c.library == library)
            )
            await connection.execute(insert(library_grants).values(_grant_values(creator)))

    async def transfer(self, library: str, account_id: AccountId) -> list[AccountId]:
        """Make the account the library's creator in one transaction; the creators become admins.

        Args:
            library: The library ID, lower-case.
            account_id: The new creator.

        Returns:
            The accounts that were the library's creator before.
        """
        creator = LibraryGrant(
            library=library, kind=SubjectKind.USER, subject=account_id, role=LibraryRole.CREATOR
        )
        demote = (
            update(library_grants)
            .where(
                library_grants.c.library == library,
                library_grants.c.kind == SubjectKind.USER.value,
                library_grants.c.role == LibraryRole.CREATOR.value,
            )
            .values(role=LibraryRole.ADMIN.value)
            .returning(library_grants.c.subject)
        )
        async with self.engine.begin() as connection:
            previous = [AccountId(row.subject) for row in await connection.execute(demote)]
            await connection.execute(_delete_grant(library, SubjectKind.USER, account_id))
            await connection.execute(insert(library_grants).values(_grant_values(creator)))
        return sorted(previous)

    async def clear(self, library: str) -> None:
        """Delete every grant on a library.

        Args:
            library: The library ID, lower-case.
        """
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(library_grants).where(library_grants.c.library == library)
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteAccessLog:
    """Implements ``ports.driven.AccessLog`` (SQLite and PostgreSQL)."""

    engine: AsyncEngine
    """The database engine."""

    async def record(self, event: AccessEvent) -> None:
        """Append an event.

        Args:
            event: What changed, by whom and when.
        """
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(access_events).values(
                    id=event.id,
                    library=event.library,
                    at=_stamp(event.at),
                    actor=event.actor,
                    change=event.change.value,
                    kind=None if event.kind is None else event.kind.value,
                    subject=event.subject,
                    role=None if event.role is None else event.role.value,
                    previous_role=None
                    if event.previous_role is None
                    else event.previous_role.value,
                )
            )

    async def newest(
        self, where: AccessLogFilter, *, older_than: str | None, limit: int
    ) -> list[AccessEvent]:
        """Return the newest events that match, newest first.

        Args:
            where: Which events.
            older_than: Only events recorded before the one with this ID.
            limit: Most events returned.

        Returns:
            Up to ``limit`` events, by ID descending.
        """
        query = select(access_events).where(*_access_conditions(where))
        if older_than is not None:
            query = query.where(access_events.c.id < older_than)
        query = query.order_by(access_events.c.id.desc()).limit(limit)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [_access_event(row) for row in rows]

    async def count(self, where: AccessLogFilter) -> int:
        """Count the events that match.

        Args:
            where: Which events.

        Returns:
            How many there are.
        """
        query = select(func.count()).select_from(access_events).where(*_access_conditions(where))
        async with self.engine.connect() as connection:
            return (await connection.execute(query)).scalar_one()


def _access_conditions(where: AccessLogFilter) -> list[Any]:
    """Return the ``WHERE`` conditions of an access log filter.

    Args:
        where: Which events.

    Returns:
        The conditions, all of which must hold.
    """
    conditions: list[Any] = []
    if where.library is not None:
        conditions.append(access_events.c.library == where.library)
    if where.changes is not None:
        conditions.append(access_events.c.change.in_(sorted(c.value for c in where.changes)))
    if where.newer_than is not None:
        conditions.append(access_events.c.id > where.newer_than)
    return conditions


def _access_event(row: Row[Any]) -> AccessEvent:
    """Map an ``access_events`` row to its entity.

    Args:
        row: The row.

    Returns:
        The event.
    """
    return AccessEvent(
        id=row.id,
        library=row.library,
        at=datetime.fromisoformat(row.at),
        actor=None if row.actor is None else AccountId(row.actor),
        change=AccessChange(row.change),
        kind=None if row.kind is None else SubjectKind(row.kind),
        subject=row.subject,
        role=None if row.role is None else LibraryRole(row.role),
        previous_role=None if row.previous_role is None else LibraryRole(row.previous_role),
    )


def _delete_grant(library: str, kind: SubjectKind, subject: str) -> Delete:
    """Return the ``DELETE`` of one grant's row.

    Args:
        library: The library ID.
        kind: Whether ``subject`` is an account ID or a group name.
        subject: The account ID or the group name.

    Returns:
        The statement for that row.
    """
    return delete(library_grants).where(
        library_grants.c.library == library,
        library_grants.c.kind == kind.value,
        library_grants.c.subject == subject,
    )


def _grant_values(grant: LibraryGrant) -> dict[str, str]:
    """Return the ``library_grants`` row of a grant.

    Args:
        grant: The grant.

    Returns:
        Its column values.
    """
    return {
        "library": grant.library,
        "kind": grant.kind.value,
        "subject": grant.subject,
        "role": grant.role.value,
    }


def _grant(row: Row[Any]) -> LibraryGrant:
    """Map a ``library_grants`` row to its entity.

    Args:
        row: The row.

    Returns:
        The grant.
    """
    return LibraryGrant(
        library=row.library,
        kind=SubjectKind(row.kind),
        subject=row.subject,
        role=LibraryRole(row.role),
    )


def _identity_values(identity: ExternalIdentity) -> dict[str, Any]:
    """Return the ``external_identities`` row of a link.

    Args:
        identity: The link.

    Returns:
        Its column values.
    """
    return {
        "issuer": identity.issuer,
        "subject": identity.subject,
        "account_id": identity.account_id,
        "provider": identity.provider,
        "sealed_tokens": identity.sealed_tokens,
        "signed_in_at": _stamp(identity.signed_in_at),
        "checked_at": _stamp(identity.checked_at),
        "next_check_at": _stamp(identity.next_check_at),
        "access_until": _stamp(identity.access_until),
    }


def _identity(row: Row[Any]) -> ExternalIdentity:
    """Map an ``external_identities`` row to its entity.

    Args:
        row: The row.

    Returns:
        The link.
    """
    return ExternalIdentity(
        issuer=row.issuer,
        subject=row.subject,
        account_id=AccountId(row.account_id),
        provider=row.provider,
        sealed_tokens=row.sealed_tokens,
        signed_in_at=datetime.fromisoformat(row.signed_in_at),
        checked_at=datetime.fromisoformat(row.checked_at),
        next_check_at=datetime.fromisoformat(row.next_check_at),
        access_until=datetime.fromisoformat(row.access_until),
    )


async def _replace_groups(
    connection: AsyncConnection, account_id: str, groups: frozenset[str]
) -> None:
    """Replace the account's groups, in the caller's transaction.

    Args:
        connection: The connection, in a transaction.
        account_id: The account.
        groups: Its groups now.
    """
    await connection.execute(
        delete(account_groups).where(account_groups.c.account_id == account_id)
    )
    if groups:
        await connection.execute(
            insert(account_groups),
            [{"account_id": account_id, "name": name} for name in sorted(groups)],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlitePreferencesRepository:
    """Implements ``ports.driven.PreferencesRepository`` (SQLite, libSQL and PostgreSQL).

    One JSON object per account, so a preference added later needs no migration: a key a row
    lacks, or a value the interface no longer offers, reads as that preference's default.
    """

    engine: AsyncEngine
    """The database engine."""

    async def get(self, account_id: AccountId) -> Preferences | None:
        """Return the preferences an account saved, or ``None`` when it never saved any.

        Args:
            account_id: The account.

        Returns:
            Its preferences, or ``None``.
        """
        query = select(account_preferences.c.preferences).where(
            account_preferences.c.account_id == account_id
        )
        async with self.engine.connect() as connection:
            stored = (await connection.execute(query)).scalar_one_or_none()
        return None if stored is None else _preferences(json.loads(stored))

    async def put(self, account_id: AccountId, preferences: Preferences) -> None:
        """Save an account's preferences, replacing the ones it had (one atomic upsert).

        Args:
            account_id: The account, which exists.
            preferences: Its new preferences.
        """
        values = {"preferences": json.dumps(_preference_values(preferences), sort_keys=True)}
        async with self.engine.begin() as connection:
            await connection.execute(
                _conflict_insert(connection, account_preferences)
                .values(account_id=account_id, **values)
                .on_conflict_do_update(
                    index_elements=[account_preferences.c.account_id], set_=values
                )
            )


def _conflict_insert(
    bind: AsyncConnection | AsyncEngine, table: Table
) -> sqlite.Insert | postgresql.Insert:
    """Return an ``INSERT`` that takes ``ON CONFLICT`` clauses, in the database's dialect.

    Args:
        bind: Where the statement runs (SQLite, libSQL or PostgreSQL).
        table: The table to insert into.

    Returns:
        The statement; both dialects spell ``on_conflict_do_update``/``_nothing`` alike.
    """
    if bind.dialect.name == "postgresql":
        return postgres_insert(table)
    return sqlite_insert(table)


def _preference_values(preferences: Preferences) -> dict[str, Any]:
    """Return the JSON object a row stores.

    Args:
        preferences: The preferences.

    Returns:
        One plain value per preference.
    """
    return {
        "theme": preferences.theme.value,
        "contrast": preferences.contrast.value,
        "text_scale": preferences.text_scale,
        "text_spacing": preferences.text_spacing.value,
        "motion": preferences.motion.value,
        "font": preferences.font.value,
        "underline_links": preferences.underline_links,
        "large_targets": preferences.large_targets,
        "language": preferences.language.value,
        "library_logos": preferences.library_logos,
    }


def _preferences(stored: object) -> Preferences:
    """Read a row's JSON object back, a missing or no longer offered value as its default.

    Args:
        stored: The decoded JSON.

    Returns:
        The preferences.
    """
    values: Mapping[str, Any] = stored if isinstance(stored, dict) else {}
    defaults = Preferences()
    scale = values.get("text_scale")
    offered = type(scale) is int and scale in TEXT_SCALES
    return Preferences(
        theme=_choice(Theme, values.get("theme"), defaults.theme),
        contrast=_choice(Contrast, values.get("contrast"), defaults.contrast),
        text_scale=scale if offered else defaults.text_scale,
        text_spacing=_choice(TextSpacing, values.get("text_spacing"), defaults.text_spacing),
        motion=_choice(Motion, values.get("motion"), defaults.motion),
        font=_choice(Font, values.get("font"), defaults.font),
        underline_links=_flag(values.get("underline_links"), default=defaults.underline_links),
        large_targets=_flag(values.get("large_targets"), default=defaults.large_targets),
        language=_choice(Language, values.get("language"), defaults.language),
        library_logos=_flag(values.get("library_logos"), default=defaults.library_logos),
    )


def _flag(value: object, *, default: bool) -> bool:
    """Return the stored yes or no, or the default when it is missing or not a boolean.

    Args:
        value: The stored value.
        default: The preference's default.

    Returns:
        The flag.
    """
    return value if isinstance(value, bool) else default


def _choice[E: StrEnum](kind: type[E], value: object, default: E) -> E:
    """Return the stored choice, or the default when it is missing or no longer offered.

    Args:
        kind: The enumeration of the choices.
        value: The stored value.
        default: The preference's default.

    Returns:
        The choice.
    """
    return next((choice for choice in kind if choice.value == value), default)
