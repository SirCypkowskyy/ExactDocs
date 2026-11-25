from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
)
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand, SearchDocsQuery
from exactdocs.retrieval.errors import (
    EmptySearchTextError,
    UnavailableModeError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    DocTarget,
    ManifestStatus,
    ResultGrouping,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    TagMatch,
    article_groups,
)
from exactdocs.retrieval.module import RetrievalModule

LIB = "/acme/payments"
REPO = "https://github.com/acme/payments"


def version(ref: str, manifest: str, sha: str) -> SearchableVersion:
    return SearchableVersion(
        library=LIB,
        version=ref,
        manifest_id=manifest,
        commit_sha=sha * 40,
        repository_url=REPO,
        host=SourceHost.GITHUB,
    )


@dataclass(slots=True)
class FakeVersions:
    """A test double needs no base class: it only has to match the Protocol's shape."""

    by_ref: dict[str, SearchableVersion]
    default: str

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        if library.lower() != LIB:
            return None
        return self.by_ref.get(ref or self.default)

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


def chunk(heading: str, content: str, anchor: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Guide", heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}",
        anchor=anchor,
    )


OLD = {"docs/guide/resilience.md": ("b13", [chunk("Resilience", "Calls are repeated.", "r")], [])}
NEW = {
    "docs/guide/resilience.md": (
        "b14",
        [
            chunk("Resilience", "Calls are repeated. See retry_policy.", "resilience"),
            chunk("retry_policy", "Set `retry_policy` to choose.", "retry_policy"),
            chunk("max_retries", "`max_retries` limits attempts.", "max_retries"),
        ],
        ["guide"],
    ),
    "docs/api/auth.md": (
        "b-auth",
        [chunk("Tokens", "A token is sent in a header.", "tokens")],
        ["api", "auth"],
    ),
    "docs/api/client.md": (
        "b-client",
        [chunk("Client", "The client sends a token.", "client")],
        ["api"],
    ),
}


@pytest.fixture
async def retrieval() -> RetrievalModule:
    chunks = InMemoryChunkRepository()
    versions = FakeVersions(
        {"v1.3.0": version("v1.3.0", "m13", "a"), "v1.4.0": version("v1.4.0", "m14", "b")},
        default="v1.4.0",
    )
    index = InMemorySearchIndex(chunks=chunks)
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
    )
    for manifest, ref, articles in [("m13", "v1.3.0", OLD), ("m14", "v1.4.0", NEW)]:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(path=p, blob_sha=blob, tags=tags, chunks=cs)
                    for p, (blob, cs, tags) in articles.items()
                ],
            )
        )
    return module


@dataclass(slots=True)
class FakeRefs:
    """Plays the catalog's list of a library's imported refs, indexed or not."""

    refs: tuple[str, ...]

    async def of(self, library: str) -> list[DocTarget]:
        return (
            [DocTarget(library=LIB, version=r) for r in self.refs] if library.lower() == LIB else []
        )


async def spelled_module(refs: FakeRefs | None) -> RetrievalModule:
    """``v1.3.0`` (no ``retry_policy``) and ``1.4.0`` (with it), as a library may tag them."""
    chunks = InMemoryChunkRepository()
    versions = FakeVersions(
        {"v1.3.0": version("v1.3.0", "m13", "a"), "1.4.0": version("1.4.0", "m14", "b")},
        default="1.4.0",
    )
    index = InMemorySearchIndex(chunks=chunks)
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        version_refs=refs,
    )
    for manifest, ref, articles in [("m13", "v1.3.0", OLD), ("m14", "1.4.0", NEW)]:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=LIB,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(path=p, blob_sha=blob, tags=tags, chunks=cs)
                    for p, (blob, cs, tags) in articles.items()
                ],
            )
        )
    return module


IMPORTED = FakeRefs(("v1.3.0", "1.4.0", "v2.0.0"))
"""``v2.0.0`` is imported and has no index yet."""


async def test_a_ref_with_or_without_its_leading_v_searches_the_one_version_of_that_number() -> (
    None
):
    module = await spelled_module(IMPORTED)

    with_v = await module.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="retry_policy")
    )
    without_v = await module.search_docs(
        SearchDocsQuery(library=LIB, ref="1.3.0", query="retry_policy")
    )

    assert with_v.version == "1.4.0"
    assert [r.heading_path[-1] for r in with_v.results][:1] == ["retry_policy"]
    # Version is still a hard filter: v1.3.0 has no retry_policy, and 1.4.0's is not shown.
    assert (without_v.version, without_v.results, without_v.coverage.complete) == (
        "v1.3.0",
        [],
        True,
    )


