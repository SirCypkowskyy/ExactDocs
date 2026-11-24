"""#355: Qdrant as the vector backend, beyond the shared contract suites.

The shared suites (``test_index_backends.py``, ``test_vector_index.py``) run the ``qdrant`` and
``qdrant_hybrid`` cases when ``EXACTDOCS_TEST_QDRANT_URL`` names a server. Here: the options
(``[index_backends.qdrant]``), the sparse vectors of native hybrid search, and what only a
server shows: the collection and its payload indexes made from the space, the API key, a
collection dropped behind the backend's back, another instance's collection.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

import integration
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.qdrant_index import (
    QdrantHybridVectorBackend,
    QdrantVectorBackend,
    point_id,
    query_words,
    vector_backend,
    words_vector,
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
)
from exactdocs.retrieval.ports import NativeHybrid
from index_backends import VECTOR_BACKEND_CASES
from qdrant_server import LOCAL, QDRANT_API_KEY, QDRANT_URL, admin, key_over_loopback
from qdrant_server import qdrant_vectors as fresh

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
LIB = "/acme/payments"
URL = "http://127.0.0.1:6333"

needs_qdrant = integration.QDRANT
"""Qdrant, a server or the client's local mode (``:memory:``): integration tests (#507)."""
not_local_mode = pytest.mark.skipif(
    QDRANT_URL == LOCAL, reason="needs a Qdrant server, not the client's local mode"
)
"""With ``needs_qdrant``: a Qdrant server, which the client's local mode does not stand for."""


def manifest(manifest_id: str, ref: str = "v1") -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{LIB}/{ref}", library=LIB, indexed_at=T0
    )


def entry(version: IndexedManifest, chunk: str, vector: tuple[float, ...]) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Retry policy"),
        content="RetryPolicy decides how often a call is retried.",
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


# ---------------------------------------------------------------- options


def test_the_options_build_a_backend_without_connecting() -> None:
    backend = vector_backend({"url": URL, "collection": "docs-prod", "timeout": "30"})

    assert isinstance(backend, QdrantVectorBackend)
    assert not isinstance(backend, NativeHybrid)  # ExactDocs fuses BM25 and the vectors
    assert (backend.name, backend.collection, backend.hybrid_words) == (
        "qdrant",
        "docs-prod",
        False,
    )


