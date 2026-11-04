"""Adapter contract: every ``ChunkRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository, chunk_set_rows
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    GetChunkSetsQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    ReadChunkQuery,
    RemoveChunksCommand,
    RemovedChunks,
)
from exactdocs.retrieval.errors import (
    ChunkNotFoundError,
    ChunkSetMismatchError,
    DuplicateChunkError,
    StaleChunkError,
)
from exactdocs.retrieval.models import (
    ChunkId,
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports import ChunkRepository, SearchIndex
from exactdocs.retrieval.use_cases import UNKNOWN_MANIFEST_GRACE, ReadChunkUseCase
from exactdocs_kernel import NOTICE

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
PAYMENTS = "/acme/payments"
CONFIG = "cfg1"


@dataclass(slots=True)
class FakeCatalog:
    """Plays the catalog for both driven ports; tests set a manifest's status directly."""

    statuses_: dict[str, ManifestStatus] = field(default_factory=dict)
    after_first_statuses: dict[str, ManifestStatus] = field(default_factory=dict)  # a race
    refs: dict[str, str] = field(default_factory=dict)  # manifest ID -> ref, for active_id

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        manifest = next(
            (
                m
                for m, s in self.statuses_.items()
                if s is ManifestStatus.ACTIVE and self.refs[m] == ref
            ),
            None,
        )
        if manifest is None or ref is None:
            return None
        return SearchableVersion(
            library=library.lower(),
            version=ref,
            manifest_id=manifest,
            commit_sha="a" * 40,
            repository_url="https://github.com/acme/payments",
            host=SourceHost.GITHUB,
        )

    async def active_id(self, target: DocTarget) -> str | None:
        return next(
            (
                m
                for m, s in self.statuses_.items()
                if s is ManifestStatus.ACTIVE and self.refs[m] == target.version
            ),
            None,
        )

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        answer = {m: s for m in manifest_ids if (s := self.statuses_.get(m))}
        self.statuses_ |= self.after_first_statuses  # the catalog moves on between two questions
        self.after_first_statuses = {}
        return answer


@dataclass(slots=True)
class FakeClock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


@dataclass(frozen=True, slots=True)
class World:
    retrieval: RetrievalModule
    catalog: FakeCatalog
    clock: FakeClock
    count_chunk_sets: Callable[[], Awaitable[int]]
    chunks: ChunkRepository

    async def index(
        self,
        manifest_id: str,
        ref: str,
        articles: dict[str, str],
        *,
        status: ManifestStatus | None = None,
    ) -> IndexedManifestOut:
        """Index articles given as ``path -> blob`` (each blob has two chunks, named after it)."""
        done = await self.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest_id,
                library="/Acme/Payments",
                ref=ref,
                config_hash=CONFIG,
                articles=[
                    ArticleChunksIn(
                        path=path,
                        blob_sha=blob,
                        tags=["guide"],
                        chunks=[
                            ChunkIn(
                                heading_path=["Doc", f"{blob} {part}"],
                                occurrence_index=0,
                                content=f"text of {blob} {part}",
                                content_hash=f"{blob}-{part}",
                                anchor=f"{blob}-{part}",
                                code_languages=["python"],
                            )
                            for part in ("one", "two")
                        ],
                    )
                    for path, blob in articles.items()
                ],
            )
        )
        if status:
            self.catalog.statuses_[manifest_id] = status
            self.catalog.refs[manifest_id] = ref
        return done

    async def read(self, chunk_id: str):
        return await self.retrieval.read_chunk(ReadChunkQuery(chunk_id=chunk_id))


@pytest.fixture(params=["memory", "sqlite"])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    catalog, clock = FakeCatalog(), FakeClock()

    def build(chunks: ChunkRepository, search: SearchIndex) -> RetrievalModule:
        return RetrievalModule.build(
            searchable=catalog,
            manifests=catalog,
            chunks=chunks,
            search=search,
            clock=clock,
        )

    if request.param == "memory":
        memory = InMemoryChunkRepository()

        async def count() -> int:
            return len(memory.chunk_sets)

        yield World(build(memory, InMemorySearchIndex(memory)), catalog, clock, count, memory)
        return
    container = Container.build(Settings())
    async with container.running():

        async def count_rows() -> int:
            async with container.engine.connect() as connection:
                return (
                    await connection.execute(select(func.count()).select_from(chunk_set_rows))
                ).scalar_one()

        sqlite = SqliteChunkRepository(container.engine)
        search = SqliteSearchIndex(container.engine)
        yield World(build(sqlite, search), catalog, clock, count_rows, sqlite)


