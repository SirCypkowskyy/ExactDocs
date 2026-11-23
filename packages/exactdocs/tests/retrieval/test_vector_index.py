"""Adapter contract: every ``VectorIndex`` stores and finds vectors the same way (RET-01).

The shared guarantees: a space holds one model's vectors and is never compared with another,
search is exact and scoped to one manifest (version is a hard filter), vectors are keyed by the
stored chunk (so a blob shared by versions is embedded once) and die with it, and a space goes
building, active, retired. The in-memory index is the reference; SQLite runs sqlite-vec, and
PostgreSQL pgvector (when ``EXACTDOCS_TEST_POSTGRES_URL`` names a server).
"""

import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container, vector_index
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import InMemoryChunkRepository, InMemoryVectorIndex
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.errors import (
    InvalidEmbeddingSpaceError,
    InvalidVectorError,
    RetiredEmbeddingSpaceError,
    UnknownEmbeddingSpaceError,
    VectorDimensionError,
)
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkKey,
    ChunkSet,
    EmbeddingSource,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    ManifestChunk,
    PendingArticle,
    PendingChunks,
    SpaceState,
    TagFilter,
    TagMatch,
    VectorCoverage,
    VectorHit,
    VectorMetric,
    as_float32,
)
from exactdocs.retrieval.ports import ChunkRepository, StoredVectors, VectorIndex
from exactdocs.retrieval.use_cases import ExternalIndexes, ExternalVectorIndex
from index_backends import VECTOR_BACKEND_CASES

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
SMALL = EmbeddingSpec(profile_kind="openai", model="a", dimensions=3)
LARGE = EmbeddingSpec(profile_kind="openai", model="b", dimensions=4)
NO_TAGS = TagFilter()


@dataclass(frozen=True, slots=True)
class World:
    chunks: ChunkRepository
    vectors: VectorIndex
    store: StoredVectors  # the database's store, which keeps every vector

    async def index(
        self,
        manifest_id: str,
        sets: dict[str, int],
        *,
        tags: dict[str, tuple[str, ...]] | None = None,
        copies: int = 1,
        library: str = "/acme/x",
    ) -> None:
        """Store a manifest with one article per blob; ``sets`` maps blob SHA to chunk count.

        Each chunk's ID is ``<manifest>:<blob>:<position>``; ``tags`` are per blob. ``copies``
        articles hold each blob (``docs/<blob>.md``, then ``docs/<blob>-<n>.md``, chunk IDs
        ``<manifest>:<blob>-<n>:<position>``), as identical files at several paths do.
        """
        chunk_sets = {
            (blob, "cfg"): ChunkSet(
                blob_sha=blob,
                config_hash="cfg",
                chunks=tuple(
                    Chunk(
                        heading_path=(f"{blob} {i}",),
                        occurrence_index=0,
                        content=f"{blob} section {i}",
                        content_hash=f"{blob}-{i}",
                        anchor=f"s{i}",
                    )
                    for i in range(count)
                ),
            )
            for blob, count in sets.items()
        }
        rows = [
            ManifestChunk(
                chunk_id=ChunkId(f"{manifest_id}:{name}:{i}"),
                article_path=f"docs/{name}.md",
                position=i,
                total=count,
                prev_chunk_id=None,
                next_chunk_id=None,
                tags=(tags or {}).get(blob, ()),
                chunk_set=(blob, "cfg"),
            )
            for blob, count in sets.items()
            for name in [blob, *(f"{blob}-{n}" for n in range(1, copies))]
            for i in range(count)
        ]
        manifest = IndexedManifest(
            manifest_id=manifest_id, version_id=f"{library}/{manifest_id}", library=library,
            indexed_at=T0,
        )  # fmt: skip
        await self.chunks.add(manifest, chunk_sets, rows)

    async def near(
        self,
        space: EmbeddingSpace,
        manifest_id: str,
        query: Sequence[float],
        limit: int = 10,
        tag_filter: TagFilter = NO_TAGS,
    ) -> list[VectorHit]:
        return list(await self.vectors.nearest(space.id, manifest_id, query, tag_filter, limit))


