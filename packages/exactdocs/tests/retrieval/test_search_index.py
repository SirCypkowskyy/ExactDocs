"""Adapter contract: every ``SearchIndex`` finds the same things, whatever engine runs it."""

from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryExcerptIndex,
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
from exactdocs.retrieval.models import DocTarget, ManifestStatus, SearchHit
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports import ChunkRepository, SearchIndex

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"


@dataclass(slots=True)
class Gone:
    """A catalog that has dropped every manifest."""

    async def find_indexed(self, target: DocTarget) -> DocTarget | None:
        return target

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

    async def index(
        self, manifest_id: str, ref: str, articles: dict, *, tags: list[str] | None = None
    ) -> None:
        await self.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest_id,
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(path=path, blob_sha=blob, tags=tags or [], chunks=chunks)
                    for path, (blob, chunks) in articles.items()
                ],
            )
        )

    async def find(
        self, manifest_id: str, query: str, tags: tuple[str, ...] = ()
    ) -> list[SearchHit]:
        return list(await self.search.search(manifest_id, query, tags, 10))


@pytest.fixture(params=["memory", "sqlite"])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    clock = Clock()

    def build(chunks: ChunkRepository, search: SearchIndex) -> RetrievalModule:
        return RetrievalModule.build(
            versions=Gone(),
            index=InMemoryExcerptIndex(),
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

        yield World(build(memory, memory_index), memory_index, clock, entries)
        return
    container = Container.build(Settings())
    async with container.running():
        index = SqliteSearchIndex(container.engine)

        async def count() -> int:
            async with container.engine.connect() as connection:
                return (
                    await connection.execute(text("SELECT count(*) FROM retrieval_search"))
                ).scalar_one()

        yield World(build(SqliteChunkRepository(container.engine), index), index, clock, count)


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
    assert [h.chunk_id for h in await world.find("m13", "retried")] != []
    assert {h.chunk_id for h in await world.find("m13", "retried")}.isdisjoint(
        h.chunk_id for h in await world.find("m13b", "retried")
    )
    assert len(await world.find("m13b", "retried")) == 1


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


async def test_a_limit_and_an_unknown_manifest(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)

    assert len(await world.search.search("m14", "retried", (), 1)) == 1
    assert await world.find("nope", "retried") == []


async def test_collecting_a_manifest_takes_its_index_entries_with_it(world: World) -> None:
    await world.index("m13", "v1.3.0", V13)
    await world.index("m14", "v1.4.0", V14)
    world.clock.at = T0 + timedelta(hours=1)  # the catalog dropped both long ago

    removed = await world.retrieval.collect_chunks(CollectChunksCommand(grace_seconds=0))

    assert removed.manifests == 2
    assert await world.index_entries() == 0
    assert await world.find("m14", "retry_policy") == []


async def test_indexing_again_fills_gaps_and_adds_nothing_twice(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)
    before = await world.index_entries()

    await world.index("m14", "v1.4.0", V14)

    assert await world.index_entries() == before == 3
