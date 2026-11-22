"""Weaviate for the external index contract suites and the Weaviate scenario (#359).

``EXACTDOCS_TEST_WEAVIATE_URL`` names a Weaviate server's REST endpoint (CI: the pinned
``cr.weaviate.io/semitechnologies/weaviate`` service; locally see ``docs/configuration.md``,
*Weaviate*), ``EXACTDOCS_TEST_WEAVIATE_GRPC_URL`` its gRPC endpoint when it is not the same host
on port 50051, and ``EXACTDOCS_TEST_WEAVIATE_API_KEY`` its API key when it requires one. Without
the URL the Weaviate cases are left out.

Every backend gets collections of its own (a random ``collection`` prefix) and drops them after.
"""

import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from weaviate import WeaviateAsyncClient

from exactdocs.retrieval.adapters.driven.weaviate_index import (
    WeaviateSearchBackend,
    WeaviateVectorBackend,
    search_backend,
    vector_backend,
)
from exactdocs.retrieval.ports import SearchBackend, VectorBackend

WEAVIATE_URL = os.environ.get("EXACTDOCS_TEST_WEAVIATE_URL") or None
WEAVIATE_GRPC_URL = os.environ.get("EXACTDOCS_TEST_WEAVIATE_GRPC_URL") or None
WEAVIATE_API_KEY = os.environ.get("EXACTDOCS_TEST_WEAVIATE_API_KEY") or None


def options(collection: str) -> dict[str, object]:
    """The ``[index_backends.weaviate]`` options of the test server."""
    assert WEAVIATE_URL is not None
    found: dict[str, object] = {"url": WEAVIATE_URL, "collection": collection}
    if WEAVIATE_GRPC_URL:
        found["grpc_url"] = WEAVIATE_GRPC_URL
    if WEAVIATE_API_KEY:
        found["api_key"] = WEAVIATE_API_KEY
    return found


async def admin(collection: str = "Admin") -> WeaviateAsyncClient:
    """A connected client of the test server, for the tests' own looks and clean-ups."""
    client = search_backend(options(collection)).connect()
    await client.connect()
    return client


async def drop_collections(prefix: str) -> None:
    """Drop every collection of the server whose name starts with ``prefix``."""
    client = await admin()
    try:
        for name in await client.collections.list_all(simple=True):
            if name.startswith(prefix):
                await client.collections.delete(name)
    finally:
        await client.close()


def prefix() -> str:
    """A fresh collection prefix (Weaviate names start with an upper-case letter)."""
    return f"Test{secrets.token_hex(6)}"


@asynccontextmanager
async def weaviate_search() -> AsyncGenerator[SearchBackend]:
    """A fresh, opened Weaviate search backend; its collection is dropped after."""
    collection = prefix()
    backend: WeaviateSearchBackend = search_backend(options(collection))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop_collections(f"{collection}_")


@asynccontextmanager
async def weaviate_vectors() -> AsyncGenerator[VectorBackend]:
    """A fresh, opened Weaviate vector backend (native hybrid); its collections dropped after."""
    collection = prefix()
    backend: WeaviateVectorBackend = vector_backend(options(collection))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop_collections(f"{collection}_")