async def test_an_article_that_did_not_change_keeps_its_chunk_ids_when_the_branch_moves(
    world: World,
) -> None:
    first = await world.index("m1", "main", {"guide/auth.md": "auth1", "guide/install.md": "inst1"})
    second = await world.index(
        "m2", "main", {"guide/auth.md": "auth1", "guide/install.md": "inst2"}
    )

    assert second.chunk_ids["guide/auth.md"] == first.chunk_ids["guide/auth.md"]
    assert second.chunk_ids["guide/install.md"] != first.chunk_ids["guide/install.md"]
    assert second.chunk_sets_stored == 1  # only the changed blob


async def test_the_same_blob_in_two_versions_is_stored_once_with_different_chunk_ids(
    world: World,
) -> None:
    old = await world.index("m1", "v1.3.0", {"guide/install.md": "inst1"})
    new = await world.index("m2", "v1.4.0", {"guide/install.md": "inst1"})

    assert await world.count_chunk_sets() == 1
    assert new.chunk_sets_stored == 0
    assert set(new.chunk_ids["guide/install.md"]).isdisjoint(old.chunk_ids["guide/install.md"])


async def test_the_same_blob_at_two_paths_gets_a_chunk_id_per_path(world: World) -> None:
    done = await world.index("m1", "main", {"a.md": "same", "b.md": "same"})

    assert await world.count_chunk_sets() == 1
    assert set(done.chunk_ids["a.md"]).isdisjoint(done.chunk_ids["b.md"])


async def test_indexing_the_same_input_twice_stores_nothing_new(world: World) -> None:
    articles = {"guide/auth.md": "auth1", "guide/install.md": "inst1"}
    first = await world.index("m1", "main", articles, status=ManifestStatus.ACTIVE)

    again = await world.index("m1", "main", articles)

    assert again.chunk_ids == first.chunk_ids
    assert (first.chunk_sets_stored, again.chunk_sets_stored) == (2, 0)
    assert await world.count_chunk_sets() == 2
    (chunk_id, *_) = first.chunk_ids["guide/auth.md"]
    assert (await world.read(chunk_id)).position == 0  # still exactly one row


async def test_a_chunk_is_read_from_the_active_manifest_only(world: World) -> None:
    old = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.SUPERSEDED)
    pending = await world.index("m2", "main", {"a.md": "two"}, status=ManifestStatus.PENDING)

    with pytest.raises(ChunkNotFoundError):  # not visible before the catalog activates it
        await world.read(pending.chunk_ids["a.md"][0])

    world.catalog.statuses_["m2"] = ManifestStatus.ACTIVE
    chunk = await world.read(pending.chunk_ids["a.md"][0])
    assert chunk.content == "text of two one"
    with pytest.raises(StaleChunkError):  # the superseded manifest's IDs are stale now
        await world.read(old.chunk_ids["a.md"][0])


