"""Azure AI Search as the search and vector backend (#353), beyond the shared contract suites.

The contract suites (``test_search_index.py``, ``test_vector_index.py``,
``test_index_backends.py``) run this backend on the in-process fake of the REST API
(``azure_search_fake.py``, plugged in as the azure-core transport). Here: the options, the index
lifecycle (made when missing, dimensions from the embedding model, a schema mismatch refused with
a clear message), what the documents carry, the filters sent to Azure, writes that wait for near
real time indexing, native hybrid in one request, the semantic ranker reranking it (#473: the
semantic configuration made or added, the request shape, a ranker over capacity), and both kinds
of credentials, the key never shown.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from azure.core.credentials import AccessToken
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from azure_search_fake import API_KEY, ENDPOINT, TOKEN, FakeSearchService, documents_of
from azure_search_server import fake_options
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.azure_search_index import (
    AzureHybridVectorBackend,
    AzureSearchBackend,
    AzureSemanticVectorBackend,
    AzureVectorBackend,
    _ThreadedCredential,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    IndexEntry,
    SpaceState,
    TagFilter,
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid, NativeRerank

T0 = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"


def manifest(manifest_id: str = "m14", ref: str = "v1.4.0") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{LIB}/{ref}", library=LIB, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    *,
    tags: tuple[str, ...] = (),
    vector: tuple[float, ...] | None = None,
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Guide", "Retries"),
        content=content,
        tags=tags,
        vector=vector,
    )


def space(dimensions: int = 3, space_id: int = 1) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


@pytest.fixture
def service() -> FakeSearchService:
    return FakeSearchService()


@pytest.fixture
async def search(service: FakeSearchService) -> AsyncIterator[AzureSearchBackend]:
    backend = search_backend(fake_options(service), transport=service.transport)
    await backend.open()
    yield backend
    await backend.close()


@pytest.fixture
async def vectors(service: FakeSearchService) -> AsyncIterator[AzureHybridVectorBackend]:
    backend = vector_backend(fake_options(service), transport=service.transport)
    assert isinstance(backend, AzureHybridVectorBackend)
    await backend.open()
    yield backend
    await backend.close()


# ---------------------------------------------------------------- options


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "endpoint must be the service's URL"),
        ({"endpoint": "http://svc.search.windows.net"}, "endpoint must be the service's URL"),
        ({"endpoint": ENDPOINT + "/indexes"}, "no path or query"),
        ({"endpoint": ENDPOINT, "index": "Docs"}, "lower-case letters"),
        ({"endpoint": ENDPOINT, "index": "a--b"}, "single dashes"),
        ({"endpoint": ENDPOINT, "auth": "api_key"}, "auth = api_key needs the key"),
        ({"endpoint": ENDPOINT, "api_key": "k", "auth": "default"}, "uses Entra ID"),
        ({"endpoint": ENDPOINT, "auth": "password"}, "auth must be one of"),
        ({"endpoint": ENDPOINT, "api_key": "k", "client_id": "c"}, "names a managed identity"),
        ({"endpoint": ENDPOINT, "hybrid": "maybe"}, "hybrid must be true or false"),
        ({"endpoint": ENDPOINT, "vector_search": "fast"}, "vector_search must be"),
        ({"endpoint": ENDPOINT, "timeout": "0"}, "timeout must be a whole number"),
        ({"endpoint": ENDPOINT, "audience": "search.azure.us"}, "audience must be an https"),
        ({"endpoint": ENDPOINT, "url": "x"}, "unknown options url"),
    ],
)
def test_invalid_options_are_refused_with_what_to_fix(
    options: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        search_backend(options)
    with pytest.raises(ValueError, match=message):
        vector_backend(options)


def test_the_key_comes_from_a_file_or_the_environment_never_both(tmp_path: Path) -> None:
    secret = tmp_path / "key"
    secret.write_text(f"{API_KEY}\n", encoding="utf-8")

    backend = search_backend({"endpoint": ENDPOINT, "api_key_file": str(secret)})

    assert backend.service.connection.hidden == (API_KEY,)
    assert API_KEY not in repr(backend)
    with pytest.raises(ValueError, match="not both"):
        search_backend({"endpoint": ENDPOINT, "api_key": "k", "api_key_file": str(secret)})
    with pytest.raises(ValueError, match="cannot be read"):
        search_backend({"endpoint": ENDPOINT, "api_key_file": str(tmp_path / "missing")})


def test_the_environment_configures_the_backend_through_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_SEARCH_BACKEND", "azure_search")
    monkeypatch.setenv("EXACTDOCS_VECTOR_BACKEND", "azure_search")
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__ENDPOINT", ENDPOINT)
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY", API_KEY)
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__INDEX", "team-docs")
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__HYBRID", "false")

    backends = build_index_backends(Settings())

    assert isinstance(backends.search, AzureSearchBackend)
    assert isinstance(backends.vectors, AzureVectorBackend)  # hybrid off: ExactDocs fuses
    assert not isinstance(backends.vectors, NativeHybrid)
    assert backends.search.index == "team-docs"
    assert backends.names == ("azure_search", "azure_search")


def test_invalid_options_stop_the_start_naming_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_SEARCH_BACKEND", "azure_search")

    with pytest.raises(StartupError, match=r"\[index_backends\.azure_search\].*endpoint"):
        build_index_backends(Settings())


def test_entra_id_is_the_default_credential_and_a_managed_identity_can_be_named() -> None:
    default = search_backend({"endpoint": ENDPOINT}).service.connection.credential()
    managed = search_backend(
        {"endpoint": ENDPOINT, "auth": "managed_identity", "client_id": "client-1"}
    ).service.connection.credential()

    assert isinstance(default, _ThreadedCredential)
    assert isinstance(default.credential, DefaultAzureCredential)
    assert isinstance(managed, _ThreadedCredential)
    assert isinstance(managed.credential, ManagedIdentityCredential)


# ---------------------------------------------------------------- index lifecycle


async def test_the_search_index_is_made_when_missing_with_identifiers_kept_whole(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    index = service.indexes["exactdocs"].definition
    fields = {f["name"]: f for f in index["fields"]}

    assert {fields[n]["analyzer"] for n in ("heading", "path", "body")} == {"whitespace"}
    for name in ("manifest_id", "library", "version_id", "chunk_id"):
        assert fields[name]["filterable"], name
    assert fields["tags"]["type"] == "Collection(Edm.String)"
    assert fields["tags"]["filterable"]
    assert index["similarity"]["@odata.type"].endswith("BM25Similarity")
    (profile,) = index["scoringProfiles"]
    assert profile["text"]["weights"] == {"heading": 20.0, "path": 4.0, "body": 1.0}
    assert "vector" not in fields
    assert search.index == "exactdocs"


async def test_an_existing_index_with_the_same_schema_is_used_as_it_is(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    v1 = manifest()
    await search.put(v1, [entry(v1, "a", "retry once")])
    again = search_backend(fake_options(service), transport=service.transport)

    await again.open()
    try:
        assert len(await again.search(["m14"], query("retry"), TagFilter(), 10)) == 1
    finally:
        await again.close()
    assert [p for m, p in service.requests if m == "POST" and p == "/indexes"] == ["/indexes"]


async def test_a_search_index_of_another_schema_stops_the_start_naming_what_differs(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    del search
    fields = service.indexes["exactdocs"].definition["fields"]
    body = next(f for f in fields if f["name"] == "body")
    body["analyzer"] = "keyword"  # as someone else's index could be
    other = search_backend(fake_options(service), transport=service.transport)

    with pytest.raises(IndexBackendUnavailableError) as refused:
        await other.open()
    await other.close()

    message = str(refused.value)
    assert "'exactdocs' does not have ExactDocs' schema" in message
    assert "'body' is analysed by 'keyword', not 'whitespace'" in message
    assert "exactdocs index rebuild" in message


async def test_a_space_index_takes_its_dimensions_from_the_embedding_model(
    service: FakeSearchService, vectors: AzureHybridVectorBackend
) -> None:
    v1 = manifest()
    await vectors.put(space(dimensions=4), v1, [entry(v1, "a", "retry", vector=(1, 0, 0, 0))])

    index = service.indexes["exactdocs-space1"].definition
    vector = next(f for f in index["fields"] if f["name"] == "vector")
    assert vector["dimensions"] == 4
    assert vector["type"] == "Collection(Edm.Single)"
    assert index["vectorSearch"]["algorithms"][0]["hnswParameters"]["metric"] == "cosine"


async def test_a_space_index_of_other_dimensions_is_never_written_to(
    service: FakeSearchService, vectors: AzureHybridVectorBackend
) -> None:
    v1 = manifest()
    await vectors.put(space(dimensions=4), v1, [entry(v1, "a", "retry", vector=(1, 0, 0, 0))])
    other = vector_backend(fake_options(service), transport=service.transport)
    await other.open()

    try:
        with pytest.raises(IndexBackendUnavailableError) as refused:
            await other.put(space(dimensions=3), v1, [entry(v1, "b", "x", vector=(1, 0, 0))])
    finally:
        await other.close()

    assert "'vector' holds vectors of 4 dimensions, not 3" in str(refused.value)
    assert set(documents_of_index(service, "exactdocs-space1")) == {"a"}


def documents_of_index(service: FakeSearchService, index: str) -> list[str]:
    return [d["chunk_id"] for d in documents_of(service, index)]


async def test_an_index_dropped_behind_its_back_is_made_again_on_the_next_write(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    v1 = manifest()
    await search.put(v1, [entry(v1, "a", "retry once")])
    del service.indexes["exactdocs"]

    with pytest.raises(IndexBackendUnavailableError, match="HTTP 404"):
        await search.put(v1, [entry(v1, "a", "retry once")])
    await search.put(v1, [entry(v1, "a", "retry once")])  # the job's retry

    assert documents_of_index(service, "exactdocs") == ["a"]


# ---------------------------------------------------------------- documents and queries


async def test_documents_carry_the_library_and_version_and_their_words(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    v1 = manifest()
    await search.put(v1, [entry(v1, "a", "Set retryPolicy.", tags=("api",))])

    (document,) = documents_of(service, "exactdocs")
    assert document["library"] == LIB
    assert document["version_id"] == f"{LIB}/v1.4.0"
    assert document["manifest_id"] == "m14"
    assert document["tags"] == ["api"]
    assert document["body"] == "set retrypolicy retry policy"


async def test_every_query_is_filtered_to_the_asked_versions_inside_azure(
    service: FakeSearchService,
    search: AzureSearchBackend,
    vectors: AzureHybridVectorBackend,
) -> None:
    v1, s = manifest(), space()
    await search.put(v1, [entry(v1, "a", "retry")])
    await vectors.put(s, v1, [entry(v1, "a", "retry", vector=(1, 0, 0))])
    service.bodies.clear()

    await search.search(["m14"], query("retry"), TagFilter(tags=("api",)), 5)
    await search.count(["m14"], query("retry"), TagFilter())
    await vectors.nearest(s, ["m14"], [1, 0, 0], TagFilter(), 5)
    await vectors.hybrid(s, ["m14"], query("retry"), [1, 0, 0], TagFilter(), 5)

    filters = [b["filter"] for b in service.bodies]
    assert (
        filters[0] == "search.in(manifest_id, 'm14', '|') and tags/any(t: search.in(t, 'api', '|'))"
    )
    assert all(f.startswith("search.in(manifest_id, 'm14', '|')") for f in filters), filters
    assert all(b.get("vectorFilterMode") == "preFilter" for b in service.bodies[2:]), service.bodies


async def test_writes_return_once_the_index_counts_them(service: FakeSearchService) -> None:
    service.lag = 4  # each write is searchable only four searches later
    backend = search_backend(fake_options(service), transport=service.transport)
    await backend.open()
    v1 = manifest()
    try:
        await backend.put(v1, [entry(v1, "a", "retry"), entry(v1, "b", "retry")])
        assert len(service.visible("exactdocs")) == 2
        assert not service.indexes["exactdocs"].pending
        await backend.delete(["m14"])
        assert service.visible("exactdocs") == {}
    finally:
        await backend.close()


async def test_native_hybrid_is_one_azure_hybrid_query(
    service: FakeSearchService, vectors: AzureHybridVectorBackend
) -> None:
    v1, s = manifest(), space()
    await vectors.put(
        s,
        v1,
        [
            entry(v1, "words", "RetryPolicy decides retries", vector=(0.0, 1.0, 0.0)),
            entry(v1, "meaning", "how often calls run again", vector=(1.0, 0.0, 0.0)),
        ],
    )
    service.bodies.clear()

    found = await vectors.hybrid(s, ["m14"], query("RetryPolicy"), [1, 0, 0], TagFilter(), 2)

    (body,) = service.bodies
    assert body["search"] == "retrypolicy retry policy"
    assert body["queryType"] == "full"
    assert body["vectorQueries"][0]["fields"] == "vector"
    assert {h.chunk_id for h in found} == {"words", "meaning"}
    assert isinstance(vectors, NativeHybrid)


async def test_exact_vector_search_asks_for_an_exhaustive_query(service: FakeSearchService) -> None:
    backend = vector_backend(
        fake_options(service, vector_search="exact", hybrid=False), transport=service.transport
    )
    await backend.open()
    v1, s = manifest(), space()
    try:
        await backend.put(s, v1, [entry(v1, "a", "a", vector=(1, 0, 0))])
        service.bodies.clear()
        await backend.nearest(s, ["m14"], [1, 0, 0], TagFilter(), 3)
    finally:
        await backend.close()

    assert service.bodies[0]["vectorQueries"][0]["exhaustive"] is True
    assert "body" not in next(iter(documents_of(service, "exactdocs-space1")))


# ---------------------------------------------------------------- credentials and failures


async def test_a_refused_key_stops_the_start_and_is_never_shown(
    service: FakeSearchService, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    wrong = "wrong-key-that-must-not-leak"
    backend = search_backend(fake_options(service, api_key=wrong), transport=service.transport)

    with pytest.raises(IndexBackendUnavailableError) as refused:
        await backend.open()
    await backend.close()

    assert "authentication failed (HTTP 403)" in str(refused.value)
    assert wrong not in str(refused.value)
    assert wrong not in caplog.text
    assert API_KEY not in caplog.text


class StaticToken:
    """A sync Entra ID credential handing out one token (as a managed identity would)."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        del kwargs
        self.scopes.append(scopes)
        return AccessToken(self.token, 4_102_444_800)


