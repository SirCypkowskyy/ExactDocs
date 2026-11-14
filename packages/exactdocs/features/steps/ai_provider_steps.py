"""Steps for AI provider profiles (#241).

A fake gateway on loopback (``fake_llm``) stands in for every endpoint a scenario names, such as
``https://llm.example.com/v1``: the scenarios check what is sent and where, not a real model. The
hybrid pipeline is a stand-in that sends the query to the embedding role's gateway, as the real
one does, so a scenario can see whether anything of a library leaves the instance.
"""

import io
import logging
import os
import tempfile
import time
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import httpx
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.models import PipelineAnswer, PipelineRequest, RetrievalMode
from fake_llm import FakeGateway, gateway
from socket_guard import AI_MODULES, NOTHING_CONFIGURED, run_guarded
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE

KEY = "sk-corp-key-never-shown"
SEARCH = "/api/v1/libraries/fixture/docs-repo/search"
JOBS = "/api/v1/libraries/fixture/docs-repo/jobs"
EMBEDDING_SECONDS = 60.0


def _gateway(context: Context, name: str = "corp") -> FakeGateway:
    """Start a fake gateway for this scenario.

    Args:
        context: The behave context.
        name: Its name in the context (``context.gateways``).

    Returns:
        The gateway.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    running = stack.enter_context(gateway())
    if not hasattr(context, "gateways"):
        context.gateways = {}
    context.gateways[name] = running
    return running


def _serve(context: Context, ai: dict | AiSettings, pipelines: dict | None = None) -> None:
    """Serve the same data again with this ``ai`` configuration.

    Args:
        context: The behave context.
        ai: The ``ai`` settings.
        pipelines: Stand-in retrieval pipelines.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    ai_settings = ai if isinstance(ai, AiSettings) else AiSettings.model_validate(ai)
    settings = context.settings.model_copy(update={"ai": ai_settings})
    container = Container.build(settings, pipelines=pipelines)
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given('the operator configures provider "{name}" of kind "{kind}" with base URL "{url}" and a key')
def step_configure(context: Context, name: str, kind: str, url: str) -> None:
    context.named_url = url  # the fake gateway stands in for it
    corp = _gateway(context, name)
    prefix = f"EXACTDOCS_AI__PROVIDERS__{name.upper()}__"
    context.ai_env = {
        f"{prefix}KIND": kind,
        f"{prefix}BASE_URL": corp.v1,
        f"{prefix}API_KEY": KEY,
    }


@given('sets the LLM role to "{llm}" and the embedding role to "{embedding}"')
def step_roles(context: Context, llm: str, embedding: str) -> None:
    context.ai_env |= {"EXACTDOCS_AI__LLM__MODEL": llm, "EXACTDOCS_AI__EMBEDDING__MODEL": embedding}
    context.roles = {"llm": llm, "embedding": embedding}


@when('the operator runs "exactdocs ai check"')
def step_ai_check(context: Context) -> None:
    output = io.StringIO()
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    root = logging.getLogger()
    root.addHandler(handler)
    env = {"EXACTDOCS_DATA_DIR": str(context.settings.data_dir), **context.ai_env}
    try:
        with patch.dict(os.environ, env), redirect_stdout(output), redirect_stderr(output):
            try:
                cli.app(["ai", "check"], exit_on_error=False, result_action="return_value")
                context.exit_code = 0
            except SystemExit as exc:
                context.exit_code = exc.code
    finally:
        root.removeHandler(handler)
    context.output = output.getvalue()
    context.logs = logs.getvalue()


@then('both roles report "ok" with the model name and the embedding dimensions')
def step_both_ok(context: Context) -> None:
    assert context.exit_code == 0, context.output
    lines = context.output.splitlines()
    llm = next(line for line in lines if line.startswith("llm:"))
    embedding = next(line for line in lines if line.startswith("embedding:"))
    assert "ok" in llm, context.output
    assert context.roles["llm"] in llm, context.output
    assert "ok" in embedding, context.output
    assert context.roles["embedding"] in embedding, context.output
    assert "3 dimensions" in embedding, context.output
    assert "ms" in llm, context.output


@then("the key never appears in the output, the logs or the REST API")
def step_key_hidden(context: Context) -> None:
    assert KEY not in context.output
    assert KEY not in context.logs
    with patch.dict(os.environ, context.ai_env):
        _serve(context, Settings().ai)  # the server reads the same environment
    listed = context.client.get("/api/v1/ai/providers")
    assert listed.status_code == HTTPStatus.OK, listed.text
    (corp,) = listed.json()["providers"]
    assert corp["key"] == "environment", corp
    assert KEY not in listed.text
    assert KEY not in context.client.get("/api/v1/ai/roles").text
    # The gateway did get it, as its credential: the only place it goes.
    assert context.gateways["corp"].seen[0].headers["authorization"] == f"Bearer {KEY}"


