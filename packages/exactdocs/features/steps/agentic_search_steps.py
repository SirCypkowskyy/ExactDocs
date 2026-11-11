"""Steps for agentic retrieval (#98): the real pipeline and Code Mode, a scripted LLM.

The ``llm`` role resolves to a profile whose chat model is a pydantic-ai ``FunctionModel``
(``scripted_explorer``), so the agent, its sandbox and its limits run for real and nothing leaves
the process.
"""

import logging
from contextlib import ExitStack
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven import ai_explorer_sdk
from scripted_explorer import ScriptedModels, browsing, greedy, looping, scripted_ai
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.search_steps import LIBRARY

QUESTION = "how do I retry failed calls"


def _serve(context: Context, model: FunctionModel, ai: dict[str, Any]) -> None:
    """Serve the same data again with the scripted model as the ``llm`` role.

    Args:
        context: The behave context.
        model: The scripted chat model.
        ai: The ``ai`` settings.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(update={"ai": AiSettings.model_validate(ai)})
    context.models = ScriptedModels(model=model)
    container = Container.build(settings, model_factory=context.models)
    context.container = container
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


def _search(context: Context, target: str, mode: str) -> dict[str, Any]:
    """Search a version of the fixture library in a mode.

    Args:
        context: The behave context.
        target: ``/owner/repo/ref``.
        mode: The mode asked for.

    Returns:
        The result.
    """
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    response = context.client.get(
        f"/api/v1/libraries/{owner}/{repo}/search",
        params={"q": QUESTION, "ref": ref, "mode": mode},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given("an LLM is configured and agentic mode is on")
def step_agentic_on(context: Context) -> None:
    _serve(context, browsing(), scripted_ai("agentic"))


@when('an agent searches "{target}" in mode "{mode}"')
def step_search_mode(context: Context, target: str, mode: str) -> None:
    context.result = _search(context, target, mode)


@then("results carry a justification and the explored path")
def step_justified(context: Context) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("agentic", None), body
    assert body["results"], body
    for result in body["results"]:
        assert result["justification"], result
        path = result["explored_path"]
        assert path, result
        assert path[0].startswith("search_docs("), path  # how the scripted agent starts
    assert context.models.chat_models == ["corp:explorer"], context.models.chat_models


@then('every result belongs to "{ref}"')
def step_all_in_version(context: Context, ref: str) -> None:
    body = context.result
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
        read = context.client.get(f"/api/v1/chunks/{result['chunk_id']}")
        assert read.status_code == HTTPStatus.OK, read.text
        assert read.json()["version"] == ref, read.text


@given("agentic mode is limited to {calls:d} tool calls")
def step_limited(context: Context, calls: int) -> None:
    _serve(context, greedy(calls + 10), scripted_ai("agentic", {"max_tool_calls": calls}))


@when("the agent needs more")
def step_needs_more(context: Context) -> None:
    context.result = _search(context, f"{LIBRARY}/v1.4.0", "agentic")


@then(
    'the run ends and the search answers with the best non-agentic mode and the reason "{reason}"'
)
def step_fell_back(context: Context, reason: str) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("bm25", reason), body
    assert body["results"], "BM25 answered"
    assert all(r["justification"] is None and r["explored_path"] == [] for r in body["results"])


class _Records(logging.Handler):
    """Keeps the log records it is given."""

    def __init__(self) -> None:
        """Start with none."""
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep a record.

        Args:
            record: The record.
        """
        self.records.append(record)


@when("the agent proposes an article that is not in the pinned version")
def step_proposes_foreign(context: Context) -> None:
    older = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": "snake_case", "ref": "v1.3.0"}
    )
    assert older.status_code == HTTPStatus.OK, older.text
    context.foreign = older.json()["results"][0]["chunk_id"]
    _serve(context, browsing(extra=[context.foreign]), scripted_ai("agentic"))
    handler = _Records()
    explorer_log = logging.getLogger(ai_explorer_sdk.__name__)
    explorer_log.addHandler(handler)
    context.add_cleanup(explorer_log.removeHandler, handler)
    context.guardrail_log = handler
    context.result = _search(context, f"{LIBRARY}/v1.4.0", "agentic")


@then("the guardrail rejects it and it is not returned")
def step_guardrail_rejected(context: Context) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("agentic", None), body
    assert body["results"], "the agent's own picks remain"
    assert context.foreign not in [r["chunk_id"] for r in body["results"]], body
    rejected = [r.getMessage() for r in context.guardrail_log.records]
    assert any("output guardrail rejected 1 pick" in m for m in rejected), rejected
    assert all(context.foreign not in m for m in rejected), "the log names no chunk"


@when("the agent calls the same tool with the same arguments {times:d} times")
def step_loops(context: Context, times: int) -> None:
    _serve(context, looping(times), scripted_ai("agentic"))
    context.result = _search(context, f"{LIBRARY}/v1.4.0", "agentic")


@then('the run ends and the search falls back to BM25 with the reason "{reason}"')
def step_fell_back_to_bm25(context: Context, reason: str) -> None:
    step_fell_back(context, reason)
