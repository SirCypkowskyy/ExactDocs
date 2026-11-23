"""Steps for Pinecone as the vector index (#362).

The instance is configured as an operator would (``EXACTDOCS_VECTOR_BACKEND=pinecone`` and its
options), so each container builds and opens its own client; the namespace is new for the
scenario and emptied after it. Without ``EXACTDOCS_TEST_PINECONE_URL`` the scenario is skipped.
"""

import asyncio
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.retrieval.dtos import ExternalIndexScope
from fake_llm import gateway
from index_backends import PINECONE_API_KEY, PINECONE_SETTLE, PINECONE_URL
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
VERSIONS = 2  # the fixture versions imported


async def _with_index[T](call: Callable[[Any], Awaitable[T]]) -> T:
    """Run ``call`` with the test index's client (the SDK is the pinecone extra's)."""
    from pinecone import AsyncPinecone  # ruff: ignore[import-outside-top-level]

    assert PINECONE_URL is not None
    async with AsyncPinecone(api_key=PINECONE_API_KEY) as client:
        index = await client.index(host=PINECONE_URL)
        async with index:
            return await call(index)


async def _records(namespace: str) -> dict[str, dict[str, Any]]:
    """Every vector of the namespace: its metadata, by ID."""

    async def read(index: Any) -> dict[str, dict[str, Any]]:
        ids = [item.id async for page in index.list(namespace=namespace) for item in page.vectors]
        found: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), 100):
            fetched = await index.fetch(ids=ids[start : start + 100], namespace=namespace)
            found |= {i: dict(v.metadata or {}) for i, v in fetched.vectors.items()}
        return found

    return await _with_index(read)


async def _wipe(namespace: str) -> None:
    """Delete every vector of the namespace."""

    async def wipe(index: Any) -> None:
        await index.delete(delete_all=True, namespace=namespace)

    await _with_index(wipe)
    await asyncio.sleep(PINECONE_SETTLE)


@given(
    "ExactDocs is configured with a Pinecone index and namespace, an embedding model, and the "
    'fixture docs repository imported at "{first}" and "{second}"'
)
def step_pinecone_instance(context: Context, first: str, second: str) -> None:
    if PINECONE_URL is None:
        context.scenario.skip("needs a Pinecone index: set EXACTDOCS_TEST_PINECONE_URL")
        return
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.namespace = f"exactdocs-bdd-{secrets.token_hex(6)}"
    stack.callback(lambda: asyncio.run(_wipe(context.namespace)))  # last: after the app stops
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    ai = AiSettings.model_validate({
        "mode": "hybrid",
        "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
        "embedding": {"model": "corp:terms"},
    })  # fmt: skip
    pinecone = {"host": PINECONE_URL, "api_key": PINECONE_API_KEY, "namespace": context.namespace}
    context.settings = Settings(
        data_dir=data_dir, ai=ai, vector_backend="pinecone", index_backends={"pinecone": pinecone}
    )
    asyncio.run(store_demo_catalog(context.settings))
    asyncio.run(import_versions(context, [first, second]))
    context.container = Container.build(context.settings, remote=OfflineGit(GitCli.locate()))
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@when('every chunk of "{ref}" is embedded into Pinecone')
def step_pinecone_embedded(context: Context, ref: str) -> None:
    step_embedded(context, ref)
    asyncio.run(asyncio.sleep(PINECONE_SETTLE))


@then("its Pinecone vectors are upserted with library and version metadata")
def step_pinecone_metadata(context: Context) -> None:
    records = asyncio.run(_records(context.namespace))
    assert records, "Pinecone holds no vector"
    manifests = {r["manifest"] for r in records.values()}
    assert len(manifests) == VERSIONS, manifests
    for vector_id, metadata in records.items():
        assert metadata["library"] == LIBRARY, metadata
        assert vector_id.startswith(f"{metadata['manifest']}#"), (vector_id, metadata)

    async def check() -> bool:
        container = Container.build(context.settings)
        async with container.running(jobs=False):
            drift = await container.retrieval.check_external_indexes(ExternalIndexScope())
        return drift.clean

    assert asyncio.run(check()), "Pinecone does not hold every embedded chunk of each version"


@then('vector searches of "{ref}" answer from Pinecone, filtered to that version')
def step_pinecone_search(context: Context, ref: str) -> None:
    def searched() -> list[dict]:
        response = context.client.get(
            SEARCH, params={"q": QUERY, "ref": ref, "mode": "vector", "limit": 10}
        )
        assert response.status_code == HTTPStatus.OK, response.text
        body = response.json()
        assert body["retrieval_mode"] == "vector", body
        return body["results"]

    results = searched()
    assert results, "the vector search found nothing"
    for result in results:
        assert result["commit_sha"] == context.commits[ref], result
    asyncio.run(_wipe(context.namespace))  # Pinecone answers, not the database's own store
    assert searched() == []