async def test_entra_id_tokens_authenticate_every_request(service: FakeSearchService) -> None:
    credential = StaticToken(TOKEN)
    options = {"endpoint": ENDPOINT, "auth": "managed_identity"}
    backend = search_backend(options, transport=service.transport, credential=credential)

    await backend.open()
    v1 = manifest()
    try:
        await backend.put(v1, [entry(v1, "a", "retry")])
        assert len(await backend.search(["m14"], query("retry"), TagFilter(), 5)) == 1
    finally:
        await backend.close()

    assert credential.scopes[0] == ("https://search.azure.com/.default",)
    refused = search_backend(
        options, transport=service.transport, credential=StaticToken("expired")
    )
    with pytest.raises(IndexBackendUnavailableError, match=r"authentication failed \(HTTP 401\)"):
        await refused.open()
    await refused.close()


async def test_a_service_that_does_not_answer_is_unavailable(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    service.unavailable = True

    with pytest.raises(IndexBackendUnavailableError, match="no answer"):
        await search.search(["m14"], query("retry"), TagFilter(), 5)


async def test_a_refused_request_names_the_services_reason(
    vectors: AzureHybridVectorBackend,
) -> None:
    v1 = manifest()
    await vectors.put(space(3), v1, [entry(v1, "a", "a", vector=(1, 0, 0))])

    with pytest.raises(
        IndexBackendUnavailableError, match="HTTP 400: The vector query has 2 dimensions"
    ):
        await vectors.nearest(space(3), ["m14"], [1, 0], TagFilter(), 3)


async def test_ids_and_tags_with_quotes_and_delimiters_are_filtered_exactly(
    service: FakeSearchService, search: AzureSearchBackend
) -> None:
    odd = manifest("m'1|,;~^")  # every search.in delimiter: the filter falls back to eq clauses
    plain = manifest("m2", ref="v2")
    await search.put(odd, [entry(odd, "a", "retry", tags=("it's",))])
    await search.put(plain, [entry(plain, "a", "retry", tags=("it's",))])

    found = await search.search([odd.manifest_id], query("retry"), TagFilter(tags=("it's",)), 5)

    assert [h.manifest_id for h in found] == ["m'1|,;~^"]
    assert service.bodies[-1]["filter"].startswith("(manifest_id eq 'm''1|,;~^')")
    await search.delete([odd.manifest_id])
    assert [h.manifest_id for h in await search.held(None)] == ["m2"]


# ---------------------------------------------------------------- the semantic ranker (#473)


SEMANTIC = "docs-semantic"
ASKED = "how are failed calls retried"


@pytest.fixture
async def semantic(service: FakeSearchService) -> AsyncIterator[AzureSemanticVectorBackend]:
    options = fake_options(service, semantic_configuration=SEMANTIC)
    backend = vector_backend(options, transport=service.transport)
    assert isinstance(backend, AzureSemanticVectorBackend)
    await backend.open()
    yield backend
    await backend.close()


async def _put_guide(backend: AzureHybridVectorBackend, s: EmbeddingSpace) -> None:
    """Three chunks the hybrid query and the semantic ranker order differently."""
    v1, v2 = manifest(), manifest("m15", "v1.5.0")
    await backend.put(
        s,
        v1,
        [
            # The words over and over, and the nearest vector: the hybrid query's first.
            entry(v1, "noise", "failed failed failed calls calls calls", vector=(1.0, 0.0, 0.0)),
            # What answers the question: the semantic ranker's first.
            entry(v1, "answer", "How are failed calls retried? Three times.", vector=(0, 0, 1)),
            entry(v1, "other", "Unrelated text", vector=(0.0, 1.0, 0.0)),
        ],
    )
    await backend.put(
        s, v2, [entry(v2, "answer", "How are failed calls retried?", vector=(1, 0, 0))]
    )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"semantic_configuration": "has space"}, "semantic_configuration 'has space' must be"),
        ({"semantic_configuration": "-dash"}, "starting with a letter or digit"),
        ({"semantic_configuration": "x" * 129}, "1 to 128 letters"),
        ({"semantic_configuration": "docs", "hybrid": False}, "it needs hybrid = true"),
    ],
)
def test_an_invalid_semantic_configuration_is_refused_with_what_to_fix(
    options: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        search_backend({"endpoint": ENDPOINT} | options)
    with pytest.raises(ValueError, match=message):
        vector_backend({"endpoint": ENDPOINT} | options)


def test_a_semantic_configuration_makes_the_backend_rerank_natively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_VECTOR_BACKEND", "azure_search")
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__ENDPOINT", ENDPOINT)
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__API_KEY", API_KEY)
    monkeypatch.setenv("EXACTDOCS_INDEX_BACKENDS__AZURE_SEARCH__SEMANTIC_CONFIGURATION", SEMANTIC)

    backends = build_index_backends(Settings())

    assert isinstance(backends.vectors, AzureSemanticVectorBackend)
    assert isinstance(backends.vectors, NativeHybrid)
    assert isinstance(backends.vectors, NativeRerank)
    assert backends.vectors.vectors.semantic == SEMANTIC
    plain = vector_backend({"endpoint": ENDPOINT, "api_key": API_KEY})
    assert isinstance(plain, NativeHybrid)
    assert not isinstance(plain, NativeRerank)  # no semantic configuration: ExactDocs reranks


async def test_a_space_index_is_made_with_the_semantic_configuration_over_plain_text(
    service: FakeSearchService, semantic: AzureSemanticVectorBackend
) -> None:
    v1 = manifest()
    await semantic.put(space(), v1, [entry(v1, "a", "Set retryPolicy.", vector=(1, 0, 0))])

    index = service.indexes["exactdocs-space1"].definition
    fields = {f["name"]: f for f in index["fields"]}
    for name in ("title", "content"):
        assert fields[name]["type"] == "Edm.String"
        assert fields[name]["searchable"], name
        assert fields[name]["retrievable"], name
    (configuration,) = index["semantic"]["configurations"]
    assert configuration["name"] == SEMANTIC
    assert configuration["prioritizedFields"]["titleField"] == {"fieldName": "title"}
    assert configuration["prioritizedFields"]["prioritizedContentFields"] == [
        {"fieldName": "content"}
    ]
    (document,) = documents_of(service, "exactdocs-space1")
    assert document["title"] == "Guide / Retries"
    assert document["content"] == "Set retryPolicy."  # as written, for the ranker to read
    assert document["body"] == "set retrypolicy retry policy"  # BM25's words unchanged


async def test_a_reranked_hybrid_query_asks_azures_semantic_ranker_in_the_same_request(
    service: FakeSearchService, semantic: AzureSemanticVectorBackend
) -> None:
    s = space()
    await _put_guide(semantic, s)
    service.bodies.clear()

    ranking = await semantic.hybrid_reranked(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)

    (body,) = service.bodies
    assert body["search"] == "how are failed calls retried"  # BM25's escaped terms, as before
    assert body["queryType"] == "full"
    assert body["semanticConfiguration"] == SEMANTIC
    assert body["semanticQuery"] == ASKED  # the ranker reads the query as written
    assert body["semanticErrorHandling"] == "partial"
    assert body["vectorQueries"][0]["fields"] == "vector"
    assert body["filter"] == "search.in(manifest_id, 'm14', '|')"  # the version, before ranking
    assert body["top"] >= 50  # every result the ranker reranks, cut after it
    assert "orderby" not in body
    assert body["select"] == "manifest_id,chunk_id"
    assert [h.chunk_id for h in ranking.hits] == ["answer", "noise", "other"]
    assert [h.score for h in ranking.hits] == [4.0, 1.6, 0.0]  # the ranker's scores, 0 to 4
    assert ranking.reranked == 3
    assert {h.manifest_id for h in ranking.hits} == {"m14"}


async def test_the_semantic_ranker_reorders_what_the_hybrid_query_found(
    semantic: AzureSemanticVectorBackend,
) -> None:
    s = space()
    await _put_guide(semantic, s)

    hybrid = await semantic.hybrid(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)
    ranking = await semantic.hybrid_reranked(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)

    assert hybrid[0].chunk_id == "noise"
    assert ranking.hits[0].chunk_id == "answer"
    assert {h.chunk_id for h in hybrid} == {h.chunk_id for h in ranking.hits}


async def test_a_semantic_ranker_over_capacity_leaves_the_hybrid_order_not_reranked(
    service: FakeSearchService, semantic: AzureSemanticVectorBackend
) -> None:
    s = space()
    await _put_guide(semantic, s)
    hybrid = await semantic.hybrid(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)
    service.semantic_overloaded = True

    ranking = await semantic.hybrid_reranked(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)

    assert ranking.reranked == 0
    assert [h.chunk_id for h in ranking.hits] == [h.chunk_id for h in hybrid]


async def test_without_a_semantic_configuration_no_semantic_parameter_is_sent(
    service: FakeSearchService, vectors: AzureHybridVectorBackend
) -> None:
    s = space()
    await _put_guide(vectors, s)
    service.bodies.clear()

    await vectors.hybrid(s, ["m14"], query(ASKED), [1, 0, 0], TagFilter(), 3)

    (body,) = service.bodies
    assert not {k for k in body if k.startswith("semantic")}, body
    assert not isinstance(vectors, NativeRerank)
    definition = service.indexes["exactdocs-space1"].definition
    assert definition["semantic"] is None
    assert not {"title", "content"} & {f["name"] for f in definition["fields"]}


async def test_an_existing_space_index_gets_the_semantic_configuration_added_in_place(
    service: FakeSearchService,
    vectors: AzureHybridVectorBackend,
    caplog: pytest.LogCaptureFixture,
) -> None:
    v1, s = manifest(), space()
    await vectors.put(s, v1, [entry(v1, "old", "retry", vector=(1, 0, 0))])
    backend = vector_backend(
        fake_options(service, semantic_configuration=SEMANTIC), transport=service.transport
    )
    await backend.open()
    caplog.set_level(logging.WARNING)

    try:
        await backend.put(s, v1, [entry(v1, "new", "retry again", vector=(0, 1, 0))])
    finally:
        await backend.close()

    assert ("PUT", "/indexes('exactdocs-space1')") in service.requests
    definition = service.indexes["exactdocs-space1"].definition
    assert [c["name"] for c in definition["semantic"]["configurations"]] == [SEMANTIC]
    assert {"title", "content"} <= {f["name"] for f in definition["fields"]}
    assert definition["@odata.etag"] != '"0x1"'  # updated, not made again
    documents = {d["chunk_id"]: d for d in documents_of(service, "exactdocs-space1")}
    assert "content" not in documents["old"]  # written before: the rebuild writes it again
    assert documents["new"]["content"] == "retry again"
    assert "exactdocs index rebuild" in caplog.text


async def test_a_semantic_configuration_of_that_name_over_other_fields_is_refused(
    service: FakeSearchService, semantic: AzureSemanticVectorBackend
) -> None:
    v1, s = manifest(), space()
    await semantic.put(s, v1, [entry(v1, "a", "retry", vector=(1, 0, 0))])
    configuration = service.indexes["exactdocs-space1"].definition["semantic"]["configurations"][0]
    configuration["prioritizedFields"]["prioritizedContentFields"] = [{"fieldName": "title"}]
    other = vector_backend(
        fake_options(service, semantic_configuration=SEMANTIC), transport=service.transport
    )
    await other.open()

    try:
        with pytest.raises(IndexBackendUnavailableError) as refused:
            await other.put(s, v1, [entry(v1, "b", "retry", vector=(1, 0, 0))])
    finally:
        await other.close()

    message = str(refused.value)
    assert "'exactdocs-space1' does not have ExactDocs' schema" in message
    assert f"semantic configuration {SEMANTIC!r} ranks other fields" in message


async def test_a_plain_text_field_the_ranker_cannot_read_is_refused(
    service: FakeSearchService, vectors: AzureHybridVectorBackend
) -> None:
    v1, s = manifest(), space()
    await vectors.put(s, v1, [entry(v1, "a", "retry", vector=(1, 0, 0))])
    fields = service.indexes["exactdocs-space1"].definition["fields"]
    content = {"name": "content", "key": False, "searchable": True, "retrievable": False}
    fields.append(fields[0] | content)
    backend = vector_backend(
        fake_options(service, semantic_configuration=SEMANTIC), transport=service.transport
    )
    await backend.open()

    try:
        with pytest.raises(IndexBackendUnavailableError, match="'content' is not retrievable"):
            await backend.put(s, v1, [entry(v1, "b", "retry", vector=(1, 0, 0))])
    finally:
        await backend.close()
