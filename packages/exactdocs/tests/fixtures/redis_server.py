"""Redis for the external index contract suites and the Redis scenario (#364).

``EXACTDOCS_TEST_REDIS_URL`` names a Redis 8 server with the Query Engine (CI: the pinned
``redis`` service; locally ``docker run -p 6379:6379 redis:8.10.3`` and ``redis://127.0.0.1:6379``),
and ``EXACTDOCS_TEST_REDIS_PASSWORD`` (with ``EXACTDOCS_TEST_REDIS_USERNAME``) its credentials
when it takes some. Without the URL the Redis cases are left out.

Every backend gets indexes and keys of its own (a random ``prefix``) and drops them after.
"""

import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from exactdocs.retrieval.adapters.driven.redis_index import search_backend, vector_backend
from exactdocs.retrieval.ports import SearchBackend, VectorBackend

REDIS_URL = os.environ.get("EXACTDOCS_TEST_REDIS_URL") or None
REDIS_USERNAME = os.environ.get("EXACTDOCS_TEST_REDIS_USERNAME") or None
REDIS_PASSWORD = os.environ.get("EXACTDOCS_TEST_REDIS_PASSWORD") or None


def options(prefix: str, *, hybrid: bool = False) -> dict[str, object]:
    """The ``[index_backends.redis]`` options of the test server."""
    assert REDIS_URL is not None
    found: dict[str, object] = {"url": REDIS_URL, "prefix": prefix, "hybrid": hybrid}
    if REDIS_USERNAME:
        found["username"] = REDIS_USERNAME
    if REDIS_PASSWORD:
        found["password"] = REDIS_PASSWORD
    return found


def admin() -> Redis:
    """A client of the test server, for the tests' own looks and clean-ups."""
    assert REDIS_URL is not None
    return Redis.from_url(
        REDIS_URL, username=REDIS_USERNAME, password=REDIS_PASSWORD, protocol=3
    )


async def drop(prefix: str) -> None:
    """Drop every index whose name starts with ``<prefix>:``, and every key under it."""
    client = admin()
    try:
        for name in await client.execute_command("FT._LIST"):
            index = name.decode() if isinstance(name, bytes) else str(name)
            if index.startswith(f"{prefix}:"):
                await client.execute_command("FT.DROPINDEX", index)
        keys = [key async for key in client.scan_iter(match=f"{prefix}:*", count=1000)]
        if keys:
            await client.unlink(*keys)
    finally:
        await client.aclose()


@asynccontextmanager
async def redis_search() -> AsyncGenerator[SearchBackend]:
    """A fresh, opened Redis search backend; its index and keys are dropped after."""
    prefix = f"test_{secrets.token_hex(6)}"
    backend = search_backend(options(prefix))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop(prefix)


@asynccontextmanager
async def redis_vectors(*, hybrid: bool = False) -> AsyncGenerator[VectorBackend]:
    """A fresh, opened Redis vector backend; its indexes and keys are dropped after."""
    prefix = f"test_{secrets.token_hex(6)}"
    backend = vector_backend(options(prefix, hybrid=hybrid))
    await backend.open()
    try:
        yield backend
    finally:
        await backend.close()
        await drop(prefix)


@asynccontextmanager
async def plain_vectors() -> AsyncGenerator[VectorBackend]:
    """The vector backend without native hybrid: ExactDocs fuses BM25 and its vectors."""
    async with redis_vectors(hybrid=False) as backend:
        yield backend


@asynccontextmanager
async def hybrid_vectors() -> AsyncGenerator[VectorBackend]:
    """The vector backend with native hybrid (``FT.HYBRID``: words and vectors fused by Redis)."""
    async with redis_vectors(hybrid=True) as backend:
        yield backend
