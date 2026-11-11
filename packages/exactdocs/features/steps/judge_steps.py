"""Steps for the LLM judge (#96): a chat profile on a fake gateway, through pydantic-ai.

The gateway answers a chat completion that offers an output tool with ratings of the prompt's
``<candidate id="...">`` elements, the last one best; with ``judge_rogue`` set it also rates a
chunk ID it was not given. A second profile on the same gateway serves the cross-encoder. The
unreranked order is taken from the same instance before any model is configured.
"""

import re
from contextlib import ExitStack
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.constants import JUDGE_INSTRUCTIONS
from exactdocs.retrieval.models import SpendEntry, SpendWindow
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE

SEARCH = "/api/v1/libraries/fixture/docs-repo/search"
SETTING = "/api/v1/libraries/fixture/docs-repo/retrieval"
LIBRARY_SCOPE = "/fixture/docs-repo"
QUERY = "how do I retry failed calls"
LIMIT = 5
"""What ``an agent searches`` asks for (reranking_steps)."""
TOP_N = 6
"""Candidates the library has judged: more than shown, and few enough for distinct ratings."""
DAILY_TOKENS = 100
"""The library's own daily token budget in the budget scenario."""


def _chat_calls(context: Context) -> list[Any]:
    return [s for s in context.gateway.seen if s.path.endswith("/chat/completions")]


def _serve(context: Context, *, cross_encoder: bool) -> None:
    """Remember the unreranked order, then serve the same data with a judge (and a reranker).

    Args:
        context: The behave context.
        cross_encoder: Configure the ``reranker`` role too.
    """
    response = context.client.get(SEARCH, params={"q": QUERY, "limit": 50})
    assert response.status_code == HTTPStatus.OK, response.text
    context.unreranked = [r["chunk_id"] for r in response.json()["results"]]
    assert len(context.unreranked) > TOP_N, "the query must find more candidates than judged"
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.gateway = stack.enter_context(gateway())
    context.reranker = context.gateway  # the reranking steps read the cross-encoder's calls
    reranker: dict[str, Any] = {"top_n": TOP_N}
    if cross_encoder:
        reranker["model"] = "rr:rerank-v3.5"
    raw: dict[str, Any] = {
        "providers": {
            "corp": {"kind": "openai-compatible", "base_url": context.gateway.v1},
            "rr": {"kind": "openai-compatible", "base_url": context.gateway.url + "/v2"},
        },
        "judge": {"model": "corp:judge-mini"},
        "reranker": reranker,
    }
    ai = AiSettings.model_validate(raw)
    context.client.__exit__(None, None, None)  # one job worker per process
    context.container = Container.build(context.settings.model_copy(update={"ai": ai}))
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


def _choose_judge(context: Context, **more: object) -> None:
    response = context.client.put(SETTING, json={"rerank_with": "judge", **more})
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["effective_reranker"] == "judge", response.text


@given("a judge model is configured and the library reranks with the judge")
def step_judge(context: Context) -> None:
    _serve(context, cross_encoder=False)
    _choose_judge(context)


@given("a reranker and a judge model are configured")
def step_both(context: Context) -> None:
    _serve(context, cross_encoder=True)
    shown = context.client.get(SETTING).json()
    assert shown["effective_reranker"] == "cross_encoder", shown


@when("the admin sets the library to rerank with the judge")
def step_admin_chooses_judge(context: Context) -> None:
    _choose_judge(context)


@given("the library's daily LLM budget is used up")
def step_library_budget_used_up(context: Context) -> None:
    _choose_judge(context, budgets={"daily_tokens": DAILY_TOKENS})
    now = datetime.now(UTC)
    entry = SpendEntry(
        scope_kind="library",
        scope_id=LIBRARY_SCOPE,
        window=SpendWindow.DAY,
        window_start=SpendWindow.DAY.start(now),
        input_tokens=DAILY_TOKENS,
        requests=1,
    )
    ledger = SqliteSpendLedger(engine=context.container.engine)
    context.client.portal.call(ledger.add, [entry])


def _search(context: Context) -> None:
    context.response = context.client.get(SEARCH, params={"q": QUERY, "limit": LIMIT})


@when("the judge model returns a chunk ID it was not given")
def step_rogue(context: Context) -> None:
    context.gateway.judge_rogue.set()
    _search(context)


@when("an agent searches with the judge configured")
def step_search_with_judge(context: Context) -> None:
    _search(context)
    # For the budget steps' check (ai_budget_steps): the body, and no cross-encoder call.
    context.result = _body(context)
    context.endpoint = context.gateway
    context.rerank_calls = 0


def _body(context: Context) -> dict[str, Any]:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    return context.response.json()


@then('the result says "reranked: true" and the candidates are ordered by the judge\'s ratings')
def step_judged(context: Context) -> None:
    body = _body(context)
    sent = context.unreranked[:TOP_N]
    assert (body["reranked"], body["fallback_reason"]) == (True, None), body
    assert body["coverage"]["reranked"] == TOP_N, body
    assert [r["chunk_id"] for r in body["results"]] == [*reversed(sent)][:LIMIT], body
    assert len(_chat_calls(context)) == 1, "one call rates every candidate"


@then("the judge was called once with the query and the candidates as delimited, untrusted text")
def step_judge_prompt(context: Context) -> None:
    (call,) = _chat_calls(context)
    messages = call.body["messages"]
    system = " ".join(str(m["content"]) for m in messages if m["role"] in {"system", "developer"})
    assert JUDGE_INSTRUCTIONS in system, messages
    (user,) = [str(m["content"]) for m in messages if m["role"] == "user"]
    assert f"<query>{QUERY}</query>" in user, user
    ids = re.findall(r'<candidate id="([^"]*)">', user)
    assert ids == [f"c{n}" for n in range(1, TOP_N + 1)], "the top N, by position"
    for chunk_id in context.unreranked:
        assert chunk_id not in user, "never a chunk ID"
    assert "fixture/docs-repo" not in user, "no library name"
    assert call.body["tools"], "the ratings are a structured output"


@then("the output validator rejects it and the search falls back to the unreranked order")
def step_rejected(context: Context) -> None:
    body = _body(context)
    assert (body["reranked"], body["fallback_reason"]) == (False, "reranker_failed"), body
    assert [r["chunk_id"] for r in body["results"]] == context.unreranked[:LIMIT], body
    assert len(_chat_calls(context)) == 1, "refused at once, never asked again"


@then("the judge was not called")
def step_judge_not_called(context: Context) -> None:
    assert _chat_calls(context) == [], context.gateway.seen


@then("the cross-encoder reranked the candidates and the judge was not called")
def step_cross_encoded(context: Context) -> None:
    body = _body(context)
    sent = context.unreranked[:TOP_N]
    assert body["reranked"] is True, body
    assert [r["chunk_id"] for r in body["results"]] == [*reversed(sent)][:LIMIT], body
    assert [s for s in context.gateway.seen if s.path.endswith("/rerank")], context.gateway.seen
    assert _chat_calls(context) == [], context.gateway.seen
