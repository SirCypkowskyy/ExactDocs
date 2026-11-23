"""Milvus for the external index contract suites and the Milvus scenario (#360).

Two cases. ``milvus_lite``: Milvus Lite, the embedded engine, on a ``.db`` directory in a
temporary directory, which needs no server and runs wherever the ``milvus-lite`` extra is
installed (the dev environment). ``milvus``: a Milvus server, the one ``EXACTDOCS_TEST_MILVUS_URL``
names (CI: the pinned ``milvusdb/milvus`` standalone image, started by
``deploy/milvus-test-server.sh``; ``EXACTDOCS_TEST_MILVUS_TOKEN`` when it requires a token), left
out without it.

Every backend gets collections of its own (a random ``collection`` prefix) and drops them after.
"""

import asyncio
import os
import secrets
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from pymilvus import MilvusClient

from exactdocs.retrieval.adapters.driven.milvus_index import MilvusVectorBackend, vector_backend
from exactdocs.retrieval.ports import VectorBackend

MILVUS_URL = os.environ.get("EXACTDOCS_TEST_MILVUS_URL") or None
MILVUS_TOKEN = os.environ.get("EXACTDOCS_TEST_MILVUS_TOKEN") or None
MILVUS_IMAGE = "milvusdb/milvus:v3.0.5"
"""The server image CI runs (``deploy/milvus-test-server.sh`` pins its digest)."""


def options(collection: str, **more: object) -> dict[str, object]:
    """The ``[index_backends.milvus]`` options of the test server."""
    assert MILVUS_URL is not None
    found: dict[str, object] = {"uri": MILVUS_URL, "collection": collection, **more}
    if MILVUS_TOKEN:
        found["token"] = MILVUS_TOKEN
    return found


def admin(uri: str) -> MilvusClient:
    """A client of the test server or a Milvus Lite directory, for the tests' own looks (close
    it; Milvus Lite's engine is shared with a backend open on the same directory)."""
    return MilvusClient(uri=uri, token=(MILVUS_TOKEN or "") if uri == MILVUS_URL else "")


def drop_collections(prefix: str) -> None:
    """Drop every collection of the test server whose name starts with ``prefix``."""
    assert MILVUS_URL is not None
    client = admin(MILVUS_URL)
    try:
        for name in client.list_collections():
            if name.startswith(prefix):
                client.drop_collection(name)
    finally:
        client.close()


@asynccontextmanager
async def place(mode: str, **more: object) -> AsyncGenerator[dict[str, object]]:
    """The options of a fresh place in Milvus: collections of a random prefix on the test server
    (``server``, dropped after) or a Milvus Lite directory in a temporary directory (``lite``,
    removed after)."""
    collection = f"test_{secrets.token_hex(6)}"
    if mode == "server":
        try:
            yield options(collection, **more)
        finally:
            await asyncio.to_thread(drop_collections, f"{collection}_")
        return
    with tempfile.TemporaryDirectory(prefix="exactdocs-milvus-") as directory:
        yield {"uri": str(Path(directory) / "milvus.db"), "collection": collection, **more}


@asynccontextmanager
async def milvus_vectors(mode: str, **more: object) -> AsyncGenerator[MilvusVectorBackend]:
    """A fresh, opened backend: of the test server (``server``) or Milvus Lite (``lite``)."""
    async with place(mode, **more) as found:
        backend = vector_backend(found)
        await backend.open()
        try:
            yield backend
        finally:
            await backend.close()


@asynccontextmanager
async def server() -> AsyncGenerator[VectorBackend]:
    """The Milvus server's case (native hybrid)."""
    async with milvus_vectors("server") as backend:
        yield backend


@asynccontextmanager
async def lite() -> AsyncGenerator[VectorBackend]:
    """Milvus Lite's case (native hybrid)."""
    async with milvus_vectors("lite") as backend:
        yield backend