async def test_many_chunks_come_back_by_id_and_unknown_ones_are_left_out(world: World) -> None:
    done = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    other = await world.index("m2", "v2", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    first, second = map(ChunkId, done.chunk_ids["a.md"])
    foreign = ChunkId(other.chunk_ids["a.md"][0])

    found = await world.chunks.get_many("m1", [second, first, ChunkId("nope"), foreign])

    assert set(found) == {first, second}  # not "nope", not another manifest's chunk
    assert found[first].chunk.content == "text of one one"
    assert found[second].row.prev_chunk_id == first
    assert await world.chunks.get_many("m1", []) == {}


async def test_a_chunk_knows_its_place_tags_and_neighbours(world: World) -> None:
    done = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    first_id, second_id = done.chunk_ids["a.md"]

    first, second = await world.read(first_id), await world.read(second_id)

    assert (first.position, first.total, first.prev_chunk_id) == (0, 2, None)
    assert (first.next_chunk_id, second.prev_chunk_id) == (second_id, first_id)
    assert (first.heading_path, first.tags, first.code_languages) == (
        ["Doc", "one one"],
        ["guide"],
        ["python"],
    )
    assert (first.library, first.version, first.article_path) == (PAYMENTS, "main", "a.md")


async def test_a_chunk_id_names_its_version_so_no_version_is_needed(world: World) -> None:
    old = await world.index("m1", "v1.3.0", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    new = await world.index("m2", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)

    assert (await world.read(old.chunk_ids["a.md"][0])).version == "v1.3.0"
    assert (await world.read(new.chunk_ids["a.md"][0])).version == "main"


async def test_a_chunk_says_where_it_came_from_and_that_it_is_untrusted(world: World) -> None:
    done = await world.index("m1", "main", {"docs/a.md": "one"}, status=ManifestStatus.ACTIVE)

    chunk = await world.read(done.chunk_ids["docs/a.md"][0])

    assert chunk.notice == NOTICE
    assert chunk.commit_sha == "a" * 40
    assert chunk.source_url == (
        "https://github.com/acme/payments/blob/" + "a" * 40 + "/docs/a.md#one-one"
    )
    assert chunk.content == "text of one one"  # verbatim: nothing is added around the stored text


async def test_a_stale_chunk_says_so_and_how_to_find_the_current_one(world: World) -> None:
    old = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.SUPERSEDED)
    await world.index("m2", "main", {"a.md": "two"}, status=ManifestStatus.ACTIVE)

    with pytest.raises(StaleChunkError) as stale:
        await world.read(old.chunk_ids["a.md"][0])

    assert stale.value.code == "stale_chunk"
    message = str(stale.value)
    assert "search_docs" in message
    assert "read_article" in message
    assert "main" not in message  # a git ref is repository text: never interpolated unlabelled


async def test_a_stale_chunk_of_a_version_without_an_active_manifest_is_still_stale(
    world: World,
) -> None:
    old = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.SUPERSEDED)

    with pytest.raises(StaleChunkError):
        await world.read(old.chunk_ids["a.md"][0])


async def test_an_id_nobody_issued_is_not_found_not_stale(world: World) -> None:
    await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)

    with pytest.raises(ChunkNotFoundError):
        await world.read("0" * 32)


async def test_the_manifests_holding_a_chunk_are_found_by_its_id(world: World) -> None:
    first = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.SUPERSEDED)
    await world.index("m2", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    chunk_id = ChunkId(first.chunk_ids["a.md"][0])

    found = await world.chunks.manifests_with_chunk(chunk_id)

    assert {m.manifest_id for m in found} == {"m1", "m2"}  # an unchanged section keeps its ID
    assert not await world.chunks.manifests_with_chunk(ChunkId("nope"))


async def test_a_chunk_of_a_manifest_indexed_under_another_ref_is_not_served(world: World) -> None:
    # The caller passed the wrong ref when indexing; the catalog serves that manifest for `main`.
    wrong = await world.index("m1", "v9", {"a.md": "one"})
    world.catalog.statuses_["m1"] = ManifestStatus.ACTIVE
    world.catalog.refs["m1"] = "main"

    with pytest.raises(ChunkNotFoundError):
        await world.read(wrong.chunk_ids["a.md"][0])


async def test_a_replay_says_so_and_a_full_dedup_does_not(world: World) -> None:
    first = await world.index("m1", "v1.3.0", {"a.md": "one"})
    deduped = await world.index("m2", "v1.4.0", {"a.md": "one"})
    replay = await world.index("m1", "v1.3.0", {"a.md": "one"})

    assert [x.already_indexed for x in (first, deduped, replay)] == [False, False, True]
    assert [x.chunk_sets_stored for x in (first, deduped, replay)] == [1, 0, 0]


async def test_a_chunk_set_cut_differently_under_the_same_config_hash_is_refused(
    world: World,
) -> None:
    await world.index("m1", "main", {"a.md": "one"})
    changed = IndexManifestCommand(
        manifest_id="m2",
        library=PAYMENTS,
        ref="main",
        config_hash=CONFIG,  # the chunker changed but the hash was not bumped
        articles=[
            ArticleChunksIn(
                path="a.md",
                blob_sha="one",
                chunks=[
                    ChunkIn(
                        heading_path=["Other"],
                        occurrence_index=0,
                        content="cut another way",
                        content_hash="x",
                        anchor="other",
                    )
                ],
            )
        ],
    )

    with pytest.raises(ChunkSetMismatchError):
        await world.retrieval.index_manifest(changed)

    assert await world.count_chunk_sets() == 1
    assert await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="m2", older_than_seconds=0)
    ) == RemovedChunks(manifests=0, chunk_sets=0)  # m2 left nothing behind


