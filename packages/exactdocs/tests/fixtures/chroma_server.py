"""Chroma for the external index contract suites and the Chroma scenario (#361).

Two cases. ``chroma_local``: the embedded persistent client on a temporary directory, which needs
no server and runs wherever the ``chroma-local`` extra is installed (the dev environment).
``chroma``: the HTTP client, against the server ``EXACTDOCS_TEST_CHROMA_URL`` names (CI: the
pinned ``chromadb/chroma`` service; locally
``docker run -p 8000:8000 chromadb/chroma:1.5.9`` and ``http://127.0.0.1:8000``), left out
without it.

Every backend gets collections of its own (a random ``collection`` prefix) and drops them after.
"""

import asyncio
import os
import secrets
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from chromadb.api.client import Client

from exactdocs.retrieval.adapters.driven.chroma_index import (
    ChromaVectorBackend,
    close_client,
    vector_backend,
)
from exactdocs.retrieval.ports import VectorBackend

CHROMA_URL = os.environ.get("EXACTDOCS_TEST_CHROMA_URL") or None
CHROMA_IMAGE = "chromadb/chroma:1.5.9"
"""The server image the CI service and the client pins agree on."""


def options(collection: str) -> dict[str, object]:
    """The ``[index_backends.chroma]`` options of the test server."""
    assert CHROMA_URL is not None
    return {"url": CHROMA_URL, "collection": collection}


def admin() -> Client:
    """A client of the test server, for the tests' own looks and clean-ups (close it)."""
    assert CHROMA_URL is not None
    return vector_backend(options("admin")).connect()


def drop_collections(prefix: str) -> None:
    """Drop every collection of the test server whose name starts with ``prefix``."""
    client = admin()
    try:
        for collection in client.list_collections():
            if collection.name.startswith(prefix):
                client.delete_collection(collection.name)
    finally:
        close_client(client)


@asynccontextmanager
async def http_vectors() -> AsyncGenerator[ChromaVectorBackend]:
    """A fresh, opened backend of the test server; its collections are dropped after."""
    collection = f"test_{secrets.token_hex(6)}"
    backend = vector_backend(options(collection))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await asyncio.to_thread(drop_collections, f"{collection}_")


@asynccontextmanager
async def local_vectors() -> AsyncGenerator[ChromaVectorBackend]:
    """A fresh, opened embedded backend on a temporary directory, removed after."""
    with tempfile.TemporaryDirectory(prefix="exactdocs-chroma-") as directory:
        backend = vector_backend({"path": directory})
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


@asynccontextmanager
async def http() -> AsyncGenerator[VectorBackend]:
    """The HTTP client's case."""
    async with http_vectors() as backend:
        yield backend


@asynccontextmanager
async def local() -> AsyncGenerator[VectorBackend]:
    """The embedded persistent client's case."""
    async with local_vectors() as backend:
        yield backend
