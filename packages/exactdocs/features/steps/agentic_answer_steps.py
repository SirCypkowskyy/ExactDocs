"""Steps for agentic answers over chosen libraries (#428): the real agent, a scripted LLM.

The ``llm`` role's chat model is a pydantic-ai ``FunctionModel`` (``scripted_explorer.answering``),
so the agent, Code Mode, its sandbox and its limits run for real and nothing leaves the process.
"""

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context

from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.models import SpendEntry, SpendWindow
from scripted_explorer import answering, greedy, scripted_ai
from steps.agentic_search_steps import serve_scripted
from steps.http_steps import DEMO_COOKIE
from steps.library_roles_steps import send_as
from steps.search_all_steps import DEFAULTS

ANSWER = "/api/v1/answer"
MODEL_REQUESTS = 2
"""The scripted agent's requests: one to run its snippet, one to answer."""


def _libraries(spec: str) -> list[str]:
    """Read ``all libraries`` or quoted IDs joined by ``and``.

    Args:
        spec: The step's text.

    Returns:
        The library IDs; empty for all libraries.
    """
    if spec.startswith("all libraries"):
        return []
    return [part.strip().strip('"') for part in spec.split(" and ")]


@given("an LLM that answers from what it reads is configured")
def step_answering(context: Context) -> None:
    serve_scripted(context, answering(), scripted_ai(None))


@given('an LLM that also cites a chunk of "{library}" is configured')
def step_citing_other(context: Context, library: str) -> None:
    found = context.client.get("/api/v1/search", params={"q": "token", "library": library})
    assert found.status_code == HTTPStatus.OK, found.text
    foreign = found.json()["results"][0]["chunk_id"]
    extra = [{"library": library, "chunk_id": foreign}]
    serve_scripted(context, answering(extra=extra), scripted_ai(None))


DAILY_TOKENS = 1000


@given("an LLM that answers from what it reads is configured, with its daily token budget used up")
def step_answering_over_budget(context: Context) -> None:
    ai = scripted_ai(None) | {"budgets": {"daily_tokens": DAILY_TOKENS}}
    serve_scripted(context, answering(), ai)
    now = datetime.now(UTC)
    entry = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=SpendWindow.DAY,
        window_start=SpendWindow.DAY.start(now),
        input_tokens=DAILY_TOKENS,
        requests=1,
    )
    ledger = SqliteSpendLedger(engine=context.container.engine)
    context.client.portal.call(ledger.add, [entry])


@given(
    "an LLM that answers from what it reads is configured, "
    "limited to {limit:d} LLM searches per minute"
)
def step_answering_rate_limited(context: Context, limit: int) -> None:
    ai = scripted_ai(None) | {"budgets": {"llm_searches_per_minute": limit}}
    serve_scripted(context, answering(), ai)


@given('a user has already asked "{question}" over all libraries {times:d} times')
def step_asked_before(context: Context, question: str, times: int) -> None:
    for _ in range(times):
        step_ask(context, question, "all libraries")
        assert _body(context)["fallback_reason"] is None, context.response.text


@given('an API token limited to "{library}"')
def step_limited_token(context: Context, library: str) -> None:
    made = send_as(
        context,
        "POST",
        "/api/v1/tokens",
        session=DEMO_COOKIE,
        json={"name": "limited", "library_ids": [library]},
    )
    assert made.status_code == HTTPStatus.CREATED, made.text
    context.token = made.json()["token"]


@given("answers are limited to {calls:d} tool calls")
def step_answers_limited(context: Context, calls: int) -> None:
    serve_scripted(context, greedy(calls + 10), scripted_ai(None, {"max_tool_calls": calls}))


@when('a user asks "{question}" over {libraries}, streaming the progress')
def step_ask_streaming(context: Context, question: str, libraries: str) -> None:
    context.chosen = _libraries(libraries)
    body = {"question": question, "libraries": context.chosen}
    events: list[tuple[str, Any]] = []
    with context.client.stream("POST", f"{ANSWER}/stream", json=body) as response:
        assert response.status_code == HTTPStatus.OK, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                events.append((name or "", json.loads(line.removeprefix("data: "))))
    context.events = events


@when('the token asks "{question}" over {libraries}')
def step_token_ask(context: Context, question: str, libraries: str) -> None:
    context.chosen = _libraries(libraries)
    context.response = send_as(
        context,
        "POST",
        ANSWER,
        token=context.token,
        json={"question": question, "libraries": context.chosen},
    )


@when('the token searches all libraries for "{query}"')
def step_token_search(context: Context, query: str) -> None:
    context.response = send_as(
        context, "GET", "/api/v1/search", token=context.token, params={"q": query}
    )


