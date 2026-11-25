"""The external index backends the shared contract suites run on (#352).

Every suite that takes a backend is parametrised over ``SEARCH_BACKEND_CASES`` /
``VECTOR_BACKEND_CASES``:

- ``tests/retrieval/test_search_index.py``: the ``SearchIndex`` contract, through the domain's
  ``ExternalSearchIndex`` (ids ``external:<name>``);
- ``tests/retrieval/test_vector_index.py``: the ``VectorIndex`` contract, through
  ``ExternalVectorIndex`` (ids ``external:<name>``);
- ``tests/retrieval/test_index_backends.py``: the backend ports themselves (put, delete,
  held, version and library filters, top-k, empty and unknown versions, native hybrid).

An adapter PR adds one ``BackendCase`` to ``EXTERNAL_BACKENDS``: a name and an async context
manager per index it can hold, yielding a fresh, empty, opened backend and cleaning it up after.
A backend that needs a server reads its URL from an ``EXACTDOCS_TEST_<NAME>_URL`` variable and
carries that variable's integration marker (``marks``, #507): its cases are always collected,
deselected unless the run includes the integration tests (``--integration``), and skipped then
when the variable is unset (as ``databases.py`` does for PostgreSQL); CI's integration job sets
it. The suites parametrize with ``params``, so the marker comes with the case. An embedded
backend (LanceDB, DuckDB, Chroma's and Milvus Lite's local modes, a libSQL file) or a fake (Azure
AI Search) needs no server: it runs on a temporary directory, or in process, wherever its extra
is installed (the dev environment has them), in every run.
"""

import asyncio
import importlib
import importlib.util
import os
import secrets
import tempfile
import uuid
from collections.abc import AsyncGenerator, Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.mark import ParameterSet

import integration
import libsql_backends
from exactdocs.retrieval.adapters.driven.elastic_index import (
    ElasticSearchBackend,
    ElasticVectorBackend,
)
from exactdocs.retrieval.adapters.driven.memory_index import (
    InMemorySearchBackend,
    InMemoryVectorBackend,
)
from exactdocs.retrieval.models import (
    BackendHit,
    BackendNeighbour,
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    TagFilter,
    TextQuery,
)
from exactdocs.retrieval.ports import NativeHybrid, SearchBackend, VectorBackend


@dataclass(frozen=True, slots=True)
class BackendCase:
    """One external backend, as the contract suites build it."""

    name: str
    search: Callable[[], AbstractAsyncContextManager[SearchBackend]] | None = None
    vectors: Callable[[], AbstractAsyncContextManager[VectorBackend]] | None = None
    counts_terms: bool = False
    """It ranks by term counts (the in-memory reference), not BM25: the suites skip the cases
    only a BM25-like ranking passes (length normalisation, a heading's ancestors)."""
    stale_statistics: bool = False
    """Deleted entries still count in its term statistics until its garbage collector runs
    (Redis' Query Engine) or its segments merge (Lucene: Elasticsearch, OpenSearch): a rebuild
    finds the same hits, with other scores."""
    marks: pytest.MarkDecorator | None = None
    """A backend on a server: the integration marker naming its variable (``integration.QDRANT``
    ...), so its cases run only with ``--integration``. ``None``: embedded or a fake, every run."""


def params(cases: Mapping[str, BackendCase], prefix: str = "") -> list[ParameterSet]:
    """The cases as a suite's parameters (``prefix`` + name), a server's with its marker.

    Args:
        cases: ``SEARCH_BACKEND_CASES`` or ``VECTOR_BACKEND_CASES``.
        prefix: Put before each name (``external:`` where the suite has other parameters too).

    Returns:
        One ``pytest.param`` per case.
    """
    return [pytest.param(f"{prefix}{name}", marks=case.marks or ()) for name, case in cases.items()]


def _lazy(module: str, factory: str) -> Callable[[], Any]:
    """A server module's backend factory, imported when a case runs (its extra's client)."""

    def build() -> Any:
        return getattr(importlib.import_module(module), factory)()

    return build


def _required(name: str) -> None:
    """``EXACTDOCS_REQUIRE_<NAME>=1`` (CI's integration job) without the server's URL: an error."""
    if os.environ.get(f"EXACTDOCS_REQUIRE_{name}") == "1" and not os.environ.get(
        f"EXACTDOCS_TEST_{name}_URL"
    ):
        message = f"EXACTDOCS_REQUIRE_{name}=1 but EXACTDOCS_TEST_{name}_URL is not set"
        raise RuntimeError(message)


@asynccontextmanager
async def _memory_search() -> AsyncGenerator[SearchBackend]:
    backend = InMemorySearchBackend()
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()


@asynccontextmanager
async def _memory_vectors() -> AsyncGenerator[VectorBackend]:
    backend = InMemoryVectorBackend()
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()