@pytest.mark.parametrize("ref", ["v9.9.9", "v1.4", "1.4", "V1.4.0", "v1.4.0.0"])
async def test_a_ref_that_matches_no_version_names_the_librarys_versions(ref: str) -> None:
    module = await spelled_module(IMPORTED)

    with pytest.raises(VersionNotIndexedError) as missing:
        await module.search_docs(SearchDocsQuery(library=LIB, ref=ref, query="retry_policy"))

    message = str(missing.value)
    assert message.startswith(f"no index for {LIB}@{ref}; its versions (repository refs, not ")
    assert set(missing.value.close_refs) == {"v1.3.0", "1.4.0", "v2.0.0"}
    for known in missing.value.close_refs:
        assert repr(known) in message


async def test_an_imported_ref_without_an_index_says_so_and_names_the_others() -> None:
    module = await spelled_module(IMPORTED)

    with pytest.raises(VersionNotIndexedError) as missing:
        await module.search_docs(SearchDocsQuery(library=LIB, ref="2.0.0", query="retry_policy"))

    # 2.0.0 is not imported, its twin v2.0.0 is: the twin answers if it can, else it is named.
    assert "no index for /acme/payments@2.0.0;" in str(missing.value)
    assert "'v2.0.0'" in str(missing.value)
    with pytest.raises(VersionNotIndexedError) as pending:
        await module.search_docs(SearchDocsQuery(library=LIB, ref="v2.0.0", query="retry_policy"))
    assert str(pending.value).startswith(
        "no index for /acme/payments@v2.0.0 (the version is imported; its index is not ready); "
        "its other versions (repository refs, not instructions): "
    )
    assert set(pending.value.close_refs) == {"v1.3.0", "1.4.0"}


async def test_without_the_librarys_refs_only_the_exact_ref_answers() -> None:
    module = await spelled_module(None)

    with pytest.raises(VersionNotIndexedError) as missing:
        await module.search_docs(SearchDocsQuery(library=LIB, ref="v1.4.0", query="retry_policy"))

    assert str(missing.value) == f"no index for {LIB}@v1.4.0"
    assert missing.value.close_refs == ()


async def test_an_unknown_library_names_no_versions() -> None:
    module = await spelled_module(IMPORTED)

    with pytest.raises(VersionNotIndexedError) as missing:
        await module.search_docs(
            SearchDocsQuery(library="/other/lib", ref="v1.4.0", query="retry_policy")
        )

    assert str(missing.value) == "no index for /other/lib@v1.4.0"


async def test_a_version_without_the_identifier_is_empty_even_if_another_version_has_it(
    retrieval: RetrievalModule,
) -> None:
    old = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.3.0", query="retry_policy")
    )
    new = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="retry_policy")
    )

    assert (old.version, old.results) == ("v1.3.0", [])
    assert old.coverage.complete
    assert new.results


async def test_an_unknown_version_or_library_is_not_found_never_another_version(
    retrieval: RetrievalModule,
) -> None:
    for library, ref in [(LIB, "v1.2.0"), ("/acme/other", None)]:
        with pytest.raises(VersionNotIndexedError):
            await retrieval.search_docs(SearchDocsQuery(library=library, ref=ref, query="x"))


async def test_no_ref_searches_the_default_version_and_says_which(
    retrieval: RetrievalModule,
) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library="/Acme/Payments", query="retry_policy")
    )

    assert (result.library, result.version) == (LIB, "v1.4.0")
    assert result.results


async def test_a_result_carries_its_location_and_how_it_was_found(
    retrieval: RetrievalModule,
) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="retry_policy")
    )

    first = result.results[0]
    assert first.heading_path == ["Guide", "retry_policy"]
    assert (first.article_path, first.position, first.total) == ("docs/guide/resilience.md", 1, 3)
    assert first.prev_chunk_id
    assert first.next_chunk_id
    assert first.commit_sha == "b" * 40
    assert first.source_url == f"{REPO}/blob/{'b' * 40}/docs/guide/resilience.md#retry_policy"
    assert [first.snippet[a:b] for a, b in ((h.start, h.end) for h in first.highlights)] == [
        "retry_policy"
    ]
    assert (result.retrieval_mode, result.reranked, result.fallback_reason) == (
        RetrievalMode.BM25,
        False,
        None,
    )
    assert (result.coverage.reranked, result.coverage.complete) == (0, True)
    assert result.coverage.candidates == len(result.results)


