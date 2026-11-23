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

import asyncio
import os
import secrets
from collections.abc import AsyncGenerator, Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

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


# ---------------------------------------------------------------- pinecone (#362)
PINECONE_URL = os.environ.get("EXACTDOCS_TEST_PINECONE_URL") or None
"""An index's host: Pinecone Local's single-index image (amd64 only; the command is in
docs/configuration.md, *Pinecone*), then ``EXACTDOCS_TEST_PINECONE_URL=http://localhost:5081``; or
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


EXTERNAL_BACKENDS: list[BackendCase] = [
    BackendCase(name="memory", search=_memory_search, vectors=_memory_vectors, counts_terms=True),
    *([BackendCase(name="pinecone", vectors=_pinecone_vectors)] if PINECONE_URL else []),
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
