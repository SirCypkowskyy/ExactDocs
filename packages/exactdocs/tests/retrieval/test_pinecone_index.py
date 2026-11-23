"""#362: the Pinecone vector backend's own logic, without a server.

The shared suites (``test_index_backends.py``, ``test_vector_index.py``) run the adapter against
a real index or Pinecone Local when ``EXACTDOCS_TEST_PINECONE_URL`` is set; Pinecone Local has
no ARM64 image and ignores sparse values, so this module checks what CI can check everywhere:
the options, the vector IDs, the sparse vectors, the checks at start, and the sparse-dense query
against a small stand-in for Pinecone's data plane (dot products and metadata filters).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pinecone import PineconeConnectionError

from exactdocs.retrieval.adapters.driven import pinecone_index
from exactdocs.retrieval.adapters.driven.pinecone_index import (
    PineconeHybridVectorBackend,
    PineconeVectorBackend,
    _parse_id,
    _sparse,
    _vector_id,
    _version_prefix,
    entry_terms,
    pinecone_options,
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
    TagMatch,
    TextQuery,
    search_terms,
)
from exactdocs.retrieval.ports import NativeHybrid

T0 = datetime(2026, 11, 23, tzinfo=UTC)
LIB = "/acme/payments"
BASE = {"host": "http://localhost:5081", "api_key": "pclocal"}


def manifest(manifest_id: str, library: str = LIB) -> IndexedManifest:
    return IndexedManifest(
        manifest_id=manifest_id, version_id=f"{library}/v1", library=library, indexed_at=T0
    )


def entry(
    version: IndexedManifest,
    chunk: str,
    content: str,
    vector: tuple[float, ...],
    tags: tuple[str, ...] = (),
) -> IndexEntry:
    return IndexEntry(
        manifest_id=version.manifest_id,
        library=version.library,
        version_id=version.version_id,
        chunk_id=ChunkId(chunk),
        article_path=f"docs/{chunk}.md",
        heading_path=("Docs", "Guide"),
        content=content,
        tags=tags,
        vector=vector,
    )


def space(space_id: int = 1, dimensions: int = 3) -> EmbeddingSpace:
    return EmbeddingSpace(
        id=EmbeddingSpaceId(space_id),
        spec=EmbeddingSpec(profile_kind="openai", model=f"m{space_id}", dimensions=dimensions),
        state=SpaceState.ACTIVE,
        created_at=T0,
    )


# ---------------------------------------------------------------- a stand-in data plane


def _matches(metadata: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    """Pinecone's metadata filter: ``$and``, ``$eq`` and ``$in`` (on a value or a list)."""
    if "$and" in condition:
        return all(_matches(metadata, c) for c in condition["$and"])
    ((key, test),) = condition.items()
    value = metadata.get(key)
    values = value if isinstance(value, list) else [value]
    if "$eq" in test:
        return test["$eq"] in values
    return any(v in test["$in"] for v in values)


@dataclass
class _Response:
    """What the SDK's responses carry, as far as the adapter reads them."""

    matches: list[Any] = field(default_factory=list)
    vectors: Any = None
    pagination: Any = None
    dimension: int | None = None
    metric: str | None = None


@dataclass
class _Item:
    id: str
    score: float = 0.0
    metadata: dict[str, Any] | None = None


