"""On PostgreSQL the search engine is chosen at start: `pg_search` when the database has it.

Needs ``EXACTDOCS_TEST_POSTGRES_URL``; the `pg_search` cases also need a server that has the
extension (``EXACTDOCS_TEST_PG_SEARCH=1``, as on CI's ParadeDB).
"""

import asyncio
import logging

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app_lifespan import serving
from databases import ADMIN_URL, PG_SEARCH, PostgresDatabase
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven import pg_search
from exactdocs.retrieval.adapters.driven.pg_search import PgSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_fts import PostgresSearchIndex
from exactdocs.retrieval.constants import (
    _PG_BM25_INDEX_NEXT,
    _PG_BM25_LOCK,
    PG_SEARCH_QUIET_SCANS,
    POSTGRES_FORMAT,
)
from exactdocs.retrieval.models import ChunkSet, TagFilter

if ADMIN_URL is None:
    pytest.skip("needs a PostgreSQL server (EXACTDOCS_TEST_POSTGRES_URL)", allow_module_level=True)

needs_pg_search = pytest.mark.skipif(not PG_SEARCH, reason="the server has no pg_search")

BM25_INDEXES = """
    SELECT ix.relname, i.indisvalid FROM pg_index i
    JOIN pg_class ix ON ix.oid = i.indexrelid
    JOIN pg_am am ON am.oid = ix.relam
    WHERE i.indrelid = 'retrieval_search'::regclass AND am.amname = 'bm25'
"""


async def _health(container: Container) -> dict[str, object]:
    app = create_app(container)
    async with (
        serving(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        return (await client.get("/api/health")).json()


async def _bm25_indexes(engine: AsyncEngine) -> list[tuple[str, bool]]:
    async with engine.connect() as connection:
        return [(r.relname, r.indisvalid) for r in await connection.execute(text(BM25_INDEXES))]


def _bm25(engine: AsyncEngine) -> PgSearchIndex:
    table = PostgresSearchIndex(engine=engine, write_settings=PG_SEARCH_QUIET_SCANS)
    return PgSearchIndex(engine=engine, table=table)


@pytest.mark.usefixtures("on_postgres")
async def test_without_pg_search_postgresql_full_text_search_answers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, "exactdocs.bootstrap.search_engine")

    health = await _health(Container.build(Settings()))

    assert health["search_engine"] == "postgres_fts"
    assert "PostgreSQL full-text search" in caplog.text
    assert "pg_search" in caplog.text  # names the extension it would rather use


@needs_pg_search
@pytest.mark.usefixtures("on_postgres")
async def test_an_available_but_uninstalled_pg_search_is_named_with_the_statement_that_adds_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, "exactdocs.bootstrap.search_engine")
    container = Container.build(Settings())

    async with container.running(jobs=False):
        state = await container.retrieval.get_search_index_state()

    assert state.engine == "postgres_fts"
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "CREATE EXTENSION pg_search" in warning.getMessage()  # a likely mistake: a warning


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_with_pg_search_bm25_answers() -> None:
    health = await _health(Container.build(Settings()))

    assert health["search_engine"] == "pg_search"


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_processes_starting_together_build_the_bm25_index_once() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
    engines = [open_database(Settings()) for _ in range(3)]
    try:
        missing = await asyncio.gather(*(_bm25(engine).prepare(create=True) for engine in engines))
        indexes = await _bm25_indexes(engines[0])
    finally:
        for engine in engines:
            await engine.dispose()

    assert missing == [None, None, None]
    assert indexes == [("retrieval_search_bm25", True)]


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_an_index_a_dead_build_left_invalid_is_built_again() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql(  # what CREATE INDEX CONCURRENTLY leaves when it dies
            "UPDATE pg_index SET indisvalid = false"
            " WHERE indexrelid = 'retrieval_search_bm25'::regclass"
        )
    again = Container.build(Settings())

    async with again.running(jobs=False):
        indexes = await _bm25_indexes(again.engine)
        state = await again.retrieval.get_search_index_state()

    assert indexes == [("retrieval_search_bm25", True)]
    assert state.engine == "pg_search"


