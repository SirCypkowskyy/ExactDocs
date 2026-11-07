"""ExactDocs on PostgreSQL: what several processes sharing one database rely on.

Every test gets a new database (``on_postgres``). Without ``EXACTDOCS_TEST_POSTGRES_URL`` this
module is skipped as a whole; CI sets ``EXACTDOCS_REQUIRE_POSTGRES=1``, so there it always runs.
"""

import asyncio
import json
import signal
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import ADMIN_URL
from exactdocs.bootstrap import database
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import (
    StartupError,
    WriteTurnTimeoutError,
    current_revision,
    migrate,
    open_database,
)
from exactdocs.bootstrap.executors import PostgresExecutorSlots
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.postgres import PostgresLibraryLocks
from exactdocs.ingestion.adapters.driving.dbos_worker import SlotState
from import_child import big_repository, page, run

if ADMIN_URL is None:
    pytest.skip("needs a PostgreSQL server (EXACTDOCS_TEST_POSTGRES_URL)", allow_module_level=True)

pytestmark = pytest.mark.usefixtures("on_postgres")

FILES = 200


@pytest.fixture
async def engines() -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """Two engines on the migrated database: as two processes would see it.

    Yields:
        The two engines; both are disposed afterwards.
    """
    first, second = open_database(Settings()), open_database(Settings())
    await migrate(first)
    yield first, second
    await first.dispose()
    await second.dispose()


async def test_processes_starting_together_migrate_once_and_agree() -> None:
    engines = [open_database(Settings()) for _ in range(3)]
    try:
        await asyncio.gather(*(migrate(engine) for engine in engines))
        revisions = {await current_revision(engine) for engine in engines}
    finally:
        for engine in engines:
            await engine.dispose()

    assert len(revisions) == 1
    assert None not in revisions


async def test_text_compares_and_sorts_by_code_point_whatever_the_locale(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, _ = engines
    async with engine.connect() as connection:
        other = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = current_schema() AND data_type = 'text'"
                " AND table_name ~ '^(catalog|identity|ingestion|retrieval)_'"
                " AND coalesce(collation_name, '') <> 'C'"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO catalog_libraries (id, title, description, source_url, host,"
                " settings) VALUES ('/a/b', 'x', '', 'u', 'git', '{}'),"
                " ('/A/c', 'x', '', 'u', 'git', '{}')"
            )
        )
        ordered = (
            await connection.execute(text("SELECT id FROM catalog_libraries ORDER BY id"))
        ).scalars()

        assert other == 0
        assert list(ordered) == ["/A/c", "/a/b"]  # SQLite's BINARY order: upper case first


