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
is left out when the variable is unset (as ``databases.py`` does for PostgreSQL), so the suites
still run everywhere; CI sets the variable. An embedded backend (LanceDB) needs no server: it
runs on a temporary directory wherever its extra is installed (the dev environment has it).
"""

import importlib
import importlib.util
import os
import tempfile
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import ModuleType

from exactdocs.retrieval.adapters.driven.elastic_index import (
    ElasticSearchBackend,
    ElasticVectorBackend,
)
from exactdocs.retrieval.adapters.driven.memory_index import (
    InMemorySearchBackend,
    InMemoryVectorBackend,
)
from exactdocs.retrieval.ports import SearchBackend, VectorBackend


@dataclass(frozen=True, slots=True)
class BackendCase:
    """One external backend, as the contract suites build it."""

    name: str
    search: Callable[[], AbstractAsyncContextManager[SearchBackend]] | None = None
    vectors: Callable[[], AbstractAsyncContextManager[VectorBackend]] | None = None
    counts_terms: bool = False
    """It ranks by term counts (the in-memory reference), not BM25: the suites skip the cases
    only a BM25-like ranking passes (length normalisation, a heading's ancestors)."""


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
    """Qdrant (#355), with and without native hybrid, when ``EXACTDOCS_TEST_QDRANT_URL`` is set."""
    if not os.environ.get("EXACTDOCS_TEST_QDRANT_URL"):
        if os.environ.get("EXACTDOCS_REQUIRE_QDRANT") == "1":  # CI: never skipped there
            message = "EXACTDOCS_REQUIRE_QDRANT=1 but EXACTDOCS_TEST_QDRANT_URL is not set"
            raise RuntimeError(message)
        return []
    import qdrant_server  # ruff: ignore[import-outside-top-level] -- the extra, only with a server

    return [
        BackendCase(name="qdrant", vectors=qdrant_server.plain),
        BackendCase(name="qdrant_hybrid", vectors=qdrant_server.hybrid),
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


EXTERNAL_BACKENDS: list[BackendCase] = [
    BackendCase(name="memory", search=_memory_search, vectors=_memory_vectors, counts_terms=True),
    *_qdrant_cases(),
    *(
        BackendCase(
            name=name,
            search=partial(_cluster_search, name),
            vectors=partial(_cluster_vectors, name),
        )
        for name in ("elasticsearch", "opensearch")
        if cluster_options(name) is not None
    ),
    *_lancedb_cases(),
    # Embedded: no server, so no EXACTDOCS_TEST_DUCKDB_URL; left out only without the extra
    # (the dev group installs it, so CI runs it).
    *(
        [BackendCase(name="duckdb", search=_duckdb_search, vectors=_duckdb_vectors)]
        if importlib.util.find_spec("duckdb") is not None
        else []
    ),
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
