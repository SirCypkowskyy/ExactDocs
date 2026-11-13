"""The one database: data directory, engine and the single Alembic history.

Every domain keeps its tables in this database (prefixed ``catalog_``, ``retrieval_``, ...) and
its adapters receive the :class:`AsyncEngine`. Schema changes are Alembic revisions in
``migrations/versions``, owned by this package so no domain depends on another's schema.

The database is a SQLite file in the data directory (the default) or PostgreSQL
(``EXACTDOCS_DATABASE_URL=postgresql+psycopg://...``), which several server processes can share.
"""

import asyncio
import contextlib
import fcntl
import logging
import os
import secrets
import socket
import sqlite3
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiosqlite
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.exc import ArgumentError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.util import await_

from exactdocs.bootstrap.cancellation import being_cancelled
from exactdocs.bootstrap.constants import (
    BUSY_TIMEOUT_MS,
    COLLATED_PREFIXES,
    LOCK_NOT_AVAILABLE,
    MIGRATION_LOCK,
    MIGRATION_TURN_NOTICE_SECONDS,
    MIGRATION_TURN_POLL_SECONDS,
    MIGRATION_TURN_REPEAT_SECONDS,
    MIGRATION_TURN_SUFFIX,
    MIGRATIONS,
    MIN_POSTGRES,
    MIN_SQLITE,
    POSTGRES_DRIVER,
    SECURE_SSLMODES,
    SESSION_PROBE,
    SPEND_LEDGER_TABLES,
    SQLITE_READ_ACTIONS,
    SQLITE_READ_PRAGMAS,
    SQLITE_WRITE_ACTIONS,
    SUPABASE_HOSTS,
    SUPABASE_TRANSACTION_PORT,
    WRITE_LOCK,
    WRITE_LOCK_TIMEOUT_MS,
)
from exactdocs.bootstrap.settings import Settings

logger = logging.getLogger(__name__)


class StartupError(RuntimeError):
    """The instance cannot start with this configuration; the message says what to change."""


class WriteTurnTimeoutError(RuntimeError):
    """On PostgreSQL, a writing transaction waited longer than ``WRITE_LOCK_TIMEOUT_MS``."""


def alembic_config(location: Path = MIGRATIONS) -> Config:
    """Alembic configuration built in code; ``env.py`` reuses the connection it is given.

    Args:
        location: The migrations directory.

    Returns:
        The configuration.
    """
    config = Config()
    config.set_main_option("script_location", str(location).replace("%", "%%"))
    return config


def _check_sqlite() -> None:
    """Refuse a SQLite library older than ``MIN_SQLITE``.

    Raises:
        StartupError: The SQLite this Python is built against is too old.
    """
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        message = (
            f"SQLite {sqlite3.sqlite_version} is too old: ExactDocs needs "
            f"{'.'.join(map(str, MIN_SQLITE))} or newer. Use a Python built against a newer SQLite "
            "(uv's managed Python or the Docker image)."
        )
        raise StartupError(message)