@needs_pg_search
async def test_a_rebuild_keeps_the_bm25_index_under_its_name(
    on_pg_search: PostgresDatabase,
) -> None:
    del on_pg_search
    container = Container.build(Settings())

    async with container.running(jobs=False):
        await container.retrieval.rebuild_search_index()
        indexes = await _bm25_indexes(container.engine)
        state = await container.retrieval.get_search_index_state()

    assert indexes == [("retrieval_search_bm25", True)]
    assert (state.engine, state.needs_rebuild) == ("pg_search", False)


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_a_rebuild_that_died_before_its_rename_does_not_break_the_next_one() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        table = PostgresSearchIndex(engine=engine)
        await table.build_next()  # what `rebuild` does, up to the swap ...
        async with engine.begin() as connection:
            await connection.exec_driver_sql(_PG_BM25_INDEX_NEXT)
        await table.swap()  # ... then it dies before renaming the index
        assert await _bm25_indexes(engine) == [("retrieval_search_next_bm25", True)]

        rebuilt = await container.retrieval.rebuild_search_index()
        indexes = await _bm25_indexes(engine)

    assert rebuilt.format == POSTGRES_FORMAT
    assert indexes == [("retrieval_search_bm25", True)]


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_a_search_sends_no_join_scan_warning() -> None:
    notices: list[str] = []
    engine = open_database(Settings())

    @event.listens_for(engine.sync_engine, "connect")
    def _collect(dbapi_connection: object, record: object) -> None:
        del record
        driver = getattr(dbapi_connection, "driver_connection", None)
        assert driver is not None
        driver.add_notice_handler(lambda notice: notices.append(notice.message_primary or ""))

    index = _bm25(engine)
    try:
        await migrate(engine)
        assert await index.prepare(create=True) is None
        await index.search_many(["m1"], "retry_policy and more", TagFilter(), 5)
        await index.count_many(["m1"], "retry", TagFilter())
        await index.index(ChunkSet(blob_sha="b", config_hash="c", chunks=()))  # an import's step
    finally:
        await engine.dispose()

    assert notices == []


@needs_pg_search
async def test_a_read_only_process_does_not_make_the_bm25_index_and_falls_back(
    on_pg_search: PostgresDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    del on_pg_search
    caplog.set_level(logging.INFO, "exactdocs.bootstrap.search_engine")
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
    reader = ReadOnlyContainer.build(Settings())

    async with reader.running():
        state = await reader.retrieval.get_search_index_state()
        indexes = await _bm25_indexes(reader.engine)

    assert (state.engine, indexes) == ("postgres_fts", [])
    assert any(
        r.levelno == logging.WARNING and "read-only" in r.getMessage() for r in caplog.records
    )


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_a_reindex_and_a_first_start_build_take_turns_with_a_build_in_progress() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        async with engine.begin() as connection:
            await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
        starting = open_database(Settings())  # a process starting meanwhile
        try:
            async with engine.connect() as holder:  # a third process is building the index
                held = await holder.execution_options(isolation_level="AUTOCOMMIT")
                await held.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _PG_BM25_LOCK})
                reindex = asyncio.create_task(container.retrieval.rebuild_search_index())
                start = asyncio.create_task(_bm25(starting).prepare(create=True))
                await asyncio.sleep(1.5)
                waiting = (reindex.done(), start.done(), await _next_table_exists(engine))
                await held.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _PG_BM25_LOCK})
                await reindex
                assert await start is None
        finally:
            await starting.dispose()
        indexes = await _bm25_indexes(engine)

    assert waiting == (False, False, False)  # neither began while the lock was held
    assert len(indexes) == 1, indexes
    assert indexes[0][1]  # valid


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_a_reindex_and_a_first_start_build_together_leave_one_bm25_index() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
    engines = [open_database(Settings()) for _ in range(2)]
    try:
        await asyncio.gather(_bm25(engines[0]).rebuild(), _bm25(engines[1]).prepare(create=True))
        indexes = await _bm25_indexes(engines[0])
    finally:
        for engine in engines:
            await engine.dispose()

    assert len(indexes) == 1, indexes
    assert indexes[0][1]  # valid


@needs_pg_search
@pytest.mark.usefixtures("on_pg_search")
async def test_a_failed_bm25_build_falls_back_with_a_warning_instead_of_failing_the_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, "exactdocs.bootstrap.search_engine")
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
    # A build that errors, as a deadlock, a cancel or a full disk would.
    monkeypatch.setattr(pg_search, "_PG_BM25_INDEX", "SELECT 1 / 0")
    again = Container.build(Settings())

    async with again.running(jobs=False):
        state = await again.retrieval.get_search_index_state()
        indexes = await _bm25_indexes(again.engine)

    assert (state.engine, indexes) == ("postgres_fts", [])
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "building the BM25 index failed" in warning.getMessage()


async def _next_table_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(text("SELECT to_regclass('retrieval_search_next')"))
    return found is not None
