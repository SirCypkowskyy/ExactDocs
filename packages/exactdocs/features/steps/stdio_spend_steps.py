"""Steps for the spend of a stdio MCP process in the shared ledger (#274).

The LLM step is the judge (#96): an OpenAI-compatible profile on the fake gateway, so the stdio
process, a real ``exactdocs serve --stdio`` subprocess, needs only its environment to call it.
The HTTP server runs in this process with the same configuration and reads the usage over REST.
"""

import json
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
from steps.mcp_stdio_steps import FRAMES, rpc, start

LIBRARY = "/fixture/docs-repo"
SETTING = f"/api/v1/libraries{LIBRARY}/retrieval"
QUERY = "how do I retry failed calls"
DAILY_TOKENS = 1_000_000
"""The instance's daily token budget: far more than one judge call takes."""
JUDGE_CALL_TOKENS = 60
"""The input and output tokens the fake gateway reports for each judge call."""


def _chat_tokens(context: Context) -> int:
    """Count the tokens the gateway reported for the chat completions it answered.

    Args:
        context: The behave context.

    Returns:
        Their input and output tokens.
    """
    calls = [s for s in context.gateway.seen if s.path.endswith("/chat/completions")]
    assert calls, "the stdio process called the judge"
    return len(calls) * JUDGE_CALL_TOKENS


@given("a stdio MCP process searches with an LLM step")
def step_stdio_spends(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.gateway = stack.enter_context(gateway())
    ai = AiSettings.model_validate(
        {
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.gateway.v1}},
            "judge": {"model": "corp:judge-mini"},
            "budgets": {"daily_tokens": DAILY_TOKENS},
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    context.container = Container.build(context.settings.model_copy(update={"ai": ai}))
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    chosen = context.client.put(SETTING, json={"rerank_with": "judge"})
    assert chosen.status_code == HTTPStatus.OK, chosen.text
    process = start(
        context.settings.data_dir,
        {
            "EXACTDOCS_AI__PROVIDERS__CORP__KIND": "openai-compatible",
            "EXACTDOCS_AI__PROVIDERS__CORP__BASE_URL": context.gateway.v1,
            "EXACTDOCS_AI__JUDGE__MODEL": "corp:judge-mini",
            "EXACTDOCS_AI__BUDGETS__DAILY_TOKENS": str(DAILY_TOKENS),
        },
    )
    assert process.stdin is not None
    try:
        rpc(process, FRAMES[0])
        process.stdin.write(json.dumps(FRAMES[1]) + "\n")
        found: Any = rpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_docs",
                    "arguments": {"library": LIBRARY, "ref": "v1.4.0", "query": QUERY},
                },
            },
        )
    finally:
        process.stdin.close()
        _, stderr = process.communicate(timeout=60)
    result = found["result"]["structuredContent"]
    assert result["reranked"] is True, (found, stderr)


@when("the HTTP server reads the AI usage")
def step_http_reads_usage(context: Context) -> None:
    response = context.client.get("/api/v1/ai/usage")
    assert response.status_code == HTTPStatus.OK, response.text
    context.usage = response.json()


def _instance(context: Context) -> dict[str, Any]:
    (instance,) = [s for s in context.usage["scopes"] if s["scope"] == "instance"]
    return instance


@then("the spend of the stdio process is included")
def step_stdio_spend_included(context: Context) -> None:
    instance = _instance(context)
    assert instance["day"]["requests"] >= 1, instance
    assert instance["day"]["tokens"] == _chat_tokens(context), instance


@then("the instance's budget is reduced by it for every process")
def step_budget_reduced(context: Context) -> None:
    instance = _instance(context)
    (budget,) = instance["budgets"]
    assert budget["tokens_left"] == DAILY_TOKENS - _chat_tokens(context), budget