@when('a user asks "{question}" over {libraries}')
def step_ask(context: Context, question: str, libraries: str) -> None:
    context.chosen = _libraries(libraries)
    context.response = context.client.post(
        ANSWER, json={"question": question, "libraries": context.chosen}
    )


def _body(context: Context) -> dict[str, Any]:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    return context.response.json()


@then("the answer is written and lists its sources")
def step_answered(context: Context) -> None:
    body = _body(context)
    assert body["fallback_reason"] is None, body
    assert "RetryPolicy" in body["answer"], body
    assert body["sources"], body
    for source in body["sources"]:
        assert source["reason"], source
    assert any(s["quote"] for s in body["sources"]), "a verbatim quote is kept"


@then("every source is from a chosen library's default version, with a link to its article")
def step_sources_chosen(context: Context) -> None:
    body = _body(context)
    chosen = set(context.chosen or DEFAULTS)
    for source in body["sources"]:
        assert source["library"] in chosen, source
        assert source["version"] == DEFAULTS[source["library"]], source
        assert source["commit_sha"] == context.commits[source["version"]], source
        assert source["article_path"], source
        read = context.client.get(f"/api/v1/chunks/{source['chunk_id']}")
        assert read.status_code == HTTPStatus.OK, read.text


@then("the run reports its tool calls out of the limit, and its tokens")
def step_usage(context: Context) -> None:
    usage = _body(context)["usage"]
    assert 0 < usage["tool_calls"] <= usage["max_tool_calls"], usage
    assert usage["requests"] >= MODEL_REQUESTS, usage
    assert usage["input_tokens"] > 0, usage
    assert usage["output_tokens"] > 0, usage


@then("progress events count the tool calls out of the limit, then the answer arrives")
def step_progress(context: Context) -> None:
    names = [name for name, _ in context.events]
    assert names[-1] == "answer", names
    progress = [data for name, data in context.events if name == "progress"]
    assert progress, names
    counts = [p["tool_calls"] for p in progress]
    assert counts == sorted(counts), counts
    assert all(p["max_tool_calls"] >= p["tool_calls"] for p in progress), progress
    final = context.events[-1][1]
    assert final["answer"], final
    assert final["usage"]["tool_calls"] == counts[-1], (final["usage"], counts)


@then('there is no answer, with the reason "{reason}"')
def step_no_answer(context: Context, reason: str) -> None:
    body = _body(context)
    assert (body["answer"], body["fallback_reason"]) == ("", reason), body
    assert body["usage"]["tool_calls"] >= 1, body


@then('no source is from "{library}"')
def step_no_source_from(context: Context, library: str) -> None:
    body = _body(context)
    assert all(s["library"] != library for s in body["sources"]), body


@when("a user checks whether agentic answers are available")
def step_availability(context: Context) -> None:
    context.response = context.client.get(ANSWER)


@then('they are not, because "{reason}"')
def step_unavailable(context: Context, reason: str) -> None:
    body = _body(context)
    assert (body["available"], body["reason"]) == (False, reason), body


@then('asking "{question}" is refused with "{code}"')
def step_refused(context: Context, question: str, code: str) -> None:
    response = context.client.post(ANSWER, json={"question": question})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert response.json()["error"] == code, response.text


@then('there is no answer, with the reason "{reason}", and no model was called')
def step_refused_before_the_model(context: Context, reason: str) -> None:
    body = _body(context)
    assert (body["answer"], body["fallback_reason"]) == ("", reason), body
    assert body["usage"]["requests"] == body["usage"]["tool_calls"] == 0, body


@then('every result of the token is from "{library}"')
def step_results_from(context: Context, library: str) -> None:
    results = _body(context)["results"]
    assert results, "the token's library answered"
    assert {r["library"] for r in results} == {library}, results


def _not_found_like_missing(context: Context, library: str, call: str) -> None:
    missing = "/missing/guide"
    outcomes = []
    for target in (library, missing):
        if call == "answer":
            body = {"question": "how do I retry failed calls", "libraries": [target]}
            response = send_as(context, "POST", ANSWER, token=context.token, json=body)
        else:
            params = {"q": "retry", "library": target}
            response = send_as(context, "GET", "/api/v1/search", token=context.token, params=params)
        outcomes.append(response)
    hidden, absent = outcomes
    assert hidden.status_code == absent.status_code == HTTPStatus.NOT_FOUND, (
        hidden.text,
        absent.text,
    )
    assert hidden.text.replace(library, missing) == absent.text, (hidden.text, absent.text)


@then(
    'asking over "{library}" with the token is refused as not found, '
    "like a library that does not exist"
)
def step_answer_hidden(context: Context, library: str) -> None:
    _not_found_like_missing(context, library, "answer")


@then(
    'searching "{library}" with the token is refused as not found, '
    "like a library that does not exist"
)
def step_search_hidden(context: Context, library: str) -> None:
    _not_found_like_missing(context, library, "search")