@pytest.fixture(
    params=["memory", *SQL_BACKENDS, *(f"external:{name}" for name in VECTOR_BACKEND_CASES)]
)
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    if request.param.startswith("external:"):
        # The domain's ExternalVectorIndex, as RetrievalModule wires it: the in-memory store
        # keeps the vectors, the backend under test answers the searches.
        case = VECTOR_BACKEND_CASES[request.param.removeprefix("external:")]
        assert case.vectors is not None
        async with case.vectors() as backend:
            chunks = InMemoryChunkRepository()
            store = InMemoryVectorIndex(chunks=chunks)
            mirror = ExternalIndexes(chunks=chunks, vectors=backend, store=store, stored=store)
            external = ExternalVectorIndex(
                store=store, backend=backend, chunks=chunks, mirror=mirror
            )
            yield World(chunks, external, store)
        return
    if request.param == "memory":
        chunks = InMemoryChunkRepository()
        store = InMemoryVectorIndex(chunks=chunks)
        yield World(chunks, store, store)
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        vectors = vector_index(engine)  # as the app picks it: libSQL's own vectors there (#474)
        yield World(SqliteChunkRepository(engine=engine), vectors, vectors)


def key(blob: str, position: int = 0) -> ChunkKey:
    return (blob, "cfg", position)


def ids(hits: list[VectorHit]) -> list[str]:
    return [h.chunk_id for h in hits]


# ---------------------------------------------------------------- spaces


async def test_a_new_space_is_building_with_its_spec_and_no_activation(world: World) -> None:
    space = await world.vectors.create_space(SMALL, T0)

    assert (space.spec, space.state, space.created_at, space.activated_at) == (
        SMALL,
        SpaceState.BUILDING,
        T0,
        None,
    )
    assert space.spec.metric is VectorMetric.COSINE
    assert await world.vectors.spaces() == [space]


async def test_a_space_is_activated_then_retired_and_its_vectors_go(world: World) -> None:
    await world.index("m1", {"b1": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("b1"): [1, 0, 0]})

    active = await world.vectors.activate_space(space.id, T0 + timedelta(hours=1))
    again = await world.vectors.activate_space(space.id, T0 + timedelta(hours=2))
    await world.vectors.retire_space(space.id)
    await world.vectors.retire_space(space.id)  # a no-op the second time

    assert (active.state, active.activated_at) == (SpaceState.ACTIVE, T0 + timedelta(hours=1))
    assert again.activated_at == active.activated_at  # the first activation is kept
    (retired,) = await world.vectors.spaces()
    assert retired.state is SpaceState.RETIRED
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.near(space, "m1", [1, 0, 0])
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.upsert(space.id, {key("b1"): [1, 0, 0]})
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.activate_space(space.id, T0)
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.coverage(space.id, "m1")


async def test_space_ids_are_never_reused(world: World) -> None:
    first = await world.vectors.create_space(SMALL, T0)
    await world.vectors.retire_space(first.id)
    second = await world.vectors.create_space(SMALL, T0)

    assert second.id != first.id
    assert [s.id for s in await world.vectors.spaces()] == [first.id, second.id]


async def test_an_unknown_space_is_not_found(world: World) -> None:
    missing = EmbeddingSpaceId(999)

    for call in (
        world.vectors.activate_space(missing, T0),
        world.vectors.retire_space(missing),
        world.vectors.upsert(missing, {}),
        world.vectors.delete(missing, []),
        world.vectors.nearest(missing, "m1", [1, 0, 0], NO_TAGS, 5),
        world.vectors.coverage(missing, "m1"),
        world.vectors.missing(missing, "m1", 5),
        world.vectors.count_missing(missing, "m1"),
    ):
        with pytest.raises(UnknownEmbeddingSpaceError):
            await call


