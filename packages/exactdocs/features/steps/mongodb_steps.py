"""Steps for MongoDB as the search and vector backend (#363), against a real MongoDB with mongot.

The server is ``EXACTDOCS_TEST_MONGODB_URL`` (CI's pinned ``mongodb/mongodb-atlas-local``
service). The instance is built from the settings an operator writes
(``EXACTDOCS_SEARCH_BACKEND``, ``EXACTDOCS_VECTOR_BACKEND`` and ``[index_backends.mongodb]``),
through the registry and the adapter's factories. The steps look into MongoDB with a client of
their own; each scenario's database is dropped after it.
"""

import asyncio
import os
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import mongodb_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
COLLECTION = "docs"
FORGET_SECONDS = 30
FIELDS = {"manifest_id", "library", "version_id", "chunk_id", "tags"}


def _mongodb_url(context: Context) -> str | None:
    """The test server, or ``None`` (the scenario is skipped) when there is none."""
    url = os.environ.get("EXACTDOCS_TEST_MONGODB_URL") or None
    if url is None:
        if os.environ.get("EXACTDOCS_REQUIRE_MONGODB") == "1":
            message = "EXACTDOCS_REQUIRE_MONGODB=1 but EXACTDOCS_TEST_MONGODB_URL names no server"
            raise RuntimeError(message)
        context.scenario.skip("needs MongoDB with mongot: set EXACTDOCS_TEST_MONGODB_URL")
    return url


@given("ExactDocs is configured with a MongoDB connection string, database and collection")
def step_mongodb_instance(context: Context) -> None:
    if _mongodb_url(context) is None:
        return
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.mongodb_database = mongodb_server.fresh_database()
    context.add_cleanup(lambda: asyncio.run(mongodb_server.drop(context.mongodb_database)))
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    options = mongodb_server.options(context.mongodb_database) | {"collection": COLLECTION}
    context.settings = Settings(
        data_dir=data_dir,
        ai=ai,
        search_backend="mongodb",
        vector_backend="mongodb",
        index_backends={"mongodb": options},
    )
    asyncio.run(store_demo_catalog(context.settings))
    context.stack = stack


@when('MongoDB is sent "{first}" and "{second}" on import and "{ref}" once embedded')
def step_mongodb_import_and_embed(context: Context, first: str, second: str, ref: str) -> None:
    asyncio.run(import_versions(context, [first, second]))  # chunks reach MongoDB on import
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


async def _documents(database: str) -> dict[str, list[dict]]:
    """Every document of the scenario's collections, by collection."""
    client = mongodb_server.admin()
    try:
        found: dict[str, list[dict]] = {}
        for name in sorted(await client[database].list_collection_names()):
            cursor = client[database][name].find({})
            found[name] = await cursor.to_list()
        return found
    finally:
        await client.close()


async def _search_indexes(database: str, collection: str) -> dict[str, str]:
    """A collection's search indexes and their types."""
    client = mongodb_server.admin()
    try:
        cursor = await client[database][collection].list_search_indexes()
        return {i["name"]: i["type"] for i in await cursor.to_list()}
    finally:
        await client.close()


@then("the chunks and vectors are stored as MongoDB documents with library and version fields")
def step_mongodb_stored(context: Context) -> None:
    database = context.mongodb_database
    documents = asyncio.run(_documents(database))
    search, *spaces = documents
    assert search == COLLECTION, list(documents)
    assert len(spaces) == 1, list(documents)  # one space: the embedding model's
    assert spaces[0].startswith(f"{COLLECTION}.space"), spaces
    chunks = documents[search]
    assert all(set(c) >= FIELDS for c in chunks), chunks[:2]
    versions = {c["version_id"] for c in chunks}
    assert versions == {f"{LIBRARY}/v1.3.0", f"{LIBRARY}/v1.4.0"}, versions
    assert {c["library"] for c in chunks} == {LIBRARY}, chunks[:2]
    vectors = documents[spaces[0]]
    assert {v["version_id"] for v in vectors} == versions  # the start embedded every version
    assert all(v.get("vector") and v["chunk_id"] for v in vectors), vectors[:2]
    assert asyncio.run(_search_indexes(database, search)) == {"exactdocs_text": "search"}
    assert asyncio.run(_search_indexes(database, spaces[0])) == {
        "exactdocs_text": "search",
        "exactdocs_vectors": "vectorSearch",
    }


def _mongodb_search(context: Context, ref: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


async def _forget(database: str) -> None:
    """Delete every document ExactDocs wrote to MongoDB (the database keeps its chunks)."""
    client = mongodb_server.admin()
    try:
        for name in await client[database].list_collection_names():
            await client[database][name].delete_many({})
    finally:
        await client.close()


@then("keyword, vector and hybrid searches answer from MongoDB, filtered to the asked version")
def step_mongodb_answered(context: Context) -> None:
    ref = context.search_ref
    assert _mongodb_search(context, "v1.3.0", "bm25")
    for mode in ("bm25", "vector", "hybrid"):
        assert _mongodb_search(context, ref, mode), mode
    # MongoDB answers, not the database: without its documents there, nothing is found.
    asyncio.run(_forget(context.mongodb_database))
    for mode in ("bm25", "vector", "hybrid"):
        deadline = time.monotonic() + FORGET_SECONDS  # the search indexes follow a moment behind
        while (found := _mongodb_search(context, ref, mode)) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert found == [], mode
