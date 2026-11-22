"""Steps for Weaviate as the search and vector backend (#359), against a real Weaviate server.

The server is ``EXACTDOCS_TEST_WEAVIATE_URL`` (CI's pinned Weaviate service, with an API key).
The instance is built from the settings an operator writes (``EXACTDOCS_SEARCH_BACKEND``,
``EXACTDOCS_VECTOR_BACKEND`` and ``[index_backends.weaviate]``), through the registry and the
adapter's factories. The steps look into Weaviate with a client of their own; each scenario's
collections are dropped after it.
"""

import asyncio
import os
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from weaviate.classes.query import Filter

import weaviate_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.retrieval.dtos import ExternalIndexScope
from fake_llm import TERM_DIMENSIONS, gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
REF = "v1.4.0"  # the version the scenario embeds and searches
OLDER = "v1.3.0"
PROPERTIES = ("manifest_id", "library", "version_id", "chunk_id", "article_path")


def _weaviate_url(context: Context) -> str | None:
    """The test server, or ``None`` (the scenario is skipped) when there is none."""
    url = os.environ.get("EXACTDOCS_TEST_WEAVIATE_URL") or None
    if url is None:
        if os.environ.get("EXACTDOCS_REQUIRE_WEAVIATE") == "1":
            message = "EXACTDOCS_REQUIRE_WEAVIATE=1 but EXACTDOCS_TEST_WEAVIATE_URL is not set"
            raise RuntimeError(message)
        context.scenario.skip("needs a Weaviate server: set EXACTDOCS_TEST_WEAVIATE_URL")
    return url


@given("ExactDocs is configured with a Weaviate URL and a collection name for both indexes")
def step_weaviate_settings(context: Context) -> None:
    if _weaviate_url(context) is None:
        return
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.weaviate_collection = weaviate_server.prefix()
    context.add_cleanup(
        lambda: asyncio.run(weaviate_server.drop_collections(f"{context.weaviate_collection}_"))
    )
    context.endpoint = stack.enter_context(gateway(by_terms=True))
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
        search_backend="weaviate",
        vector_backend="weaviate",
        index_backends={"weaviate": weaviate_server.options(context.weaviate_collection)},
    )
    context.weaviate_stack = stack
    asyncio.run(store_demo_catalog(context.settings))


@when(
    'the fixture docs repository is imported into Weaviate at "{first}" and "{second}", '
    'and "{ref}" is embedded'
)
def step_weaviate_import(context: Context, first: str, second: str, ref: str) -> None:
    asyncio.run(import_versions(context, [first, second]))
    context.container = Container.build(context.settings, remote=OfflineGit(GitCli.locate()))
    context.client = context.weaviate_stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    step_embedded(context, ref)


def _where(version_id: str) -> Any:
    return Filter.by_property("version_id").equal(version_id)


async def _look(collection_prefix: str, version_id: str) -> dict[str, tuple[dict, list[Any]]]:
    """Each of the scenario's collections: its schema, and a version's objects (with vectors)."""
    client = await weaviate_server.admin()
    try:
        found = {}
        for name in sorted(await client.collections.list_all(simple=True)):
            if not name.startswith(collection_prefix):
                continue
            collection = client.collections.use(name)
            schema = (await collection.config.get()).to_dict()
            objects = await collection.query.fetch_objects(
                filters=_where(version_id), limit=10_000, include_vector=True
            )
            found[name.removeprefix(collection_prefix)] = (schema, list(objects.objects))
    finally:
        await client.close()
    return found


async def _forget(collection_prefix: str, version_id: str) -> None:
    """Delete a version's objects from Weaviate only (the database keeps its chunks)."""
    client = await weaviate_server.admin()
    try:
        for name in await client.collections.list_all(simple=True):
            if name.startswith(collection_prefix):
                await client.collections.use(name).data.delete_many(where=_where(version_id))
    finally:
        await client.close()


async def _drift(context: Context) -> bool:
    """Whether Weaviate holds what the stored chunks and vectors give (the drift check)."""
    container = Container.build(context.settings)
    async with container.running(jobs=False):
        return (await container.retrieval.check_external_indexes(ExternalIndexScope())).clean


@then(
    "its chunks are Weaviate objects with library and version properties and ExactDocs' own vectors"
)
def step_weaviate_objects(context: Context) -> None:
    found = asyncio.run(_look(f"{context.weaviate_collection}_", f"{LIBRARY}/{REF}"))
    assert sorted(found) == ["search", "space1"], sorted(found)  # created when missing
    search_schema, chunks = found["search"]
    space_schema, embedded = found["space1"]
    assert chunks, f"no object of {REF} in the search collection"
    assert len(embedded) == len(chunks), (len(embedded), len(chunks))
    for schema in (search_schema, space_schema):
        assert schema["vectorConfig"]["default"]["vectorizer"] == {"none": {}}, schema
    for item in (*chunks, *embedded):
        properties = item.properties
        assert all(properties[p] for p in PROPERTIES), properties
        assert properties["library"] == LIBRARY, properties
        assert properties["version_id"] == f"{LIBRARY}/{REF}", properties
    assert len({o.properties["manifest_id"] for o in chunks}) == 1
    # The vectors are ExactDocs' own (the fake gateway's dimensions), never Weaviate's.
    assert all(len(o.vector["default"]) == TERM_DIMENSIONS for o in embedded)
    assert not any(o.vector for o in chunks)  # the search collection holds no vector
    assert asyncio.run(_drift(context)), "Weaviate does not hold what the database gives"


def _search(context: Context, ref: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


@then("keyword, vector and hybrid searches answer from Weaviate, filtered to the asked version")
def step_weaviate_searches(context: Context) -> None:
    for mode in ("bm25", "vector", "hybrid"):
        assert _search(context, REF, mode), mode
    older = _search(context, OLDER, "bm25")  # the older version: its own chunks only
    assert older, OLDER
    # Weaviate answers, not the database: without the version's objects there, nothing is found.
    asyncio.run(_forget(f"{context.weaviate_collection}_", f"{LIBRARY}/{REF}"))
    for mode in ("bm25", "vector", "hybrid"):
        assert _search(context, REF, mode) == [], mode
    # The other version is untouched (its scores may move: BM25 counts the whole collection).
    after = _search(context, OLDER, "bm25")
    assert {r["chunk_id"] for r in after} == {r["chunk_id"] for r in older}, (after, older)