def open_database(settings: Settings, *, read_only: bool = False) -> AsyncEngine:
    """Prepare the data directory and return an engine (no connection is made yet).

    ``read_only`` opens an existing database file with ``mode=ro`` and ``PRAGMA query_only``: it
    creates no directory, switches no journal mode and can never write. A missing file is a
    ``StartupError`` naming it.

    Args:
        settings: The instance settings, for the database URL and the data directory.
        read_only: Open an existing SQLite file that can never be written.

    Returns:
        The engine.

    Raises:
        StartupError: The URL is invalid, names another database than SQLite or PostgreSQL, or
            the data directory cannot be used.
    """
    try:
        url = make_url(settings.effective_database_url)
    except ArgumentError as exc:
        message = "EXACTDOCS_DATABASE_URL is not a valid database URL."
        raise StartupError(message) from exc
    if url.get_backend_name() == "postgresql":
        return _open_postgres(url, settings, read_only=read_only)
    if url.get_backend_name() != "sqlite":
        message = (
            f"Unsupported database {url.get_backend_name()!r}: use SQLite or PostgreSQL "
            "(postgresql+psycopg://...)."
        )
        raise StartupError(message)
    _check_sqlite()
    if read_only:
        return _open_read_only(url)
    _prepare_directory(settings.data_dir)
    if url.database and url.database != ":memory:":
        _prepare_directory(Path(url.database).parent)
    # isolation_level=None: SQLAlchemy emits BEGIN itself (see `_begin`), so DDL is transactional
    # too, and the PRAGMAs below run in autocommit mode (WAL cannot be set inside a transaction).
    engine = create_async_engine(url, connect_args={"isolation_level": None})
    event.listen(engine.sync_engine, "connect", _configure_connection)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def _open_read_only(url: URL) -> AsyncEngine:
    """Open an existing SQLite file read-only (``mode=ro`` and ``PRAGMA query_only``).

    Args:
        url: The database URL.

    Returns:
        The engine.
    """
    uri = _existing_file(url, mode="ro")
    engine = create_async_engine(uri, connect_args={"isolation_level": None})
    event.listen(engine.sync_engine, "connect", _configure_read_only_connection)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def _existing_file(url: URL, *, mode: str) -> URL:
    """Name an existing SQLite file as a URI opened in this mode; it is never created.

    Args:
        url: The database URL.
        mode: SQLite's ``mode`` URI parameter (``ro`` or ``rw``).

    Returns:
        The file's URI; query parameters of ``EXACTDOCS_DATABASE_URL`` do not carry over.

    Raises:
        StartupError: The URL names an in-memory database, or no file exists.
    """
    if not url.database or url.database == ":memory:":
        message = "Read-only access needs a database file, not an in-memory database."
        raise StartupError(message)
    path = Path(url.database)
    if not path.is_file():
        message = (
            f"No ExactDocs database at {path}. Start `exactdocs serve` once (or run "
            "`exactdocs admin create`) to create it, or set EXACTDOCS_DATA_DIR to the directory "
            "that holds it."
        )
        raise StartupError(message)
    return URL.create(
        url.drivername,
        database=path.resolve().as_uri(),
        query={"mode": mode, "uri": "true"},
    )


