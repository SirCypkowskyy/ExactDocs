"""Steps for Milvus as the vector backend (#360).

The instance is built from the settings an operator writes (``EXACTDOCS_VECTOR_BACKEND`` and
``[index_backends.milvus]``), through the registry and the adapter's factory: Milvus Lite in a
temporary directory, or the Milvus server ``EXACTDOCS_TEST_MILVUS_URL`` names (CI's pinned
``milvusdb/milvus`` standalone; an ``@integration`` example, #507). The steps look into Milvus
with a client of their own; each scenario's collections (or directory) are removed after it.
"""

import secrets
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import milvus_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.milvus_index import (
    MilvusHybridVectorBackend,
    vector_backend,
)
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
SCALAR_KEYS = ("manifest_id", "library", "version_id")


@given("ExactDocs is configured with a Milvus {place} URI and a collection name")
def step_milvus_instance(context: Context, place: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    collection = f"behave_{secrets.token_hex(6)}"
    if place == "server":  # an @integration example: environment.py skips it without one
        assert milvus_server.MILVUS_URL, "EXACTDOCS_TEST_MILVUS_URL is not set"
        context.milvus_options = milvus_server.options(collection)
        context.add_cleanup(milvus_server.drop_collections, f"{collection}_")
    else:
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-milvus-"))
        context.milvus_options = {
            "uri": str(Path(directory) / "milvus.db"),
            "collection": collection,
        }
    context.milvus_collection = collection
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
            "vector_backend": "milvus",
            "index_backends": {"milvus": context.milvus_options},
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


@when('version "{ref}" is embedded into Milvus')
def step_milvus_embedding(context: Context, ref: str) -> None:
    step_embedded(context, ref)
    context.embedded_ref = ref


def _uri(context: Context) -> str:
    """The URI the instance's backend uses (Milvus Lite's made absolute, as the factory does)."""
    return vector_backend(context.milvus_options).uri


def _collections(context: Context) -> list[str]:
    client = milvus_server.admin(_uri(context))
    try:
        return sorted(
            n
            for n in client.list_collections()
            if n.startswith(f"{context.milvus_collection}_space")
        )
    finally:
        client.close()


@then(
    "its vectors are inserted into Milvus with library and version fields, "
    "with a scalar index for filtering"
)
def step_milvus_inserted(context: Context) -> None:
    version_id = f"{LIBRARY}/{context.embedded_ref}"
    names = _collections(context)
    assert len(names) == 1, names  # one collection: the embedding model's space
    client = milvus_server.admin(_uri(context))
    try:
        fields = {f["name"] for f in client.describe_collection(names[0])["fields"]}
        assert {*SCALAR_KEYS, "chunk_id", "vector", "text", "sparse"} <= fields, fields
        indexed = {
            client.describe_index(names[0], index)["field_name"]: client.describe_index(
                names[0], index
            )["index_type"]
            for index in client.list_indexes(names[0])
        }
        for key in SCALAR_KEYS:
            assert indexed.get(key) == "INVERTED", indexed
        rows = client.query(
            names[0],
            filter=f'version_id == "{version_id}"',
            output_fields=["library", "manifest_id", "chunk_id"],
            limit=1000,
        )
    finally:
        client.close()
    assert rows, f"no row of {version_id} in Milvus"
    assert {r["library"] for r in rows} == {LIBRARY}, rows[:3]
    assert len({r["manifest_id"] for r in rows}) == 1, rows[:3]


def _search(context: Context, ref: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


@then("vector and hybrid searches answer from Milvus, filtered to the asked version")
def step_milvus_answered(context: Context) -> None:
    ref = context.embedded_ref
    assert isinstance(context.container.index_backends.vectors, MilvusHybridVectorBackend)
    assert _search(context, ref, "vector")
    assert _search(context, ref, "hybrid")
    # Milvus answers, not the database's store: without the version's rows there, neither the
    # vector search nor Milvus' own hybrid ranking finds anything.
    client = milvus_server.admin(_uri(context))
    try:
        for name in _collections(context):
            client.delete(name, filter=f'version_id == "{LIBRARY}/{ref}"')
    finally:
        client.close()
    assert _search(context, ref, "vector") == []
    assert _search(context, ref, "hybrid") == []
