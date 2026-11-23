"""Steps for Redis as the search and vector backend (#364), against a real Redis 8 server.

The server is ``EXACTDOCS_TEST_REDIS_URL`` (CI's pinned ``redis`` service). The instance is built
from the settings an operator writes (``EXACTDOCS_SEARCH_BACKEND``, ``EXACTDOCS_VECTOR_BACKEND``
and ``[index_backends.redis]``), through the registry and the adapter's factories. The steps look
into Redis with a client of their own; each scenario's indexes and keys are dropped after it.
"""

import asyncio
import os
import secrets
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import redis_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
TAGGED = {"manifest_id", "library", "version_id", "chunk_id", "tags"}


def _redis_url(context: Context) -> str | None:
    """The test server, or ``None`` (the scenario is skipped) when there is none."""
    url = os.environ.get("EXACTDOCS_TEST_REDIS_URL") or None
    if url is None:
        if os.environ.get("EXACTDOCS_REQUIRE_REDIS") == "1":
            message = "EXACTDOCS_REQUIRE_REDIS=1 but EXACTDOCS_TEST_REDIS_URL names no server"
            raise RuntimeError(message)
        context.scenario.skip("needs a Redis 8 server: set EXACTDOCS_TEST_REDIS_URL")
    return url


@given("ExactDocs is configured with a Redis URL and an index prefix, with native hybrid search")
def step_redis_instance(context: Context) -> None:
    if _redis_url(context) is None:
        return
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.redis_prefix = f"behave_{secrets.token_hex(6)}"
    context.add_cleanup(lambda: asyncio.run(redis_server.drop(context.redis_prefix)))
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    context.settings = Settings(
        data_dir=data_dir,
        ai=ai,
        search_backend="redis",
        vector_backend="redis",
        index_backends={"redis": redis_server.options(context.redis_prefix, hybrid=True)},
    )
    asyncio.run(store_demo_catalog(context.settings))
    context.stack = stack


@when('"{first}" and "{second}" are imported and "{ref}" is embedded')
def step_import_and_embed(context: Context, first: str, second: str, ref: str) -> None:
    asyncio.run(import_versions(context, [first, second]))  # chunks reach Redis on import
    context.container = Container.build(context.settings)  # its start queues the embedding
    context.client = context.stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    step_embedded(context, ref)
    context.search_ref = ref


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


async def _hashes(prefix: str, index: str) -> list[dict[str, str]]:
    """Every hash of one of the scenario's indexes, decoded (vectors left out)."""
    client = redis_server.admin()
    try:
        found = []
        async for key in client.scan_iter(match=f"{prefix}:{index}:*", count=1000):
            fields = {_text(k): v for k, v in (await client.hgetall(key)).items()}
            vector = fields.pop("vector", None)
            found.append(
                {k: _text(v) for k, v in fields.items()} | {"has_vector": str(bool(vector))}
            )
        return found
    finally:
        await client.aclose()


async def _indexes(prefix: str) -> dict[str, set[str]]:
    """The scenario's indexes, and the TAG fields of each."""
    client = redis_server.admin()
    try:
        found: dict[str, set[str]] = {}
        for name in await client.execute_command("FT._LIST"):
            index = name.decode()
            if not index.startswith(f"{prefix}:"):
                continue
            info = await client.execute_command("FT.INFO", index)
            found[index] = {
                a[b"attribute"].decode() for a in info[b"attributes"] if a[b"type"] == b"TAG"
            }
        return found
    finally:
        await client.aclose()


@then("its chunks and vectors are stored as hashes with library and version TAG fields")
def step_stored(context: Context) -> None:
    prefix, ref = context.redis_prefix, context.search_ref
    indexes = asyncio.run(_indexes(prefix))
    search, *spaces = sorted(indexes)
    assert search == f"{prefix}:search", indexes
    assert len(spaces) == 1, indexes  # one vector index: the embedding model's space
    assert all(tags >= TAGGED for tags in indexes.values()), indexes
    chunks = asyncio.run(_hashes(prefix, "search"))
    versions = {c["version_id"] for c in chunks}
    assert versions == {f"{LIBRARY}/v1.3.0", f"{LIBRARY}/v1.4.0"}, versions
    assert {c["library"] for c in chunks} == {LIBRARY}, chunks[:3]
    vectors = asyncio.run(_hashes(prefix, spaces[0].removeprefix(f"{prefix}:")))
    assert vectors, f"no vector of {ref} in Redis"
    embedded = {v["version_id"] for v in vectors}
    assert embedded == versions, embedded  # the start embedded every active version
    assert all(v["has_vector"] == "True" and v["chunk_id"] for v in vectors), vectors[:3]


def _search(context: Context, ref: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


async def _forget(prefix: str) -> None:
    """Delete every hash ExactDocs wrote to Redis (the database keeps its chunks and vectors)."""
    client = redis_server.admin()
    try:
        keys = [key async for key in client.scan_iter(match=f"{prefix}:*", count=1000)]
        if keys:
            await client.unlink(*keys)
    finally:
        await client.aclose()


@then("keyword, vector and hybrid searches answer from Redis, filtered to the asked version")
def step_answered(context: Context) -> None:
    ref = context.search_ref
    assert _search(context, "v1.3.0", "bm25")
    for mode in ("bm25", "vector", "hybrid"):
        assert _search(context, ref, mode), mode
    # Redis answers, not the database: without its hashes there, nothing is found.
    asyncio.run(_forget(context.redis_prefix))
    for mode in ("bm25", "vector"):
        assert _search(context, ref, mode) == [], mode