def open_spend_ledger_database(settings: Settings) -> AsyncEngine:
    """Return the one engine a read-only (``serve --stdio``) process writes with: its AI spend.

    The process's other engine stays read-only. On SQLite this one opens the existing file with
    ``mode=rw`` and an authorizer that refuses every write but to ``SPEND_LEDGER_TABLES``, every
    schema change and attachment, and every ``PRAGMA`` but a read of ``SQLITE_READ_PRAGMAS``. On
    PostgreSQL it connects as the same role without ``default_transaction_read_only``: only the
    spend ledger is given it, so the limit there is this code path, not the database. No
    connection is made yet.

    Args:
        settings: The instance's settings.

    Returns:
        The engine.

    Raises:
        StartupError: The database URL is invalid or names no existing database file.
    """
    try:
        url = make_url(settings.effective_database_url)
    except ArgumentError as exc:
        message = "EXACTDOCS_DATABASE_URL is not a valid database URL."
        raise StartupError(message) from exc
    if url.get_backend_name() == "postgresql":
        engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=1,  # it only adds spend, a few rows now and then
            max_overflow=1,
        )
        event.listen(engine.sync_engine, "begin", _begin_postgres)
        return engine
    engine = create_async_engine(
        _existing_file(url, mode="rw"), connect_args={"isolation_level": None}
    )
    event.listen(engine.sync_engine, "connect", _configure_spend_ledger_connection)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def _configure_spend_ledger_connection(
    dbapi_connection: DBAPIConnection, record: ConnectionPoolEntry
) -> None:
    """Make a connection wait for locks, then allow it to write the spend ledger only.

    Args:
        dbapi_connection: SQLAlchemy's adapter over the aiosqlite connection.
        record: The pool's record of it, which holds the aiosqlite connection itself.

    Raises:
        TypeError: The pool's connection is not an aiosqlite one.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()
    driver = record.driver_connection
    if not isinstance(driver, aiosqlite.Connection):
        message = "the spend ledger's SQLite connection is not an aiosqlite connection"
        raise TypeError(message)
    await_(driver.set_authorizer(spend_ledger_authorizer))


def spend_ledger_authorizer(
    action: int,
    first: str | None,
    second: str | None,
    database: str | None,
    trigger: str | None,
) -> int:
    """SQLite authorizer of the spend ledger's connection: reads anywhere, writes to the ledger.

    Args:
        action: What the statement does (``sqlite3.SQLITE_*``).
        first: The table of a read or write, or the PRAGMA's name.
        second: The column, or the value a PRAGMA is set to.
        database: The schema: writes go to ``main`` only, never to a ``temp`` table of the same
            name.
        trigger: The trigger or view the access comes from.

    Returns:
        ``SQLITE_OK`` or ``SQLITE_DENY``.
    """
    del trigger
    if action in SQLITE_READ_ACTIONS:
        return sqlite3.SQLITE_OK
    if action in SQLITE_WRITE_ACTIONS and first in SPEND_LEDGER_TABLES and database == "main":
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and first in SQLITE_READ_PRAGMAS and second is None:
        return sqlite3.SQLITE_OK  # only reads it
    return sqlite3.SQLITE_DENY


def _open_postgres(url: URL, settings: Settings, *, read_only: bool) -> AsyncEngine:
    """Return an engine on PostgreSQL through psycopg 3 (no connection is made yet).

    Args:
        url: The database URL.
        settings: The instance's settings (the data directory is still prepared for a server).
        read_only: Every transaction is read-only (``default_transaction_read_only``).

    Returns:
        The engine.

    Raises:
        StartupError: Another PostgreSQL driver is named, or Supabase's pooler in transaction mode.
    """
    if url.drivername != POSTGRES_DRIVER:
        message = (
            f"Unsupported PostgreSQL driver {url.drivername!r}: ExactDocs uses psycopg 3, "
            "write the URL as postgresql+psycopg://... (or postgresql://...)."
        )
        raise StartupError(message)
    _check_supabase(url)
    if not read_only:
        _prepare_directory(settings.data_dir)  # git's work folders and known_hosts live there
    options = "-c default_transaction_read_only=on" if read_only else None
    engine = create_async_engine(
        url,
        pool_pre_ping=True,  # a server restart or a pooler leaves dead connections behind
        connect_args={"options": options} if options else {},
    )
    event.listen(engine.sync_engine, "begin", _begin_postgres)
    return engine


def _check_supabase(url: URL) -> None:
    """Refuse Supabase's transaction-mode pooler; warn when its connection may be unencrypted.

    In transaction mode a pooler hands each transaction to any server connection: psycopg's
    prepared statements, the advisory locks of the executor slots and DBOS's ``LISTEN`` all need
    the same session from one statement to the next. Only the URL is read; nothing connects.

    Hosts and ports are read as libpq reads them: the query's ``host`` and ``port`` win over the
    URL's own, a host list is checked host by host, and a trailing dot or capitals change
    nothing. A Supabase pooler named by its IP address (an IPv6 literal on 6543, say) cannot be
    recognised: that is the one form this check lets through.

    Args:
        url: The database URL.

    Raises:
        StartupError: The URL names Supabase's pooler in transaction mode (port 6543).
    """
    supabase = [
        (host, port) for host, port in _hosts_and_ports(url) if host.endswith(SUPABASE_HOSTS)
    ]
    for host, port in supabase:
        if port == str(SUPABASE_TRANSACTION_PORT):
            message = (
                f"EXACTDOCS_DATABASE_URL names Supabase's connection pooler in transaction mode "
                f"({host}:{SUPABASE_TRANSACTION_PORT}), which ExactDocs cannot use: its jobs and "
                "prepared statements need a session. Use the session pooler (the same host, port "
                "5432) or the direct connection (db.<project-ref>.supabase.co, port 5432; IPv6 "
                "only unless the project has the IPv4 add-on), with ?sslmode=require."
            )
            raise StartupError(message)
    sslmode = _query_value(url, "sslmode") or os.environ.get("PGSSLMODE")
    if supabase and sslmode not in SECURE_SSLMODES:
        logger.warning(
            "EXACTDOCS_DATABASE_URL names Supabase (%s) without sslmode=require: the connection "
            "may not be encrypted. Add ?sslmode=require (or verify-full with Supabase's CA), or "
            "set PGSSLMODE.",
            supabase[0][0],
        )


def _query_value(url: URL, name: str) -> str | None:
    """Return a query parameter of the URL (the last one, if it is repeated).

    Args:
        url: The database URL.
        name: The parameter.

    Returns:
        Its value, or ``None``.
    """
    value = url.query.get(name)
    if isinstance(value, tuple):
        return value[-1] if value else None
    return value


def _hosts_and_ports(url: URL) -> list[tuple[str, str]]:
    """List the hosts the URL connects to, each with its port, as libpq would read them.

    Args:
        url: The database URL.

    Returns:
        Each host (lowercase, without a trailing dot) and its port (``5432`` when none is given).
    """
    hosts = (_query_value(url, "host") or url.host or "").split(",")
    ports = (_query_value(url, "port") or (str(url.port) if url.port else "")).split(",")
    if len(ports) == 1:  # one port for every host
        ports *= len(hosts)
    return [
        (host.strip().lower().rstrip("."), (port.strip() or "5432"))
        for host, port in zip(hosts, ports, strict=False)
    ]


def _begin_postgres(connection: Connection) -> None:
    """Make a ``begin_immediate`` transaction take turns with the others that ask for it.

    SQLite has one writer at a time and the adapters rely on ``BEGIN IMMEDIATE`` to make a
    read-then-write atomic (the first admin, a manifest's activation). On PostgreSQL the same
    transactions take one transaction-level advisory lock, released at commit or rollback, so
    they keep that guarantee across every process using the database. A turn waits at most
    ``WRITE_LOCK_TIMEOUT_MS``, as SQLite waits ``BUSY_TIMEOUT_MS``, then fails with
    ``WriteTurnTimeoutError``. The price is SQLite's too: one writing transaction at a time,
    whatever the number of processes.

    Args:
        connection: The connection whose transaction begins.

    Raises:
        WriteTurnTimeoutError: Another transaction kept the turn past ``WRITE_LOCK_TIMEOUT_MS``.
        OperationalError: The lock failed for another reason.
    """
    if not connection.get_execution_options().get("begin_immediate", False):
        return
    connection.exec_driver_sql(f"SET LOCAL lock_timeout = {WRITE_LOCK_TIMEOUT_MS}")
    try:
        connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock({WRITE_LOCK})")
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
            raise
        message = (
            f"Another ExactDocs process kept the database's write turn for over "
            f"{WRITE_LOCK_TIMEOUT_MS // 1000} s; try again."
        )
        raise WriteTurnTimeoutError(message) from error
    connection.exec_driver_sql("SET LOCAL lock_timeout = DEFAULT")


def is_postgres(engine: AsyncEngine) -> bool:
    """Tell whether the engine is on PostgreSQL.

    Args:
        engine: The database engine.

    Returns:
        ``True`` for PostgreSQL, ``False`` for SQLite.
    """
    return engine.dialect.name == "postgresql"


def _configure_read_only_connection(
    dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry
) -> None:
    """Make a read-only connection wait for locks and refuse every write.

    Args:
        dbapi_connection: The new DB-API connection.
        _: The pool's record of it (unused).
    """
    cursor = dbapi_connection.cursor()
    try:
        # Only what a reader needs: foreign_keys and synchronous matter for writes alone.
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA query_only=ON")  # on top of mode=ro: every write is refused
    finally:
        cursor.close()


def _prepare_directory(path: Path) -> None:
    """Create ``path`` if missing and prove it is writable, or fail naming it.

    Args:
        path: The directory.

    Raises:
        StartupError: The directory cannot be created or written to.
    """
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)  # private when we create it
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as exc:
        message = (
            f"Cannot use {path} as data directory: {exc.strerror or exc}. "
            "Make it writable or set EXACTDOCS_DATA_DIR to another directory."
        )
        raise StartupError(message) from exc


def _configure_connection(dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
    """Set a new SQLite connection up: busy timeout, WAL, ``synchronous`` and foreign keys.

    Args:
        dbapi_connection: The new DB-API connection.
        _: The pool's record of it (unused).
    """
    cursor = dbapi_connection.cursor()
    try:
        # First, so the statements below wait for a lock instead of failing at once.
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        _enable_wal(cursor)  # readers don't block the writer
        cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
        cursor.execute("PRAGMA foreign_keys=ON")  # per connection; used within a domain only
    finally:
        cursor.close()


def _enable_wal(cursor: DBAPICursor) -> None:
    """Switch the file to WAL (persistent, so only the first connection ever changes anything).

    Leaving rollback mode needs an exclusive lock, and SQLite returns SQLITE_BUSY for it at once
    without calling the busy handler when two connections race for it (each holds a shared lock
    the other waits on), so ``busy_timeout`` does not cover this statement. Retry it ourselves
    for as long as that timeout; the losers then find the file already in WAL.

    Args:
        cursor: A cursor of the new connection.

    Raises:
        OperationalError: The switch failed for another reason than a busy file, or the file
            stayed busy for longer than ``BUSY_TIMEOUT_MS``.
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
    while True:
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode & 0xFF != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                raise
            # Blocking sleep is deliberate: this is a sync connect listener, and it only runs
            # on the first connections to a new file (afterwards the pragma is a no-op).
            time.sleep(0.01)
        else:
            return


def _begin(connection: Connection) -> None:
    """Begin a transaction: ``BEGIN IMMEDIATE`` when the connection asks for one.

    Args:
        connection: The connection whose transaction begins.
    """
    immediate = connection.get_execution_options().get("begin_immediate", False)
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")


async def migrate(engine: AsyncEngine, *, location: Path = MIGRATIONS) -> None:
    """Bring the schema to the Alembic head (a no-op when it already is).

    Foreign keys are off while revisions run, because a batch alteration recreates a table and
    SQLite would otherwise apply ``ON DELETE CASCADE`` to the rows of the tables that reference
    it. ``PRAGMA foreign_key_check`` before the commit proves the revisions left no violation.
    Processes starting together on one SQLite file migrate one after the other (the later ones
    find nothing left to do): each first takes the migration turn (``_migration_turn``, a file
    lock it waits for as long as another process's migration takes), then runs the revisions in
    a ``BEGIN IMMEDIATE`` transaction. SQLite's own wait for a lock (``BUSY_TIMEOUT_MS``) is not
    long enough on its own: it does not depend on how fast the machine migrates (#320).

    On PostgreSQL the revisions run in one transaction that first takes an advisory lock (the
    same turn-taking across processes), and the text columns of ExactDocs' tables are then given
    the "C" collation (see ``COLLATED_PREFIXES``).

    Args:
        engine: The database engine.
        location: The migrations directory.
    """
    if is_postgres(engine):
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade_postgres, location)
        return
    # The turn comes first, so the first connection's switch to WAL is taken in turn too.
    async with _migration_turn(engine), engine.connect() as connection:
        await connection.execution_options(begin_immediate=True)
        # Raw cursor: the pragma is a no-op inside a transaction, which SQLAlchemy would begin.
        await connection.run_sync(_pragma, "foreign_keys=OFF")
        try:
            async with connection.begin():
                await connection.run_sync(_upgrade, location)
        finally:
            await connection.run_sync(_pragma, "foreign_keys=ON")


@contextlib.asynccontextmanager
async def _migration_turn(engine: AsyncEngine) -> AsyncGenerator[None]:
    """Hold the SQLite file's migration turn: an exclusive ``flock`` on a file next to it.

    A process waits for the turn for as long as another process's migration takes, however slow
    the machine is, and without blocking the event loop: it tries the lock again every
    ``MIGRATION_TURN_POLL_SECONDS``, so a start cancelled while it waits stops at once. A long
    wait is logged as a warning naming the lock file and the holder, first after
    ``MIGRATION_TURN_NOTICE_SECONDS`` and then every ``MIGRATION_TURN_REPEAT_SECONDS``. The
    kernel releases the lock of a process that dies, so a crash leaves no stale turn behind.
    An in-memory database has no other process to wait for.

    ``flock`` (not ``fcntl.lockf``) on purpose: it locks per open file description, so two
    engines of one process exclude each other as two processes do, while a POSIX record lock
    would let every descriptor of the same process through.

    Args:
        engine: A SQLite engine.

    Yields:
        Nothing, while this process holds the turn.

    Raises:
        StartupError: The lock file cannot be opened (another user's file, a missing directory).
    """
    path = database_file(engine)
    if path is None:
        yield
        return
    turn = path.with_name(path.name + MIGRATION_TURN_SUFFIX)
    try:
        descriptor = os.open(turn, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        message = (
            f"Cannot open {turn}, the lock processes take turns on to migrate: "
            f"{exc.strerror or exc}. Run every ExactDocs command as the same user, or, with "
            "every ExactDocs process stopped, remove the file (it only names the last holder)."
        )
        raise StartupError(message) from exc
    try:
        started = time.monotonic()
        notice_at = started + MIGRATION_TURN_NOTICE_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                now = time.monotonic()
                if now >= notice_at:
                    notice_at = now + MIGRATION_TURN_REPEAT_SECONDS
                    logger.warning(
                        "Waited %.0f s for another ExactDocs process (%s) to migrate %s; "
                        "it holds %s.",
                        now - started,
                        _turn_holder(descriptor),
                        path,
                        turn,
                    )
                await asyncio.sleep(MIGRATION_TURN_POLL_SECONDS)
            else:
                break
        _write_turn_holder(descriptor, _this_holder())
        try:
            yield
        finally:
            _write_turn_holder(descriptor, "")  # a later waiter names no finished process
    finally:
        os.close(descriptor)  # releases the lock


def _write_turn_holder(descriptor: int, holder: str) -> None:
    """Record who holds the migration turn in its lock file; a diagnostic only, never needed.

    Args:
        descriptor: The lock file, open for writing.
        holder: Who holds the turn, or ``""`` once it is given back.
    """
    with contextlib.suppress(OSError):
        os.ftruncate(descriptor, 0)
        # A host name need not be valid UTF-8 (surrogates): escape it, never fail the start.
        os.pwrite(descriptor, holder.encode(errors="backslashreplace"), 0)


def _this_holder() -> str:
    """Name this process as the migration turn's holder, as far as the system tells.

    Returns:
        ``pid <n> on <host>``, or ``pid <n>`` when the host name cannot be read.
    """
    try:
        return f"pid {os.getpid()} on {socket.gethostname()}"
    except OSError:
        return f"pid {os.getpid()}"


def _turn_holder(descriptor: int) -> str:
    """Tell who the migration turn's lock file names as its holder, as far as it says.

    Args:
        descriptor: The lock file, open for reading.

    Returns:
        The holder (``pid <n> on <host>``), or ``"holder unknown"``.
    """
    try:
        holder = os.pread(descriptor, 256, 0).decode(errors="replace").strip()
    except OSError:
        holder = ""
    return holder or "holder unknown"


def _pragma(connection: Connection, pragma: str) -> None:
    """Run one ``PRAGMA`` on the raw DB-API connection, outside any transaction.

    Args:
        connection: The connection.
        pragma: The pragma and its value, e.g. ``foreign_keys=OFF``.
    """
    cursor = connection.connection.cursor()
    try:
        cursor.execute(f"PRAGMA {pragma}")
    finally:
        cursor.close()


def _upgrade(connection: Connection, location: Path) -> None:
    """Run the SQLite revisions up to the head, then prove they left no foreign key violation.

    Args:
        connection: The connection, in its ``BEGIN IMMEDIATE`` transaction.
        location: The migrations directory.

    Raises:
        StartupError: The revisions left foreign key violations (the transaction rolls back).
    """
    config = alembic_config(location)
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        message = f"The migration left {len(violations)} foreign key violation(s); rolled back."
        raise StartupError(message)


async def warn_unless_session(engine: AsyncEngine) -> bool:
    """Warn when the PostgreSQL connection loses its session state between transactions.

    One pooled connection sets a session-level value (``set_config(..., false)``) in one
    transaction and reads it back in the next. Behind a pooler in transaction mode (PgBouncer's
    ``pool_mode = transaction``, Supabase's port 6543, another provider's) the second
    transaction may run on another server connection, or on one the pooler reset, and the value
    is gone. That is logged as one WARNING and the start goes on. The probe cannot prove the
    opposite: a transaction-mode pooler with one idle server connection keeps the value, so no
    warning is no guarantee. It opens no connection of its own (the pool's, checked out once)
    and costs three statements in two transactions; the last clears the value. SQLite has no
    session to lose: nothing is done. A probe that fails (a pooler that refuses
    ``set_config``, a dropped connection, a ``statement_timeout``) is logged as a WARNING too
    and the start goes on, unless the start is being cancelled.

    Args:
        engine: The database engine, already migrated.

    Returns:
        ``True`` when the value was lost and the warning logged.
    """
    if not is_postgres(engine):
        return False
    try:
        lost = await _session_is_lost(engine)
    except Exception as exc:
        if being_cancelled():  # the error replaced the start's cancellation: stop all the same
            raise
        logger.warning(
            "Could not check that the PostgreSQL connection (%s) keeps its session between "
            "transactions; the start goes on: %s",
            shown_url(engine.url),
            exc,
        )
        return False
    if not lost:
        return False
    logger.warning(
        "The PostgreSQL connection (%s) lost its session state between two transactions: "
        "EXACTDOCS_DATABASE_URL looks like a connection pooler in transaction mode, which "
        "ExactDocs does not support (its jobs, advisory locks and prepared statements need a "
        "session). Jobs may fail at random. Use a session connection instead: the pooler in "
        "session mode (PgBouncer's pool_mode = session; Supabase's session pooler, port 5432) "
        "or the direct connection to PostgreSQL.",
        shown_url(engine.url),
    )
    return True


async def _session_is_lost(engine: AsyncEngine) -> bool:
    """Set a session value in one transaction, read it in the next, then clear it.

    Clearing it matters behind a transaction-mode pooler that kept the value: the server
    connection is shared with other clients afterwards.

    Args:
        engine: A PostgreSQL engine.

    Returns:
        ``True`` when the second transaction did not see the value.
    """
    token = secrets.token_hex(8)
    async with engine.connect() as connection:
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config(:name, :token, false)"),
                {"name": SESSION_PROBE, "token": token},
            )
        async with connection.begin():
            found = await connection.scalar(
                text("SELECT current_setting(:name, true)"), {"name": SESSION_PROBE}
            )
            await connection.execute(
                text("SELECT set_config(:name, '', false)"), {"name": SESSION_PROBE}
            )
    return found != token


