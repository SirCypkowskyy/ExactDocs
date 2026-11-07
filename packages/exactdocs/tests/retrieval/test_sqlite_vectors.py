"""What only the SQLite vector index does: tables per space, sqlite-vec loaded lazily, backups."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.backup import create_backup, restore_backup
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_vectors import SqliteVectorIndex
from exactdocs.retrieval.errors import VectorStoreUnavailableError
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

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
SPEC = EmbeddingSpec(profile_kind="openai", model="a", dimensions=3)


def _broken_extension() -> str:
    """Stand for a Python whose sqlite-vec does not load."""
    return "/nowhere/vec0"


def _missing_package() -> str:
    """Stand for an install without the ``[ai]`` extra."""
    name = "sqlite_vec"
    raise ModuleNotFoundError(name)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield container.engine


async def _store_manifest(engine: AsyncEngine, manifest_id: str = "m1") -> None:
    chunk = Chunk(
        heading_path=("Retries",), occurrence_index=0, content="x", content_hash="h", anchor="r"
    )
    await SqliteChunkRepository(engine=engine).add(
        IndexedManifest(
            manifest_id=manifest_id, version_id="/acme/x/v1", library="/acme/x", indexed_at=T0
        ),
        {("b1", "cfg"): ChunkSet(blob_sha="b1", config_hash="cfg", chunks=(chunk,))},
        [
            ManifestChunk(
                chunk_id=ChunkId("c1"), article_path="docs/a.md", position=0, total=1,
                prev_chunk_id=None, next_chunk_id=None, tags=(), chunk_set=("b1", "cfg"),
            )
        ],
    )  # fmt: skip


async def _tables(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE name LIKE 'retrieval_vec_%' ORDER BY name")
        )
        return [r.name for r in rows]


async def test_each_space_has_its_own_table_until_it_is_retired(engine: AsyncEngine) -> None:
    vectors = SqliteVectorIndex(engine=engine)
    first = await vectors.create_space(SPEC, T0)
    second = await vectors.create_space(SPEC, T0)

    created = await _tables(engine)
    await vectors.retire_space(first.id)

    assert created == [f"retrieval_vec_{first.id}", f"retrieval_vec_{second.id}"]
    assert await _tables(engine) == [f"retrieval_vec_{second.id}"]


@pytest.mark.parametrize("extension", [_broken_extension, _missing_package])
async def test_without_sqlite_vec_vectors_are_kept_but_cannot_be_searched(
    engine: AsyncEngine, extension: Callable[[], str]
) -> None:
    vectors = SqliteVectorIndex(engine=engine, extension=extension)
    await _store_manifest(engine)
    space = await vectors.create_space(SPEC, T0)

    stored = await vectors.upsert(space.id, {("b1", "cfg", 0): [1, 0, 0]})

    assert stored == 1
    assert await vectors.coverage(space.id, "m1") == VectorCoverage(chunks=1, embedded=1)
    assert not await vectors.available()
    with pytest.raises(VectorStoreUnavailableError) as error:
        await vectors.nearest(space.id, "m1", [1, 0, 0], TagFilter(), 5)
    assert error.value.code == "vector_store_unavailable"


async def test_sqlite_vec_is_loaded_only_by_a_search(engine: AsyncEngine) -> None:
    vectors = SqliteVectorIndex(engine=engine)
    await _store_manifest(engine)
    space = await vectors.create_space(SPEC, T0)
    await vectors.upsert(space.id, {("b1", "cfg", 0): [1, 0, 0]})
    await vectors.coverage(space.id, "m1")
    loaded = text("SELECT count(*) FROM pragma_function_list WHERE name = 'vec_distance_cosine'")

    async with engine.connect() as connection:
        before = await connection.scalar(loaded)
        (hit,) = await vectors.nearest(space.id, "m1", [1, 0, 0], TagFilter(), 5)
        after = await connection.scalar(loaded)

    assert (before, hit.chunk_id) == (0, "c1")
    assert after == 0  # the search loaded it into its own connection only


async def test_reindex_leaves_the_vectors_alone() -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        vectors = SqliteVectorIndex(engine=container.engine)
        await _store_manifest(container.engine)
        space = await vectors.create_space(SPEC, T0)
        await vectors.upsert(space.id, {("b1", "cfg", 0): [1, 0, 0]})

        await container.retrieval.rebuild_search_index()

        coverage = await vectors.coverage(space.id, "m1")
        hits = await vectors.nearest(space.id, "m1", [1, 0, 0], TagFilter(), 5)
    assert coverage == VectorCoverage(chunks=1, embedded=1)
    assert [h.chunk_id for h in hits] == ["c1"]


async def test_a_backup_round_trips_the_spaces_and_their_vectors(tmp_path: Path) -> None:
    source, target = Settings(data_dir=tmp_path / "source"), Settings(data_dir=tmp_path / "target")
    container = Container.build(source)
    async with container.running(jobs=False):
        vectors = SqliteVectorIndex(engine=container.engine)
        await _store_manifest(container.engine)
        space = await vectors.create_space(SPEC, T0)
        active = await vectors.activate_space(space.id, T0)
        await vectors.upsert(space.id, {("b1", "cfg", 0): [0, 1, 0]})

    create_backup(source, tmp_path / "backup.tar.gz")
    await restore_backup(target, tmp_path / "backup.tar.gz")

    restored = open_database(target)
    try:
        vectors = SqliteVectorIndex(engine=restored)
        assert await vectors.spaces() == [active]
        (hit,) = await vectors.nearest(space.id, "m1", [0, 1, 0], TagFilter(), 5)
        assert (hit.chunk_id, round(hit.distance, 6)) == ("c1", 0)
    finally:
        await restored.dispose()