@pytest.mark.parametrize(
    ("kind", "model", "dimensions"),
    [("openai", " ", 3), ("", "a", 3), ("openai", "a", 0), ("openai", "a", 16_001)],
)
def test_a_spec_no_store_can_hold_is_refused(kind: str, model: str, dimensions: int) -> None:
    with pytest.raises(InvalidEmbeddingSpaceError):
        EmbeddingSpec(profile_kind=kind, model=model, dimensions=dimensions)


# ---------------------------------------------------------------- search


async def test_nearest_chunks_come_only_from_the_manifest_nearest_first_with_distances(
    world: World,
) -> None:
    await world.index("v13", {"old": 2})
    await world.index("v14", {"new": 3})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(
        space.id,
        {
            key("old", 0): [1, 0, 0],  # identical to the query, but in the other version
            key("old", 1): [1, 0.1, 0],
            key("new", 0): [0, 1, 0],
            key("new", 1): [1, 1, 0],
            key("new", 2): [-1, 0, 0],
        },
    )

    hits = await world.near(space, "v14", [1, 0, 0], limit=2)

    assert ids(hits) == ["v14:new:1", "v14:new:0"]
    assert hits[0].distance == pytest.approx(1 - 1 / math.sqrt(2), abs=1e-6)
    assert hits[1].distance == pytest.approx(1, abs=1e-6)
    every = await world.near(space, "v14", [1, 0, 0])
    assert ids(every) == ["v14:new:1", "v14:new:0", "v14:new:2"]
    assert every[2].distance == pytest.approx(2, abs=1e-6)


async def test_a_wrong_version_gets_nothing(world: World) -> None:
    await world.index("v13", {"old": 1})
    await world.index("v14", {"new": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("old"): [1, 0, 0]})

    assert await world.near(space, "v14", [1, 0, 0]) == []
    assert await world.near(space, "unknown-manifest", [1, 0, 0]) == []


async def test_a_blob_shared_by_two_versions_has_one_vector_found_from_both(world: World) -> None:
    await world.index("v13", {"shared": 1})
    await world.index("v14", {"shared": 1})
    space = await world.vectors.create_space(SMALL, T0)

    stored = await world.vectors.upsert(space.id, {key("shared"): [0, 0, 1]})

    assert stored == 1
    assert ids(await world.near(space, "v13", [0, 0, 1])) == ["v13:shared:0"]
    assert ids(await world.near(space, "v14", [0, 0, 1])) == ["v14:shared:0"]
    assert await world.vectors.coverage(space.id, "v13") == VectorCoverage(chunks=1, embedded=1)