async def test_duplicate_chunk_ids_in_one_article_are_refused_and_nothing_is_stored(
    world: World,
) -> None:
    twin = ChunkIn(
        heading_path=["A"], occurrence_index=0, content="x", content_hash="h", anchor="a"
    )
    command = IndexManifestCommand(
        manifest_id="m1",
        library=PAYMENTS,
        ref="main",
        config_hash=CONFIG,
        articles=[ArticleChunksIn(path="a.md", blob_sha="b", chunks=[twin, twin])],
    )

    with pytest.raises(DuplicateChunkError):
        await world.retrieval.index_manifest(command)

    assert await world.count_chunk_sets() == 0


async def test_discarding_removes_pending_manifests_and_their_unshared_chunk_sets(
    world: World,
) -> None:
    await world.index("act", "main", {"a.md": "kept"}, status=ManifestStatus.ACTIVE)
    await world.index("old", "main", {"a.md": "gone-soon"}, status=ManifestStatus.SUPERSEDED)
    await world.index(
        "pend", "main", {"a.md": "kept", "b.md": "fresh"}, status=ManifestStatus.PENDING
    )

    world.clock.at = T0 + timedelta(seconds=1)
    removed = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(library="/Acme/Payments", older_than_seconds=0)
    )

    assert (removed.manifests, removed.chunk_sets) == (1, 1)  # "fresh" was only in `pend`
    assert await world.count_chunk_sets() == 2


async def test_discarding_by_id_leaves_other_pending_manifests(world: World) -> None:
    await world.index("p1", "main", {"a.md": "one"}, status=ManifestStatus.PENDING)
    await world.index("p2", "main", {"a.md": "two"}, status=ManifestStatus.PENDING)

    removed = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="p1")
    )

    assert removed.manifests == 1
    assert await world.count_chunk_sets() == 1


async def test_a_manifest_the_catalog_does_not_know_yet_survives_a_discard(world: World) -> None:
    # Index runs before the catalog has answered for the manifest: it is "unknown", not dropped.
    await world.index("fresh", "main", {"a.md": "one"})

    by_library = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(library="/Acme/Payments")
    )
    by_id = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="fresh", older_than_seconds=0)
    )

    assert (by_library.manifests, by_id.manifests) == (0, 0)
    assert await world.count_chunk_sets() == 1


async def test_a_manifest_the_catalog_dropped_long_ago_is_discarded(world: World) -> None:
    await world.index("orphan", "main", {"a.md": "one"})  # the catalog never heard of it

    world.clock.at = T0 + UNKNOWN_MANIFEST_GRACE + timedelta(seconds=1)
    removed = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="orphan")
    )

    assert (removed.manifests, removed.chunk_sets) == (1, 1)


async def test_a_manifest_activated_while_a_discard_runs_is_kept(world: World) -> None:
    done = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.PENDING)
    world.catalog.after_first_statuses = {"m1": ManifestStatus.ACTIVE}  # activated mid-discard

    removed = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="m1")
    )

    assert (removed.manifests, removed.chunk_sets) == (0, 0)
    assert await world.count_chunk_sets() == 1
    assert (await world.read(done.chunk_ids["a.md"][0])).content == "text of one one"


async def test_a_manifest_in_a_state_retrieval_cannot_name_is_never_removed(world: World) -> None:
    await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.OTHER)

    world.clock.at = T0 + timedelta(days=30)
    discarded = await world.retrieval.discard_pending_chunks(
        DiscardPendingChunksCommand(manifest_id="m1")
    )
    collected = await world.retrieval.collect_chunks(CollectChunksCommand())

    assert (discarded.manifests, collected.manifests) == (0, 0)


async def test_a_manifest_that_comes_back_during_a_collection_is_kept(world: World) -> None:
    await world.index("m1", "main", {"a.md": "one"})  # unknown to the catalog
    world.catalog.after_first_statuses = {"m1": ManifestStatus.ACTIVE}
    world.catalog.refs["m1"] = "main"

    world.clock.at = T0 + timedelta(days=8)
    removed = await world.retrieval.collect_chunks(CollectChunksCommand())

    assert removed.manifests == 0


def test_discarding_without_any_filter_is_refused() -> None:
    with pytest.raises(ValueError, match="give a manifest_id"):
        DiscardPendingChunksCommand()


