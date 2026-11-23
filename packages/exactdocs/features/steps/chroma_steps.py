"""Steps for Chroma as the vector backend (#361).

The instance is built from the settings an operator writes (``EXACTDOCS_VECTOR_BACKEND`` and
``[index_backends.chroma]``), through the registry and the adapter's factory: a Chroma server
when ``EXACTDOCS_TEST_CHROMA_URL`` is set (CI's pinned ``chromadb/chroma`` service), otherwise
the embedded client in a temporary directory. The steps look into Chroma with a client of their
own; each scenario's collections (or directory) are removed after it.
"""

import math
import os
import secrets
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from http import HTTPStatus
from typing import Any, cast

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import chroma_server
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.chroma_index import close_client, vector_backend
from fake_llm import gateway, term_vector
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
SAME_DIRECTION = 1 - 1e-6  # float32 vectors: the same vector, give or take rounding


@given("ExactDocs is configured with a Chroma server URL (or a local path) and a collection name")
def step_chroma_instance(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    collection = f"behave_{secrets.token_hex(6)}"
    if chroma_server.CHROMA_URL:
        context.chroma_options = chroma_server.options(collection)
        context.add_cleanup(chroma_server.drop_collections, f"{collection}_")
    elif os.environ.get("EXACTDOCS_REQUIRE_CHROMA") == "1":  # CI: the server, never skipped
        message = "EXACTDOCS_REQUIRE_CHROMA=1 but EXACTDOCS_TEST_CHROMA_URL is not set"
        raise RuntimeError(message)
    else:
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-chroma-"))
        context.chroma_options = {"path": directory, "collection": collection}
    context.chroma_collection = collection
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
            "vector_backend": "chroma",
            "index_backends": {"chroma": context.chroma_options},
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


@when('version "{ref}" is embedded into Chroma')
def step_embedding(context: Context, ref: str) -> None:
    step_embedded(context, ref)
    context.embedded_ref = ref


def _records(context: Context, version_id: str) -> tuple[list[str], dict[str, Any], dict]:
    """The scenario's collections, the first one's own metadata and configuration, and the
    version's records (metadata and embeddings), read with a client of the steps' own."""
    client = vector_backend(context.chroma_options).connect()
    try:
        names = sorted(
            c.name
            for c in client.list_collections()
            if c.name.startswith(f"{context.chroma_collection}_space")
        )
        collection = client.get_collection(names[0], embedding_function=None)
        own = {
            "metadata": dict(collection.metadata or {}),
            "configuration": collection.configuration_json,
        }
        records = collection.get(
            where={"version_id": version_id},
            include=cast("Any", ["metadatas", "embeddings"]),
        )
    finally:
        close_client(client)
    return names, own, cast("dict", records)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.hypot(*a) * math.hypot(*b))


@then("its vectors are added with library and version metadata and ExactDocs' own embeddings")
def step_added(context: Context) -> None:
    version_id = f"{LIBRARY}/{context.embedded_ref}"
    names, own, records = _records(context, version_id)
    assert len(names) == 1, names  # one collection: the embedding model's space
    assert own["metadata"]["exactdocs_dimensions"] > 0, own
    # No embedding function of Chroma's: the collection is told none, so it never embeds.
    assert own["configuration"].get("embedding_function") in (None, {"type": "legacy"}), own
    metadatas = records["metadatas"]
    assert metadatas, f"no record of {version_id} in Chroma"
    assert {m["library"] for m in metadatas} == {LIBRARY}, metadatas[:3]
    assert len({m["manifest_id"] for m in metadatas}) == 1, metadatas[:3]
    assert all(m["chunk_id"] and m["article_path"] for m in metadatas), metadatas[:3]
    # Every stored vector is one the embedding endpoint (ExactDocs' model) returned.
    texts = [
        text
        for seen in context.endpoint.seen
        if seen.path.split("?")[0].endswith("/embeddings")
        for text in (seen.body["input"] if isinstance(seen.body["input"], list) else [])
    ]
    returned = [term_vector(t) for t in texts]
    for embedding in records["embeddings"]:
        vector = [float(v) for v in embedding]
        best = max(_cosine(vector, r) for r in returned)
        assert best >= SAME_DIRECTION, best


def _search(context: Context, ref: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": QUERY, "ref": ref, "mode": "vector"})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("vector", None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


@then("vector searches answer from Chroma, filtered to the asked version")
def step_answered(context: Context) -> None:
    ref = context.embedded_ref
    assert _search(context, ref)
    # Chroma answers, not the database's store: without the version's records there, nothing
    # is near.
    client = vector_backend(context.chroma_options).connect()
    try:
        for collection in client.list_collections():
            if collection.name.startswith(f"{context.chroma_collection}_space"):
                client.get_collection(collection.name, embedding_function=None).delete(
                    where={"version_id": f"{LIBRARY}/{ref}"}
                )
    finally:
        close_client(client)
    assert _search(context, ref) == []
