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

from databases import SEARCH_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.pg_search import PgSearchIndex
from exactdocs.retrieval.adapters.driven.postgres_fts import PostgresSearchIndex
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_fts import SqliteSearchIndex, _statements
from exactdocs.retrieval.constants import _SEARCH
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
    age_index: Callable[[], Awaitable[None]]  # record an older format, as an older build left it

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


async def _sql_index(
    backend: str, container: Container
) -> SqliteSearchIndex | PostgresSearchIndex | PgSearchIndex:
    """The search adapter of a database backend, on the running container's database."""
    if backend == "sqlite":
        return SqliteSearchIndex(engine=container.engine)
    table = PostgresSearchIndex(engine=container.engine)
    if backend != "pg_search":
        return table
    index = PgSearchIndex(engine=container.engine, table=table)
    assert await index.prepare(create=True) is None
    return index


@pytest.fixture(params=["memory", *SEARCH_BACKENDS])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[World]:
    clock = Clock()

    def build(
        chunks: ChunkRepository,
        search: InMemorySearchIndex | SqliteSearchIndex | PostgresSearchIndex | PgSearchIndex,
    ) -> RetrievalModule:
        return RetrievalModule.build(
            defaults=InMemoryDefaultVersions(),
            libraries=InMemoryLibraries(),
            searchable=Gone(),
            manifests=Gone(),
            chunks=chunks,
            search=search,
            maintenance=search,
            library_modes=InMemoryLibraryModes(),
            clock=clock,
        )

    if request.param == "memory":
        memory = InMemoryChunkRepository()
        memory_index = InMemorySearchIndex(chunks=memory)

        async def entries() -> int:
            return sum(
                len(memory.chunk_sets[k].chunks)
                for k in memory_index.indexed & set(memory.chunk_sets)
            )

        async def forget() -> None:
            memory_index.indexed.clear()

        async def age() -> None:
            memory_index.stored_format = 0

        yield World(
            build(memory, memory_index), memory_index, clock, entries, forget, "memory", age
        )
        return
    postgres = request.param != "sqlite"
    if postgres:
        request.getfixturevalue("on_" + request.param)
    container = Container.build(Settings())
    async with container.running(jobs=False):
        index = await _sql_index(request.param, container)

        async def count() -> int:
            async with container.engine.connect() as connection:
                return (
                    await connection.execute(text("SELECT count(*) FROM retrieval_search"))
                ).scalar_one()

        async def lose_one() -> None:
            async with container.engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM retrieval_search WHERE chunk_id = "
                        "(SELECT min(id) FROM retrieval_chunks)"
                        if postgres
                        else "DELETE FROM retrieval_search WHERE rowid = "
                        "(SELECT min(id) FROM retrieval_chunks)"
                    )
                )

        async def age() -> None:
            async with container.engine.begin() as connection:
                await connection.execute(text("UPDATE retrieval_search_format SET format = 0"))

        yield World(
            build(SqliteChunkRepository(engine=container.engine), index),
            index,
            clock,
            count,
            lose_one,
            request.param,
            age,
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


async def test_words_in_any_script_are_found_whatever_the_database_locale(
    world: World,
) -> None:
    # `postgres_c` is a database in the C locale, whose `[[:alnum:]]` only knows ASCII.
    await world.index(
        "m1",
        "main",
        {
            "fr.md": ("fr", [section("Desserts", "La crème brûlée se sert froide.")]),
            "el.md": ("el", [section("Αρχή", "ωμέγα σημαίνει μεγάλο.")]),
            "ja.md": ("ja", [section("概要", "日本語 の 説明 です")]),
            "en.md": ("en", [section("Other", "Nothing to see here.")]),
        },
    )

    for query, snippet in [
        ("brûlée", "La crème brûlée"),
        ("crème", "La crème brûlée"),
        ("ωμέγα", "ωμέγα σημαίνει"),
        ("日本語", "日本語"),
    ]:
        found = await world.find("m1", query)
        assert [hit.snippet[: len(snippet)] for hit in found] == [snippet], (query, found)
        start, end = found[0].highlights[0]
        assert found[0].snippet[start:end] == query


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


async def test_one_search_over_several_manifests_names_the_manifest_of_each_hit(
    world: World,
) -> None:
    await world.index("m13", "v1.3.0", V13)
    await world.index("m14", "v1.4.0", V14)
    await world.index("other", "v2", {"x.md": ("blob-x", [section("X", "retried retried")])})

    found = await world.search.search_many(["m13", "m14"], "retried", TagFilter(), 10)

    assert {f.manifest_id for f in found} == {"m13", "m14"}  # "other" was not asked for
    assert [f.hit.score for f in found] == sorted((f.hit.score for f in found), reverse=True)
    assert await world.search.search_many([], "retried", TagFilter(), 10) == []
    assert len(await world.search.search_many(["m13", "m14"], "retried", TagFilter(), 1)) == 1


async def test_a_chunk_set_shared_by_two_manifests_is_a_hit_for_each_with_one_score(
    world: World,
) -> None:
    await world.index("a", "v1", V13)
    await world.index("b", "v1", V13)

    found = await world.search.search_many(["a", "b"], "retried", TagFilter(), 10)

    assert sorted(f.manifest_id for f in found) == ["a", "b"]
    assert found[0].hit.score == found[1].hit.score  # one set of statistics, not one per manifest


async def test_counts_per_manifest_are_not_capped_and_leave_out_zeros(world: World) -> None:
    many = {f"g/{i}.md": (f"blob-{i}", [section(f"Retry {i}", "retry")]) for i in range(12)}
    await world.index("big", "v1", many, tagged={"g/0.md": ["x"]})
    await world.index("m13", "v1.3.0", V13)

    ask = ["big", "m13", "nope"]
    assert await world.search.count_many(ask, "retry", TagFilter()) == {"big": 12}
    assert await world.search.count_many(ask, "retried", TagFilter()) == {"m13": 1}
    assert await world.search.count_many(ask, "retry", TagFilter(tags=("x",))) == {"big": 1}
    assert await world.search.count_many([], "retry", TagFilter()) == {}
    assert await world.search.count_many(ask, "()*", TagFilter()) == {}


async def test_the_all_tag_filter_across_manifests_keeps_chunks_with_every_tag(
    world: World,
) -> None:
    both = {"a.md": ("blob-a", [section("A", "token")])}
    one = {"b.md": ("blob-b", [section("B", "token")])}
    await world.index("m1", "v1", both, tags=["api", "auth"])
    await world.index("m2", "v1", one, tags=["api"])

    for tags, match, wanted in [
        (("api", "auth"), TagMatch.ALL, {"m1": 1}),
        (("api",), TagMatch.ALL, {"m1": 1, "m2": 1}),
        (("auth", "billing"), TagMatch.ALL, {}),
        (("auth", "billing"), TagMatch.ANY, {"m1": 1}),
    ]:
        tag_filter = TagFilter(tags=tags, match=match)
        found = await world.search.search_many(["m1", "m2"], "token", tag_filter, 10)
        assert {f.manifest_id: 1 for f in found} == wanted
        assert await world.search.count_many(["m1", "m2"], "token", tag_filter) == wanted


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


async def test_a_rebuild_finds_the_same_and_fills_lost_entries(world: World) -> None:
    await world.index("m13", "v1.3.0", V13)
    await world.index("m14", "v1.4.0", V14)
    before = [await world.find(m, q) for m in ("m13", "m14") for q in ("retry_policy", "retried")]
    await world.punch_gap()

    rebuilt = await world.retrieval.rebuild_search_index()

    assert rebuilt.entries == await world.index_entries() == 4
    after = [await world.find(m, q) for m in ("m13", "m14") for q in ("retry_policy", "retried")]
    assert after == before
    assert await world.find("m13", "retry_policy") == []  # still version-exact


async def test_an_index_in_an_older_format_needs_a_rebuild_until_rebuilt(world: World) -> None:
    await world.index("m14", "v1.4.0", V14)
    assert not (await world.retrieval.get_search_index_state()).needs_rebuild
    await world.age_index()

    aged = await world.retrieval.get_search_index_state()
    assert aged.needs_rebuild
    assert aged.stored_format is not None
    assert aged.stored_format < aged.current_format
    assert len(await world.find("m14", "retry_policy")) == 2  # the old index still answers

    rebuilt = await world.retrieval.rebuild_search_index()

    state = await world.retrieval.get_search_index_state()
    assert (state.needs_rebuild, state.stored_format) == (False, rebuilt.format)
    assert rebuilt.format == state.current_format


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


async def test_a_section_naming_a_term_outranks_the_sub_sections_under_it(world: World) -> None:
    if world.engine == "memory":
        pytest.skip("the memory reference does not weigh a heading's ancestors")
    child = ChunkIn(
        heading_path=["Guide", "Docker", "Troubleshooting"],
        occurrence_index=0,
        content="If the port is taken, pick another one.",
        content_hash="h-child",
        anchor="troubleshooting",
    )
    await world.index(
        "m1",
        "main",
        {
            "a.md": ("a", [section("Docker", "Pull the image, then docker run it."), child]),
            **{f"f{i}.md": (f"f{i}", [section(f"Other {i}", f"unrelated {i}")]) for i in range(5)},
        },
    )

    defining, *_ = await world.find("m1", "docker")
    both, *_ = await world.find("m1", "docker troubleshooting")

    assert defining.snippet.startswith("Pull the image")
    assert both.snippet.startswith("If the port")  # the ancestors still count


async def test_bm25_prefers_the_shorter_chunk_with_the_same_term(world: World) -> None:
    if world.engine == "memory":
        pytest.skip("the memory reference only counts terms; the database engines normalise length")
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


async def test_the_search_plan_materializes_the_ranking_and_probes_manifests_by_chunk_set() -> None:
    """The join order is what keeps a search at milliseconds (a bad plan took seconds).

    Plan shape on SQLite 3.35+: rank first (MATERIALIZE), probe the manifest rows by
    (blob_sha, config_hash) through `ix_retrieval_manifest_chunks_set` (from the migrations), and
    only then fetch snippets for the survivors. A probe per searched manifest instead would cost
    O(hits x manifests); measured, an extra covering index made that plan win and was slower.
    """
    container = Container.build(Settings())
    async with container.running(jobs=False):
        statement = _statements("EXPLAIN QUERY PLAN " + _SEARCH)[None]
        params = {
            "heading_weight": 1.0,
            "path_weight": 1.0,
            "text_weight": 1.0,
            "identifiers_weight": 1.0,
            "match": '"x"',
            "manifests": ["a", "b"],
            "limit": 5,
        }
        async with container.engine.connect() as connection:
            plan = (await connection.execute(statement, params)).all()
    steps = [row.detail for row in plan]
    assert any(step.startswith("MATERIALIZE ranked") for step in steps), steps
    probe = [s for s in steps if s.startswith("SEARCH mc USING")]
    assert probe
    assert "ix_retrieval_manifest_chunks_set (blob_sha=? AND config_hash=?)" in probe[0], steps
    # The snippets are fetched for the ranked survivors: r outside, then a lookup by rowid.
    outer = [s for s in steps if s.startswith(("SCAN r", "SCAN retrieval_search"))]
    assert outer[-2:] == ["SCAN r", "SCAN retrieval_search VIRTUAL TABLE INDEX 0:=M4"], steps