def _qdrant_cases() -> list[BackendCase]:
    """Qdrant (#355), with and without native hybrid, on ``EXACTDOCS_TEST_QDRANT_URL``."""
    _required("QDRANT")  # CI: never skipped there
    return [
        BackendCase(
            name="qdrant", vectors=_lazy("qdrant_server", "plain"), marks=integration.QDRANT
        ),
        BackendCase(
            name="qdrant_hybrid",
            vectors=_lazy("qdrant_server", "hybrid"),
            marks=integration.QDRANT,
        ),
    ]


def cluster_options(name: str) -> dict[str, object] | None:
    """The options of a test cluster (#354), from ``EXACTDOCS_TEST_<NAME>_URL``; ``None`` unset.

    ``EXACTDOCS_TEST_<NAME>_USERNAME`` / ``_PASSWORD`` sign in with basic auth,
    ``EXACTDOCS_TEST_ELASTICSEARCH_API_KEY`` with an API key, ``EXACTDOCS_TEST_<NAME>_CA`` checks
    a ``https`` cluster against that CA file. Each run gets its own index prefix, every write is
    searchable at once (``refresh = true``) and indexes have no replica (single-node clusters).
    """
    variable = f"EXACTDOCS_TEST_{name.upper()}"
    url = os.environ.get(f"{variable}_URL")
    if not url:
        return None
    options: dict[str, object] = {
        "url": url,
        "index_prefix": f"exactdocs-test-{uuid.uuid4().hex[:12]}",
        "refresh": "true",
        "number_of_replicas": 0,
    }
    for option in ("username", "password", "api_key", "ca"):
        value = os.environ.get(f"{variable}_{option.upper()}")
        if value:
            options["ca_certs" if option == "ca" else option] = value
    return options


async def drop_indexes(backend: ElasticSearchBackend | ElasticVectorBackend) -> None:
    """Delete every index and pipeline a test cluster backend's prefix names."""
    prefix = backend.cluster.options.index_prefix
    listed = await backend.cluster.send(
        "GET", f"/{prefix}-*", params={"expand_wildcards": "all"}, allow=(404,)
    )
    for index in listed.body:
        await backend.cluster.send("DELETE", f"/{index}", allow=(404,))
    if backend.cluster.flavour == "opensearch":
        await backend.cluster.send("DELETE", f"/_search/pipeline/{prefix}-hybrid", allow=(404,))


@asynccontextmanager
async def _opened[B: (ElasticSearchBackend, ElasticVectorBackend)](backend: B) -> AsyncGenerator[B]:
    """Open a test cluster backend; delete its indexes and close it after."""
    await backend.open()
    try:
        yield backend
    finally:
        try:
            await drop_indexes(backend)
        finally:
            await backend.close()


def _module(name: str) -> ModuleType:
    """The adapter module of a cluster backend (imported only when its cluster is set)."""
    return importlib.import_module(f"exactdocs.retrieval.adapters.driven.{name}_index")


def _cluster_search(name: str) -> AbstractAsyncContextManager[SearchBackend]:
    """A fresh search backend on the test cluster."""
    options = cluster_options(name)
    assert options is not None
    backend: ElasticSearchBackend = _module(name).search_backend(options)
    return _opened(backend)


def _cluster_vectors(name: str) -> AbstractAsyncContextManager[VectorBackend]:
    """A fresh vector backend on the test cluster."""
    options = cluster_options(name)
    assert options is not None
    backend: ElasticVectorBackend = _module(name).vector_backend(options)
    return _opened(backend)


def _lancedb() -> ModuleType:
    """Import the LanceDB adapter (its extra) only when a LanceDB case runs."""
    return importlib.import_module("exactdocs.retrieval.adapters.driven.lancedb_index")


@asynccontextmanager
async def _lancedb_search() -> AsyncGenerator[SearchBackend]:
    with tempfile.TemporaryDirectory(prefix="exactdocs-lancedb-") as directory:
        backend = _lancedb().search_backend({"uri": directory})
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


@asynccontextmanager
async def _lancedb_vectors() -> AsyncGenerator[VectorBackend]:
    with tempfile.TemporaryDirectory(prefix="exactdocs-lancedb-") as directory:
        backend = _lancedb().vector_backend({"uri": directory})
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


def _lancedb_cases() -> list[BackendCase]:
    """LanceDB (#356), embedded: on a temporary directory whenever its extra is installed."""
    if importlib.util.find_spec("lancedb") is None:
        return []
    return [BackendCase(name="lancedb", search=_lancedb_search, vectors=_lancedb_vectors)]


DUCKDB_MODULE = "exactdocs.retrieval.adapters.driven.duckdb_index"  # only with the extra


