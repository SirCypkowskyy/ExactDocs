"""What only the pgvector index does: ``vector(<n>)`` tables per space, the extension created once.

These run only with ``EXACTDOCS_TEST_POSTGRES_URL`` (CI: ParadeDB, which ships pgvector). The
behaviour every vector store shares is in ``test_vector_index.py``.
"""

import asyncio
import math
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import ADMIN_URL, SECRET_KEY, PostgresDatabase, postgres_database
from exactdocs.bootstrap import database
from exactdocs.bootstrap.constants import WRITE_LOCK
from exactdocs.bootstrap.container import Container, vector_index
from exactdocs.bootstrap.database import open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.postgres_vectors import PostgresVectorIndex
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.errors import (
    RetiredEmbeddingSpaceError,
    VectorDimensionError,
    VectorStoreUnavailableError,
)
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkSet,
    EmbeddingSpec,
    IndexedManifest,
    ManifestChunk,
    TagFilter,
    VectorCoverage,
)

pytestmark = pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
SPEC = EmbeddingSpec(profile_kind="openai", model="a", dimensions=3)
LARGE = 3072
"""text-embedding-3-large: above pgvector's 2,000-dimension limit for an index on ``vector``."""


@pytest.fixture
async def engine(on_postgres: PostgresDatabase) -> AsyncIterator[AsyncEngine]:
    del on_postgres
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield container.engine


@pytest.fixture
def without_vector(monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresDatabase]:
    """A database without the ``vector`` extension, owned by a role that may not create it.

    Yields:
        The database.
    """
    with postgres_database(owner_without_createdb=True, without_extensions=("vector",)) as db:
        monkeypatch.setenv("EXACTDOCS_DATABASE_URL", db.url)
        monkeypatch.setenv("EXACTDOCS_SECRET_KEY", SECRET_KEY)
        yield db


def _as_admin(database: PostgresDatabase, statement: str) -> None:
    """Run one statement in the test's database as the server's superuser."""
    url = make_url(ADMIN_URL or "").set(drivername="postgresql", database=database.name)
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as admin:
        admin.execute(statement.encode())


async def _store_manifest(engine: AsyncEngine, manifest_id: str = "m1", chunks: int = 1) -> None:
    sets = {
        ("b1", "cfg"): ChunkSet(
            blob_sha="b1",
            config_hash="cfg",
            chunks=tuple(
                Chunk(
                    heading_path=(f"H{i}",),
                    occurrence_index=0,
                    content=f"x{i}",
                    content_hash=f"h{i}",
                    anchor=f"a{i}",
                )
                for i in range(chunks)
            ),
        )
    }
    rows = [
        ManifestChunk(
            chunk_id=ChunkId(f"c{i}"),
            article_path="docs/a.md",
            position=i,
            total=chunks,
            prev_chunk_id=None,
            next_chunk_id=None,
            tags=(),
            chunk_set=("b1", "cfg"),
        )
        for i in range(chunks)
    ]
    manifest = IndexedManifest(
        manifest_id=manifest_id, version_id="/acme/x/v1", library="/acme/x", indexed_at=T0
    )
    await SqliteChunkRepository(engine=engine).add(manifest, sets, rows)


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with engine.connect() as connection:
        return [tuple(r) for r in await connection.execute(text(sql), params)]


async def test_the_container_picks_pgvector_on_postgresql(engine: AsyncEngine) -> None:
    assert isinstance(vector_index(engine), PostgresVectorIndex)
    assert vector_index(engine).requirement() == "vector"


async def test_each_space_has_a_vector_table_of_its_dimensions_until_it_is_retired(
    engine: AsyncEngine,
) -> None:
    vectors = PostgresVectorIndex(engine=engine)
    small = await vectors.create_space(SPEC, T0)
    large = await vectors.create_space(
        EmbeddingSpec(profile_kind="openai", model="b", dimensions=LARGE), T0
    )

    columns = await _rows(
        engine,
        "SELECT c.relname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a"
        " JOIN pg_class c ON c.oid = a.attrelid"
        " WHERE c.relname LIKE 'retrieval_vec_%' AND a.attname = 'embedding' ORDER BY c.relname",
    )
    await vectors.retire_space(small.id)
    left = await _rows(
        engine,
        "SELECT relname FROM pg_class WHERE relname LIKE 'retrieval_vec_%' AND relkind = 'r'",
    )

    assert columns == [
        (f"retrieval_vec_{small.id}", "vector(3)"),
        (f"retrieval_vec_{large.id}", f"vector({LARGE})"),
    ]
    assert left == [(f"retrieval_vec_{large.id}",)]


