"""#359: Weaviate as the search and vector backend, beyond the shared contract suites.

The shared suites (``test_index_backends.py``, ``test_search_index.py``, ``test_vector_index.py``)
run the ``weaviate`` case when ``EXACTDOCS_TEST_WEAVIATE_URL`` names a server. Here: the options
(``[index_backends.weaviate]``), and what only a server shows: the collections made when missing
(self-provided vectors, no vectorizer), the objects' properties and ExactDocs' own vectors, a
collection dropped behind the backend's back, the API key, and native hybrid's weighting.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from weaviate.connect.v4 import ConnectionAsync

from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.weaviate_index import (
    WeaviateSearchBackend,
    WeaviateVectorBackend,
    _endpoint,
    _grpc,
    object_id,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.errors import IndexBackendUnavailableError
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
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid
from index_backends import SEARCH_BACKEND_CASES, VECTOR_BACKEND_CASES
from weaviate_server import WEAVIATE_API_KEY, WEAVIATE_URL, admin, options, weaviate_search
from weaviate_server import weaviate_vectors as fresh

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
OTHER = "/other/lib"
URL = "http://127.0.0.1:8080"

needs_server = pytest.mark.skipif(
    WEAVIATE_URL is None, reason="needs a Weaviate server: set EXACTDOCS_TEST_WEAVIATE_URL"
)


def manifest(manifest_id: str, ref: str = "v1", library: str = LIB) -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/{ref}", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    vector: tuple[float, ...] | None = None,
    content: str = "RetryPolicy decides how often a call is retried.",
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Retry policy"),
        content=content,
        tags=("api",),
        vector=vector,
    )


def space(space_id: int = 1, dimensions: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model="m", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


def query(text: str) -> TextQuery:
    return TextQuery(text=text, terms=tuple(search_terms(text)))


# ---------------------------------------------------------------- options


def test_the_options_build_both_backends_without_connecting() -> None:
    found = {"url": URL, "collection": "docsProd", "timeout": "30", "alpha": "0.3"}
    search, vectors = search_backend(found), vector_backend(found | {"fusion": "ranked"})

    assert (search.name, search.collection) == ("weaviate", "docsProd")
    assert not isinstance(search, NativeHybrid)
    assert isinstance(vectors, NativeHybrid)  # hybrid is Weaviate's own hybrid query
    assert (vectors.alpha, vectors.fusion.name) == (0.3, "RANKED")


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({}, "url is required"),
        ({"url": "127.0.0.1:8080"}, "url must be http"),
        ({"url": "http://127.0.0.1:port"}, "invalid port"),
        ({"url": URL, "grpc_url": "grpc.example.com:50051"}, "grpc_url must be http"),
        ({"url": URL, "colection": "x"}, "unknown options colection"),
        ({"url": URL, "collection": "my docs"}, "collection 'my docs'"),
        ({"url": URL, "collection": "1docs"}, "collection '1docs'"),
        ({"url": URL, "timeout": "soon"}, "timeout must be a number"),
        ({"url": URL, "timeout": 0}, "timeout must be a positive"),
        ({"url": URL, "alpha": 2}, "alpha must be between 0 and 1"),
        ({"url": URL, "fusion": "rrf"}, "fusion must be relative_score or ranked"),
        ({"url": URL, "api_key": "k", "api_key_file": "/k"}, "not both"),
        ({"url": URL, "api_key_file": "/nonexistent/weaviate.key"}, "cannot be read"),
    ],
)
def test_invalid_options_are_refused(given: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        search_backend(given)


def test_the_api_key_may_come_from_a_file(tmp_path: Path) -> None:
    key = tmp_path / "weaviate.key"
    key.write_text("", "utf-8")
    with pytest.raises(ValueError, match="is empty"):
        vector_backend({"url": URL, "api_key_file": str(key)})
    key.write_text("s3cret\n", "utf-8")

    assert isinstance(vector_backend({"url": URL, "api_key_file": str(key)}), WeaviateVectorBackend)


def test_the_grpc_endpoint_defaults_to_the_same_host_or_weaviate_clouds() -> None:
    def grpc(url: str, **more: str) -> tuple[str, int, bool]:
        found = _grpc(more, _endpoint("url", url, None))
        return found.host, found.port, found.secure

    assert grpc("http://weaviate:8080") == ("weaviate", 50051, False)
    assert grpc("https://abc.c0.europe-west3.gcp.weaviate.cloud") == (
        "grpc-abc.c0.europe-west3.gcp.weaviate.cloud",
        443,
        True,
    )
    assert grpc(URL, grpc_url="https://grpc.example.com") == ("grpc.example.com", 443, True)


def test_the_settings_name_weaviate_for_both_indexes() -> None:
    settings = Settings(
        search_backend="weaviate",
        vector_backend="weaviate",
        index_backends={"weaviate": {"url": URL}},
    )

    backends = build_index_backends(settings)

    assert isinstance(backends.search, WeaviateSearchBackend)
    assert isinstance(backends.vectors, WeaviateVectorBackend)
    assert backends.names == ("weaviate", "weaviate")


def test_an_object_is_one_chunk_of_one_version_the_same_every_time() -> None:
    assert object_id("m1", "a") == object_id("m1", "a")
    assert len({object_id("m1", "a"), object_id("m2", "a"), object_id("m1", "b")}) == 3


async def test_a_server_that_does_not_answer_is_unavailable_naming_no_secret() -> None:
    backend = vector_backend({"url": "http://127.0.0.1:9", "api_key": "s3cret", "timeout": 1})

    with pytest.raises(IndexBackendUnavailableError) as raised:
        await backend.open()
    await backend.close()

    assert raised.value.backend == "weaviate"
    assert "s3cret" not in str(raised.value)
    with pytest.raises(IndexBackendUnavailableError, match="not open"):
        await backend.held(EmbeddingSpaceId(1), None)


@needs_server
async def test_connecting_never_asks_pypi_for_the_latest_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(
        ConnectionAsync, "_check_package_version", lambda _self, colour: asked.append(colour)
    )
    async with weaviate_search():
        pass

    assert asked == []  # no request leaves for pypi.org: the server is all it talks to


@needs_server
async def test_a_grpc_endpoint_that_does_not_answer_stops_the_start() -> None:
    backend = search_backend(options("Grpc") | {"grpc_url": "http://127.0.0.1:9", "timeout": 3})

    with pytest.raises(IndexBackendUnavailableError, match="gRPC API does not answer"):
        await backend.open()
    await backend.close()


# ---------------------------------------------------------------- against Weaviate


@needs_server
async def test_a_spaces_collection_is_made_with_exactdocs_vectors_and_no_vectorizer() -> None:
    async with fresh() as backend:
        assert isinstance(backend, WeaviateVectorBackend)
        v1 = manifest("m1")
        await backend.put(space(7, dimensions=4), v1, [entry(v1, "a", (1.0, 0.0, 0.0, 0.0))])
        name = f"{backend.collection}_space7"

        client = await admin()
        try:
            collection = client.collections.use(name)
            config = await collection.config.get()
            stored = await collection.query.fetch_object_by_id(
                object_id("m1", "a"), include_vector=True
            )
        finally:
            await client.close()

    schema = config.to_dict()
    assert schema.get("vectorizer") in {None, "none"}  # no collection-wide vectorizer either
    assert list(schema["vectorConfig"]) == ["default"]
    vectors = schema["vectorConfig"]["default"]
    assert vectors["vectorizer"] == {"none": {}}  # no module, so no model provider is called
    assert vectors["vectorIndexConfig"]["distanceMetric"] == "cosine"
    assert stored is not None
    assert stored.vector["default"] == [1.0, 0.0, 0.0, 0.0]  # ExactDocs' own vector
    properties = stored.properties
    assert {k: properties[k] for k in ("manifest_id", "library", "version_id", "chunk_id")} == {
        "manifest_id": "m1",
        "library": LIB,
        "version_id": f"{LIB}/v1",
        "chunk_id": "a",
    }
    assert properties["tags"] == ["api"]
    assert properties["heading"] == "retry policy"
    assert "retrypolicy" in str(properties["body"]).split()  # identifier_tokens, for BM25


@needs_server
async def test_the_search_collection_is_made_on_the_first_write_without_vectors() -> None:
    async with weaviate_search() as backend:
        assert isinstance(backend, WeaviateSearchBackend)
        client = await admin()
        try:
            name = f"{backend.collection}_search"
            assert not await client.collections.exists(name)  # made when missing, not before
            v1 = manifest("m1")
            await backend.put(v1, [entry(v1, "a")])
            config = await client.collections.use(name).config.get()
        finally:
            await client.close()

    assert config.to_dict()["vectorConfig"]["default"]["vectorizer"] == {"none": {}}


@needs_server
async def test_a_collection_dropped_behind_its_back_is_made_again_on_the_next_write() -> None:
    async with fresh() as backend:
        assert isinstance(backend, WeaviateVectorBackend)
        s, v1 = space(), manifest("m1")
        await backend.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        client = await admin()
        try:
            await client.collections.delete(f"{backend.collection}_space1")
        finally:
            await client.close()

        assert await backend.nearest(s, ["m1"], [1, 0, 0], TagFilter(), 5) == []
        assert await backend.held(s.id, None) == []
        await backend.put(s, v1, [entry(v1, "b", (0.0, 1.0, 0.0))])

        assert await backend.held(s.id, None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1)
        ]


@needs_server
async def test_held_names_each_versions_library() -> None:
    async with weaviate_search() as backend:
        mine, theirs = manifest("m1"), manifest("o1", library=OTHER)
        await backend.put(mine, [entry(mine, "a")])
        await backend.put(theirs, [entry(theirs, "a"), entry(theirs, "b")])

        assert await backend.held(None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1),
            HeldVersion(manifest_id="o1", library=OTHER, entries=2),
        ]


@needs_server
@pytest.mark.skipif(not WEAVIATE_API_KEY, reason="the test server takes no API key")
async def test_a_server_with_an_api_key_refuses_a_backend_without_it() -> None:
    for key in (None, "not-the-key"):
        given = options("Refused")
        given.pop("api_key", None)
        backend = search_backend(given | ({"api_key": key} if key else {}))
        with pytest.raises(IndexBackendUnavailableError, match="HTTP 401") as raised:
            await backend.open()
        await backend.close()
        assert "not-the-key" not in str(raised.value)


@needs_server
async def test_native_hybrid_weighs_the_words_and_the_vector_by_alpha() -> None:
    async with fresh() as backend:
        assert isinstance(backend, WeaviateVectorBackend)
        s, v1 = space(), manifest("m1")
        await backend.put(
            s,
            v1,
            [
                entry(v1, "words", (0.0, 1.0, 0.0), "timeout timeout"),
                entry(v1, "meaning", (1.0, 0.0, 0.0), "how long a call may wait"),
            ],
        )

        async def first(alpha: float) -> str:
            backend.alpha = alpha
            found = await backend.hybrid(s, ["m1"], query("timeout"), [1, 0, 0], TagFilter(), 1)
            return found[0].chunk_id

        assert await first(0.0) == "words"  # the words alone (BM25)
        assert await first(1.0) == "meaning"  # the vector alone


@needs_server
async def test_a_hybrid_search_without_words_ranks_by_the_vector() -> None:
    async with fresh() as backend:
        s, v1 = space(), manifest("m1")
        await backend.put(
            s, v1, [entry(v1, "near", (1.0, 0.0, 0.0)), entry(v1, "far", (-1.0, 0.0, 0.0))]
        )
        assert isinstance(backend, WeaviateVectorBackend)
        found = await backend.hybrid(
            s, ["m1"], TextQuery(text="?", terms=()), [1, 0, 0], TagFilter(), 1
        )

    assert [h.chunk_id for h in found] == ["near"]


def test_the_contract_cases_cover_weaviate_when_a_server_is_given() -> None:
    expected = {"weaviate"} if WEAVIATE_URL else set()
    assert expected <= set(SEARCH_BACKEND_CASES)
    assert expected <= set(VECTOR_BACKEND_CASES)
