"""The data directory and the migrated SQLite database."""

import os
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
    StartupError,
    alembic_config,
    current_revision,
)
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import GetLibraryQuery
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import Library, LibraryName, Version


def head() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


async def test_empty_data_dir_gets_a_database_at_the_alembic_head(
    isolated_data_dir: Path,
) -> None:
    assert not isolated_data_dir.exists()
    container = Container.build(Settings())

    async with container.running():
        assert await current_revision(container.engine) == head()

    assert (isolated_data_dir / "exactdocs.db").is_file()


async def test_a_stored_library_is_listed_after_a_restart() -> None:
    library = Library(name=LibraryName("/acme/payments"), versions=frozenset({Version("1.4")}))
    first = Container.build(Settings())
    async with first.running():
        await SqliteLibraryRepository(first.engine).save(library)

    second = Container.build(Settings())
    async with second.running():
        listed = await second.catalog.list_libraries()
        found = await second.catalog.get_library(GetLibraryQuery(name="/acme/payments"))

    assert [lib.name for lib in listed.libraries] == ["/acme/payments"]
    assert found.versions == ["1.4"]


async def test_nothing_survives_in_another_data_dir(tmp_path: Path) -> None:
    first = Container.build(Settings())
    async with first.running():
        await SqliteLibraryRepository(first.engine).save(Library(name=LibraryName("/a/b")))

    other = Container.build(Settings(data_dir=tmp_path / "other"))
    async with other.running():
        with pytest.raises(LibraryNotFoundError):
            await other.catalog.get_library(GetLibraryQuery(name="/a/b"))


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
                await connection.execute(
                    text("INSERT INTO catalog_library_versions VALUES ('/no/such', '1')")
                )


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
