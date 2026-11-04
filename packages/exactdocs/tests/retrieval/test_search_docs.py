from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from exactdocs.retrieval.adapters.driven.memory import InMemoryChunkRepository, InMemorySearchIndex
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand, SearchDocsQuery
from exactdocs.retrieval.errors import (
    EmptySearchTextError,
    UnavailableModeError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    DocTarget,
    ManifestStatus,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    TagMatch,
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
    module = RetrievalModule.build(
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=InMemorySearchIndex(chunks),
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
    module = RetrievalModule.build(
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=InMemorySearchIndex(chunks),
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