@asynccontextmanager
async def _duckdb_search() -> AsyncGenerator[SearchBackend]:
    """DuckDB is embedded: a fresh database file in a temporary folder, no server."""
    build = importlib.import_module(DUCKDB_MODULE).search_backend
    with tempfile.TemporaryDirectory(prefix="exactdocs-duckdb-") as folder:
        backend = build({"path": str(Path(folder) / "index.duckdb"), "threads": 2})
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


@asynccontextmanager
async def _duckdb_vectors() -> AsyncGenerator[VectorBackend]:
    build = importlib.import_module(DUCKDB_MODULE).vector_backend
    with tempfile.TemporaryDirectory(prefix="exactdocs-duckdb-") as folder:
        backend = build({"path": str(Path(folder) / "index.duckdb"), "threads": 2})
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


def _chroma_cases() -> list[BackendCase]:
    """Chroma (#361): embedded always, over HTTP on ``EXACTDOCS_TEST_CHROMA_URL``'s server."""
    import chroma_server  # ruff: ignore[import-outside-top-level] -- the extra, only here

    _required("CHROMA")  # CI: never skipped there
    return [
        BackendCase(name="chroma_local", vectors=chroma_server.local),
        BackendCase(name="chroma", vectors=chroma_server.http, marks=integration.CHROMA),
    ]


def _redis_cases() -> list[BackendCase]:
    """Redis (#364), search and vectors, and vectors with native hybrid, on
    ``EXACTDOCS_TEST_REDIS_URL``'s server."""
    _required("REDIS")  # CI: never skipped there
    return [
        BackendCase(
            name="redis",
            search=_lazy("redis_server", "redis_search"),
            vectors=_lazy("redis_server", "plain_vectors"),
            stale_statistics=True,
            marks=integration.REDIS,
        ),
        BackendCase(
            name="redis_hybrid",
            vectors=_lazy("redis_server", "hybrid_vectors"),
            marks=integration.REDIS,
        ),
    ]


def _milvus_cases() -> list[BackendCase]:
    """Milvus (#360): Milvus Lite always, a server on ``EXACTDOCS_TEST_MILVUS_URL``."""
    import milvus_server  # ruff: ignore[import-outside-top-level] -- the extra, only here

    _required("MILVUS")  # CI: never skipped there
    return [
        BackendCase(name="milvus_lite", vectors=milvus_server.lite),
        BackendCase(name="milvus", vectors=milvus_server.server, marks=integration.MILVUS),
    ]


def _mongodb_cases() -> list[BackendCase]:
    """MongoDB (#363), search and vectors, and vectors with native hybrid, on
    ``EXACTDOCS_TEST_MONGODB_URL``'s server."""
    _required("MONGODB")  # CI: never skipped there
    return [
        BackendCase(
            name="mongodb",
            search=_lazy("mongodb_server", "mongodb_search"),
            vectors=_lazy("mongodb_server", "plain_vectors"),
            marks=integration.MONGODB,
        ),
        BackendCase(
            name="mongodb_hybrid",
            vectors=_lazy("mongodb_server", "hybrid_vectors"),
            marks=integration.MONGODB,
        ),
    ]


def _libsql_cases() -> list[BackendCase]:
    """libSQL (#358): a server on ``EXACTDOCS_TEST_LIBSQL_URL``, and a local file where the
    ``libsql`` package is installed (see ``libsql_backends.py``)."""
    libsql_backends.server_url()  # EXACTDOCS_REQUIRE_LIBSQL=1 without the URL: an error
    found = [
        BackendCase(
            name="libsql",
            search=libsql_backends.server_search,
            vectors=libsql_backends.server_vectors,
            marks=integration.LIBSQL,
        )
    ]
    if libsql_backends.HAS_DRIVER:
        found.append(
            BackendCase(
                name="libsql_file",
                search=libsql_backends.file_search,
                vectors=libsql_backends.file_vectors,
            )
        )
    return found


# ---------------------------------------------------------------- pinecone (#362)
PINECONE_URL = os.environ.get("EXACTDOCS_TEST_PINECONE_URL") or None
"""An index's host: Pinecone Local's single-index image (amd64 only; the command is in
docs/configuration/index-backends/pinecone.md), then
``EXACTDOCS_TEST_PINECONE_URL=http://localhost:5081``; or
a real serverless ``dotproduct`` index of at least 256 dimensions (the manual ``pinecone.yml``
workflow). Each test gets a namespace of its own, emptied after."""
PINECONE_API_KEY = os.environ.get("EXACTDOCS_TEST_PINECONE_API_KEY") or "pclocal"
"""The API key; Pinecone Local takes any."""
PINECONE_HYBRID = os.environ.get("EXACTDOCS_TEST_PINECONE_HYBRID") == "1"
"""Test the sparse-dense hybrid too (a real index: Pinecone Local ignores sparse values)."""
PINECONE_SETTLE = float(os.environ.get("EXACTDOCS_TEST_PINECONE_SETTLE") or 0)
"""Seconds to wait after each write: a real serverless index is eventually consistent."""


