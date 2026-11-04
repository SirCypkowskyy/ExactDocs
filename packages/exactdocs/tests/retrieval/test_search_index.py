"""Adapter contract: every ``SearchIndex`` finds the same things, whatever engine runs it.

The shared guarantee is scoping to a manifest, escaping, tags, limits, highlights, the order of a
clear winner (a heading match beats body matches) and cleanup with the chunks. How good BM25
ranks otherwise (length normalisation, ties, scale) is the ranking suite's job (E5-04); the
memory reference only counts terms, so those cases run on SQLite alone.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    CollectChunksCommand,
    IndexManifestCommand,
)
from exactdocs.retrieval.models import (
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SearchHit,
    TagFilter,
    TagMatch,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports import ChunkRepository, SearchIndex

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"


@dataclass(slots=True)
class Gone:
    """A catalog that has dropped every manifest."""

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del library, ref
        return None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@dataclass(slots=True)
class Clock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


def section(heading: str, content: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Guide", heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}",
        anchor=heading.lower(),
    )


# Shaped like the fixture repository's v1.3.0 / v1.4.0: `retry_policy` is introduced in 1.4.0.
V13 = {"guide/retries.md": ("blob-13", [section("Retries", "Calls are retried three times.")])}
V14 = {
    "guide/retries.md": (
        "blob-14",
        [
            section("Retries", "Calls are retried. See also the retry_policy setting."),
            section("retry_policy", "`retry_policy` sets how often a failed call is retried."),
        ],
    ),
    "guide/auth.md": ("blob-auth", [section("Auth", "Tokens expire after an hour.")]),
}


@dataclass(frozen=True, slots=True)
class World:
    retrieval: RetrievalModule
    search: SearchIndex
    clock: Clock
    index_entries: Callable[[], Awaitable[int]]
    punch_gap: Callable[[], Awaitable[None]]  # lose one index entry, as a crash could
    engine: str

    async def index(
        self,
        manifest_id: str,
        ref: str,
        articles: dict,
        *,
        tags: list[str] | None = None,
        tagged: dict[str, list[str]] | None = None,
    ) -> None:
        await self.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest_id,
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path=path,
                        blob_sha=blob,
                        tags=(tagged or {}).get(path, tags or []),
                        chunks=chunks,
                    )
                    for path, (blob, chunks) in articles.items()
                ],
            )
        )

    async def find(
        self,
        manifest_id: str,
        query: str,
        tags: tuple[str, ...] = (),
        match: TagMatch = TagMatch.ANY,
    ) -> list[SearchHit]:
        return list(
            await self.search.search(manifest_id, query, TagFilter(tags=tags, match=match), 10)
        )


@pytest.fixture(params=["memory", "sqlite"])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    clock = Clock()

    def build(chunks: ChunkRepository, search: SearchIndex) -> RetrievalModule:
        return RetrievalModule.build(
            searchable=Gone(),
            manifests=Gone(),
            chunks=chunks,
            search=search,
            clock=clock,
        )

    if request.param == "memory":
        memory = InMemoryChunkRepository()
        memory_index = InMemorySearchIndex(memory)

        async def entries() -> int:
            return sum(
                len(memory.chunk_sets[k].chunks)
                for k in memory_index.indexed & set(memory.chunk_sets)
            )

        async def forget() -> None:
            memory_index.indexed.clear()

        yield World(build(memory, memory_index), memory_index, clock, entries, forget, "memory")
        return
    container = Container.build(Settings())
    async with container.running():
        index = SqliteSearchIndex(container.engine)

        async def count() -> int:
            async with container.engine.connect() as connection:
                return (
                    await connection.execute(text("SELECT count(*) FROM retrieval_search"))
                ).scalar_one()

        async def lose_one() -> None:
            async with container.engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM retrieval_search "
                        "WHERE rowid = (SELECT min(id) FROM retrieval_chunks)"
                    )
                )

        yield World(
            build(SqliteChunkRepository(container.engine), index),
            index,
            clock,
            count,
            lose_one,
            "sqlite",
        )


async def test_an_older_version_does_not_find_what_only_the_newer_one_has(world: World) -> None:
    await world.index("m13", "v1.3.0", V13)
    await world.index("m14", "v1.4.0", V14)

    assert await world.find("m13", "retry_policy") == []
    assert await world.find("m14", "retry_policy")


async def test_the_defining_section_comes_first_with_a_snippet_and_highlights(
    world: World,
) -> None:
    await world.index("m14", "v1.4.0", V14)

    first, second = await world.find("m14", "retry_policy")

    assert first.score > second.score
    assert first.snippet == "`retry_policy` sets how often a failed call is retried."
    assert [first.snippet[a:b] for a, b in first.highlights] == ["retry_policy"]


async def test_a_chunk_set_shared_by_two_manifests_is_indexed_once_and_found_from_both(
    world: World,
) -> None:
    await world.index("m13", "v1.3.0", V13)
    before = await world.index_entries()
    await world.index("m13b", "v1.3.1", V13)

    assert await world.index_entries() == before == 1
    old_ids = {h.chunk_id for h in await world.find("m13", "retried")}
    new_ids = {h.chunk_id for h in await world.find("m13b", "retried")}
    assert len(old_ids) == len(new_ids) == 1
    assert old_ids.isdisjoint(new_ids)  # one stored chunk, two version-scoped IDs


@pytest.mark.parametrize(
    "query",
    [
        '"',
        'retry"policy',
        "NEAR(retry policy)",
        "retry*",
        "(retry",
        "retry AND",
        "text:retry",
        "-",
        "''",
    ],
)
async def test_a_query_is_text_and_never_a_syntax_error(world: World, query: str) -> None:
    await world.index("m14", "v1.4.0", V14)

    await world.find("m14", query)  # must not raise


async def test_special_characters_are_dropped_and_the_words_still_match(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)

    assert await world.find("m14", '"retry_policy" NEAR (*') != []
    assert await world.find("m14", "()*") == []


async def test_identifier_parts_match_prose_and_the_whole_matches_code(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)

    assert await world.find("m14", "retryPolicy") != []  # `retry` and `policy` in prose
    assert await world.find("m14", "RETRY_POLICY") != []


async def test_the_tag_filter_keeps_chunks_with_any_of_the_tags(world: World) -> None:
    await world.index("m14", "v1.4.0", V14, tags=["guide"])

    assert await world.find("m14", "tokens", ("reference",)) == []
    assert len(await world.find("m14", "tokens", ("reference", "guide"))) == 1


async def test_the_all_filter_keeps_chunks_with_every_tag(world: World) -> None:
    await world.index("m14", "v1.4.0", V14, tags=["api", "auth"])

    both = await world.find("m14", "tokens", ("api", "auth"), TagMatch.ALL)
    assert len(both) == 1
    assert await world.find("m14", "tokens", ("api", "billing"), TagMatch.ALL) == []
    assert len(await world.find("m14", "tokens", ("api", "billing"), TagMatch.ANY)) == 1


async def test_the_top_k_is_computed_after_filtering(world: World) -> None:
    # Ten untagged chunks outrank the one tagged chunk. With limit 1 the tagged one must still
    # come back, which only happens when the filter runs before the cut.
    articles = {
        f"guide/loud{i}.md": (f"blob-loud{i}", [section(f"Retry {i}", "retry retry retry retry")])
        for i in range(10)
    } | {"guide/quiet.md": ("blob-quiet", [section("Quiet", "retry once")])}
    await world.index("m", "v1.4.0", articles, tagged={"guide/quiet.md": ["quiet"]})

    for match in TagMatch:
        found = await world.search.search("m", "retry", TagFilter(tags=("quiet",), match=match), 1)
        assert len(found) == 1
        assert found[0].snippet == "retry once"


async def test_a_limit_and_an_unknown_manifest(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)

    assert len(await world.search.search("m14", "retried", TagFilter(), 1)) == 1
    assert await world.find("nope", "retried") == []


async def test_collecting_a_manifest_takes_its_index_entries_with_it(world: World) -> None:
    await world.index("m13", "v1.3.0", V13)
    await world.index("m14", "v1.4.0", V14)
    world.clock.at = T0 + timedelta(hours=1)  # the catalog dropped both long ago

    removed = await world.retrieval.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert removed.manifests == 2
    assert await world.index_entries() == 0
    assert await world.find("m14", "retry_policy") == []


async def test_indexing_again_adds_nothing_twice(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)
    before = await world.index_entries()

    await world.index("m14", "v1.4.0", V14)

    assert await world.index_entries() == before == 3


async def test_indexing_again_fills_an_entry_lost_in_a_crash(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)
    await world.punch_gap()
    assert await world.index_entries() < 3

    await world.index("m14", "v1.4.0", V14)  # the replay of a manifest that is already stored

    assert await world.index_entries() == 3
    assert len(await world.find("m14", "retry_policy")) == 2
    assert len(await world.find("m14", "tokens")) == 1


async def test_a_word_inside_an_identifier_is_highlighted_where_it_stands(world: World) -> None:
    await world.index(
        "m1", "main", {"a.md": ("b", [section("Policies", "Set retryPolicy to tune calls.")])}
    )

    (hit,) = await world.find("m1", "retry")

    assert [hit.snippet[a:b] for a, b in hit.highlights] == ["retryPolicy"]


async def test_a_heading_match_outranks_many_body_matches(world: World) -> None:
    body = "retry_policy " * 5 + "is mentioned a lot."
    await world.index(
        "m1",
        "main",
        {
            "a.md": ("a", [section("Mentions", body)]),
            "b.md": ("b", [section("retry_policy", "Defined here.")]),
            # BM25 weighs a term by how rare it is, so the corpus needs chunks without it.
            **{f"f{i}.md": (f"f{i}", [section(f"Other {i}", f"unrelated {i}")]) for i in range(5)},
        },
    )

    first, second = await world.find("m1", "retry_policy")

    assert first.snippet == "Defined here."
    assert first.score > second.score


async def test_bm25_prefers_the_shorter_chunk_with_the_same_term(world: World) -> None:
    if world.engine != "sqlite":
        pytest.skip("length normalisation is BM25's; the memory reference only counts terms")
    await world.index(
        "m1",
        "main",
        {
            "long.md": ("l", [section("Long", "timeout " + "filler " * 200)]),
            "short.md": ("s", [section("Short", "timeout is the limit.")]),
        },
    )

    first, _ = await world.find("m1", "timeout")

    assert first.snippet.startswith("timeout is")
