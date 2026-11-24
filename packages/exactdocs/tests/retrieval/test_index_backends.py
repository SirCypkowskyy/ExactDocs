"""Adapter contract of the external index backends themselves (#352): ``SearchBackend``,
``VectorBackend`` and the optional ``NativeHybrid`` and ``NativeRerank``.

What every backend must do, whatever engine it talks to: put (add or replace) and delete per
version, report what it holds per version (the drift check), keep versions and libraries apart,
rank best first and cut at the limit, give nothing for an unknown version or when nothing
matches, and keep embedding spaces apart. The ``SearchIndex`` and ``VectorIndex`` suites run the
same backends again through the domain. An adapter PR adds its case to
``tests/fixtures/index_backends.py``; nothing here changes.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from exactdocs.retrieval.models import (
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    SpaceState,
    TagFilter,
    TagMatch,
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid, NativeRerank, SearchBackend, VectorBackend
from index_backends import SEARCH_BACKEND_CASES, VECTOR_BACKEND_CASES, params

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
OTHER = "/other/lib"
NO_TAGS = TagFilter()


def manifest(manifest_id: str, library: str = LIB, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/{ref}", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    *,
    heading: str = "Guide",
    tags: tuple[str, ...] = (),
    vector: tuple[float, ...] | None = None,
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", heading),
        content=content,
        tags=tags,
        vector=vector,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


def space(space_id: int = 1, dimensions: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model=f"m{space_id}", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


@pytest.fixture(params=params(SEARCH_BACKEND_CASES))
async def search(request: pytest.FixtureRequest) -> AsyncIterator[SearchBackend]:
    factory = SEARCH_BACKEND_CASES[request.param].search
    assert factory is not None
    async with factory() as backend:
        yield backend


@pytest.fixture(params=params(VECTOR_BACKEND_CASES))
async def vectors(request: pytest.FixtureRequest) -> AsyncIterator[VectorBackend]:
    factory = VECTOR_BACKEND_CASES[request.param].vectors
    assert factory is not None
    async with factory() as backend:
        yield backend


# ---------------------------------------------------------------- search backends


async def test_a_new_backend_holds_nothing_and_finds_nothing(search: SearchBackend) -> None:
    assert await search.held(None) == []
    assert await search.search(["m1"], query("retry"), NO_TAGS, 10) == []
    assert await search.count(["m1"], query("retry"), NO_TAGS) == {}


async def test_put_adds_and_replaces_entries_per_version(search: SearchBackend) -> None:
    v1 = manifest("m1")
    await search.put(v1, [entry(v1, "a", "retry once"), entry(v1, "b", "no match")])
    await search.put(v1, [entry(v1, "a", "retry once"), entry(v1, "c", "retry twice")])

    assert await search.held(None) == [HeldVersion(manifest_id="m1", library=LIB, entries=3)]
    found = await search.search(["m1"], query("retry"), NO_TAGS, 10)
    assert sorted(h.chunk_id for h in found) == ["a", "c"]


async def test_a_replaced_entry_is_found_by_its_new_text_and_tags(search: SearchBackend) -> None:
    v1 = manifest("m1")
    await search.put(v1, [entry(v1, "a", "old words", tags=("old",))])
    await search.put(v1, [entry(v1, "a", "fresh words", tags=("new",))])

    assert await search.search(["m1"], query("old"), NO_TAGS, 10) == []
    assert len(await search.search(["m1"], query("fresh"), TagFilter(tags=("new",)), 10)) == 1
    assert await search.search(["m1"], query("fresh"), TagFilter(tags=("old",)), 10) == []


async def test_delete_removes_whole_versions_only(search: SearchBackend) -> None:
    v1, v2 = manifest("m1"), manifest("m2", ref="v2")
    await search.put(v1, [entry(v1, "a", "retry")])
    await search.put(v2, [entry(v2, "a", "retry")])

    await search.delete(["m1", "never-held"])

    assert [h.manifest_id for h in await search.held(None)] == ["m2"]
    assert await search.search(["m1"], query("retry"), NO_TAGS, 10) == []
    assert [
        h.manifest_id for h in await search.search(["m1", "m2"], query("retry"), NO_TAGS, 10)
    ] == ["m2"]


async def test_held_is_filtered_by_library(search: SearchBackend) -> None:
    mine, theirs = manifest("m1"), manifest("o1", library=OTHER)
    await search.put(mine, [entry(mine, "a", "retry")])
    await search.put(theirs, [entry(theirs, "a", "retry"), entry(theirs, "b", "retry")])

    assert await search.held(LIB) == [HeldVersion(manifest_id="m1", library=LIB, entries=1)]
    assert await search.held(OTHER) == [HeldVersion(manifest_id="o1", library=OTHER, entries=2)]
    assert await search.held("/nobody/here") == []


async def test_a_search_never_returns_a_version_it_was_not_given(search: SearchBackend) -> None:
    old, new = manifest("m13", ref="v1.3.0"), manifest("m14", ref="v1.4.0")
    await search.put(old, [entry(old, "x", "Calls are retried three times.")])
    await search.put(new, [entry(new, "x", "retry_policy sets how often a call is retried.")])

    assert [h.manifest_id for h in await search.search(["m13"], query("retried"), NO_TAGS, 10)] == [
        "m13"
    ]
    assert await search.search(["m13"], query("retry_policy"), NO_TAGS, 10) == []
    assert await search.count(["m13", "m14"], query("retry_policy"), NO_TAGS) == {"m14": 1}


async def test_an_entry_of_two_versions_is_a_hit_for_each_with_one_score(
    search: SearchBackend,
) -> None:
    a, b = manifest("a"), manifest("b", library=OTHER)
    await search.put(a, [entry(a, "x", "token expiry")])
    await search.put(b, [entry(b, "x", "token expiry")])

    found = await search.search(["a", "b"], query("token"), NO_TAGS, 10)

    assert sorted(h.manifest_id for h in found) == ["a", "b"]
    assert found[0].score == found[1].score


async def test_the_top_k_is_best_first_and_cut_at_k(search: SearchBackend) -> None:
    v1 = manifest("m1")
    await search.put(
        v1, [entry(v1, f"c{n}", " ".join(["retry"] * n) + " filler") for n in range(1, 6)]
    )

    found = await search.search(["m1"], query("retry"), NO_TAGS, 3)

    assert [h.chunk_id for h in found] == ["c5", "c4", "c3"]
    assert [h.score for h in found] == sorted((h.score for h in found), reverse=True)
    assert await search.count(["m1"], query("retry"), NO_TAGS) == {"m1": 5}


async def test_the_tag_filter_applies_before_the_cut(search: SearchBackend) -> None:
    v1 = manifest("m1")
    loud = [entry(v1, f"l{i}", "retry retry retry retry") for i in range(5)]
    await search.put(v1, [*loud, entry(v1, "quiet", "retry once", tags=("api", "v2"))])

    for match in TagMatch:
        found = await search.search(
            ["m1"], query("retry"), TagFilter(tags=("api",), match=match), 1
        )
        assert [h.chunk_id for h in found] == ["quiet"]
    both = TagFilter(tags=("api", "v3"), match=TagMatch.ALL)
    assert await search.search(["m1"], query("retry"), both, 10) == []
    assert await search.count(["m1"], query("retry"), both) == {}


async def test_a_query_is_matched_by_its_terms_never_parsed(search: SearchBackend) -> None:
    v1 = manifest("m1")
    await search.put(v1, [entry(v1, "a", "Set retryPolicy (or retry_policy) to tune calls.")])

    for text in ['"retry_policy" NEAR (*', "retry*", "text:retry", "RETRY_POLICY", "retryPolicy"]:
        assert len(await search.search(["m1"], query(text), NO_TAGS, 10)) == 1, text
    assert await search.search([], query("retry"), NO_TAGS, 10) == []


# ---------------------------------------------------------------- vector backends


async def test_a_new_vector_backend_holds_nothing(vectors: VectorBackend) -> None:
    assert await vectors.held(EmbeddingSpaceId(1), None) == []
    assert await vectors.nearest(space(), ["m1"], [1, 0, 0], NO_TAGS, 10) == []


async def test_nearest_is_per_version_nearest_first_with_cosine_distances(
    vectors: VectorBackend,
) -> None:
    s, old, new = space(), manifest("m13", ref="v1.3.0"), manifest("m14", ref="v1.4.0")
    await vectors.put(s, old, [entry(old, "x", "x", vector=(1.0, 0.0, 0.0))])
    await vectors.put(
        s,
        new,
        [
            entry(new, "far", "far", vector=(-1.0, 0.0, 0.0)),
            entry(new, "mid", "mid", vector=(0.0, 1.0, 0.0)),
            entry(new, "near", "near", vector=(1.0, 1.0, 0.0)),
        ],
    )

    hits = await vectors.nearest(s, ["m14"], [1, 0, 0], NO_TAGS, 2)

    assert [(h.manifest_id, h.chunk_id) for h in hits] == [("m14", "near"), ("m14", "mid")]
    assert hits[0].distance == pytest.approx(1 - 2**-0.5, abs=1e-6)
    assert hits[1].distance == pytest.approx(1, abs=1e-6)
    assert [h.manifest_id for h in await vectors.nearest(s, ["m13"], [1, 0, 0], NO_TAGS, 10)] == [
        "m13"
    ]
    assert await vectors.nearest(s, ["unknown"], [1, 0, 0], NO_TAGS, 10) == []


async def test_spaces_are_kept_apart_and_dropped_whole(vectors: VectorBackend) -> None:
    small, large, v1 = space(1, 3), space(2, 4), manifest("m1")
    await vectors.put(small, v1, [entry(v1, "a", "a", vector=(1.0, 0.0, 0.0))])
    await vectors.put(large, v1, [entry(v1, "a", "a", vector=(0.0, 0.0, 0.0, 1.0))])

    assert [h.chunk_id for h in await vectors.nearest(small, ["m1"], [1, 0, 0], NO_TAGS, 5)] == [
        "a"
    ]
    await vectors.drop_space(small.id)
    await vectors.drop_space(EmbeddingSpaceId(99))  # unknown: nothing to do

    assert await vectors.held(small.id, None) == []
    assert await vectors.nearest(small, ["m1"], [1, 0, 0], NO_TAGS, 5) == []
    assert await vectors.held(large.id, None) == [
        HeldVersion(manifest_id="m1", library=LIB, entries=1)
    ]


async def test_put_replaces_and_remove_and_delete_take_entries_out(vectors: VectorBackend) -> None:
    s, v1, v2 = space(), manifest("m1"), manifest("o1", library=OTHER)
    await vectors.put(s, v1, [entry(v1, "a", "a", vector=(1.0, 0.0, 0.0))])
    await vectors.put(s, v1, [entry(v1, "a", "a", vector=(0.0, 1.0, 0.0))])  # replaced
    await vectors.put(s, v1, [entry(v1, "b", "b", vector=(0.0, 0.0, 1.0))])
    await vectors.put(s, v2, [entry(v2, "a", "a", vector=(0.0, 1.0, 0.0))])

    assert (await vectors.nearest(s, ["m1"], [0, 1, 0], NO_TAGS, 1))[0].chunk_id == "a"
    assert await vectors.held(s.id, OTHER) == [
        HeldVersion(manifest_id="o1", library=OTHER, entries=1)
    ]
    await vectors.remove(s.id, "m1", [ChunkId("a"), ChunkId("zz")])
    assert [h.chunk_id for h in await vectors.nearest(s, ["m1"], [0, 1, 0], NO_TAGS, 5)] == ["b"]
    await vectors.delete(["m1"])
    assert await vectors.held(s.id, None) == [
        HeldVersion(manifest_id="o1", library=OTHER, entries=1)
    ]


async def test_the_vector_tag_filter_applies_before_ranking(vectors: VectorBackend) -> None:
    s, v1 = space(), manifest("m1")
    await vectors.put(
        s,
        v1,
        [
            entry(v1, "near", "near", vector=(1.0, 0.0, 0.0)),
            entry(v1, "tagged", "tagged", tags=("api",), vector=(-1.0, 0.0, 0.0)),
        ],
    )

    hits = await vectors.nearest(s, ["m1"], [1, 0, 0], TagFilter(tags=("api",)), 1)

    assert [h.chunk_id for h in hits] == ["tagged"]


async def test_native_hybrid_ranks_both_halves_within_the_versions(vectors: VectorBackend) -> None:
    if not isinstance(vectors, NativeHybrid):
        pytest.skip("this backend leaves hybrid to ExactDocs' reciprocal rank fusion")
    s, v1, v2 = space(), manifest("m1"), manifest("m2", ref="v2")
    await vectors.put(
        s,
        v1,
        [
            entry(v1, "words", "RetryPolicy decides retries", vector=(0.0, 1.0, 0.0)),
            entry(v1, "meaning", "how often calls run again", vector=(1.0, 0.0, 0.0)),
            entry(v1, "other", "unrelated", vector=(0.0, 0.0, 1.0)),
        ],
    )
    await vectors.put(s, v2, [entry(v2, "words", "RetryPolicy", vector=(1.0, 0.0, 0.0))])

    found = await vectors.hybrid(s, ["m1"], query("RetryPolicy"), [1, 0, 0], NO_TAGS, 2)

    assert {h.manifest_id for h in found} == {"m1"}
    assert {h.chunk_id for h in found} == {"words", "meaning"}  # one from each half
    assert [h.score for h in found] == sorted((h.score for h in found), reverse=True)


async def test_native_rerank_reranks_the_hybrid_answer_within_the_versions(
    vectors: VectorBackend,
) -> None:
    if not isinstance(vectors, NativeRerank):
        pytest.skip("this backend leaves reranking to ExactDocs' own reranker")
    s, v1, v2 = space(), manifest("m1"), manifest("m2", ref="v2")
    retried = "Failed calls are retried three times with exponential backoff, then the client fails"
    await vectors.put(
        s,
        v1,
        [
            entry(
                v1, "install", "Install the client with pip", heading="Install", vector=(1, 0, 0)
            ),
            entry(v1, "retries", retried, heading="Retries", vector=(0.6, 0.8, 0.0)),
            entry(
                v1,
                "tagged",
                "How failed calls are retried",
                heading="Retry policy",
                tags=("api",),
                vector=(0.0, 0.0, 1.0),
            ),
        ],
    )
    await vectors.put(s, v2, [entry(v2, "retries", retried, vector=(1.0, 0.0, 0.0))])
    asked = query("how are failed calls retried")

    found = await vectors.hybrid_reranked(s, ["m1"], asked, [1, 0, 0], NO_TAGS, 3)
    tagged = await vectors.hybrid_reranked(s, ["m1"], asked, [1, 0, 0], TagFilter(tags=("api",)), 3)

    assert {h.manifest_id for h in found.hits} == {"m1"}  # never another version
    assert 0 < found.reranked <= len(found.hits) == 3
    head = [h.score for h in found.hits[: found.reranked]]
    assert head == sorted(head, reverse=True)  # the ranker's order
    # The vector alone puts the installation first; the ranker puts what answers the query first.
    assert {h.chunk_id for h in found.hits[:2]} == {"tagged", "retries"}
    assert [h.chunk_id for h in tagged.hits] == ["tagged"]  # filtered before ranking
