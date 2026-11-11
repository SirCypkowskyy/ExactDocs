"""Steps for hybrid search (#92): the real pipeline, a fake embedding endpoint that hashes terms.

Every version is embedded by the background ``embed`` jobs, through pydantic-ai, from the fake
gateway on loopback; the query is embedded the same way at search time.
"""

import time
from contextlib import ExitStack
from http import HTTPStatus

from behave import given, then
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.models import identifier_tokens
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.search_steps import LIBRARY

EMBEDDING_SECONDS = 60.0
SEARCH = f"/api/v1/libraries{LIBRARY}/search"
REF = "v1.4.0"


@given('the operator chose retrieval mode "{mode}" and an embedding model')
def step_hybrid_instance(context: Context, mode: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    context.search_ref = REF  # 'an agent searches' (reranking_steps) searches this version
    ai = AiSettings.model_validate(
        {
            "mode": mode,
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    container = Container.build(context.settings.model_copy(update={"ai": ai}))
    context.container = container
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given('every chunk of "{ref}" is embedded')
def step_embedded(context: Context, ref: str) -> None:
    deadline = time.monotonic() + EMBEDDING_SECONDS
    jobs: list[dict] = []
    while time.monotonic() < deadline:
        response = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs", params={"limit": 100})
        assert response.status_code == HTTPStatus.OK, response.text
        jobs = [j for j in response.json()["jobs"] if j["kind"] == "embed"]
        if jobs and all(j["state"] in {"succeeded", "failed"} for j in jobs):
            break
        time.sleep(0.05)
    assert [j["state"] for j in jobs if j["version"] == ref] == ["succeeded"], jobs
    estimate = context.client.get("/api/v1/ai/embedding/estimate")
    assert estimate.status_code == HTTPStatus.OK, estimate.text
    assert estimate.json()["chunks"] == 0, estimate.text  # nothing is left to embed


@given("the embedding provider refuses every call")
def step_provider_refuses(context: Context) -> None:
    context.endpoint.broken.set()


@then("no chunk from another version is returned")
def step_only_this_version(context: Context) -> None:
    body = context.response.json()
    assert body["version"] == REF, body
    assert body["results"], body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[REF], result
        # A chunk ID names its version: reading it back says which version it is of.
        read = context.client.get(f"/api/v1/chunks/{result['chunk_id']}")
        assert read.status_code == HTTPStatus.OK, read.text
        assert read.json()["version"] == REF, read.json()


@then('the section defining "{identifier}" ranks first, as in BM25')
def step_identifier_first(context: Context, identifier: str) -> None:
    hybrid = context.response.json()
    assert (hybrid["retrieval_mode"], hybrid["fallback_reason"]) == ("hybrid", None), hybrid
    bm25 = context.client.get(SEARCH, params={"q": context.query, "ref": REF, "mode": "bm25"})
    assert bm25.status_code == HTTPStatus.OK, bm25.text
    first = bm25.json()["results"][0]
    # The section whose heading is the identifier's words (`Retry policy`, holding `RetryPolicy`).
    heading = " ".join(first["heading_path"][-1:]).casefold()
    assert identifier_tokens(identifier).split()[1:] == heading.split(), first
    assert hybrid["results"][0]["chunk_id"] == first["chunk_id"], (hybrid, first)