async def test_collection_drops_manifests_the_catalog_forgot_after_the_grace_period(
    world: World,
) -> None:
    await world.index("act", "main", {"a.md": "kept"}, status=ManifestStatus.ACTIVE)
    await world.index("old", "main", {"a.md": "stale"})  # superseded, then collected by the catalog
    world.clock.at = T0 + timedelta(days=6)
    await world.index("recent", "main", {"a.md": "recent"})  # also unknown, but inside the grace

    world.clock.at = T0 + timedelta(days=8)
    removed = await world.retrieval.collect_chunks(CollectChunksCommand())

    assert (removed.manifests, removed.chunk_sets) == (1, 1)
    assert await world.count_chunk_sets() == 2  # "kept" and "recent"


async def test_stored_chunk_sets_come_back_by_blob_and_config_and_unknown_ones_are_left_out(
    world: World,
) -> None:
    await world.index("m1", "main", {"a.md": "one", "b.md": "two"})

    found = await world.retrieval.get_chunk_sets(
        GetChunkSetsQuery(config_hash=CONFIG, blob_shas=["two", "nope", "one", "one"])
    )
    other_config = await world.retrieval.get_chunk_sets(
        GetChunkSetsQuery(config_hash="other", blob_shas=["one"])
    )

    assert set(found.chunks) == {"one", "two"}
    assert [c.content for c in found.chunks["one"]] == ["text of one one", "text of one two"]
    assert found.chunks["one"][0].code_languages == ["python"]
    assert other_config.chunks == {}


async def test_an_id_held_by_two_versions_is_refused_not_guessed(world: World) -> None:
    done = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.ACTIVE)
    # Not reachable with the real hash (it covers the version): a corrupted index must not be
    # resolved by whichever row comes first.
    await world.index("m2", "v2", {"a.md": "two"}, status=ManifestStatus.ACTIVE)
    chunk_id = ChunkId(done.chunk_ids["a.md"][0])
    rows = world.chunks
    holders = await rows.manifests_with_chunk(chunk_id)
    assert len(holders) == 1  # sanity: IDs of different versions differ

    class TwoVersions:
        async def manifests_with_chunk(self, _: ChunkId):
            return [
                replace(holders[0], manifest_id="x1", version_id="/acme/payments/main"),
                replace(holders[0], manifest_id="x2", version_id="/acme/payments/v2"),
            ]

    use_case = ReadChunkUseCase(world.catalog, world.catalog, TwoVersions())  # ty: ignore[invalid-argument-type]
    with pytest.raises(ChunkNotFoundError):
        await use_case(ReadChunkQuery(chunk_id=chunk_id))


@pytest.mark.xfail(
    reason="E9-03 keeps tombstones for collected manifests; until then an old ID is not_found",
    strict=True,
    raises=ChunkNotFoundError,
)
async def test_a_stale_id_stays_stale_after_its_manifest_was_collected(world: World) -> None:
    old = await world.index("m1", "main", {"a.md": "one"}, status=ManifestStatus.SUPERSEDED)
    await world.index("m2", "main", {"a.md": "two"}, status=ManifestStatus.ACTIVE)
    world.catalog.statuses_.pop("m1")  # the catalog collected m1: it no longer knows the ID

    with pytest.raises(StaleChunkError):
        await world.read(old.chunk_ids["a.md"][0])


async def test_removing_chunks_frees_what_only_removed_manifests_used(world: World) -> None:
    await world.index("m1", "v1", {"a.md": "shared", "b.md": "old"})
    await world.index("m2", "v2", {"a.md": "shared"}, status=ManifestStatus.ACTIVE)
    world.catalog.refs["m2"] = "v2"  # m1 is unknown to the catalog: it was just removed

    removed = await world.retrieval.remove_chunks(RemoveChunksCommand(manifest_ids=["m1", "m1"]))

    assert (removed.manifests, removed.chunk_sets) == (1, 1)  # "old" goes, "shared" stays
    assert await world.count_chunk_sets() == 1


async def test_removing_chunks_never_removes_a_manifest_the_catalog_still_knows(
    world: World,
) -> None:
    await world.index("m1", "v1", {"a.md": "one"}, status=ManifestStatus.PENDING)

    removed = await world.retrieval.remove_chunks(RemoveChunksCommand(manifest_ids=["m1", "nope"]))

    assert (removed.manifests, removed.chunk_sets) == (0, 0)
    assert await world.count_chunk_sets() == 1
