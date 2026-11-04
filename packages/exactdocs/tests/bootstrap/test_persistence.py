"""The data directory and the migrated SQLite database."""

import asyncio
import os
import shutil
import sqlite3
import stat
import textwrap
from pathlib import Path

import pytest
from alembic import op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import (
    BUSY_TIMEOUT_MS,
    MIGRATIONS,
    StartupError,
    alembic_config,
    current_revision,
    migrate,
    open_database,
)
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import GetLibraryQuery, ListLibrariesQuery
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import HostKind, Library, LibraryId

ORPHAN_VERSION = (
    "INSERT INTO catalog_library_versions VALUES ('/no/such', 'v1', 'tag', 'abc', '2026-11-04')"
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
        await SqliteLibraryRepository(first.engine).save(library("/acme/payments"))

    second = Container.build(Settings())
    async with second.running():
        listed = await second.catalog.list_libraries(ListLibrariesQuery())
        found = await second.catalog.get_library(GetLibraryQuery(id="/acme/payments"))

    assert [lib.id for lib in listed.libraries] == ["/acme/payments"]
    assert found.title == "Payments"


async def test_nothing_survives_in_another_data_dir(tmp_path: Path) -> None:
    first = Container.build(Settings())
    async with first.running():
        await SqliteLibraryRepository(first.engine).save(library("/a/b"))

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


def test_only_sqlite_is_supported() -> None:
    with pytest.raises(StartupError, match="only SQLite"):
        Container.build(Settings(database_url="postgresql://user:secret@host/db"))


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
        repository = SqliteLibraryRepository(container.engine)
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
    # The race is in the first moments of a fresh database file, so every round gets its own.
    for round_ in range(5):
        monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(tmp_path / f"round-{round_}"))
        containers = [Container.build(Settings()) for _ in range(8)]

        async def start(container: Container) -> str | None:
            async with container.running():
                return await current_revision(container.engine)

        assert await asyncio.gather(*(start(c) for c in containers)) == [head()] * 8


def test_an_sqlite_older_than_the_floor_stops_startup_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 1))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.34.1")

    with pytest.raises(StartupError, match=r"SQLite 3\.34\.1 is too old.*3\.35"):
        open_database(Settings())