@pytest.mark.parametrize("hybrid", [True, "true", "1", "on"])
def test_the_hybrid_option_makes_qdrant_fuse_words_and_vectors(hybrid: object) -> None:
    backend = vector_backend({"url": URL, "hybrid": hybrid})

    assert isinstance(backend, QdrantHybridVectorBackend)
    assert isinstance(backend, NativeHybrid)
    assert backend.hybrid_words


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "url is required"),
        ({"url": "127.0.0.1:6333"}, "url is required"),
        ({"url": URL, "colection": "x"}, "unknown options colection"),
        ({"url": URL, "collection": "my docs"}, "collection 'my docs'"),
        ({"url": URL, "timeout": "soon"}, "timeout must be"),
        ({"url": URL, "timeout": 0}, "timeout must be"),
        ({"url": URL, "hybrid": "maybe"}, "hybrid must be true or false"),
        ({"url": URL, "quantization": "binary"}, "quantization must be none or scalar"),
        ({"url": URL, "api_key": "k", "api_key_file": "/k"}, "not both"),
        ({"url": URL, "api_key_file": "/nonexistent/qdrant.key"}, "cannot be read"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        vector_backend(options)


def test_the_api_key_may_come_from_a_file(tmp_path: Path) -> None:
    key = tmp_path / "qdrant.key"
    key.write_text("", "utf-8")
    with pytest.raises(ValueError, match="is empty"):
        vector_backend({"url": URL, "api_key_file": str(key)})
    key.write_text("s3cret\n", "utf-8")

    assert isinstance(vector_backend({"url": URL, "api_key_file": str(key)}), QdrantVectorBackend)


def test_the_settings_name_qdrant_for_the_vector_index_only() -> None:
    settings = Settings(
        vector_backend="qdrant", index_backends={"qdrant": {"url": URL, "hybrid": True}}
    )

    backends = build_index_backends(settings)

    assert backends.search is None
    assert isinstance(backends.vectors, QdrantHybridVectorBackend)
    assert backends.names == ("database", "qdrant")
    with pytest.raises(ValueError, match="the qdrant backend cannot hold the search index"):
        Settings(search_backend="qdrant")


async def test_a_server_that_does_not_answer_is_unavailable_naming_no_secret() -> None:
    backend = vector_backend({"url": "http://127.0.0.1:9", "api_key": "s3cret", "timeout": 1})

    with key_over_loopback(), pytest.raises(IndexBackendUnavailableError) as raised:
        await backend.open()
    await backend.close()

    assert raised.value.backend == "qdrant"
    assert "s3cret" not in str(raised.value)
    with pytest.raises(IndexBackendUnavailableError, match="not open"):
        await backend.held(EmbeddingSpaceId(1), None)


# ---------------------------------------------------------------- points and words


def test_a_point_is_one_chunk_of_one_version_the_same_every_time() -> None:
    assert point_id("m1", "a") == point_id("m1", "a")
    assert len({point_id("m1", "a"), point_id("m2", "a"), point_id("m1", "b")}) == 3


def test_the_words_are_weighed_as_bm25_does_headings_counting_more() -> None:
    words = words_vector(("Retry policy",), "Calls are retried. retry retry")
    query = query_words(["retry", "retry", "policy"])
    weights = dict(zip(words.indices, words.values, strict=True))

    assert len(set(words.indices)) == len(words.indices)  # one dimension per term
    assert len(query.indices) == 2  # each term once
    assert query.values == [1.0, 1.0]
    retry, policy = query.indices
    assert weights[retry] > weights[policy] > 0  # twice in the body and once in a heading
    assert words_vector((), "").indices == []


# ---------------------------------------------------------------- against Qdrant


@needs_qdrant
@not_local_mode
async def test_a_spaces_collection_and_payload_indexes_are_made_from_the_space() -> None:
    async with fresh() as backend:
        assert isinstance(backend, QdrantVectorBackend)
        v1 = manifest("m1")
        await backend.put(space(7, dimensions=4), v1, [entry(v1, "a", (1.0, 0.0, 0.0, 0.0))])

        client = admin()
        try:
            info = await client.get_collection(f"{backend.collection}_space7")
            points, _ = await client.scroll(f"{backend.collection}_space7", with_payload=True)
        finally:
            await client.close()

    vectors = info.config.params.vectors
    assert isinstance(vectors, dict)
    assert (vectors["dense"].size, vectors["dense"].distance.value) == (4, "Cosine")
    assert {"manifest_id", "library", "tags"} <= set(info.payload_schema)
    assert [p.payload for p in points] == [
        {
            "manifest_id": "m1",
            "library": LIB,
            "version_id": f"{LIB}/v1",
            "chunk_id": "a",
            "article_path": "docs/a.md",
            "heading_path": ["Docs", "Retry policy"],
            "tags": ["api"],
        }
    ]


@needs_qdrant
@not_local_mode
async def test_a_collection_dropped_behind_its_back_is_made_again_on_the_next_write() -> None:
    async with fresh() as backend:
        assert isinstance(backend, QdrantVectorBackend)
        s, v1 = space(), manifest("m1")
        await backend.put(s, v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        client = admin()
        try:
            await client.delete_collection(f"{backend.collection}_space1")
        finally:
            await client.close()

        assert await backend.nearest(s, ["m1"], [1, 0, 0], TagFilter(), 5) == []
        await backend.put(s, v1, [entry(v1, "b", (0.0, 1.0, 0.0))])

        assert await backend.held(s.id, None) == [
            HeldVersion(manifest_id="m1", library=LIB, entries=1)
        ]


@needs_qdrant
@not_local_mode
async def test_another_instances_collection_of_other_dimensions_is_never_written() -> None:
    async with fresh() as backend:
        v1 = manifest("m1")
        await backend.put(space(1, dimensions=3), v1, [entry(v1, "a", (1.0, 0.0, 0.0))])
        assert isinstance(backend, QdrantVectorBackend)
        other = QdrantVectorBackend(connect=admin, collection=backend.collection)
        await other.open()
        try:
            with pytest.raises(IndexBackendUnavailableError, match="give this instance its own"):
                await other.put(space(1, dimensions=4), v1, [entry(v1, "a", (1.0, 0, 0, 0))])
        finally:
            await other.close()


@needs_qdrant
@not_local_mode
@pytest.mark.skipif(not QDRANT_API_KEY, reason="the test server takes no API key")
async def test_a_server_with_an_api_key_refuses_a_backend_without_it() -> None:
    assert QDRANT_URL is not None
    for key in (None, "not-the-key"):
        backend = vector_backend({"url": QDRANT_URL} | ({"api_key": key} if key else {}))
        with key_over_loopback(), pytest.raises(IndexBackendUnavailableError, match=r"HTTP 40[13]"):
            await backend.open()
        await backend.close()


@needs_qdrant
async def test_a_hybrid_search_without_words_ranks_by_the_vector() -> None:
    async with fresh(hybrid=True) as backend:
        assert isinstance(backend, QdrantHybridVectorBackend)
        s, v1 = space(), manifest("m1")
        await backend.put(
            s, v1, [entry(v1, "near", (1.0, 0.0, 0.0)), entry(v1, "far", (-1.0, 0.0, 0.0))]
        )
        found = await backend.hybrid(
            s, ["m1"], TextQuery(text="?", terms=()), [1, 0, 0], TagFilter(), 1
        )

    assert [h.chunk_id for h in found] == ["near"]


def test_the_contract_cases_cover_qdrant_as_integration_cases() -> None:
    cases = {name: VECTOR_BACKEND_CASES[name] for name in ("qdrant", "qdrant_hybrid")}

    assert {name: case.marks for name, case in cases.items()} == {
        "qdrant": integration.QDRANT,
        "qdrant_hybrid": integration.QDRANT,
    }
