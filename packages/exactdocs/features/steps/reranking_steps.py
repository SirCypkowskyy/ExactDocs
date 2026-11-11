"""Steps for the reranker (#93).

A fake gateway on loopback (``fake_llm``) stands in for the reranker endpoint: it scores the
candidates in the reverse of the order they were sent, so a reranked result is easy to tell from
the order the search found. The unreranked order is taken from the same instance before the
reranker is configured.
"""

from contextlib import ExitStack
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE

SEARCH = "/api/v1/libraries/fixture/docs-repo/search"
SETTING = "/api/v1/libraries/fixture/docs-repo/retrieval"
QUERY = "how do I retry failed calls"
LIMIT = 5
"""What the agent asks for: fewer than the candidates reranked."""
DEFAULT_TOP_N = 32
KEY = "rr-key-never-shown"


def _results(context: Context, limit: int) -> list[dict[str, Any]]:
    response = context.client.get(SEARCH, params={"q": QUERY, "limit": limit})
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["results"]


def _serve_with_reranker(
    context: Context, kind: str, path: str = "", timeout: float | None = None
) -> None:
    """Remember the unreranked order, then serve the same data with a reranker on a fake gateway.

    Args:
        context: The behave context.
        kind: The profile's kind (``openai-compatible`` or ``tei``).
        path: The base URL's path on the gateway (``/v2``, ``/slow/v2``).
        timeout: The reranker's timeout, in seconds; the default when ``None``.
    """
    context.unreranked = [r["chunk_id"] for r in _results(context, 50)]
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.reranker = stack.enter_context(gateway())
    role: dict[str, object] = {"model": "rr:rerank-v3.5"}
    if timeout is not None:
        role["timeout"] = timeout
    ai = AiSettings.model_validate(
        {
            "providers": {
                "rr": {"kind": kind, "base_url": context.reranker.url + path, "api_key": KEY}
            },
            "reranker": role,
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    container = Container.build(context.settings.model_copy(update={"ai": ai}))
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given("a reranker endpoint that times out")
def step_slow_reranker(context: Context) -> None:
    _serve_with_reranker(context, "openai-compatible", "/slow/v2", timeout=0.2)


@given("a reranker is configured")
def step_reranker(context: Context) -> None:
    _serve_with_reranker(context, "openai-compatible", "/v2")


@given("a TEI reranker is configured")
def step_tei_reranker(context: Context) -> None:
    _serve_with_reranker(context, "tei")


@given("the admin sets the library's rerank top N to {top_n:d}")
def step_library_top_n(context: Context, top_n: int) -> None:
    response = context.client.put(SETTING, json={"rerank_top_n": top_n})
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["rerank_top_n"] == top_n, response.text


@when('an agent searches "{query}"')
def step_agent_searches(context: Context, query: str) -> None:
    context.response = context.client.get(SEARCH, params={"q": query, "limit": LIMIT})


def _body(context: Context) -> dict[str, Any]:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    return context.response.json()


@then('results arrive in the unreranked order with "reranked: false" and a fallback reason')
def step_unreranked(context: Context) -> None:
    body = _body(context)
    assert body["reranked"] is False, body
    assert body["coverage"]["reranked"] == 0, body
    assert body["fallback_reason"] == "reranker_timeout", body
    assert [r["chunk_id"] for r in body["results"]] == context.unreranked[:LIMIT], body


def _reranked(context: Context, top_n: int) -> None:
    body = _body(context)
    sent = context.unreranked[:top_n]
    assert body["reranked"] is True, body
    assert body["fallback_reason"] is None, body
    assert body["coverage"]["reranked"] == len(sent), body
    expected = [*reversed(sent), *context.unreranked[top_n:]][:LIMIT]
    assert [r["chunk_id"] for r in body["results"]] == expected, body
    reranked_scores = [r["score"] for r in body["results"][: len(sent)]]
    assert reranked_scores == sorted(reranked_scores, reverse=True), body


@then('the result says "reranked: true" and the candidates are ordered by the reranker\'s score')
def step_reranked(context: Context) -> None:
    assert len(context.unreranked) > LIMIT, "the query must find more candidates than shown"
    _reranked(context, DEFAULT_TOP_N)


@then(
    'the result says "reranked: true" and only the top {top_n:d} candidates were sent to the '
    "reranker"
)
def step_reranked_top_n(context: Context, top_n: int) -> None:
    _reranked(context, top_n)
    (call,) = [s for s in context.reranker.seen if s.path.endswith("/rerank")]
    assert len(call.body["documents"]) == top_n, call.body


@then("the reranker was sent the query and the candidates' chunk text only")
def step_sent(context: Context) -> None:
    (call,) = [s for s in context.reranker.seen if s.path.endswith("/rerank")]
    assert call.path == "/v2/rerank", call.path
    assert call.headers["authorization"] == f"Bearer {KEY}", call.headers
    assert set(call.body) == {"model", "query", "documents"}, call.body
    assert call.body["query"] == QUERY, call.body
    sent = context.unreranked[:DEFAULT_TOP_N]
    texts = []
    for chunk_id in sent:
        read = context.client.get(f"/api/v1/chunks/{chunk_id}")
        assert read.status_code == HTTPStatus.OK, read.text
        texts.append(read.json()["content"])
    assert call.body["documents"] == texts, call.body
    for document in call.body["documents"]:
        assert "fixture/docs-repo" not in document, document
