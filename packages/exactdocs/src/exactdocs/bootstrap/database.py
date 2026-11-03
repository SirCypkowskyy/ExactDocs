"""The one SQLite database: data directory, engine and the single Alembic history.

Every domain keeps its tables in this database (prefixed ``catalog_``, ``retrieval_``, ...) and
its adapters receive the :class:`AsyncEngine`. Schema changes are Alembic revisions in
``migrations/versions``, owned by this package so no domain depends on another's schema.
"""

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry

from exactdocs.bootstrap.settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_MS = 5000


class StartupError(RuntimeError):
    """The instance cannot start with this configuration; the message says what to change."""


def alembic_config() -> Config:
    """Alembic configuration built in code; ``env.py`` reuses the connection it is given."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS).replace("%", "%%"))
    return config


def open_database(settings: Settings) -> AsyncEngine:
    """Prepare the data directory and return an engine (no connection is made yet)."""
    url = make_url(settings.effective_database_url)
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
        path.mkdir(parents=True, exist_ok=True)
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
        cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
        cursor.execute("PRAGMA foreign_keys=ON")  # per connection; used within a domain only
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def _begin(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


async def migrate(engine: AsyncEngine) -> None:
    """Bring the schema to the Alembic head (a no-op when it already is)."""
    # ponytail: two processes migrating an empty database at the same instant may hit
    # "database is locked"; add an application lock if that ever happens in practice.
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)


def _upgrade(connection: Connection) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def current_revision(engine: AsyncEngine) -> str | None:
    """Return the schema revision the database is at, or ``None`` before the first migration."""
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )
