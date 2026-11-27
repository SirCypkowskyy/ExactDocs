"""The data directory and the migrated SQLite database."""

import asyncio
import fcntl
import logging
import os
import re
import shutil
import sqlite3
import stat
import textwrap
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from alembic import op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap import database
from exactdocs.bootstrap.constants import BUSY_TIMEOUT_MS, MIGRATION_TURN_SUFFIX, MIGRATIONS
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import (
    StartupError,
    alembic_config,
    current_revision,
    database_file,
    migrate,
    open_database,
    open_spend_ledger_database,
)
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import GetLibraryQuery, ListLibrariesQuery
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import HostKind, Library, LibraryId
from sqlite_guard import no_connection_left_open

ORPHAN_VERSION = (
    "INSERT INTO catalog_library_versions (library_id, ref, kind, commit_sha, imported_at) "
    "VALUES ('/no/such', 'v1', 'tag', 'abc', '2026-11-04')"
)


def library(library_id: str) -> Library:
    return Library(
        id=LibraryId(library_id),
        title="Payments",
        source_url="https://github.com/acme/payments",
        host=HostKind.GITHUB,
    )


def head() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


async def test_empty_data_dir_gets_a_database_at_the_alembic_head(
    isolated_data_dir: Path,
) -> None:
    container = Container.build(Settings())

    async with container.running():
        assert await current_revision(container.engine) == head()

    assert (isolated_data_dir / "exactdocs.db").is_file()


async def test_a_stored_library_is_listed_after_a_restart() -> None:
    first = Container.build(Settings())
    async with first.running():
        await SqliteLibraryRepository(engine=first.engine).save(library("/acme/payments"))

    second = Container.build(Settings())
    async with second.running():
        listed = await second.catalog.list_libraries(ListLibrariesQuery())
        found = await second.catalog.get_library(GetLibraryQuery(id="/acme/payments"))

    assert [lib.id for lib in listed.libraries] == ["/acme/payments"]
    assert found.title == "Payments"


async def test_a_container_runs_once_at_a_time() -> None:
    """A second run would share the engine, and the first to stop would dispose it under the other.

    A connection the other run had checked out (a job worker's poll) would then go back to a dead
    pool and never be closed (#203).
    """
    container = Container.build(Settings())
    app = create_app(container)

    async with container.running():
        with pytest.raises(RuntimeError, match="already running"):
            async with container.running(jobs=False):
                pass
        with pytest.raises(RuntimeError, match="already running"):
            async with app.router.lifespan_context(app):  # the app's lifespan runs it too
                pass
        assert await current_revision(container.engine) == head()  # the first run is untouched

    async with app.router.lifespan_context(app):  # stopped, it may run again
        assert await current_revision(container.engine) == head()


async def test_a_read_only_container_runs_once_at_a_time() -> None:
    async with Container.build(Settings()).running():
        pass  # a database to open read-only
    reader = ReadOnlyContainer.build(Settings())

    async with reader.running():
        with pytest.raises(RuntimeError, match="already running"):
            async with reader.running():
                pass

    async with reader.running():  # stopped, it may run again
        assert await current_revision(reader.engine) == head()


