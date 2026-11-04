"""The one SQLite database: data directory, engine and the single Alembic history.

Every domain keeps its tables in this database (prefixed ``catalog_``, ``retrieval_``, ...) and
its adapters receive the :class:`AsyncEngine`. Schema changes are Alembic revisions in
``migrations/versions``, owned by this package so no domain depends on another's schema.
"""

import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.exc import ArgumentError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry

from exactdocs.bootstrap.settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_MS = 5000


class StartupError(RuntimeError):
    """The instance cannot start with this configuration; the message says what to change."""


def alembic_config(location: Path = MIGRATIONS) -> Config:
    """Alembic configuration built in code; ``env.py`` reuses the connection it is given."""
    config = Config()
    config.set_main_option("script_location", str(location).replace("%", "%%"))
    return config


MIN_SQLITE = (3, 35)  # search uses `WITH ... AS MATERIALIZED`


def _check_sqlite() -> None:
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
    """
    _check_sqlite()
    try:
        url = make_url(settings.effective_database_url)
    except ArgumentError as exc:
        message = "EXACTDOCS_DATABASE_URL is not a valid database URL."
        raise StartupError(message) from exc
    if url.get_backend_name() != "sqlite":
        message = f"Unsupported database {url.get_backend_name()!r}: only SQLite is supported"
        raise StartupError(message)
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
    # Only the file is kept: query parameters of EXACTDOCS_DATABASE_URL do not carry over.
    uri = URL.create(
        url.drivername,
        database=path.resolve().as_uri(),
        query={"mode": "ro", "uri": "true"},
    )
    engine = create_async_engine(uri, connect_args={"isolation_level": None})
    event.listen(engine.sync_engine, "connect", _configure_read_only_connection)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def _configure_read_only_connection(
    dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        # Only what a reader needs: foreign_keys and synchronous matter for writes alone.
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA query_only=ON")  # on top of mode=ro: every write is refused
    finally:
        cursor.close()


def _prepare_directory(path: Path) -> None:
    """Create ``path`` if missing and prove it is writable, or fail naming it."""
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
    immediate = connection.get_execution_options().get("begin_immediate", False)
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")


async def migrate(engine: AsyncEngine, *, location: Path = MIGRATIONS) -> None:
    """Bring the schema to the Alembic head (a no-op when it already is).

    Foreign keys are off while revisions run, because a batch alteration recreates a table and
    SQLite would otherwise apply ``ON DELETE CASCADE`` to the rows of the tables that reference
    it. ``PRAGMA foreign_key_check`` before the commit proves the revisions left no violation.
    The transaction is ``BEGIN IMMEDIATE``: processes starting together migrate one after the
    other (the later ones find nothing left to do) instead of failing with "database is locked".
    """
    async with engine.connect() as connection:
        await connection.execution_options(begin_immediate=True)
        # Raw cursor: the pragma is a no-op inside a transaction, which SQLAlchemy would begin.
        await connection.run_sync(_pragma, "foreign_keys=OFF")
        try:
            async with connection.begin():
                await connection.run_sync(_upgrade, location)
        finally:
            await connection.run_sync(_pragma, "foreign_keys=ON")


def _pragma(connection: Connection, pragma: str) -> None:
    cursor = connection.connection.cursor()
    try:
        cursor.execute(f"PRAGMA {pragma}")
    finally:
        cursor.close()


def _upgrade(connection: Connection, location: Path) -> None:
    config = alembic_config(location)
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        message = f"The migration left {len(violations)} foreign key violation(s); rolled back."
        raise StartupError(message)


async def current_revision(engine: AsyncEngine) -> str | None:
    """Return the schema revision the database is at, or ``None`` before the first migration."""
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )


async def check_schema_is_current(engine: AsyncEngine) -> None:
    """Refuse a database a reader cannot use: unreadable, not migrated, or newer than this build."""
    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
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
    if revision == head:
        return
    if revision and revision not in {r.revision for r in script.walk_revisions()}:
        message = (
            f"The ExactDocs database at {path} was migrated by a newer ExactDocs (revision "
            f"{revision}; this one knows up to {head}). Upgrade this ExactDocs "
            "(for uvx: `uvx --refresh exactdocs`)."
        )
        raise StartupError(message)
    found = f"at revision {revision}" if revision else "empty"
    message = (
        f"The ExactDocs database at {path} is {found}, but this version needs {head}. "
        "Start `exactdocs serve` to migrate it, then try again."
    )
    raise StartupError(message)
