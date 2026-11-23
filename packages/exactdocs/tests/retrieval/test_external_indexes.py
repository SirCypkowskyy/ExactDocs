"""#352: external search and vector backends follow the stored chunks, and are rebuilt from them.

An import writes the version, a removal or a collection deletes it (before the database does), a
re-tag rewrites the tags; a backend that does not answer is tried again, then fails the job that
wrote (nothing is lost: the database still holds it). The check names what a backend lost,
holds in part or still holds after a removal; a rebuild writes it again from the database.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemoryVectorIndex,
)
from exactdocs.retrieval.adapters.driven.memory_index import (
    InMemorySearchBackend,
    InMemoryVectorBackend,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ArticleTagsIn,
    ChunkIn,
    CollectChunksCommand,
    ExternalIndexScope,
    IndexManifestCommand,
    RemoveChunksCommand,
    RetagArticlesCommand,
    SearchDocsQuery,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError, UnknownIndexVersionError
from exactdocs.retrieval.models import (
    DocTarget,
    DriftKind,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    IndexEntry,
    IndexKind,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
    TagFilter,
    TextQuery,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.use_cases import ExternalIndexes, ExternalVectorIndex

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
GUIDE = {
    "retries.md": ["Calls are retried three times.", "Set retry_policy to change it."],
    "auth.md": ["Tokens expire after an hour."],
}
OTHER_GUIDE = {"intro.md": ["Welcome to the other library."]}
SPEC = EmbeddingSpec(profile_kind="openai", model="m", dimensions=3)


@dataclass(slots=True)
class Clock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class Catalog:
    """What the catalog says: each active version, by library and ref."""

    active: dict[tuple[str, str], str] = field(default_factory=dict)

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        manifest = self.active.get((library, ref or "v1"))
        if manifest is None:
            return None
        return SearchableVersion(
            library=library,
            version=ref or "v1",
            manifest_id=manifest,
            commit_sha="c" * 40,
            repository_url="https://github.com/acme/payments",
            host=SourceHost.GITHUB,
        )

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        live = set(self.active.values())
        return {m: ManifestStatus.ACTIVE for m in manifest_ids if m in live}


@dataclass(slots=True)
class Flaky:
    """A search backend that fails the next ``failures`` calls that write, then works."""

    inner: InMemorySearchBackend = field(default_factory=InMemorySearchBackend)
    failures: int = 0
    calls: int = 0
    name: str = "flaky"

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise IndexBackendUnavailableError(self.name, "ConnectError")

    async def open(self) -> None:
        await self.inner.open()

    async def close(self) -> None:
        await self.inner.close()

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        self._maybe_fail()
        await self.inner.put(manifest, entries)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        self._maybe_fail()
        await self.inner.delete(manifest_ids)

    async def held(self, library: str | None):
        return await self.inner.held(library)

    async def search(self, manifest_ids, query: TextQuery, tag_filter: TagFilter, limit: int):
        return await self.inner.search(manifest_ids, query, tag_filter, limit)

    async def count(self, manifest_ids, query: TextQuery, tag_filter: TagFilter):
        return await self.inner.count(manifest_ids, query, tag_filter)


@dataclass(slots=True)
class World:
    module: RetrievalModule
    chunks: InMemoryChunkRepository
    catalog: Catalog
    clock: Clock
    search: Flaky
    vectors: InMemoryVectorBackend
    store: InMemoryVectorIndex

    async def index(
        self,
        manifest_id: str,
        ref: str,
        articles: dict[str, list[str]],
        *,
        library: str = LIB,
        tags: tuple[str, ...] = (),
    ) -> None:
        await self.module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest_id,
                library=library,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path=path,
                        blob_sha=f"blob-{path}-{len(texts)}",
                        tags=list(tags),
                        chunks=[
                            ChunkIn(
                                heading_path=["Guide", f"{path} {i}"],
                                occurrence_index=0,
                                content=text,
                                content_hash=f"h-{text}",
                                anchor=f"s{i}",
                            )
                            for i, text in enumerate(texts)
                        ],
                    )
                    for path, texts in articles.items()
                ],
            )
        )
        self.catalog.active[library, ref] = manifest_id

    async def found(self, ref: str, query: str, library: str = LIB) -> list[str]:
        result = await self.module.search_docs(
            SearchDocsQuery(library=library, ref=ref, query=query)
        )
        return [r.snippet for r in result.results]

    async def held(self) -> dict[str, int]:
        return {h.manifest_id: h.entries for h in await self.search.held(None)}


def _world(*, vectors: bool = False) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog, clock = Catalog(), Clock()
    search, vector_backend = Flaky(), InMemoryVectorBackend()
    store = InMemoryVectorIndex(chunks=chunks)
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        clock=clock,
        vectors=store,
        search_backend=search,
        vector_backend=vector_backend if vectors else None,
        stored_vectors=store if vectors else None,
        external_retry_seconds=0,
    )
    return World(module, chunks, catalog, clock, search, vector_backend, store)


# ---------------------------------------------------------------- in step with imports and removals


async def test_an_import_writes_the_version_and_searches_are_answered_from_the_backend() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)

    assert await world.held() == {"m1": 3}
    assert await world.found("v1", "retry_policy") == ["Set retry_policy to change it."]
    world.search.inner.entries.clear()  # the backend, not the database's index, answers
    assert await world.found("v1", "retry_policy") == []


async def test_a_write_the_backend_refuses_for_a_moment_is_tried_again() -> None:
    world = _world()
    world.search.failures = 2

    await world.index("m1", "v1", GUIDE)

    assert await world.held() == {"m1": 3}
    assert world.search.calls == 3


async def test_a_backend_that_stays_down_fails_the_import_and_a_retry_writes_it() -> None:
    world = _world()
    world.search.failures = 100

    with pytest.raises(IndexBackendUnavailableError, match="flaky"):
        await world.index("m1", "v1", GUIDE)

    assert await world.held() == {}
    assert world.search.calls == 4  # EXTERNAL_WRITE_ATTEMPTS
    world.search.failures = 0
    await world.index("m1", "v1", GUIDE)  # the job's retry: the chunks are already stored
    assert await world.held() == {"m1": 3}


async def test_a_removal_deletes_from_the_backend_first_and_waits_for_it() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)
    await world.index("m2", "v2", OTHER_GUIDE)
    world.catalog.active.pop((LIB, "v1"))
    world.search.failures = 100

    with pytest.raises(IndexBackendUnavailableError):
        await world.module.remove_chunks(RemoveChunksCommand(manifest_ids=["m1"]))

    assert "m1" in world.chunks.manifests  # nothing deleted: the next collection retries
    world.search.failures = 0
    world.clock.at = T0 + timedelta(hours=1)
    removed = await world.module.collect_chunks(CollectChunksCommand(grace_seconds=0))
    assert removed.manifests == 1
    assert await world.held() == {"m2": 1}


async def test_a_retag_rewrites_the_tags_the_backend_filters_by() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)

    await world.module.retag_articles(
        RetagArticlesCommand(
            manifest_id="m1", articles=[ArticleTagsIn(path="auth.md", tags=["security"])]
        )
    )

    found = await world.search.search(
        ["m1"], TextQuery(text="tokens", terms=("tokens",)), TagFilter(tags=("security",)), 10
    )
    assert len(found) == 1


# ---------------------------------------------------------------- drift and rebuild


async def test_the_check_names_missing_incomplete_and_orphaned_versions() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)
    await world.index("m2", "v2", OTHER_GUIDE)
    await world.index("o1", "v1", OTHER_GUIDE, library="/other/lib")
    assert (await world.module.check_external_indexes(ExternalIndexScope())).clean

    await world.search.inner.delete(["m2"])  # lost, as a backend reset would
    world.search.inner.entries["m1"].pop(next(iter(world.search.inner.entries["m1"])))
    world.chunks.manifests.pop("o1")  # removed from the database behind the backend's back
    world.chunks.rows.pop("o1")

    drift = await world.module.check_external_indexes(ExternalIndexScope())

    assert drift.indexes == [IndexKind.SEARCH]
    assert sorted((v.drift, v.manifest_id, v.held, v.expected) for v in drift.versions) == [
        (DriftKind.INCOMPLETE, "m1", 2, 3),
        (DriftKind.MISSING, "m2", 0, 1),
        (DriftKind.ORPHANED, "o1", 1, 0),
    ]
    one = await world.module.check_external_indexes(ExternalIndexScope(library=LIB, version="v2"))
    assert [(v.drift, v.version_id) for v in one.versions] == [
        (DriftKind.MISSING, "/acme/payments/v2")
    ]


async def test_a_rebuild_restores_what_was_lost_and_deletes_what_was_removed() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)
    await world.index("m2", "v2", OTHER_GUIDE)
    await world.index("o1", "v1", OTHER_GUIDE, library="/other/lib")
    before = await world.found("v1", "retry_policy")
    orphan = world.search.inner.entries.pop("o1")  # o1's entries stand for a removed version's
    world.search.inner.entries.clear()
    world.search.inner.entries["gone"] = {
        chunk_id: replace(e, manifest_id="gone") for chunk_id, e in orphan.items()
    }

    rebuilt = await world.module.rebuild_external_indexes(ExternalIndexScope())

    assert (rebuilt.versions, rebuilt.search_entries, rebuilt.vector_entries) == (3, 5, 0)
    assert rebuilt.orphans == 1
    assert await world.held() == {"m1": 3, "m2": 1, "o1": 1}
    assert (await world.module.check_external_indexes(ExternalIndexScope())).clean
    assert await world.found("v1", "retry_policy") == before


async def test_a_rebuild_can_be_narrowed_to_a_library_or_a_version() -> None:
    world = _world()
    await world.index("m1", "v1", GUIDE)
    await world.index("m2", "v2", OTHER_GUIDE)
    await world.index("o1", "v1", OTHER_GUIDE, library="/other/lib")
    world.search.inner.entries.clear()

    one = await world.module.rebuild_external_indexes(ExternalIndexScope(library=LIB, version="v2"))
    assert (one.versions, await world.held()) == (1, {"m2": 1})
    library = await world.module.rebuild_external_indexes(
        ExternalIndexScope(library="/Acme/Payments")
    )
    assert (library.versions, await world.held()) == (2, {"m1": 3, "m2": 1})
    with pytest.raises(UnknownIndexVersionError):
        await world.module.rebuild_external_indexes(ExternalIndexScope(library=LIB, version="v9"))


async def test_without_backends_there_is_nothing_to_check_or_rebuild() -> None:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    module = RetrievalModule.build(
        searchable=Catalog(),
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=Catalog(),
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
    )

    drift = await module.check_external_indexes(ExternalIndexScope())
    rebuilt = await module.rebuild_external_indexes(ExternalIndexScope())

    assert (drift.indexes, drift.versions, drift.checked) == ([], [], 0)
    assert (rebuilt.indexes, rebuilt.versions) == ([], 0)


# ---------------------------------------------------------------- vectors


async def _embedded(world: World) -> EmbeddingSpaceId:
    """Store a vector for every chunk in a new active space, as the embed jobs would."""
    space = await world.store.create_space(SPEC, T0)
    keys = [
        (blob, cfg, i)
        for (blob, cfg), s in world.chunks.chunk_sets.items()
        for i in range(len(s.chunks))
    ]
    await world.store.upsert(space.id, {k: (1.0, 0.1 * n, 0.5) for n, k in enumerate(keys, 1)})
    await world.store.activate_space(space.id, T0)
    return space.id


async def test_moving_vectors_to_a_backend_and_rebuilding_gives_the_same_neighbours() -> None:
    world = _world()  # chunks and vectors in the database only
    await world.index("m1", "v1", GUIDE)
    await world.index("m2", "v2", GUIDE | OTHER_GUIDE)
    space_id = await _embedded(world)
    before = await world.store.nearest(space_id, "m2", [1, 0.2, 0.5], TagFilter(), 10)
    moved = _world(vectors=True)  # the operator configures a vector backend...
    moved.chunks.manifests.update(world.chunks.manifests)
    moved.chunks.rows.update(world.chunks.rows)
    moved.chunks.chunk_sets.update(world.chunks.chunk_sets)
    moved.store.spaces_by_id.update(world.store.spaces_by_id)
    moved.store.vectors.update(world.store.vectors)
    moved.catalog.active.update(world.catalog.active)
    drift = await moved.module.check_external_indexes(ExternalIndexScope())
    assert {(v.index, v.drift) for v in drift.versions} == {
        (IndexKind.SEARCH, DriftKind.MISSING),
        (IndexKind.VECTORS, DriftKind.MISSING),
    }

    rebuilt = await moved.module.rebuild_external_indexes(ExternalIndexScope())  # ...and rebuilds

    assert (rebuilt.versions, rebuilt.vector_entries) == (2, 3 + 4)
    held = {h.manifest_id: h.entries for h in await moved.vectors.held(space_id, None)}
    assert held == {"m1": 3, "m2": 4}  # every version's embeddings, per version
    searched = ExternalVectorIndex(
        store=moved.store,
        backend=moved.vectors,
        chunks=moved.chunks,
        mirror=ExternalIndexes(chunks=moved.chunks),
    )
    after = await searched.nearest(space_id, "m2", [1, 0.2, 0.5], TagFilter(), 10)
    assert [h.chunk_id for h in after] == [h.chunk_id for h in before]
    assert [h.distance for h in after] == pytest.approx([h.distance for h in before], abs=1e-9)


async def test_a_version_sharing_embedded_chunks_gets_their_vectors_when_imported() -> None:
    world = _world(vectors=True)
    await world.index("m1", "v1", GUIDE)
    space_id = await _embedded(world)
    await world.module.rebuild_external_indexes(ExternalIndexScope())

    await world.index("m2", "v2", GUIDE)  # the same blobs: nothing to embed, vectors copied

    held = {h.manifest_id: h.entries for h in await world.vectors.held(space_id, None)}
    assert held == {"m1": 3, "m2": 3}


async def test_a_retired_space_is_dropped_from_the_backend() -> None:
    world = _world(vectors=True)
    await world.index("m1", "v1", GUIDE)
    space_id = await _embedded(world)
    await world.module.rebuild_external_indexes(ExternalIndexScope())
    assert await world.vectors.held(space_id, None)
    wrapped = ExternalVectorIndex(
        store=world.store,
        backend=world.vectors,
        chunks=world.chunks,
        mirror=ExternalIndexes(
            chunks=world.chunks, vectors=world.vectors, store=world.store, stored=world.store
        ),
    )

    await wrapped.retire_space(space_id)

    assert await world.vectors.held(space_id, None) == []