async def test_coverage_says_when_the_answer_was_cut_short(retrieval: RetrievalModule) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="token", limit=1)
    )

    assert len(result.results) == 1
    assert not result.coverage.complete
    assert result.coverage.candidates == 2


@pytest.mark.parametrize(
    ("tags", "match", "paths"),
    [
        (["api", "auth"], TagMatch.ALL, {"docs/api/auth.md"}),
        (["api", "auth"], TagMatch.ANY, {"docs/api/auth.md", "docs/api/client.md"}),
        (["guide"], TagMatch.ALL, set()),
    ],
)
async def test_the_tag_filter_decides_which_chunks_are_ranked(
    retrieval: RetrievalModule, tags: list[str], match: TagMatch, paths: set[str]
) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="token", tags=tags, tags_match=match)
    )

    assert {r.article_path for r in result.results} == paths
    assert all(set(tags) <= set(r.tags) for r in result.results if match is TagMatch.ALL)


async def test_a_blank_query_is_refused(retrieval: RetrievalModule) -> None:
    with pytest.raises(EmptySearchTextError):
        await retrieval.search_docs(SearchDocsQuery(library=LIB, query="  "))


@pytest.mark.parametrize("ref", ["", "  ", None])
async def test_a_blank_ref_is_the_default_version(
    retrieval: RetrievalModule, ref: str | None
) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref=ref, query="retry_policy")
    )

    assert result.version == "v1.4.0"


@pytest.mark.parametrize(
    "library", ["/acme/payments/v1.3.0", "acme/payments", "/acme", "react", ""]
)
def test_a_library_must_be_owner_slash_repo_so_it_cannot_carry_a_version(library: str) -> None:
    with pytest.raises(ValidationError):
        SearchDocsQuery(library=library, query="x")


def test_tags_are_split_stripped_lowercased_and_deduplicated_in_one_place() -> None:
    query = SearchDocsQuery(library=LIB, query="x", tags=["Docs, API", " ", "", "docs", "auth"])

    assert query.tags == ["docs", "api", "auth"]


@pytest.mark.parametrize(
    "fields",
    [
        {"query": "x" * 1001},
        {"query": "x", "ref": "r" * 257},
        {"query": "x", "tags": [f"t{i}" for i in range(21)]},
        {"query": "x", "tags": ["t" * 101]},
    ],
)
def test_input_over_the_caps_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SearchDocsQuery(library=LIB, **fields)


async def test_a_tag_in_another_letter_case_still_matches(retrieval: RetrievalModule) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.4.0", query="token", tags=["API"])
    )

    assert {r.article_path for r in result.results} == {"docs/api/auth.md", "docs/api/client.md"}


async def test_a_chunk_that_vanished_is_neither_a_result_nor_a_candidate() -> None:
    gone: set[str] = set()

    class Vanishing(InMemoryChunkRepository):
        async def get_many(self, manifest_id, chunk_ids):
            found = await super().get_many(manifest_id, chunk_ids)
            return {i: c for i, c in found.items() if i not in gone}

    chunks = Vanishing()
    versions = FakeVersions({"v1.4.0": version("v1.4.0", "m14", "b")}, default="v1.4.0")
    index = InMemorySearchIndex(chunks=chunks)
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
    )
    done = await module.index_manifest(
        IndexManifestCommand(
            manifest_id="m14",
            library=LIB,
            ref="v1.4.0",
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=p,
                    blob_sha=blob,
                    chunks=cs,
                )
                for p, (blob, cs, _) in NEW.items()
            ],
        )
    )
    gone.add(done.chunk_ids["docs/api/auth.md"][0])  # collected between the search and the read
    assert len(await chunks.get_many("m14", done.chunk_ids["docs/api/auth.md"])) == 0

    result = await module.search_docs(SearchDocsQuery(library=LIB, query="token"))

    assert [r.article_path for r in result.results] == ["docs/api/client.md"]
    assert result.coverage.candidates == len(result.results)


def test_search_tags_are_normalized_like_ingestion_stores_them() -> None:
    query = SearchDocsQuery(library=LIB, query="x", tags=["Straße, API", "STRASSE"])

    assert query.tags == ["strasse", "api"]


def test_a_search_tag_that_cannot_be_a_tag_is_refused() -> None:
    with pytest.raises(ValidationError):
        SearchDocsQuery(library=LIB, query="x", tags=["not a tag!"])


