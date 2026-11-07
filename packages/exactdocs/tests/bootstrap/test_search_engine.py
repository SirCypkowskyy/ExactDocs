"""On PostgreSQL the search engine is chosen at start: `pg_search` when the database has it.

Needs ``EXACTDOCS_TEST_POSTGRES_URL``; the `pg_search` cases also need a server that has the
extension (``EXACTDOCS_TEST_PG_SEARCH=1``, as on CI's ParadeDB).
"""

import logging

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app_lifespan import serving
from databases import ADMIN_URL, PG_SEARCH, PostgresDatabase
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

if ADMIN_URL is None:
    pytest.skip("needs a PostgreSQL server (EXACTDOCS_TEST_POSTGRES_URL)", allow_module_level=True)

needs_pg_search = pytest.mark.skipif(not PG_SEARCH, reason="the server has no pg_search")

BM25_INDEXES = """
    SELECT ix.relname FROM pg_index i
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


async def _bm25_indexes(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        return list((await connection.execute(text(BM25_INDEXES))).scalars())


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
    assert "CREATE EXTENSION pg_search" in caplog.text


@needs_pg_search
async def test_with_pg_search_bm25_answers_and_its_index_is_made_once(
    on_pg_search: PostgresDatabase,
) -> None:
    del on_pg_search
    first = Container.build(Settings())

    health = await _health(first)
    async with Container.build(Settings()).running(jobs=False):  # a second start, as a 2nd process
        pass

    assert health["search_engine"] == "pg_search"
    second = Container.build(Settings())
    async with second.running(jobs=False):
        assert await _bm25_indexes(second.engine) == ["retrieval_search_bm25"]


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

    assert indexes == ["retrieval_search_bm25"]
    assert (state.engine, state.needs_rebuild) == ("pg_search", False)


@needs_pg_search
async def test_a_read_only_process_does_not_make_the_bm25_index_and_falls_back(
    on_pg_search: PostgresDatabase,
) -> None:
    del on_pg_search
    container = Container.build(Settings())
    async with container.running(jobs=False), container.engine.begin() as connection:
        await connection.exec_driver_sql("DROP INDEX retrieval_search_bm25")
    reader = ReadOnlyContainer.build(Settings())

    async with reader.running():
        state = await reader.retrieval.get_search_index_state()
        indexes = await _bm25_indexes(reader.engine)

    assert (state.engine, indexes) == ("postgres_fts", [])