def shown_url(url: URL) -> str:
    """Render a database URL for a log line or an error, with every password hidden.

    ``hide_password`` covers the userinfo only; libpq also reads a ``password`` query key.

    Args:
        url: The database URL.

    Returns:
        The URL with ``***`` for the userinfo password and no ``password`` query key.
    """
    return url.difference_update_query(["password"]).render_as_string(hide_password=True)


def _upgrade_postgres(connection: Connection, location: Path) -> None:
    """Run the revisions on PostgreSQL, one process at a time, then collate the text columns.

    Args:
        connection: A connection inside the migration's transaction.
        location: The Alembic revisions.

    Raises:
        StartupError: The server is older than PostgreSQL 14, or the database is not UTF8.
    """
    version = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
    if int(version) < MIN_POSTGRES:
        message = f"PostgreSQL {version} is too old: ExactDocs needs PostgreSQL 14 or newer."
        raise StartupError(message)
    encoding = connection.exec_driver_sql("SHOW server_encoding").scalar_one()
    if encoding != "UTF8":
        message = (
            f"The PostgreSQL database is encoded in {encoding}: ExactDocs needs UTF8 "
            "(CREATE DATABASE ... ENCODING 'UTF8')."
        )
        raise StartupError(message)
    connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock({MIGRATION_LOCK})")
    config = alembic_config(location)
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    _collate_by_code_point(connection)


