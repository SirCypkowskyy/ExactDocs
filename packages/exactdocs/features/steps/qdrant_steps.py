"""Steps for Qdrant as the vector backend (#355), against a real Qdrant server.

The server is ``EXACTDOCS_TEST_QDRANT_URL`` (CI's pinned ``qdrant/qdrant`` service, with an API
key). The instance is built from the settings an operator writes (``EXACTDOCS_VECTOR_BACKEND`` and
``[index_backends.qdrant]``), through the registry and the adapter's factory. The steps look into
Qdrant with a client of their own; each scenario's collections are dropped after it.
"""

import asyncio
import os
import secrets
from contextlib import ExitStack
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from qdrant_client import models

import qdrant_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
REF = "v1.4.0"  # the version the scenario embeds and searches
INDEXED = {"manifest_id", "library", "tags"}


def _qdrant_url(context: Context) -> str | None:
    """The test server, or ``None`` (the scenario is skipped) when there is none."""
    url = os.environ.get("EXACTDOCS_TEST_QDRANT_URL") or None
    if url is None or url == ":memory:":
        if os.environ.get("EXACTDOCS_REQUIRE_QDRANT") == "1":
            message = "EXACTDOCS_REQUIRE_QDRANT=1 but EXACTDOCS_TEST_QDRANT_URL names no server"
            raise RuntimeError(message)
        context.scenario.skip("needs a Qdrant server: set EXACTDOCS_TEST_QDRANT_URL")
        return None
    return url


@given("ExactDocs is configured with a Qdrant URL and collection name, with native hybrid search")
def step_qdrant_instance(context: Context) -> None:
    if _qdrant_url(context) is None:
        return
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.qdrant_collection = f"behave_{secrets.token_hex(6)}"
    context.add_cleanup(
        lambda: asyncio.run(qdrant_server.drop_collections(f"{context.qdrant_collection}_"))
    )
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    settings = context.settings.model_copy(
        update={
            "ai": ai,
            "vector_backend": "qdrant",
            "index_backends": {
                "qdrant": qdrant_server.options(context.qdrant_collection, hybrid=True)
            },
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    context.container = Container.build(settings)
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@when('every chunk of "{ref}" is embedded')
def step_embedding(context: Context, ref: str) -> None:
    step_embedded(context, ref)


async def _look(collection_prefix: str, version_id: str) -> tuple[list[str], set[str], list[dict]]:
    """The scenario's collections, the first one's indexed fields and a version's payloads."""
    client = qdrant_server.admin()
    try:
        collections = sorted(
            c.name
            for c in (await client.get_collections()).collections
            if c.name.startswith(collection_prefix)
        )
        info = await client.get_collection(collections[0])
        points, _ = await client.scroll(
            collections[0],
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="version_id", match=models.MatchValue(value=version_id)
                    )
                ]
            ),
            limit=10_000,
            with_payload=True,
        )
    finally:
        await client.close()
    return collections, set(info.payload_schema), [p.payload or {} for p in points]


async def _forget(collection_prefix: str, version_id: str) -> None:
    """Delete a version's points from Qdrant only (the database keeps its vectors)."""
    client = qdrant_server.admin()
    try:
        for collection in (await client.get_collections()).collections:
            if collection.name.startswith(collection_prefix):
                await client.delete(
                    collection.name,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="version_id", match=models.MatchValue(value=version_id)
                                )
                            ]
                        )
                    ),
                    wait=True,
                )
    finally:
        await client.close()


@then("its vectors are upserted with library and version payload fields, indexed for filtering")
def step_upserted(context: Context) -> None:
    prefix = f"{context.qdrant_collection}_space"
    collections, indexed, payloads = asyncio.run(_look(prefix, f"{LIBRARY}/{REF}"))
    assert len(collections) == 1, collections  # one collection: the embedding model's space
    assert indexed >= INDEXED, indexed
    assert payloads, f"no point of {REF} in Qdrant"
    assert {p["library"] for p in payloads} == {LIBRARY}, payloads[:3]
    assert len({p["manifest_id"] for p in payloads}) == 1, payloads[:3]
    assert all(p["chunk_id"] and p["article_path"] for p in payloads), payloads[:3]


def _search(context: Context, ref: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


@then("vector and hybrid searches answer from Qdrant, filtered to the asked version")
def step_answered(context: Context) -> None:
    assert _search(context, REF, "vector")
    assert _search(context, REF, "hybrid")
    # Qdrant answers, not the database's store: without its points there, nothing is near.
    asyncio.run(_forget(f"{context.qdrant_collection}_space", f"{LIBRARY}/{REF}"))
    assert _search(context, REF, "vector") == []