async def test_dimensions_above_the_index_limit_are_searched_exactly(engine: AsyncEngine) -> None:
    await _store_manifest(engine, chunks=3)
    vectors = PostgresVectorIndex(engine=engine)
    space = await vectors.create_space(
        EmbeddingSpec(profile_kind="openai", model="large", dimensions=LARGE), T0
    )
    basis = [[1.0 if d == i else 0.0 for d in range(LARGE)] for i in range(3)]
    await vectors.upsert(space.id, {("b1", "cfg", i): v for i, v in enumerate(basis)})
    query = [1.0, 1.0] + [0.0] * (LARGE - 2)

    hits = await vectors.nearest(space.id, "m1", query, TagFilter(), 3)

    assert [h.chunk_id for h in hits] == ["c0", "c1", "c2"]
    assert [h.distance for h in hits] == pytest.approx([1 - 1 / math.sqrt(2)] * 2 + [1], abs=1e-6)


async def test_the_extension_is_created_when_the_role_may(on_postgres: PostgresDatabase) -> None:
    _as_admin(on_postgres, "DROP EXTENSION IF EXISTS vector CASCADE")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        vectors = PostgresVectorIndex(engine=container.engine)
        assert await vectors.available()
        installed = await _rows(
            container.engine, "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
        await vectors.create_space(SPEC, T0)

    assert installed == [("vector",)]


@pytest.mark.usefixtures("without_vector")
async def test_a_role_that_may_not_create_the_extension_gets_a_clear_error() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        vectors = PostgresVectorIndex(engine=container.engine)

        assert not await vectors.available()
        with pytest.raises(VectorStoreUnavailableError) as error:
            await vectors.create_space(SPEC, T0)
        assert await vectors.spaces() == []  # nothing half-made

    message = str(error.value)
    assert 'extension "vector"' in message
    assert "CREATE EXTENSION vector" in message  # what the operator has to run
    assert error.value.code == "vector_store_unavailable"


async def test_the_extension_is_tried_once_per_process(without_vector: PostgresDatabase) -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        first = PostgresVectorIndex(engine=container.engine)
        assert not await first.available()
        _as_admin(without_vector, "CREATE EXTENSION vector")

        again = await first.available()  # not tried again: every search asks
        restarted = await PostgresVectorIndex(engine=container.engine).available()

    assert (again, restarted) == (False, True)


async def test_without_the_ai_extra_the_store_cannot_search(engine: AsyncEngine) -> None:
    def missing_package() -> Any:
        name = "pgvector"
        raise ModuleNotFoundError(name)

    vectors = PostgresVectorIndex(engine=engine, vector_type=missing_package)

    assert not await vectors.available()
    with pytest.raises(VectorStoreUnavailableError, match=r"\[ai\] extra"):
        await vectors.create_space(SPEC, T0)


async def test_a_space_retired_by_another_process_is_reported_retired(
    engine: AsyncEngine,
) -> None:
    await _store_manifest(engine)
    searching, other = PostgresVectorIndex(engine=engine), PostgresVectorIndex(engine=engine)
    space = await searching.create_space(SPEC, T0)
    await searching.upsert(space.id, {("b1", "cfg", 0): [1, 0, 0]})
    assert len(await searching.nearest(space.id, "m1", [1, 0, 0], TagFilter(), 5)) == 1

    await other.retire_space(space.id)

    with pytest.raises(RetiredEmbeddingSpaceError):
        await searching.nearest(space.id, "m1", [1, 0, 0], TagFilter(), 5)
    assert await other.spaces() != []


async def test_vectors_go_with_their_chunks_on_postgresql(engine: AsyncEngine) -> None:
    await _store_manifest(engine)
    vectors = PostgresVectorIndex(engine=engine)
    space = await vectors.create_space(SPEC, T0)
    await vectors.upsert(space.id, {("b1", "cfg", 0): [1, 0, 0]})

    await SqliteChunkRepository(engine=engine).remove(["m1"])
    await _store_manifest(engine, "m2")  # the same blob comes back: embedded anew

    assert await vectors.coverage(space.id, "m1") == VectorCoverage(chunks=0, embedded=0)
    assert await vectors.coverage(space.id, "m2") == VectorCoverage(chunks=1, embedded=0)


async def test_a_new_process_can_write_and_search_first_thing(engine: AsyncEngine) -> None:
    # The extension is looked for outside the write turn the upsert takes, or it would wait for
    # itself until the turn times out.
    await _store_manifest(engine)
    space = await PostgresVectorIndex(engine=engine).create_space(SPEC, T0)

    stored = await PostgresVectorIndex(engine=engine).upsert(
        space.id, {("b1", "cfg", 0): [1, 0, 0]}
    )
    hits = await PostgresVectorIndex(engine=engine).nearest(
        space.id, "m1", [1, 0, 0], TagFilter(), 1
    )

    assert (stored, [h.chunk_id for h in hits]) == (1, ["c0"])


# ---------------------------------------------------------------- review round 1


async def test_a_read_only_process_waits_for_the_extension_instead_of_giving_up(
    on_postgres: PostgresDatabase,
) -> None:
    # `serve --stdio` reads through a read-only engine: it may not create the extension, and
    # must see it once the server has.
    _as_admin(on_postgres, "DROP EXTENSION IF EXISTS vector CASCADE")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        reader = open_database(Settings(), read_only=True)
        try:
            store = PostgresVectorIndex(engine=reader)
            assert not await store.available()
            with pytest.raises(VectorStoreUnavailableError, match="not created yet") as error:
                await store.create_space(SPEC, T0)
            assert "restart" not in str(error.value)

            assert await PostgresVectorIndex(engine=container.engine).available()  # the server
            seen = await store.available()
        finally:
            await reader.dispose()

    assert seen


async def test_a_present_extension_is_found_without_waiting_for_the_write_turn(
    on_postgres: PostgresDatabase, engine: AsyncEngine
) -> None:
    _as_admin(on_postgres, "CREATE EXTENSION IF NOT EXISTS vector")
    async with engine.begin() as holder:  # another process holds the write turn
        await holder.execute(text(f"SELECT pg_advisory_xact_lock({WRITE_LOCK})"))
        assert await asyncio.wait_for(PostgresVectorIndex(engine=engine).available(), 5)


async def test_a_write_turn_that_times_out_falls_back_and_is_tried_again(
    on_postgres: PostgresDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_admin(on_postgres, "DROP EXTENSION IF EXISTS vector CASCADE")
    monkeypatch.setattr(database, "WRITE_LOCK_TIMEOUT_MS", 200)
    container = Container.build(Settings())
    async with container.running(jobs=False):
        store = PostgresVectorIndex(engine=container.engine)
        async with container.engine.connect() as holder:
            await holder.execute(text(f"SELECT pg_advisory_lock({WRITE_LOCK})"))
            busy = await store.available()
            await holder.execute(text(f"SELECT pg_advisory_unlock({WRITE_LOCK})"))
        later = await store.available()

    assert (busy, later) == (False, True)


async def test_activating_a_space_gives_the_planner_its_statistics(engine: AsyncEngine) -> None:
    await _store_manifest(engine, chunks=3)
    vectors = PostgresVectorIndex(engine=engine)
    space = await vectors.create_space(SPEC, T0)
    await vectors.upsert(space.id, {("b1", "cfg", i): [1, i, 0] for i in range(3)})

    await vectors.activate_space(space.id, T0)

    analyzed = await _rows(
        engine,
        "SELECT last_analyze IS NOT NULL OR last_autoanalyze IS NOT NULL"
        " FROM pg_stat_user_tables WHERE relname = :table",
        table=f"retrieval_vec_{space.id}",
    )
    assert analyzed == [(True,)]


async def test_an_invalid_vector_is_refused_before_the_write_turn(engine: AsyncEngine) -> None:
    await _store_manifest(engine)
    vectors = PostgresVectorIndex(engine=engine)
    space = await vectors.create_space(SPEC, T0)

    async with engine.begin() as holder:  # validating needs no turn: it fails at once
        await holder.execute(text(f"SELECT pg_advisory_xact_lock({WRITE_LOCK})"))
        with pytest.raises(VectorDimensionError):
            await asyncio.wait_for(vectors.upsert(space.id, {("b1", "cfg", 0): [1, 0]}), 5)