async def test_a_write_transaction_waits_for_another_process_s(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = engines
    order: list[str] = []

    async def write(engine: AsyncEngine, name: str, hold: float) -> None:
        async with engine.execution_options(begin_immediate=True).begin() as connection:
            await connection.execute(text("SELECT 1"))
            order.append(f"{name} in")
            await asyncio.sleep(hold)
            order.append(f"{name} out")

    holder = asyncio.create_task(write(first, "a", 0.3))
    await asyncio.sleep(0.1)
    await write(second, "b", 0)
    await holder

    assert order == ["a in", "a out", "b in", "b out"]


async def test_a_library_s_lock_is_held_across_processes_and_per_purpose(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = engines
    tags_a = PostgresLibraryLocks(engine=first, purpose="tags")
    tags_b = PostgresLibraryLocks(engine=second, purpose="tags")
    settings_b = PostgresLibraryLocks(engine=second, purpose="settings")
    order: list[str] = []

    async def hold(locks: PostgresLibraryLocks, library: str, name: str, seconds: float) -> None:
        async with locks.of(library):
            order.append(f"{name} in")
            await asyncio.sleep(seconds)
            order.append(f"{name} out")

    holder = asyncio.create_task(hold(tags_a, "/Acme/Docs", "a", 0.4))
    await asyncio.sleep(0.1)
    # Another purpose and another library do not wait; the same library (any case) does.
    await hold(settings_b, "/acme/docs", "settings", 0)
    await hold(tags_b, "/other/lib", "other", 0)
    await hold(tags_b, "/acme/docs", "b", 0)
    await holder

    assert order == [
        "a in",
        "settings in",
        "settings out",
        "other in",
        "other out",
        "a out",
        "b in",
        "b out",
    ]


async def test_each_process_takes_the_lowest_free_executor_slot(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = (PostgresExecutorSlots(engine=e) for e in engines)

    async with first.claim() as one:
        async with second.claim() as two:
            assert (one, two) == ("exactdocs-0", "exactdocs-1")
            async with second.orphaned([one, two, "local", "exactdocs-x"]) as dead:
                assert list(dead) == []  # both alive: neither may be adopted
        async with first.orphaned([one, two]) as dead:
            assert list(dead) == ["exactdocs-1"]  # its process stopped
            async with second.claim() as again:
                assert again == "exactdocs-2"  # slot 1 is held while it is adopted
        async with second.claim() as again:
            assert again == "exactdocs-1"


async def test_an_import_killed_halfway_resumes_in_the_next_process(tmp_path: Path) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    log = tmp_path / "chunked.log"

    code, _, err = await run(str(tmp_path / "one"), url, commit, str(log), "120")
    assert code == -signal.SIGKILL, err
    log.unlink()
    # Another data directory: on PostgreSQL the jobs live in the database, not next to it.
    code, out, err = await run(str(tmp_path / "two"), url, "-", str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == [page(n) for n in range(121, FILES + 1)]
    job = json.loads(out)
    assert (job["state"], job["done"], job["total"]) == ("succeeded", FILES, FILES)
    assert job["articles"] == [page(n) for n in range(1, FILES + 1)]


async def test_the_jobs_of_a_process_that_never_comes_back_are_adopted(tmp_path: Path) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    log = tmp_path / "chunked.log"
    engine = open_database(Settings())
    await migrate(engine)
    try:
        # A live process holds slot 0, so the one that is killed runs as exactdocs-1.
        async with PostgresExecutorSlots(engine=engine).claim() as live:
            assert live == "exactdocs-0"
            code, _, err = await run(str(tmp_path / "one"), url, commit, str(log), "120")
        assert code == -signal.SIGKILL, err
    finally:
        await engine.dispose()
    log.unlink()
    # The next process takes slot 0: DBOS resumes nothing of its own, the worker adopts slot 1's.
    code, out, err = await run(str(tmp_path / "two"), url, "-", str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == [page(n) for n in range(121, FILES + 1)]
    job = json.loads(out)
    assert (job["state"], job["done"], job["total"]) == ("succeeded", FILES, FILES)
    assert job["articles"] == [page(n) for n in range(1, FILES + 1)]


def test_dbos_keeps_its_tables_in_the_configured_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_DBOS_SYSTEM_SCHEMA", "exactdocs_jobs")
    container = Container.build(Settings())

    worker = container.job_worker
    assert worker.system_database_url == container.engine.url.render_as_string(hide_password=False)
    assert worker.system_schema == "exactdocs_jobs"
    assert worker.database is None
    assert worker.executors is not None


def test_a_dbos_schema_must_be_a_plain_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_DBOS_SYSTEM_SCHEMA", 'dbos"; drop table x; --')
    with pytest.raises(ValueError, match="dbos_system_schema"):
        Settings()


async def test_the_stdio_server_refuses_an_empty_database() -> None:
    container = ReadOnlyContainer.build(Settings())
    with pytest.raises(StartupError, match="is empty"):
        async with container.running():
            pass


async def test_the_stdio_server_reads_postgresql_but_cannot_write_to_it() -> None:
    engine = open_database(Settings())
    await migrate(engine)
    await engine.dispose()
    container = ReadOnlyContainer.build(Settings())

    async with container.running(), container.engine.connect() as connection:
        with pytest.raises(DBAPIError, match="read-only transaction"):
            await connection.execute(text("DELETE FROM catalog_libraries"))


async def test_collation_keeps_a_column_s_type_and_skips_what_generated_columns_read(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, _ = engines
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE catalog_later (short varchar(5), read text,"
                " words tsvector GENERATED ALWAYS AS (to_tsvector('simple', read)) STORED)"
            )
        )
    await migrate(engine)  # as a later revision's columns would be collated

    async with engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name, data_type, character_maximum_length, collation_name"
                    " FROM information_schema.columns WHERE table_name = 'catalog_later'"
                    " AND column_name IN ('short', 'read') ORDER BY column_name"
                )
            )
        ).all()

    assert [tuple(c) for c in columns] == [
        ("read", "text", None, None),
        ("short", "character varying", 5, "C"),
    ]


async def test_a_writer_that_waits_too_long_for_its_turn_fails_clearly(
    engines: tuple[AsyncEngine, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "WRITE_LOCK_TIMEOUT_MS", 200)
    first, second = engines
    async with first.execution_options(begin_immediate=True).begin() as holder:
        await holder.execute(text("SELECT 1"))
        with pytest.raises(WriteTurnTimeoutError, match="write turn"):
            async with second.execution_options(begin_immediate=True).begin() as waiter:
                await waiter.execute(text("SELECT 1"))
    async with second.execution_options(begin_immediate=True).begin() as later:
        assert await later.scalar(text("SHOW lock_timeout")) == "0"  # only the turn waits


async def _drop_slot_connection(engine: AsyncEngine, slot: int) -> None:
    """Kill the backend that holds the slot, as a failover or an idle timeout would."""
    async with engine.connect() as connection:
        killed = await connection.scalar(
            text(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_locks"
                " WHERE locktype = 'advisory' AND classid = 1163412547 AND objid = :slot"
                " AND objsubid = 2"
            ),
            {"slot": slot},
        )
        await connection.commit()
    assert killed == 1
    await asyncio.sleep(0.1)  # the server ends the backend asynchronously


async def test_a_process_whose_slot_connection_died_takes_it_back_or_stops(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = (PostgresExecutorSlots(engine=e) for e in engines)

    async with first.claim() as mine:  # its release must not fail on a dead connection
        assert await first.keep() is SlotState.HELD
        await _drop_slot_connection(engines[0], 0)
        assert await first.keep() is SlotState.RETAKEN  # nobody took it meanwhile
        assert await first.keep() is SlotState.HELD

        await _drop_slot_connection(engines[0], 0)
        async with second.claim() as theirs:  # a process starting now gets the free slot
            assert theirs == mine
            assert await first.keep() is SlotState.LOST  # so this one must stop