class _Settled:
    """A vector backend that waits after each write, until a real index shows it."""

    def __init__(self, backend: VectorBackend, seconds: float) -> None:
        self.backend, self.seconds, self.name = backend, seconds, backend.name

    async def open(self) -> None:
        await self.backend.open()

    async def close(self) -> None:
        await self.backend.close()

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        await self.backend.put(space, manifest, entries)
        await asyncio.sleep(self.seconds)

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        await self.backend.remove(space_id, manifest_id, chunk_ids)
        await asyncio.sleep(self.seconds)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        await self.backend.delete(manifest_ids)
        await asyncio.sleep(self.seconds)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        await self.backend.drop_space(space_id)
        await asyncio.sleep(self.seconds)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        return await self.backend.held(space_id, library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        return await self.backend.nearest(space, manifest_ids, query, tag_filter, limit)


class _SettledHybrid(_Settled):
    """``_Settled`` for a backend that implements ``NativeHybrid``."""

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        assert isinstance(self.backend, NativeHybrid)
        return await self.backend.hybrid(space, manifest_ids, query, vector, tag_filter, limit)


@asynccontextmanager
async def _pinecone_vectors() -> AsyncGenerator[VectorBackend]:
    # Imported here: the extra's client is loaded only where a Pinecone index is configured.
    from pinecone import AsyncPinecone  # ruff: ignore[import-outside-top-level]

    from exactdocs.retrieval.adapters.driven.pinecone_index import (  # ruff: ignore[import-outside-top-level]
        vector_backend,
    )

    assert PINECONE_URL is not None
    namespace = f"exactdocs-test-{secrets.token_hex(6)}"
    backend = vector_backend({
        "host": PINECONE_URL,
        "api_key": PINECONE_API_KEY,
        "namespace": namespace,
        "hybrid": PINECONE_HYBRID,
    })  # fmt: skip
    await backend.open()
    try:
        if not PINECONE_SETTLE:
            yield backend
        else:
            settled = _SettledHybrid if isinstance(backend, NativeHybrid) else _Settled
            yield settled(backend, PINECONE_SETTLE)
    finally:
        await backend.close()
        async with AsyncPinecone(api_key=PINECONE_API_KEY) as client:
            index = await client.index(host=PINECONE_URL)
            async with index:
                await index.delete(delete_all=True, namespace=namespace)


def _azure_search_cases() -> list[BackendCase]:
    """Azure AI Search (#353): always on the in-process fake of its REST API (there is no
    emulator), and on a real service (``EXACTDOCS_TEST_AZURE_SEARCH_URL``) as integration cases."""
    import azure_search_server  # ruff: ignore[import-outside-top-level] -- the extra's client

    return [
        BackendCase(
            name=name,
            search=search,
            vectors=vectors,
            marks=None if name.startswith("azure_search_fake") else integration.AZURE_SEARCH,
        )
        for name, search, vectors in azure_search_server.cases()
    ]


EXTERNAL_BACKENDS: list[BackendCase] = [
    BackendCase(name="memory", search=_memory_search, vectors=_memory_vectors, counts_terms=True),
    *_qdrant_cases(),
    *(
        BackendCase(
            name=name,
            search=partial(_cluster_search, name),
            vectors=partial(_cluster_vectors, name),
            stale_statistics=True,
            marks=marks,
        )
        for name, marks in (
            ("elasticsearch", integration.ELASTICSEARCH),
            ("opensearch", integration.OPENSEARCH),
        )
    ),
    *_lancedb_cases(),
    # Embedded: no server, so no EXACTDOCS_TEST_DUCKDB_URL; left out only without the extra
    # (the dev group installs it, so CI runs it).
    *(
        [BackendCase(name="duckdb", search=_duckdb_search, vectors=_duckdb_vectors)]
        if importlib.util.find_spec("duckdb") is not None
        else []
    ),
    *_chroma_cases(),
    *_redis_cases(),
    *_milvus_cases(),
    *_mongodb_cases(),
    *_libsql_cases(),
    BackendCase(name="pinecone", vectors=_pinecone_vectors, marks=integration.PINECONE),
    *_azure_search_cases(),
]
"""Every external backend the suites run on here. Add yours (see the module docstring)."""

SEARCH_BACKEND_CASES: dict[str, BackendCase] = {
    case.name: case for case in EXTERNAL_BACKENDS if case.search is not None
}
"""The backends that can hold the search index, by name."""
VECTOR_BACKEND_CASES: dict[str, BackendCase] = {
    case.name: case for case in EXTERNAL_BACKENDS if case.vectors is not None
}
"""The backends that can hold the vector index, by name."""
