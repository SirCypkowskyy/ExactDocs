"""Qdrant for the external index contract suites and the Qdrant scenario (#355).

``EXACTDOCS_TEST_QDRANT_URL`` names a Qdrant server (CI: the pinned ``qdrant/qdrant`` service;
locally ``docker run -p 6333:6333 qdrant/qdrant:v1.20.0`` and ``http://127.0.0.1:6333``), and
``EXACTDOCS_TEST_QDRANT_API_KEY`` its API key when it requires one. Without the URL the Qdrant
cases are left out. ``:memory:`` runs the client's in-process local mode instead, an
approximation for a machine without Docker (it ignores payload indexes): CI uses the server.

Every backend gets collections of its own (a random ``collection`` prefix) and drops them after.
"""

import os
import secrets
import warnings
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from qdrant_client import AsyncQdrantClient
from qdrant_client.common.client_warnings import SEEN_MESSAGES

from exactdocs.retrieval.adapters.driven.qdrant_index import (
    QdrantHybridVectorBackend,
    QdrantVectorBackend,
    vector_backend,
)
from exactdocs.retrieval.ports import VectorBackend

QDRANT_URL = os.environ.get("EXACTDOCS_TEST_QDRANT_URL") or None
QDRANT_API_KEY = os.environ.get("EXACTDOCS_TEST_QDRANT_API_KEY") or None
LOCAL = ":memory:"
INSECURE_KEY = "Api key is used with an insecure connection."
"""qdrant-client's warning for a key sent over http: the CI service is on loopback."""


def options(collection: str, *, hybrid: bool = False) -> dict[str, object]:
    """The ``[index_backends.qdrant]`` options of the test server."""
    assert QDRANT_URL is not None
    assert QDRANT_URL != LOCAL
    found: dict[str, object] = {"url": QDRANT_URL, "collection": collection, "hybrid": hybrid}
    if QDRANT_API_KEY:
        found["api_key"] = QDRANT_API_KEY
    return found


@contextmanager
def key_over_loopback() -> Generator[None]:
    """Silence the warning about a key over http (the test server is on loopback)."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=INSECURE_KEY, category=UserWarning)
        yield


def admin() -> AsyncQdrantClient:
    """A client of the test server, for the tests' own looks and clean-ups."""
    assert QDRANT_URL is not None
    with key_over_loopback():
        return AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, check_compatibility=False)


async def drop_collections(prefix: str) -> None:
    """Drop every collection of the server whose name starts with ``prefix``."""
    client = admin()
    try:
        for collection in (await client.get_collections()).collections:
            if collection.name.startswith(prefix):
                await client.delete_collection(collection.name)
    finally:
        await client.close()


def build(collection: str, *, hybrid: bool) -> QdrantVectorBackend:
    """A backend of the test server (through the factory), or of the local mode."""
    if QDRANT_URL == LOCAL:
        SEEN_MESSAGES.add("create-local-payload-indexes")  # local mode ignores them, and says so
        kind = QdrantHybridVectorBackend if hybrid else QdrantVectorBackend
        return kind(connect=lambda: AsyncQdrantClient(location=LOCAL), collection=collection)
    return vector_backend(options(collection, hybrid=hybrid))


@asynccontextmanager
async def qdrant_vectors(*, hybrid: bool = False) -> AsyncGenerator[VectorBackend]:
    """A fresh, opened Qdrant vector backend; its collections are dropped after."""
    collection = f"test_{secrets.token_hex(6)}"
    backend = build(collection, hybrid=hybrid)
    with key_over_loopback():
        await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        if QDRANT_URL != LOCAL:
            await drop_collections(f"{collection}_")


@asynccontextmanager
async def plain() -> AsyncGenerator[VectorBackend]:
    """The backend without native hybrid: ExactDocs fuses BM25 and its vectors."""
    async with qdrant_vectors(hybrid=False) as backend:
        yield backend


@asynccontextmanager
async def hybrid() -> AsyncGenerator[VectorBackend]:
    """The backend with native hybrid (sparse words and dense vectors fused by Qdrant)."""
    async with qdrant_vectors(hybrid=True) as backend:
        yield backend