@pytest.mark.parametrize(
    "opener",
    [open_database, lambda s: open_database(s, read_only=True), open_spend_ledger_database],
    ids=["read_write", "read_only", "spend_ledger"],
)
async def test_a_connect_cancelled_while_sqlite_opens_closes_the_connection(
    opener: Callable[[Settings], AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with Container.build(Settings()).running():
        pass  # a database to open
    engine = opener(Settings())
    entered, release = threading.Event(), threading.Event()
    real_connect = sqlite3.connect

    def held(database: str, **kwargs: Any) -> sqlite3.Connection:
        entered.set()
        release.wait(5)
        return real_connect(database, **kwargs)

    async def connect() -> None:
        async with engine.connect():
            pass

    monkeypatch.setattr(sqlite3, "connect", held)
    try:
        with no_connection_left_open():  # the cancellation must not leave it open (#630)
            task = asyncio.create_task(connect())
            await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        await engine.dispose()


async def test_nothing_survives_in_another_data_dir(tmp_path: Path) -> None:
    first = Container.build(Settings())
    async with first.running():
        await SqliteLibraryRepository(engine=first.engine).save(library("/a/b"))

    other = Container.build(Settings(data_dir=tmp_path / "other"))
    async with other.running():
        with pytest.raises(LibraryNotFoundError):
            await other.catalog.get_library(GetLibraryQuery(id="/a/b"))


def test_data_dir_that_cannot_be_created_fails_naming_the_path(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    data_dir = blocker / "data"

    with pytest.raises(StartupError, match="file/data"):
        Container.build(Settings(data_dir=data_dir))


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores directory permissions"
)
def test_read_only_data_dir_fails_naming_the_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "readonly"
    data_dir.mkdir(mode=0o500)

    with pytest.raises(StartupError, match="readonly") as raised:
        Container.build(Settings(data_dir=data_dir))

    assert "EXACTDOCS_DATA_DIR" in str(raised.value)


def test_data_dir_is_private_when_we_create_it(isolated_data_dir: Path) -> None:
    Container.build(Settings())

    assert stat.S_IMODE(isolated_data_dir.stat().st_mode) == 0o700


def test_a_malformed_database_url_is_rejected_without_echoing_it() -> None:
    with pytest.raises(StartupError) as raised:
        Container.build(Settings(database_url="not a url, password=hunter2"))

    assert "hunter2" not in str(raised.value)


async def test_database_url_overrides_the_file_in_the_data_dir(
    tmp_path: Path, isolated_data_dir: Path
) -> None:
    database = tmp_path / "elsewhere" / "custom.db"
    settings = Settings(database_url=f"sqlite:///{database.as_posix()}")

    async with Container.build(settings).running():
        pass

    assert database.is_file()
    assert not (isolated_data_dir / "exactdocs.db").exists()


def test_only_sqlite_and_postgresql_are_supported() -> None:
    with pytest.raises(StartupError, match="use SQLite, PostgreSQL"):
        Container.build(Settings(database_url="mysql://user:secret@host/db"))


def test_postgresql_runs_on_psycopg_only() -> None:
    with pytest.raises(StartupError, match="psycopg 3"):
        Container.build(Settings(database_url="postgresql+asyncpg://user:secret@host/db"))


@pytest.mark.parametrize("url", ["postgresql://u:p@db/x", "postgresql+psycopg://u:p@db/x"])
def test_both_postgresql_spellings_mean_psycopg(url: str) -> None:
    settings = Settings(database_url=url)

    assert settings.effective_database_url == "postgresql+psycopg://u:p@db/x"
    assert settings.uses_postgres
    assert not Settings().uses_postgres


def test_postgresql_needs_one_secret_key_for_every_process() -> None:
    # Checked before any connection: the host does not have to exist.
    with pytest.raises(StartupError, match="EXACTDOCS_SECRET_KEY"):
        Container.build(Settings(database_url="postgresql://user:secret@nowhere.invalid/db"))


async def test_connections_use_wal_foreign_keys_and_a_busy_timeout() -> None:
    container = Container.build(Settings())
    async with container.running(), container.engine.connect() as connection:
        pragmas = {
            name: (await connection.execute(text(f"PRAGMA {name}"))).scalar_one()
            for name in ("journal_mode", "foreign_keys", "busy_timeout")
        }

    assert pragmas == {"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": BUSY_TIMEOUT_MS}


async def test_foreign_keys_are_enforced_within_a_domain() -> None:
    container = Container.build(Settings())
    async with container.running():
        with pytest.raises(IntegrityError):
            async with container.engine.begin() as connection:
                await connection.execute(text(ORPHAN_VERSION))


def test_migration_history_is_linear() -> None:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()

    assert len(heads) == 1, (
        f"parallel migrations: rebase one so its down_revision is the head {heads}"
    )


async def test_a_revision_can_create_fts5_tables_with_op_execute() -> None:
    def create_fts5_table(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            op.execute("CREATE VIRTUAL TABLE catalog_fts_probe USING fts5(body)")

    container = Container.build(Settings())
    async with container.running(), container.engine.begin() as connection:
        await connection.run_sync(create_fts5_table)
        await connection.execute(text("INSERT INTO catalog_fts_probe VALUES ('verbatim docs')"))
        match = await connection.execute(
            text("SELECT body FROM catalog_fts_probe WHERE catalog_fts_probe MATCH 'verbatim'")
        )

    assert match.scalar_one() == "verbatim docs"


def add_revision(tmp_path: Path, body: str) -> Path:
    """A copy of the real migrations plus one more revision on top of the current head."""
    location = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, location, ignore=shutil.ignore_patterns("__pycache__"))
    (location / "versions" / "99999999_extra.py").write_text(
        f'"""Extra."""\n'
        f"import sqlalchemy as sa\n"
        f"from alembic import op\n"
        f"revision = 'extra'\n"
        f"down_revision = {head()!r}\n"
        f"branch_labels = None\n"
        f"depends_on = None\n"
        f"def upgrade() -> None:\n{textwrap.indent(textwrap.dedent(body), '    ')}\n"
        f"def downgrade() -> None:\n    pass\n"
    )
    return location


async def test_a_batch_alteration_keeps_the_rows_that_reference_the_table(tmp_path: Path) -> None:
    container = Container.build(Settings())
    location = add_revision(
        tmp_path,
        """
        with op.batch_alter_table("catalog_libraries", recreate="always") as batch:
            batch.add_column(sa.Column("note", sa.Text, nullable=True))
        """,
    )
    async with container.running():
        repository = SqliteLibraryRepository(engine=container.engine)
        stored = library("/acme/payments")
        await repository.save(stored)

        await migrate(container.engine, location=location)

        assert await current_revision(container.engine) == "extra"
        assert await repository.get(stored.id) == stored
        # foreign keys are back on for ordinary connections
        async with container.engine.connect() as connection:
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1


async def test_a_migration_that_breaks_a_foreign_key_is_rolled_back(tmp_path: Path) -> None:
    container = Container.build(Settings())
    location = add_revision(tmp_path, f"op.execute({ORPHAN_VERSION!r})")
    async with container.running():
        with pytest.raises(StartupError, match="foreign key"):
            await migrate(container.engine, location=location)

        assert await current_revision(container.engine) == head()
        async with container.engine.connect() as connection:
            rows = await connection.execute(text("SELECT count(*) FROM catalog_library_versions"))
            assert rows.scalar_one() == 0


async def test_processes_starting_together_all_migrate_an_empty_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Processes" are containers on one event loop: a real race all the same, since the
    # migration turn is an flock, per open file description (fcntl.lockf would not be).
    # The race is in the first moments of a fresh database file, so every round gets its own.
    for round_ in range(5):
        monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(tmp_path / f"round-{round_}"))
        containers = [Container.build(Settings()) for _ in range(8)]

        async def start(container: Container) -> str | None:
            async with container.running(jobs=False):  # one job worker per process
                return await current_revision(container.engine)

        assert await asyncio.gather(*(start(c) for c in containers)) == [head()] * 8


SLOW_REVISION = """
import asyncio
from sqlalchemy.util import await_
await_(asyncio.sleep(0.6))  # holds the write lock without blocking the event loop
"""


async def test_a_process_waits_for_another_migration_longer_than_sqlite_waits_for_a_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A busy machine: the other process's migration outlasts SQLite's own wait (#320).
    monkeypatch.setattr(database, "BUSY_TIMEOUT_MS", 50)
    location = add_revision(tmp_path, SLOW_REVISION)
    engines = [open_database(Settings()) for _ in range(3)]
    try:
        await asyncio.gather(*(migrate(engine, location=location) for engine in engines))

        assert [await current_revision(engine) for engine in engines] == ["extra"] * 3
    finally:
        for engine in engines:
            await engine.dispose()


def migration_turn(engine: AsyncEngine) -> Path:
    path = database_file(engine)
    assert path is not None
    return path.with_name(path.name + MIGRATION_TURN_SUFFIX)


def turn_taken(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """An event set as soon as a migration takes the turn (it then names itself in the file)."""
    taken = asyncio.Event()
    # Written the moment the flock is held.
    write = database._write_turn_holder  # ruff: ignore[private-member-access]

    def noting(descriptor: int, holder: str) -> None:
        write(descriptor, holder)
        if holder:
            taken.set()

    monkeypatch.setattr(database, "_write_turn_holder", noting)
    return taken


async def test_a_start_cancelled_while_it_waits_for_another_migration_stops_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = add_revision(tmp_path, SLOW_REVISION)
    taken = turn_taken(monkeypatch)
    first, second = open_database(Settings()), open_database(Settings())
    try:
        migrating = asyncio.create_task(migrate(first, location=location))
        await taken.wait()  # the first holds the migration turn
        waiting = asyncio.create_task(migrate(second, location=location))
        await asyncio.sleep(0.1)
        waiting.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiting, timeout=0.2)  # did not wait for the first to finish
        await migrating
        await migrate(second, location=location)  # the turn was given back

        assert await current_revision(second) == "extra"
    finally:
        await first.dispose()
        await second.dispose()


class _TurnWarnings(logging.Handler):
    """Collects the waiters' warnings, and says when a second one has come."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []
        self.repeated = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if "to migrate" in record.getMessage():
            self.messages.append(record.getMessage())
            if len(self.messages) >= 2:  # the first notice and one repeat
                self.repeated.set()


async def test_a_long_wait_for_another_migration_is_logged_again_naming_the_lock_and_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "MIGRATION_TURN_NOTICE_SECONDS", 0.05)
    monkeypatch.setattr(database, "MIGRATION_TURN_REPEAT_SECONDS", 0.1)
    warnings = _TurnWarnings()
    database.logger.addHandler(warnings)
    engine = open_database(Settings())
    turn = migration_turn(engine)
    holder = os.open(turn, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)  # another process holds the turn ...
        os.write(holder, b"pid 4242 on elsewhere")  # ... and says who it is
        waiting = asyncio.create_task(migrate(engine))
        await asyncio.wait_for(warnings.repeated.wait(), timeout=10)
        os.close(holder)  # the holder lets go
        holder = -1
        await waiting

        assert await current_revision(engine) == head()
        assert all(str(turn) in m and "pid 4242 on elsewhere" in m for m in warnings.messages)
        assert not turn.read_text()  # a finished migration names no holder
    finally:
        database.logger.removeHandler(warnings)
        if holder >= 0:
            os.close(holder)
        await engine.dispose()


async def test_a_host_name_that_is_not_utf8_never_fails_the_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database.socket, "gethostname", lambda: "host\udcff")
    engine = open_database(Settings())
    try:
        await migrate(engine)

        assert await current_revision(engine) == head()
        assert not migration_turn(engine).read_text()  # cleared again after the migration
    finally:
        await engine.dispose()


async def test_a_migration_lock_in_a_missing_directory_stops_startup_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(tmp_path / "data"))
    engine = open_database(Settings())
    try:
        shutil.rmtree(tmp_path / "data")  # gone before the first connection
        with pytest.raises(StartupError, match=re.escape(str(migration_turn(engine)))):
            await migrate(engine)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores file permissions"
)
async def test_a_migration_lock_of_another_user_stops_startup_naming_it() -> None:
    engine = open_database(Settings())
    turn = migration_turn(engine)
    turn.touch(mode=0o000)  # as left by a command run as another user (mode 0600, not ours)
    try:
        with pytest.raises(StartupError, match="same user") as raised:
            await migrate(engine)

        assert str(turn) in str(raised.value)
    finally:
        turn.chmod(0o600)
        await engine.dispose()


def test_an_sqlite_older_than_the_floor_stops_startup_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 1))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.34.1")

    with pytest.raises(StartupError, match=r"SQLite 3\.34\.1 is too old.*3\.35"):
        open_database(Settings())
