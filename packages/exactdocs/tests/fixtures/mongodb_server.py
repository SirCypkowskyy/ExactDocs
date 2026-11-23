"""MongoDB for the external index contract suites and the MongoDB scenario (#363).

``EXACTDOCS_TEST_MONGODB_URL`` names a MongoDB with Atlas Search and Vector Search (``mongot``):
CI's pinned ``mongodb/mongodb-atlas-local`` service; locally
``docker run -d -p 27017:27017 mongodb/mongodb-atlas-local:9.0.8`` and
``mongodb://127.0.0.1:27017/?directConnection=true``. Without it the MongoDB cases are left out.

Every backend gets a database of its own (a random name) and drops it after.
"""

import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pymongo import AsyncMongoClient

from exactdocs.retrieval.adapters.driven.mongodb_index import search_backend, vector_backend
from exactdocs.retrieval.ports import SearchBackend, VectorBackend

MONGODB_URL = os.environ.get("EXACTDOCS_TEST_MONGODB_URL") or None


def options(database: str, *, hybrid: bool = True) -> dict[str, object]:
    """The ``[index_backends.mongodb]`` options of the test server."""
    assert MONGODB_URL is not None
    return {"url": MONGODB_URL, "database": database, "hybrid": hybrid, "index_timeout": 60}


def admin() -> AsyncMongoClient:
    """A client of the test server, for the tests' own looks and clean-ups."""
    assert MONGODB_URL is not None
    return AsyncMongoClient(MONGODB_URL, serverSelectionTimeoutMS=10_000)


def fresh_database() -> str:
    """A database name no other test uses."""
    return f"test_{secrets.token_hex(6)}"


async def drop(database: str) -> None:
    """Drop a test database, with its collections and their search indexes."""
    client = admin()
    try:
        await client.drop_database(database)
    finally:
        await client.close()


@asynccontextmanager
async def mongodb_search() -> AsyncGenerator[SearchBackend]:
    """A fresh, opened MongoDB search backend; its database is dropped after."""
    database = fresh_database()
    backend = search_backend(options(database))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop(database)


@asynccontextmanager
async def mongodb_vectors(*, hybrid: bool) -> AsyncGenerator[VectorBackend]:
    """A fresh, opened MongoDB vector backend; its database is dropped after."""
    database = fresh_database()
    backend = vector_backend(options(database, hybrid=hybrid))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop(database)


@asynccontextmanager
async def plain_vectors() -> AsyncGenerator[VectorBackend]:
    """The vector backend without native hybrid: ExactDocs fuses BM25 and its vectors."""
    async with mongodb_vectors(hybrid=False) as backend:
        yield backend


@asynccontextmanager
async def hybrid_vectors() -> AsyncGenerator[VectorBackend]:
    """The vector backend with native hybrid (``$rankFusion`` of ``$search`` and
    ``$vectorSearch``)."""
    async with mongodb_vectors(hybrid=True) as backend:
        yield backend