async def test_ties_are_broken_by_chunk_id(world: World) -> None:
    await world.index("m", {"b": 2, "a": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(
        space.id, {key("b", 1): [0, 2, 0], key("a"): [0, 1, 0], key("b", 0): [0, 3, 0]}
    )

    assert ids(await world.near(space, "m", [0, 1, 0])) == ["m:a:0", "m:b:0", "m:b:1"]


@pytest.mark.parametrize(
    ("tags", "match", "expected"),
    [
        (("api",), TagMatch.ANY, ["m:far:0"]),
        (("api", "v2"), TagMatch.ANY, ["m:mid:0", "m:far:0"]),
        (("api", "v2"), TagMatch.ALL, []),
    ],
)
async def test_tags_filter_before_ranking(
    world: World, tags: tuple[str, ...], match: TagMatch, expected: list[str]
) -> None:
    await world.index("m", {"near": 1, "mid": 1, "far": 1}, tags={"mid": ("v2",), "far": ("api",)})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(
        space.id, {key("near"): [1, 0, 0], key("mid"): [1, 1, 0], key("far"): [0, 1, 0]}
    )

    hits = await world.near(
        space, "m", [1, 0, 0], limit=2, tag_filter=TagFilter(tags=tags, match=match)
    )

    assert ids(hits) == expected


# ---------------------------------------------------------------- two models never meet


async def test_vectors_of_two_spaces_are_never_compared(world: World) -> None:
    await world.index("m", {"b": 2})
    small = await world.vectors.create_space(SMALL, T0)
    large = await world.vectors.create_space(LARGE, T0)
    await world.vectors.upsert(small.id, {key("b", 0): [1, 0, 0]})
    await world.vectors.upsert(large.id, {key("b", 1): [0, 0, 0, 1]})

    assert ids(await world.near(large, "m", [0, 0, 0, 1])) == ["m:b:1"]
    assert ids(await world.near(small, "m", [1, 0, 0])) == ["m:b:0"]
    with pytest.raises(VectorDimensionError):
        await world.near(small, "m", [0, 0, 0, 1])  # a query of the other model


async def test_a_vector_of_the_wrong_size_stores_nothing(world: World) -> None:
    await world.index("m", {"b": 2})
    space = await world.vectors.create_space(SMALL, T0)

    with pytest.raises(VectorDimensionError, match="4 dimensions; the embedding space has 3"):
        await world.vectors.upsert(space.id, {key("b", 0): [1, 0, 0], key("b", 1): [1, 0, 0, 0]})

    assert await world.vectors.coverage(space.id, "m") == VectorCoverage(chunks=2, embedded=0)


@pytest.mark.parametrize("vector", [[0, 0, 0], [math.nan, 1, 0], [math.inf, 1, 0], [1e39, 1, 0]])
async def test_a_vector_without_a_direction_or_with_no_float32_value_is_refused(
    world: World, vector: list[float]
) -> None:
    await world.index("m", {"b": 1})
    space = await world.vectors.create_space(SMALL, T0)

    with pytest.raises(InvalidVectorError):
        await world.vectors.upsert(space.id, {key("b"): vector})
    with pytest.raises(InvalidVectorError):
        await world.near(space, "m", vector)


# ---------------------------------------------------------------- writes, coverage, cleanup


async def test_upsert_replaces_and_skips_chunks_that_are_not_stored(world: World) -> None:
    await world.index("m", {"b": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("b"): [1, 0, 0]})

    stored = await world.vectors.upsert(space.id, {key("b"): [0, 1, 0], key("gone"): [1, 0, 0]})

    assert stored == 1
    (hit,) = await world.near(space, "m", [0, 1, 0])
    assert hit.distance == pytest.approx(0, abs=1e-6)


async def test_deleted_vectors_are_no_longer_found(world: World) -> None:
    await world.index("m", {"b": 2})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("b", 0): [1, 0, 0], key("b", 1): [0, 1, 0]})

    deleted = await world.vectors.delete(space.id, [key("b", 0), key("b", 0), key("nothing")])

    assert deleted == 1
    assert ids(await world.near(space, "m", [1, 0, 0])) == ["m:b:1"]


async def test_coverage_and_missing_chunks_of_a_manifest(world: World) -> None:
    await world.index("m", {"a": 2, "b": 1})
    space = await world.vectors.create_space(SMALL, T0)
    empty = await world.vectors.coverage(space.id, "m")
    await world.vectors.upsert(space.id, {key("a", 1): [1, 0, 0]})

    coverage = await world.vectors.coverage(space.id, "m")

    assert (empty, empty.complete) == (VectorCoverage(chunks=3, embedded=0), False)
    assert coverage == VectorCoverage(chunks=3, embedded=1)
    assert await world.vectors.missing(space.id, "m", 10) == [key("a", 0), key("b", 0)]
    assert await world.vectors.missing(space.id, "m", 1) == [key("a", 0)]
    await world.vectors.upsert(space.id, {key("a", 0): [1, 0, 0], key("b", 0): [1, 0, 0]})
    assert (await world.vectors.coverage(space.id, "m")).complete
    assert await world.vectors.missing(space.id, "m", 10) == []
    assert (await world.vectors.coverage(space.id, "unknown")).complete