@given("the process environment has OPENAI_API_KEY, OPENAI_BASE_URL and ANTHROPIC_API_KEY set")
def step_poisoned(context: Context) -> None:
    trap = _gateway(context, "trap")
    variables = {
        "OPENAI_API_KEY": "sk-host-openai-key",
        "OPENAI_BASE_URL": trap.v1,
        "ANTHROPIC_API_KEY": "sk-host-anthropic-key",
    }
    patcher = patch.dict(os.environ, variables)
    patcher.start()
    context.add_cleanup(patcher.stop)


@given('provider "{name}" of kind "{kind}" has no key')
def step_keyless(context: Context, name: str, kind: str) -> None:
    corp = _gateway(context, name)
    _serve(
        context,
        {
            "providers": {name: {"kind": kind, "base_url": corp.v1}},
            "llm": {"model": f"{name}:gpt-4.1-mini"},
        },
    )


@when('ExactDocs calls "{name}"')
def step_call(context: Context, name: str) -> None:
    context.response = context.client.post(f"/api/v1/ai/providers/{name}/check")


@then("the request goes to corp's base URL with no OpenAI key, and nothing goes to OPENAI_BASE_URL")
def step_went_to_corp(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["checks"][0]["status"] == "ok", context.response.text
    calls = context.gateways["corp"].seen  # the llm role, and the judge that defaults to it
    assert calls
    for seen in calls:
        assert seen.path == "/v1/chat/completions"
        assert seen.headers["authorization"] == "Bearer unused"
    assert context.gateways["trap"].seen == []


class SendsTheQuery:
    """Stand-in hybrid pipeline: embeds the query at the gateway, then answers ``hybrid``."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        async with httpx.AsyncClient() as client:
            body = {"model": "e5", "input": [request.query]}
            await client.post(f"{self.url}/embeddings", json=body)
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


@given('provider "{name}" is configured for every role')
def step_every_role(context: Context, name: str) -> None:
    corp = _gateway(context, name)
    roles = ("embedding", "reranker", "llm", "judge")
    _serve(
        context,
        {
            "mode": "hybrid",  # not a default (docs/evals.md): chosen, so AI is used with AI on
            "providers": {name: {"kind": "openai-compatible", "base_url": corp.v1}},
            **{role: {"model": f"{name}:m"} for role in roles},
        },
        pipelines={RetrievalMode.HYBRID: SendsTheQuery(corp.v1)},
    )
    _wait_for_embedding(context)  # until then, a version answers BM25 (#91)
    before = context.client.get(SEARCH, params={"q": "retry_policy"})
    assert before.json()["retrieval_mode"] == "hybrid", before.text
    assert corp.seen, "with AI on, the stand-in pipeline reaches the gateway"
    corp.seen.clear()


def _wait_for_embedding(context: Context) -> None:
    """Wait until the background embedding of the fixture library is done.

    Args:
        context: The behave context.
    """
    deadline = time.monotonic() + EMBEDDING_SECONDS
    while time.monotonic() < deadline:
        listed = context.client.get(JOBS, params={"limit": 100}).json()["jobs"]
        embeds = [job for job in listed if job["kind"] == "embed"]
        if embeds and all(job["state"] in {"succeeded", "failed"} for job in embeds):
            assert all(job["state"] == "succeeded" for job in embeds), embeds
            return
        time.sleep(0.05)
    message = "the background embedding did not finish"
    raise AssertionError(message)


@when('the admin sets library "{library}" to AI "off"')
def step_ai_off(context: Context, library: str) -> None:
    path = f"/api/v1/libraries{library}/retrieval"
    context.response = context.client.put(path, json={"ai_enabled": False})
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    context.searches = [
        context.client.get(SEARCH, params={"q": q}) for q in ("retry_policy", "token")
    ]


@then("no chunk or query of that library is sent to any provider")
def step_nothing_sent(context: Context) -> None:
    assert context.response.json()["configured_roles"] == [], context.response.text
    assert context.gateways["corp"].seen == []


@then('searches in it answer with "{mode}"')
def step_answer_mode(context: Context, mode: str) -> None:
    for response in context.searches:
        assert response.status_code == HTTPStatus.OK, response.text
        assert response.json()["retrieval_mode"] == mode, response.text


@given("no AI provider is configured")
def step_nothing(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.fresh_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))


@when("ExactDocs starts and serves searches")
def step_start_fresh(context: Context) -> None:
    context.guarded = run_guarded(context.fresh_dir, NOTHING_CONFIGURED)


@then('no module of the "exactdocs[ai]" extra is imported and no outbound connection is opened')
def step_nothing_loaded(context: Context) -> None:
    loaded = set(context.guarded["modules"])
    assert not (loaded | {m.split(".")[0] for m in loaded}) & AI_MODULES
    assert context.guarded["blocked"] == []
    assert context.guarded["trap"] == 0