@dataclass
class FakeIndex:
    """A dense index with sparse values that scores ``dense·q + sparse·q`` (dotproduct)."""

    dimension: int = 8
    metric: str | None = "dotproduct"
    records: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    queries: list[dict[str, Any]] = field(default_factory=list)
    down: bool = False

    def _ns(self, namespace: str) -> dict[str, dict[str, Any]]:
        if self.down:
            reason = "connection refused"
            raise PineconeConnectionError(reason)
        return self.records.setdefault(namespace, {})

    async def describe_index_stats(self) -> _Response:
        self._ns("")
        return _Response(dimension=self.dimension, metric=self.metric)

    async def upsert(self, *, vectors: Sequence[dict[str, Any]], namespace: str, **_: Any) -> None:
        for record in vectors:
            assert len(record["values"]) == self.dimension
            self._ns(namespace)[record["id"]] = dict(record)

    async def query(self, *, top_k: int, vector: Sequence[float], namespace: str, **kw: Any):
        self.queries.append(kw)
        sparse = kw.get("sparse_vector") or {"indices": [], "values": []}
        wanted = dict(zip(sparse["indices"], sparse["values"], strict=True))
        scored = []
        for vector_id, record in self._ns(namespace).items():
            if not _matches(record["metadata"], kw["filter"]):
                continue
            score = math.fsum(a * b for a, b in zip(record["values"], vector, strict=True))
            held = record.get("sparse_values") or {"indices": [], "values": []}
            score += math.fsum(
                v * wanted.get(i, 0.0) for i, v in zip(held["indices"], held["values"], strict=True)
            )
            scored.append(_Item(id=vector_id, score=score))
        scored.sort(key=lambda m: -m.score)
        return _Response(matches=scored[:top_k])

    async def list_paginated(self, *, prefix: str | None, limit: int, pagination_token, namespace):
        ids = sorted(i for i in self._ns(namespace) if i.startswith(prefix or ""))
        start = int(pagination_token or 0)
        page = ids[start : start + limit]
        more = start + limit < len(ids)
        return _Response(
            vectors=[_Item(id=i) for i in page],
            pagination=_Pagination(next=str(start + limit)) if more else None,
        )

    async def delete(self, *, ids: Sequence[str], namespace: str) -> None:
        for vector_id in ids:
            self._ns(namespace).pop(vector_id, None)

    async def fetch(self, *, ids: Sequence[str], namespace: str) -> _Response:
        held = self._ns(namespace)
        return _Response(
            vectors={i: _Item(id=i, metadata=held[i]["metadata"]) for i in ids if i in held}
        )

    async def close(self) -> None:
        pass


@dataclass
class _Pagination:
    next: str


@dataclass
class FakeClient:
    index_: FakeIndex
    opened_with: dict[str, Any] = field(default_factory=dict)

    async def index(self, name: str = "", *, host: str = "") -> FakeIndex:
        self.opened_with = {"name": name, "host": host}
        return self.index_

    async def close(self) -> None:
        pass


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeIndex:
    index = FakeIndex()
    monkeypatch.setattr(pinecone_index, "AsyncPinecone", lambda **_: FakeClient(index))
    return index


async def opened(options: Mapping[str, object]) -> PineconeVectorBackend:
    backend = vector_backend({**BASE, **options})
    await backend.open()
    return backend


# ---------------------------------------------------------------- options