async def test_missing_chunks_are_counted_once_each_like_the_keys_returned(
    world: World,
) -> None:
    await world.index("m", {"a": 2, "b": 1}, copies=3)  # the same files at three paths
    await world.index("n", {"a": 2})  # another version sharing blob a
    space = await world.vectors.create_space(SMALL, T0)

    before = await world.vectors.count_missing(space.id, "m")
    await world.vectors.upsert(space.id, {key("a", 0): [1, 0, 0], key("a", 1): [0, 1, 0]})

    assert (await world.vectors.coverage(space.id, "m")).chunks == 9  # rows, one per path
    assert before == 3  # a's two chunks and b's one, whatever the number of paths
    assert await world.vectors.count_missing(space.id, "m") == 1  # only b's chunk is left
    assert await world.vectors.missing(space.id, "m", 100) == [key("b", 0)]
    assert await world.vectors.count_missing(space.id, "n") == 0  # embedded through m
    assert await world.vectors.count_missing(space.id, "unknown") == 0
    await world.vectors.retire_space(space.id)
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.count_missing(space.id, "m")


async def test_coverage_of_many_manifests_is_counted_at_once(world: World) -> None:
    await world.index("m", {"a": 2, "b": 1})
    await world.index("n", {"a": 2})  # shares blob a with m: counted for each manifest
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("a", 1): [1, 0, 0]})

    found = await world.vectors.coverage_many(space.id, ["m", "n", "unknown"])

    assert found == {
        "m": VectorCoverage(chunks=3, embedded=1),
        "n": VectorCoverage(chunks=2, embedded=1),
    }
    assert await world.vectors.coverage_many(space.id, []) == {}
    await world.vectors.retire_space(space.id)
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.coverage_many(space.id, ["m"])


async def test_vectors_are_removed_with_their_chunk_sets(world: World) -> None:
    await world.index("v13", {"old": 1, "shared": 1})
    await world.index("v14", {"shared": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("old"): [1, 0, 0], key("shared"): [0, 1, 0]})

    await world.chunks.remove(["v13"])  # garbage collection of the old version
    await world.index("v13b", {"old": 1})  # the same blob comes back: embedded anew

    assert await world.vectors.coverage(space.id, "v13b") == VectorCoverage(chunks=1, embedded=0)
    assert ids(await world.near(space, "v14", [0, 1, 0])) == ["v14:shared:0"]


async def test_the_store_can_search(world: World) -> None:
    assert await world.vectors.available()


async def test_a_vector_is_at_distance_zero_from_itself_never_below(world: World) -> None:
    await world.index("m", {"b": 20})
    space = await world.vectors.create_space(LARGE, T0)
    vectors = {key("b", i): [0.1 * i + 0.3, -0.7 * i, 1.3, i**0.5 - 2.1] for i in range(20)}
    await world.vectors.upsert(space.id, vectors)

    for i, vector in enumerate(vectors.values()):
        (hit,) = await world.near(space, "m", vector, limit=1)
        assert hit.chunk_id == f"m:b:{i}"
        assert 0 <= hit.distance < 1e-6


# ---------------------------------------------------------------- embedding jobs (#91)


def characters(blob: str, position: int) -> int:
    """The characters ``pending`` counts for a chunk ``World.index`` stores: text and headings."""
    return len(f"{blob} section {position}") + len(f"{blob} {position}")


async def test_pending_counts_each_stored_chunk_once_across_manifests(world: World) -> None:
    await world.index("m1", {"b1": 2})
    await world.index("m2", {"b1": 2, "b2": 1})

    pending = await world.vectors.pending(None, ["m1", "m2"])

    expected = characters("b1", 0) + characters("b1", 1) + characters("b2", 0)
    assert pending == PendingChunks(
        chunks=3,
        characters=expected,
        # Each chunk once, under its first manifest and path: b1's under m1, b2's under m2.
        articles=(
            PendingArticle(manifest_id="m1", article_path="docs/b1.md", chunks=2),
            PendingArticle(manifest_id="m2", article_path="docs/b2.md", chunks=1),
        ),
    )
    assert await world.vectors.pending(None, []) == PendingChunks(chunks=0, characters=0)
    assert await world.vectors.pending(None, ["unknown"]) == PendingChunks(chunks=0, characters=0)


