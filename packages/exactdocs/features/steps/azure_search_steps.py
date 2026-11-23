"""Steps for Azure AI Search as the search and vector backend (#353), on the fake service.

The operator's settings name the backend (``EXACTDOCS_SEARCH_BACKEND``,
``EXACTDOCS_VECTOR_BACKEND``, ``[index_backends.azure_search]`` with the endpoint and index, the
key from the environment); every container of the scenario builds its backends from those
options through the adapter's factories, with the fake service's transport in place of the
network (there is no emulator to run). The steps look into the fake service to see what Azure
holds and was asked.
"""

import asyncio
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from fastmcp import Client

from azure_search_fake import API_KEY, ENDPOINT, FakeSearchService, documents_of
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.index_backends import IndexBackends
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.azure_search_index import search_backend, vector_backend
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

INDEX = "team-docs"
QUERY = "how do I retry failed calls"
FIELDS = {"id", "manifest_id", "library", "version_id", "chunk_id", "tags", "body"}


def _backends(context: Context) -> IndexBackends:
    """Fresh backends from the operator's options, talking to the fake service."""
    options = context.settings.index_backends["azure_search"]
    transport = context.azure.transport
    return IndexBackends(
        search=search_backend(options, transport=transport),
        vectors=vector_backend(options, transport=transport),
    )


@given("ExactDocs is configured with an Azure AI Search endpoint and index name")
def step_azure_instance(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.azure = FakeSearchService()
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    # What an operator writes: the endpoint and index in the file, the key in the environment.
    options = {"endpoint": ENDPOINT, "index": INDEX, "api_key": API_KEY}
    plain = Settings(data_dir=data_dir, ai=ai)
    asyncio.run(store_demo_catalog(plain))  # the demo account: no index involved
    context.settings = plain.model_copy(
        update={
            "search_backend": "azure_search",
            "vector_backend": "azure_search",
            "index_backends": {"azure_search": options},
        }
    )
    context.stack = stack


@when('"{first}" and "{second}" are imported into Azure AI Search and "{ref}" is embedded')
def step_azure_import_and_embed(context: Context, first: str, second: str, ref: str) -> None:
    # The chunks reach Azure AI Search on import.
    asyncio.run(import_versions(context, [first, second], index_backends=_backends(context)))
    container = Container.build(context.settings, index_backends=_backends(context))
    context.client = context.stack.enter_context(  # its start queues the embedding
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    step_embedded(context, ref)
    context.search_ref = ref


@then("the Azure AI Search indexes hold their chunks and vectors with library and version fields")
def step_azure_stored(context: Context) -> None:
    service = context.azure
    assert sorted(service.indexes) == [INDEX, f"{INDEX}-space1"], sorted(service.indexes)
    chunks = list(documents_of(service, INDEX))
    assert chunks, "nothing was written to the search index"
    assert all(set(c) >= FIELDS for c in chunks), chunks[:2]
    versions = {c["version_id"] for c in chunks}
    assert versions == {f"{LIBRARY}/v1.3.0", f"{LIBRARY}/v1.4.0"}, versions
    assert {c["library"] for c in chunks} == {LIBRARY}, chunks[:2]
    vectors = list(documents_of(service, f"{INDEX}-space1"))
    assert {v["version_id"] for v in vectors} == versions  # the start embedded every version
    assert all(len(v["vector"]) == len(vectors[0]["vector"]) > 1 for v in vectors), vectors[:1]
    dimensions = next(
        f["dimensions"]
        for f in service.indexes[f"{INDEX}-space1"].definition["fields"]
        if f["name"] == "vector"
    )
    assert dimensions == len(vectors[0]["vector"]), dimensions  # the embedding model's


def _search_docs(context: Context, ref: str, mode: str) -> dict[str, Any]:
    """``search_docs`` over MCP, from a container of its own (fresh backends, same service)."""

    async def call() -> dict[str, Any]:
        container = Container.build(context.settings, index_backends=_backends(context))
        async with container.running(jobs=False), Client(build_mcp(container)) as mcp:
            arguments = {"library": LIBRARY, "ref": ref, "query": QUERY, "mode": mode}
            result = await mcp.call_tool("search_docs", arguments)
            return dict(result.structured_content or {})

    data = asyncio.run(call())
    assert data["version"] == ref, data
    assert (data["retrieval_mode"], data.get("fallback_reason")) == (mode, None), data
    return data


@then("search_docs answers from Azure AI Search, filtered to the asked version")
def step_azure_answered(context: Context) -> None:
    service, ref = context.azure, context.search_ref
    manifests = {c["version_id"]: c["manifest_id"] for c in documents_of(service, INDEX)}
    for version, mode in (("v1.3.0", "bm25"), (ref, "bm25"), (ref, "vector"), (ref, "hybrid")):
        service.bodies.clear()
        found = _search_docs(context, version, mode)
        assert found["results"], (version, mode, found)
        assert found["commit_sha"] == context.commits[version], found
        wanted = manifests[f"{LIBRARY}/{version}"]
        searches = [b for b in service.bodies if "filter" in b and "facets" not in b]
        assert searches, (version, mode)  # Azure AI Search was asked, filtered to the version
        assert all(f"'{wanted}'" in b["filter"] for b in searches), searches
        others = set(manifests.values()) - {wanted}
        assert not any(f"'{m}'" in b["filter"] for b in searches for m in others), searches
        if mode == "hybrid":  # native: one Azure hybrid query, words and vector together
            assert any(b.get("search") and b.get("vectorQueries") for b in searches), searches
    # Azure AI Search answers, not the database: without its documents, nothing is found.
    for index in service.indexes.values():
        index.documents.clear()
    for mode in ("bm25", "vector", "hybrid"):
        assert _search_docs(context, ref, mode)["results"] == [], mode