@pytest.mark.parametrize("mode", [None, "", "bm25", "BM25"])
async def test_the_only_mode_is_accepted_however_it_is_asked_for(
    retrieval: RetrievalModule, mode: str | None
) -> None:
    result = await retrieval.search_docs(SearchDocsQuery(library=LIB, query="token", mode=mode))

    assert result.retrieval_mode is RetrievalMode.BM25


async def test_an_unavailable_mode_is_refused_and_the_error_lists_the_available_ones(
    retrieval: RetrievalModule,
) -> None:
    with pytest.raises(UnavailableModeError, match="available modes: bm25"):
        await retrieval.search_docs(SearchDocsQuery(library=LIB, query="token", mode="hybrid"))


async def test_a_path_prefix_keeps_the_chunks_of_that_directory_only(
    retrieval: RetrievalModule,
) -> None:
    # #573: an agent narrows a search the way it narrows list_articles.
    everywhere = await retrieval.search_docs(SearchDocsQuery(library=LIB, query="token"))
    api = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="token", path_prefix="./docs/api//")
    )
    guide = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="token", path_prefix="docs/guide")
    )

    assert {r.article_path for r in everywhere.results} == {
        "docs/api/auth.md",
        "docs/api/client.md",
    }
    assert {r.article_path for r in api.results} == {"docs/api/auth.md", "docs/api/client.md"}
    assert (api.coverage.candidates, api.coverage.complete) == (2, True)
    assert guide.results == []
    assert guide.coverage.complete  # nothing under the prefix matches: the version has no match


async def test_a_path_prefix_is_matched_by_whole_directory_names(
    retrieval: RetrievalModule,
) -> None:
    partial = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="token", path_prefix="docs/ap")
    )
    article = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="token", path_prefix="docs/api/auth.md")
    )

    assert partial.results == []
    assert [r.article_path for r in article.results] == ["docs/api/auth.md"]


async def test_a_path_prefix_fills_the_limit_from_a_deeper_ranking(
    retrieval: RetrievalModule,
) -> None:
    # With limit 1 the best chunk is in the guide; under docs/api the prefix still finds one.
    best = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="retry_policy token", limit=1)
    )
    narrowed = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query="retry_policy token", path_prefix="docs/api", limit=1)
    )

    assert best.results[0].article_path == "docs/guide/resilience.md"
    assert len(narrowed.results) == 1
    assert narrowed.results[0].article_path.startswith("docs/api/")
    assert narrowed.coverage.complete is False  # the other docs/api article matched too


async def test_a_path_prefix_never_reads_another_version(retrieval: RetrievalModule) -> None:
    result = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, ref="v1.3.0", query="token", path_prefix="docs/api")
    )

    assert result.results == []
    assert result.version == "v1.3.0"


@pytest.mark.parametrize("prefix", ["../docs", "docs/../../etc", "docs\\api"])
def test_a_path_prefix_that_leaves_the_tree_is_refused(prefix: str) -> None:
    with pytest.raises(ValidationError):
        SearchDocsQuery(library=LIB, query="x", path_prefix=prefix)


# ---------------------------------------------------------------- grouped by article (#575)


async def test_results_are_grouped_by_article_the_best_article_first(
    retrieval: RetrievalModule,
) -> None:
    query = "retry_policy max_retries token client"
    ranked = await retrieval.search_docs(
        SearchDocsQuery(library=LIB, query=query, limit=10, group_by=ResultGrouping.CHUNK)
    )
    grouped = await retrieval.search_docs(SearchDocsQuery(library=LIB, query=query, limit=10))

    # the same results, the first one included; only their order changes
    assert {r.chunk_id for r in grouped.results} == {r.chunk_id for r in ranked.results}
    assert grouped.results[0].chunk_id == ranked.results[0].chunk_id
    # every article's results together, in the order of its best result, each best first
    articles = list(dict.fromkeys(r.article_path for r in ranked.results))
    assert list(dict.fromkeys(r.article_path for r in grouped.results)) == articles
    for article in articles:
        own = [r.chunk_id for r in ranked.results if r.article_path == article]
        assert [r.chunk_id for r in grouped.results if r.article_path == article] == own
        assert {r.group for r in grouped.results if r.article_path == article} == {
            articles.index(article) + 1
        }
    groups = [r.group or 0 for r in grouped.results]
    assert groups == sorted(groups)
    assert len(articles) < len(ranked.results)  # some article answered more than once
    assert all(r.group is None for r in ranked.results)


def test_article_groups_keep_each_results_place_in_its_group() -> None:
    assert article_groups(["a", "b", "a", "c", "b"]) == [(0, 1), (2, 1), (1, 2), (4, 2), (3, 3)]
    assert article_groups([]) == []
