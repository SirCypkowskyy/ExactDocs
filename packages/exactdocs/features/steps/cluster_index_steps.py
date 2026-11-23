"""Steps for Elasticsearch and OpenSearch as the search and vector backends (#354).

The instance runs against the test cluster (``EXACTDOCS_TEST_<ENGINE>_URL``) under an index
prefix of its own, deleted after the scenario. Embeddings come from the fake gateway on
loopback, as in the hybrid search scenarios; the background ``embed`` jobs write them to the
database's store and to the cluster.
"""

import asyncio
import importlib
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.elastic_index import (
    ElasticSearchBackend,
    ElasticVectorBackend,
)
from exactdocs.retrieval.models import EmbeddingSpaceId, HeldVersion
from fake_llm import gateway
from index_backends import cluster_options, drop_indexes
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
EMBEDDING_SECONDS = 120.0
KEYS = ("manifest_id", "library", "version_id", "chunk_id", "tags")


def _backends(context: Context) -> tuple[ElasticSearchBackend, ElasticVectorBackend]:
    """The engine's backends on the scenario's options (not opened)."""
    module = importlib.import_module(
        f"exactdocs.retrieval.adapters.driven.{context.cluster_engine}_index"
    )
    options = context.cluster_options
    return module.search_backend(options), module.vector_backend(options)


async def _held(context: Context) -> tuple[dict, list[HeldVersion], list[HeldVersion]]:
    """Every index's mapping, and what the search index and the vector index hold."""
    search, vectors = _backends(context)
    await search.cluster.open()
    await vectors.cluster.open()
    try:
        prefix = search.cluster.options.index_prefix
        mapping = (await search.cluster.send("GET", f"/{prefix}-*/_mapping")).body
        spaces = [name for name in mapping if name != search.index]
        assert len(spaces) == 1, mapping  # one embedding space
        space = EmbeddingSpaceId(int(spaces[0].rsplit("-", 1)[1]))
        return mapping, list(await search.held(None)), list(await vectors.held(space, None))
    finally:
        await search.close()
        await vectors.close()


async def _drop(context: Context) -> None:
    """Delete every index the scenario wrote."""
    search, vectors = _backends(context)
    await search.cluster.open()
    try:
        await drop_indexes(search)
        await drop_indexes(vectors)
    finally:
        await search.close()


@given('ExactDocs is configured with a "{engine}" cluster URL and an index prefix')
def step_cluster_instance(context: Context, engine: str) -> None:
    options = cluster_options(engine)
    assert options is not None, f"EXACTDOCS_TEST_{engine.upper()}_URL"
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.cluster_engine, context.cluster_options = engine, options
    stack.callback(lambda: asyncio.run(_drop(context)))
    endpoint = stack.enter_context(gateway(by_terms=True))
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    context.settings = Settings(
        data_dir=data_dir,
        ai=ai,
        search_backend=engine,
        vector_backend=engine,
        index_backends={engine: options},
    )
    context.cluster_stack = stack
    asyncio.run(store_demo_catalog(context.settings))


@when('versions "{first}" and "{second}" are imported and embedded into the cluster')
def step_imported_and_embedded(context: Context, first: str, second: str) -> None:
    asyncio.run(import_versions(context, [first, second]))
    # The server's start queues the versions' embedding; its job worker writes the vectors.
    context.client = context.cluster_stack.enter_context(
        TestClient(
            create_app(Container.build(context.settings)),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    deadline = time.monotonic() + EMBEDDING_SECONDS
    jobs: list[dict] = []
    while time.monotonic() < deadline:
        response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs", params={"limit": 100})
        assert response.status_code == HTTPStatus.OK, response.text
        jobs = [j for j in response.json()["jobs"] if j["kind"] == "embed"]
        if {j["version"] for j in jobs} == {first, second} and all(
            j["state"] in {"succeeded", "failed"} for j in jobs
        ):
            break
        time.sleep(0.1)
    assert sorted(j["state"] for j in jobs) == ["succeeded", "succeeded"], jobs
    context.cluster_refs = (first, second)


@then(
    "their chunks are indexed with library and version as keyword fields and their vectors in "
    'a "{field}" field'
)
def step_indexed(context: Context, field: str) -> None:
    mapping, held, held_vectors = asyncio.run(_held(context))
    for index, found in mapping.items():
        properties = found["mappings"]["properties"]
        assert {properties[k]["type"] for k in KEYS} == {"keyword"}, (index, properties)
    vector_fields = [m["mappings"]["properties"].get("vector") for m in mapping.values()]
    assert [v["type"] for v in vector_fields if v] == [field], vector_fields
    assert len(held) == len(context.cluster_refs), held
    assert all(h.library == LIBRARY for h in held), held
    assert sorted(h.entries for h in held) == sorted(h.entries for h in held_vectors), (
        held,
        held_vectors,
    )


@then("search_docs answers from the cluster, filtered to the asked version")
def step_answers_from_the_cluster(context: Context) -> None:
    old, new = context.cluster_refs
    for mode in ("bm25", "hybrid"):
        found = _search(context, new, "retry_policy", mode)
        assert found, mode
        assert all(r["commit_sha"] == context.commits[new] for r in found), found
        # Only v1.4.0 defines `retry_policy`: the older version's words never match it.
        assert not _search(context, old, "retry_policy", "bm25")
    # The cluster answers: once it loses the newer version, the search finds nothing there.
    search, _ = _backends(context)

    async def lose() -> None:
        await search.cluster.open()
        try:
            version = {"term": {"version_id": f"{LIBRARY}/{new}"}}
            await search.cluster.delete_where(search.index, version)
        finally:
            await search.close()

    asyncio.run(lose())
    assert _search(context, new, "retry_policy", "bm25") == []


def _search(context: Context, ref: str, query: str, mode: str) -> list[dict]:
    """Search one version through the REST API in a mode; the mode must answer itself."""
    response = context.client.get(
        SEARCH, params={"q": query, "ref": ref, "mode": mode, "limit": 10}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body.get("fallback_reason")) == (mode, None), body
    return body["results"]