async def test_pending_leaves_out_chunks_with_a_vector_in_the_space(world: World) -> None:
    await world.index("m1", {"b1": 2, "b2": 1})
    space = await world.vectors.create_space(SMALL, T0)
    other = await world.vectors.create_space(LARGE, T0)
    await world.vectors.upsert(space.id, {key("b1", 0): [1, 0, 0], key("b2"): [0, 1, 0]})

    assert await world.vectors.pending(space.id, ["m1"]) == PendingChunks(
        chunks=1,
        characters=characters("b1", 1),
        articles=(PendingArticle(manifest_id="m1", article_path="docs/b1.md", chunks=1),),
    )
    assert (await world.vectors.pending(other.id, ["m1"])).chunks == 3
    await world.vectors.retire_space(space.id)
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.vectors.pending(space.id, ["m1"])


async def test_embedding_sources_read_the_text_heading_path_and_article(world: World) -> None:
    await world.index("m1", {"b1": 2})
    await world.index("m2", {"b2": 1})

    found = await world.chunks.embedding_sources("m1", [key("b1", 1), key("b2"), key("zz")])

    assert found == {
        key("b1", 1): EmbeddingSource(
            article_path="docs/b1.md", heading_path=("b1 1",), content="b1 section 1"
        )
    }
    assert await world.chunks.embedding_sources("m1", []) == {}


# ---------------------------------------------------------------- per version (#352)


async def test_removing_one_version_leaves_the_vectors_another_version_shares(
    world: World,
) -> None:
    await world.index("v13", {"shared": 1, "old": 1})
    await world.index("v14", {"shared": 1})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("shared"): [0, 1, 0], key("old"): [1, 0, 0]})

    await world.chunks.remove(["v13"])

    assert await world.near(space, "v13", [0, 1, 0]) == []
    assert ids(await world.near(space, "v14", [0, 1, 0])) == ["v14:shared:0"]


async def test_versions_of_another_library_are_not_searched(world: World) -> None:
    await world.index("a1", {"same": 1})
    await world.index("b1", {"same": 1}, library="/other/lib")
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("same"): [0, 0, 1]})

    assert ids(await world.near(space, "a1", [0, 0, 1])) == ["a1:same:0"]
    assert ids(await world.near(space, "b1", [0, 0, 1])) == ["b1:same:0"]


async def test_the_top_k_is_the_k_nearest_in_order(world: World) -> None:
    await world.index("m", {"b": 5})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("b", i): [1, 0.5 * i, 0] for i in range(5)})

    hits = await world.near(space, "m", [1, 0, 0], limit=3)

    assert ids(hits) == ["m:b:0", "m:b:1", "m:b:2"]
    assert [h.distance for h in hits] == sorted(h.distance for h in hits)


async def test_a_version_without_vectors_or_unknown_gets_an_empty_result(world: World) -> None:
    space = await world.vectors.create_space(SMALL, T0)
    assert await world.near(space, "m", [1, 0, 0]) == []  # nothing stored at all

    await world.index("m", {"b": 2})

    assert await world.near(space, "m", [1, 0, 0]) == []  # chunks, but no vector yet
    assert await world.near(space, "unknown", [1, 0, 0]) == []


async def test_stored_vectors_are_read_back_as_the_store_keeps_them(world: World) -> None:
    await world.index("m", {"b": 2})
    space = await world.vectors.create_space(SMALL, T0)
    await world.vectors.upsert(space.id, {key("b", 0): [0.1, 0.2, 0.3]})

    found = await world.store.stored(space.id, [key("b", 0), key("b", 1), key("zz")])

    assert list(found) == [key("b", 0)]
    assert found[key("b", 0)] == pytest.approx((0.1, 0.2, 0.3), abs=1e-7)  # float32
    assert found[key("b", 0)] == as_float32(found[key("b", 0)])
    await world.vectors.retire_space(space.id)
    with pytest.raises(RetiredEmbeddingSpaceError):
        await world.store.stored(space.id, [key("b", 0)])
