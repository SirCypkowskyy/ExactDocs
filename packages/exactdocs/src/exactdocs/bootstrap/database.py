"""The one SQLite database: data directory, engine and the single Alembic history.

Every domain keeps its tables in this database (prefixed ``catalog_``, ``retrieval_``, ...) and
its adapters receive the :class:`AsyncEngine`. Schema changes are Alembic revisions in
``migrations/versions``, owned by this package so no domain depends on another's schema.
"""

import sqlite3
import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection, DBAPICursor
from sqlalchemy.exc import ArgumentError
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


def open_database(settings: Settings) -> AsyncEngine:
    """Prepare the data directory and return an engine (no connection is made yet)."""
    try:
        url = make_url(settings.effective_database_url)
    except ArgumentError as exc:
        message = "EXACTDOCS_DATABASE_URL is not a valid database URL."
        raise StartupError(message) from exc
    if url.get_backend_name() != "sqlite":
        message = f"Unsupported database {url.get_backend_name()!r}: only SQLite is supported"
        raise StartupError(message)
    _prepare_directory(settings.data_dir)
    if url.database and url.database != ":memory:":
        _prepare_directory(Path(url.database).parent)
    # isolation_level=None: SQLAlchemy emits BEGIN itself (see `_begin`), so DDL is transactional
    # too, and the PRAGMAs below run in autocommit mode (WAL cannot be set inside a transaction).
    engine = create_async_engine(url, connect_args={"isolation_level": None})
    event.listen(engine.sync_engine, "connect", _configure_connection)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


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
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
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
