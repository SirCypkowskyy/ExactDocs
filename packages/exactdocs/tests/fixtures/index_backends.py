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
still run everywhere; CI sets the variable.
"""

import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

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
    stale_statistics: bool = False
    """Deleted entries still count in its term statistics until its garbage collector runs
    (Redis' Query Engine): a rebuild finds the same hits, with other scores."""


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


def _redis_cases() -> list[BackendCase]:
    """Redis (#364), search and vectors, and vectors with native hybrid, when
    ``EXACTDOCS_TEST_REDIS_URL`` is set."""
    if not os.environ.get("EXACTDOCS_TEST_REDIS_URL"):
        if os.environ.get("EXACTDOCS_REQUIRE_REDIS") == "1":  # CI: never skipped there
            message = "EXACTDOCS_REQUIRE_REDIS=1 but EXACTDOCS_TEST_REDIS_URL is not set"
            raise RuntimeError(message)
        return []
    import redis_server  # ruff: ignore[import-outside-top-level] -- the extra, only with a server

    return [
        BackendCase(
            name="redis",
            search=redis_server.redis_search,
            vectors=redis_server.plain_vectors,
            stale_statistics=True,
        ),
        BackendCase(name="redis_hybrid", vectors=redis_server.hybrid_vectors),
    ]


EXTERNAL_BACKENDS: list[BackendCase] = [
    BackendCase(name="memory", search=_memory_search, vectors=_memory_vectors, counts_terms=True),
    *_redis_cases(),
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