def _collate_by_code_point(connection: Connection) -> None:
    """Give every text column of ExactDocs' tables the "C" collation, once.

    SQLite compares text byte by byte; a PostgreSQL database usually has a locale's collation
    (``en_US.utf8``), under which ``B`` sorts after ``a`` and listings would come out in another
    order. Revisions create plain ``Text`` columns, so this runs after every migration and only
    changes the columns that are not "C" yet (a new revision's, or every column of a new database),
    keeping their exact type (``varchar(n)`` too). A column a generated column or a view reads
    cannot change type and is left alone: give such a column ``Text(collation="C")`` in its
    revision, as ``0c4e8a2f6b19`` does.

    Args:
        connection: A connection inside the migration's transaction.
    """
    rows = connection.execute(
        text(
            "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)"
            " FROM pg_attribute a"
            " JOIN pg_class c ON c.oid = a.attrelid"
            " JOIN pg_type t ON t.oid = a.atttypid"
            " WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'r'"
            " AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = ''"
            " AND t.typcategory = 'S'"
            " AND a.attcollation <> (SELECT oid FROM pg_collation WHERE collname = 'C'"
            "  AND collnamespace = 'pg_catalog'::regnamespace)"
            " AND left(c.relname, strpos(c.relname, '_')) = ANY(:prefixes)"
            # A column a generated column or a view reads cannot change type: those keep theirs.
            " AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.refobjid = a.attrelid"
            "  AND d.refobjsubid = a.attnum"
            "  AND (d.classid = 'pg_rewrite'::regclass"
            "  OR (d.classid = 'pg_attrdef'::regclass AND d.deptype = 'n')))"
            " ORDER BY c.relname, a.attnum"
        ),
        {"prefixes": list(COLLATED_PREFIXES)},
    ).all()
    preparer = connection.dialect.identifier_preparer
    for table, column, column_type in rows:
        connection.exec_driver_sql(
            f"ALTER TABLE {preparer.quote(table)} ALTER COLUMN {preparer.quote(column)}"
            f' TYPE {column_type} COLLATE "C"'
        )


