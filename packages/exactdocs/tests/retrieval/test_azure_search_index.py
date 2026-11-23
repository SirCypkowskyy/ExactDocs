"""Azure AI Search as the search and vector backend (#353), beyond the shared contract suites.

The contract suites (``test_search_index.py``, ``test_vector_index.py``,
``test_index_backends.py``) run this backend on the in-process fake of the REST API
(``azure_search_fake.py``, plugged in as the azure-core transport). Here: the options, the index
lifecycle (made when missing, dimensions from the embedding model, a schema mismatch refused with
a clear message), what the documents carry, the filters sent to Azure, writes that wait for near
real time indexing, native hybrid in one request, and both kinds of credentials, the key never
shown.
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
from exactdocs.retrieval.ports import NativeHybrid

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