def test_the_options_are_checked_and_defaulted() -> None:
    checked = pinecone_options(BASE)
    assert (checked.host, checked.index, checked.api_key) == (BASE["host"], None, "pclocal")
    assert (checked.namespace, checked.hybrid, checked.hybrid_alpha) == ("exactdocs", False, 0.5)
    from_env = pinecone_options({
        "index": "docs", "api_key": "k", "namespace": "team-a", "hybrid": "true",
        "hybrid_alpha": "0.25", "timeout": "5",
    })  # fmt: skip
    assert (from_env.index, from_env.namespace, from_env.hybrid) == ("docs", "team-a", True)
    assert (from_env.hybrid_alpha, from_env.timeout) == (0.25, 5.0)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"api_key": "k"}, "one of host"),
        ({**BASE, "index": "docs"}, "one of host"),
        ({"host": "h"}, "api_key"),
        ({**BASE, "api_key_file": "/nowhere"}, "not both"),
        ({**BASE, "collection": "x"}, "unknown option"),
        ({**BASE, "namespace": "naïve"}, "ASCII"),
        ({**BASE, "hybrid": "maybe"}, "true or false"),
        ({**BASE, "hybrid_alpha": "1.5"}, "between 0 and 1"),
        ({**BASE, "timeout": "0"}, "positive"),
        ({**BASE, "timeout": "soon"}, "number"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        pinecone_options(options)


def test_the_key_can_come_from_a_file(tmp_path: Path) -> None:
    key = tmp_path / "pinecone-key"
    key.write_text("pcsk_secret\n", "utf-8")
    assert pinecone_options({"host": "h", "api_key_file": str(key)}).api_key == "pcsk_secret"
    with pytest.raises(ValueError, match="cannot be read") as refused:
        pinecone_options({"host": "h", "api_key_file": str(tmp_path / "missing")})
    assert "pcsk" not in str(refused.value)


def test_hybrid_makes_a_native_hybrid_backend() -> None:
    assert not isinstance(vector_backend(BASE), NativeHybrid)
    assert isinstance(vector_backend({**BASE, "hybrid": True}), PineconeHybridVectorBackend)
    assert isinstance(vector_backend({**BASE, "hybrid": True}), NativeHybrid)


# ---------------------------------------------------------------- IDs and sparse vectors


@pytest.mark.parametrize(
    ("manifest_id", "chunk_id"),
    [("0f3a9c", "c1"), ("m#1", "a#b/c"), ("ü/x y", "%41"), ("m1", "")],
)
def test_a_vector_id_names_its_version_space_and_chunk(manifest_id: str, chunk_id: str) -> None:
    vector_id = _vector_id(manifest_id, EmbeddingSpaceId(7), chunk_id)
    assert vector_id.isascii()
    assert _parse_id(vector_id) == (manifest_id, 7, chunk_id)
    assert vector_id.startswith(_version_prefix(manifest_id))
    assert not _vector_id("m1", EmbeddingSpaceId(1), "x").startswith(_version_prefix("m"))
    assert _parse_id("not-ours") is None


def test_a_chunks_terms_are_those_a_query_matches_with_headings_counting_more() -> None:
    weights = entry_terms(entry(manifest("m"), "c", "retryPolicy retries; retry", (1.0,)))
    assert set(search_terms("RetryPolicy")) <= set(weights)
    assert weights["guide"] > weights["retries"]  # a heading term
    assert weights["retry"] > weights["retries"]  # twice: retryPolicy's part, and the word


def test_a_sparse_vector_is_unit_length_and_scaled() -> None:
    sparse = _sparse({"retry": 3.0, "policy": 4.0}, scale=0.5)
    assert sparse is not None
    assert math.isclose(math.hypot(*sparse["values"]), 0.5)
    assert sorted(sparse["indices"]) == sparse["indices"]
    assert _sparse({}) is None


# ---------------------------------------------------------------- against the stand-in


async def test_start_refuses_an_index_it_cannot_use(fake: FakeIndex) -> None:
    fake.metric = "euclidean"
    with pytest.raises(IndexBackendUnavailableError, match="cosine or dotproduct"):
        await opened({})
    fake.metric = "cosine"
    await opened({})
    with pytest.raises(IndexBackendUnavailableError, match="must be dotproduct"):
        await opened({"hybrid": True})
    fake.down = True
    with pytest.raises(IndexBackendUnavailableError, match="connection refused"):
        await opened({})


async def test_an_index_is_opened_by_name_too(fake: FakeIndex) -> None:
    backend = await opened({"host": None, "index": "docs"})
    await backend.put(space(), manifest("m1"), [entry(manifest("m1"), "a", "a", (1.0, 0, 0))])
    assert fake.records["exactdocs"]


async def test_smaller_models_are_padded_and_larger_ones_refused(fake: FakeIndex) -> None:
    backend = await opened({})
    v1 = manifest("m1")
    await backend.put(space(1, 3), v1, [entry(v1, "a", "a", (3.0, 4.0, 0.0))])
    (record,) = fake.records["exactdocs"].values()
    assert record["values"] == pytest.approx([0.6, 0.8, 0, 0, 0, 0, 0, 0])
    assert record["metadata"] == {"manifest": "m1", "library": LIB, "space": 1}
    with pytest.raises(IndexBackendUnavailableError, match="at least 9 dimensions"):
        await backend.put(space(2, 9), v1, [entry(v1, "a", "a", (1.0,) * 9)])
    assert await backend.nearest(space(2, 9), ["m1"], [1.0] * 9, TagFilter(), 5) == []


@pytest.mark.usefixtures("fake")
async def test_namespaces_keep_instances_apart() -> None:
    ours, theirs = await opened({"namespace": "a"}), await opened({"namespace": "b"})
    v1 = manifest("m1")
    await ours.put(space(), v1, [entry(v1, "x", "x", (1.0, 0, 0))])

    assert await theirs.held(EmbeddingSpaceId(1), None) == []
    assert await theirs.nearest(space(), ["m1"], [1, 0, 0], TagFilter(), 5) == []
    assert await ours.held(EmbeddingSpaceId(1), None) == [
        HeldVersion(manifest_id="m1", library=LIB, entries=1)
    ]


async def test_a_version_is_deleted_by_its_id_prefix_in_every_space(fake: FakeIndex) -> None:
    backend = await opened({})
    keep, gone = manifest("m1"), manifest("m10")
    for s in (space(1), space(2)):
        await backend.put(s, keep, [entry(keep, f"c{n}", "x", (1.0, 0, 0)) for n in range(150)])
        await backend.put(s, gone, [entry(gone, f"c{n}", "x", (1.0, 0, 0)) for n in range(150)])

    await backend.delete(["m10"])

    assert {i.split("#")[0] for i in fake.records["exactdocs"]} == {"m1"}
    assert len(fake.records["exactdocs"]) == 300
    await backend.drop_space(EmbeddingSpaceId(1))
    assert {i.split("#")[1] for i in fake.records["exactdocs"]} == {"2"}


async def test_searches_are_filtered_to_the_space_versions_and_tags(fake: FakeIndex) -> None:
    backend = await opened({})
    await backend.nearest(
        space(4), ["m1", "m1", "m2"], [1, 0, 0], TagFilter(tags=("a", "b"), match=TagMatch.ALL), 3
    )
    await backend.nearest(space(4), ["m1"], [1, 0, 0], TagFilter(tags=("a", "b")), 3)

    assert [q["filter"] for q in fake.queries] == [
        {
            "$and": [
                {"space": {"$eq": 4}},
                {"manifest": {"$in": ["m1", "m2"]}},
                {"tags": {"$in": ["a"]}},
                {"tags": {"$in": ["b"]}},
            ]
        },
        {
            "$and": [
                {"space": {"$eq": 4}},
                {"manifest": {"$in": ["m1"]}},
                {"tags": {"$in": ["a", "b"]}},
            ]
        },
    ]
    assert await backend.nearest(space(), [], [1, 0, 0], TagFilter(), 3) == []


async def test_hybrid_ranks_the_query_words_and_its_vector_in_one_query(fake: FakeIndex) -> None:
    backend = await opened({"hybrid": True})
    assert isinstance(backend, NativeHybrid)
    s, v1, v2 = space(), manifest("m1"), manifest("m2")
    await backend.put(
        s,
        v1,
        [
            entry(v1, "words", "RetryPolicy decides retries", (0.0, 1.0, 0.0)),
            entry(v1, "meaning", "how often calls run again", (1.0, 0.0, 0.0)),
            entry(v1, "other", "unrelated", (0.0, 0.0, 1.0)),
        ],
    )
    await backend.put(s, v2, [entry(v2, "words", "RetryPolicy", (1.0, 0.0, 0.0))])
    query = TextQuery(text="RetryPolicy", terms=tuple(search_terms("RetryPolicy")))

    found = await backend.hybrid(s, ["m1"], query, [1, 0, 0], TagFilter(), 2)

    assert {(h.manifest_id, h.chunk_id) for h in found} == {("m1", "words"), ("m1", "meaning")}
    assert [h.score for h in found] == sorted((h.score for h in found), reverse=True)
    sent = fake.queries[-1]["sparse_vector"]
    assert math.isclose(math.hypot(*sent["values"]), 0.5)  # 1 - hybrid_alpha
    no_words = await backend.hybrid(
        s, ["m1"], TextQuery(text="", terms=()), [1, 0, 0], TagFilter(), 1
    )
    assert [h.chunk_id for h in no_words] == ["meaning"]
    assert fake.queries[-1]["sparse_vector"] is None


async def test_a_backend_that_does_not_answer_says_so(fake: FakeIndex) -> None:
    backend = await opened({})
    fake.down = True
    with pytest.raises(IndexBackendUnavailableError, match="'pinecone' is unavailable"):
        await backend.held(EmbeddingSpaceId(1), None)
    await backend.close()
    with pytest.raises(IndexBackendUnavailableError, match="not connected"):
        await backend.delete(["m1"])