async def current_revision(engine: AsyncEngine) -> str | None:
    """Return the schema revision the database is at, or ``None`` before the first migration.

    Args:
        engine: The database engine.

    Returns:
        The revision, or ``None``.
    """
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )


def schema_head() -> str | None:
    """Return the Alembic head revision this build migrates to.

    Returns:
        The head revision, or ``None`` if there are no revisions.
    """
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def database_file(engine: AsyncEngine) -> Path | None:
    """Return the file the engine's SQLite database lives in.

    Args:
        engine: The database engine.

    Returns:
        The path, or ``None`` for an in-memory database.
    """
    database = engine.url.database
    if is_postgres(engine) or not database or database == ":memory:":
        return None
    if database.startswith("file:"):  # the read-only engine's URI form
        return Path(unquote(urlparse(database).path))
    return Path(database)


def database_file_missing(engine: AsyncEngine) -> bool:
    """Tell, without connecting, whether the database file is gone.

    Connecting to a missing SQLite file would create an empty one, so probes ask this first.
    A PostgreSQL database has no file: always ``False``.

    Args:
        engine: The database engine.

    Returns:
        ``True`` when the engine has a file and it does not exist.
    """
    path = database_file(engine)
    return path is not None and not path.is_file()


async def check_schema_is_current(engine: AsyncEngine) -> None:
    """Refuse a database a reader cannot use: unreadable, not migrated, or newer than this build.

    Args:
        engine: The database engine.

    Raises:
        StartupError: The database cannot be read, or is not at this build's head revision.
    """
    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
    if is_postgres(engine):
        where = shown_url(engine.url)
        try:
            revision = await current_revision(engine)
        except OperationalError as exc:
            message = f"Cannot read the ExactDocs database at {where}: {exc.orig}."
            raise StartupError(message) from exc
        _refuse_revision(script, revision, head, where)
        return
    path = Path(unquote(urlparse(engine.url.database or "").path))
    try:
        revision = await current_revision(engine)
    except OperationalError as exc:
        message = (
            f"Cannot read {path}: {exc.orig}. In WAL mode SQLite must create {path.name}-wal and "
            f"{path.name}-shm next to the database when no server is running, and it cannot "
            f"in {path.parent}. Start `exactdocs serve`, or make the directory writable. Run "
            "stdio as the same user as the server: files created by another user can stop the "
            "server from starting later."
        )
        raise StartupError(message) from exc
    _refuse_revision(script, revision, head, str(path))


def _refuse_revision(
    script: ScriptDirectory, revision: str | None, head: str | None, where: str
) -> None:
    """Raise ``StartupError`` unless the database is at ``head``.

    Args:
        script: This build's revisions.
        revision: The database's revision.
        head: The revision this build needs.
        where: The database, as the message names it.

    Raises:
        StartupError: The database is behind, empty or ahead of this build.
    """
    if revision == head:
        return
    if revision and revision not in {r.revision for r in script.walk_revisions()}:
        message = (
            f"The ExactDocs database at {where} was migrated by a newer ExactDocs (revision "
            f"{revision}; this one knows up to {head}). Upgrade this ExactDocs "
            "(for uvx: `uvx --refresh exactdocs`)."
        )
        raise StartupError(message)
    found = f"at revision {revision}" if revision else "empty"
    message = (
        f"The ExactDocs database at {where} is {found}, but this version needs {head}. "
        "Start `exactdocs serve` to migrate it, then try again."
    )
    raise StartupError(message)
