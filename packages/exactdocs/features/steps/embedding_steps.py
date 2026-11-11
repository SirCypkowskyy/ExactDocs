"""Steps for background embedding (#91).

A fake gateway on loopback (``fake_llm``) is the embedding endpoint: it answers every text with
the same small vector and records what it was sent. The hybrid pipeline is a stand-in until #92:
it answers ``hybrid`` with no hits, so a scenario sees which mode a search ran in.
"""

import asyncio
import io
import os
import threading
import time
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http import HTTPStatus
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.retrieval.adapters.driven.sqlite_vectors import SqliteVectorIndex
from exactdocs.retrieval.models import (
    EmbeddingSpace,
    PipelineAnswer,
    PipelineRequest,
    RetrievalMode,
    SpaceState,
)
from fake_llm import FakeGateway, gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, step_running
from steps.search_steps import LIBRARY, import_versions

EMBEDDING_SECONDS = 60.0


class AnswersHybrid:
    """Stand-in hybrid pipeline: answers ``hybrid`` with no hits."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


def start_gateway(context: Context, hold: threading.Event | None = None) -> FakeGateway:
    """Start a fake embedding endpoint for this scenario.

    Args:
        context: The behave context.
        hold: Holds its embedding answers until set.

    Returns:
        The gateway.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    return stack.enter_context(gateway(hold))


def embedding_ai(endpoint: FakeGateway, model: str) -> AiSettings:
    """Configure one OpenAI-compatible profile and its embedding model.

    Args:
        endpoint: The fake gateway.
        model: The embedding model.

    Returns:
        The ``ai`` settings.
    """
    return AiSettings.model_validate(
        {
            "providers": {"corp": {"kind": "openai-compatible", "base_url": endpoint.v1}},
            "embedding": {"model": f"corp:{model}"},
        }
    )


def serve_embedding(context: Context, ai: AiSettings) -> None:
    """Serve the same data again with this ``ai`` configuration (and the stand-in hybrid).

    Args:
        context: The behave context.
        ai: The ``ai`` settings.
    """
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(update={"ai": ai})
    container = Container.build(settings, pipelines={RetrievalMode.HYBRID: AnswersHybrid()})
    context.container = container
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


def _embed_jobs(context: Context, library: str) -> list[dict]:
    """List the library's embedding jobs.

    Args:
        context: The behave context.
        library: The library ID.

    Returns:
        Its ``embed`` jobs, newest first.
    """
    response = context.client.get(f"/api/v1/libraries{library}/jobs", params={"limit": 100})
    assert response.status_code == HTTPStatus.OK, response.text
    return [job for job in response.json()["jobs"] if job["kind"] == "embed"]


def wait_for_embedding(context: Context, library: str) -> list[dict]:
    """Wait until no embedding job of the library is queued or running.

    Args:
        context: The behave context.
        library: The library ID.

    Returns:
        Its ``embed`` jobs.
    """
    deadline = time.monotonic() + EMBEDDING_SECONDS
    while time.monotonic() < deadline:
        jobs = _embed_jobs(context, library)
        if jobs and all(job["state"] in {"succeeded", "failed"} for job in jobs):
            return jobs
        time.sleep(0.05)
    message = "the embedding jobs did not finish"
    raise AssertionError(message)


def _spaces(context: Context) -> list[EmbeddingSpace]:
    """List the instance's embedding spaces.

    Args:
        context: The behave context.

    Returns:
        Every space, oldest first.
    """
    vectors = SqliteVectorIndex(engine=context.container.engine)
    return list(context.client.portal.call(vectors.spaces))


def _search(context: Context) -> dict:
    """Search the fixture library's default version.

    Args:
        context: The behave context.

    Returns:
        The result.
    """
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": "retry_policy", "ref": "v1.4.0"}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given('chunks were embedded with model "{model}"')
def step_embedded_with(context: Context, model: str) -> None:
    context.first = start_gateway(context)
    serve_embedding(context, embedding_ai(context.first, model))
    jobs = wait_for_embedding(context, LIBRARY)
    assert {job["version"] for job in jobs} == {"v1.3.0", "v1.4.0"}, jobs
    assert all(job["state"] == "succeeded" for job in jobs), jobs
    (space,) = _spaces(context)
    assert (space.spec.model, space.state) == (model, SpaceState.ACTIVE), space
    assert _search(context)["retrieval_mode"] == "hybrid"
    context.first_space = space


@when('the operator switches to model "{model}"')
def step_switch(context: Context, model: str) -> None:
    held = threading.Event()
    context.add_cleanup(held.set)
    context.second = start_gateway(context, hold=held)
    serve_embedding(context, embedding_ai(context.second, model))
    # The new model's jobs wait for the gateway: the instance is mid-way through re-embedding.
    context.during = [_search(context), _search(context)]
    held.set()


@then('all chunks are re-embedded with "{model}" in the background while BM25 answers')
def step_reembedded(context: Context, model: str) -> None:
    deadline = time.monotonic() + EMBEDDING_SECONDS
    while time.monotonic() < deadline:
        spaces = _spaces(context)
        if any(s.spec.model == model and s.state is SpaceState.ACTIVE for s in spaces):
            break
        time.sleep(0.05)
    jobs = wait_for_embedding(context, LIBRARY)
    assert all(job["state"] == "succeeded" for job in jobs), jobs
    old, new = _spaces(context)
    assert old.id == context.first_space.id, (old, new)
    assert (old.state, new.spec.model, new.state) == (SpaceState.RETIRED, model, SpaceState.ACTIVE)
    sent = [seen for seen in context.second.seen if seen.path == "/v1/embeddings"]
    assert sent, "the new model was called"
    assert {seen.body["model"] for seen in sent} == {model}
    estimate = context.client.get("/api/v1/ai/embedding/estimate")
    assert estimate.status_code == HTTPStatus.OK, estimate.text
    assert estimate.json()["chunks"] == 0, estimate.text  # every version is covered
    assert _search(context)["retrieval_mode"] == "hybrid"


@then(
    'until a version is covered by "{model}", its searches answer "{mode}" with fallback reason '
    '"{reason}"'
)
def step_until_covered(context: Context, model: str, mode: str, reason: str) -> None:
    del model
    for body in context.during:
        assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, reason), body
        assert body["results"], "BM25 answered while the new model embedded"


@given('library "{library}" has AI "off"')
def step_library_off(context: Context, library: str) -> None:
    step_running(context)
    asyncio.run(import_versions(context, ["v1.4.0"], library=library))
    response = context.client.put(
        f"/api/v1/libraries{library}/retrieval", json={"ai_enabled": False}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    context.library = library


@when("the embedding jobs run")
def step_jobs_run(context: Context) -> None:
    context.endpoint = start_gateway(context)
    serve_embedding(context, embedding_ai(context.endpoint, "e5"))
    # Queued by hand as well: the job itself refuses a library with AI off.
    command = EnqueueJobCommand(kind="embed", library=context.library, version="v1.4.0")
    context.client.portal.call(context.container.ingestion.enqueue_job, command)
    context.jobs = wait_for_embedding(context, context.library)


@then('no chunk of "{library}" is sent to the embedding provider')
def step_nothing_sent(context: Context, library: str) -> None:
    assert library == context.library
    assert all(job["state"] == "succeeded" for job in context.jobs), context.jobs
    assert context.endpoint.seen == []
    assert _spaces(context) == []


@given("an embedding model is configured and nothing is embedded yet")
def step_configured(context: Context) -> None:
    context.endpoint = start_gateway(context)
    prefix = "EXACTDOCS_AI__PROVIDERS__CORP__"
    context.ai_env = {
        f"{prefix}KIND": "openai-compatible",
        f"{prefix}BASE_URL": context.endpoint.v1,
        "EXACTDOCS_AI__EMBEDDING__MODEL": "corp:text-embedding-3-small",
    }


@when('the operator runs "exactdocs ai estimate"')
def step_estimate(context: Context) -> None:
    output = io.StringIO()
    env = {"EXACTDOCS_DATA_DIR": str(context.settings.data_dir), **context.ai_env}
    with patch.dict(os.environ, env), redirect_stdout(output), redirect_stderr(output):
        try:
            cli.app(["ai", "estimate"], exit_on_error=False, result_action="return_value")
            context.exit_code = 0
        except SystemExit as exc:
            context.exit_code = exc.code
    context.output = output.getvalue()


@then("it prints the chunks, the estimated tokens and the estimated USD, labelled as an estimate")
def step_printed(context: Context) -> None:
    assert context.exit_code == 0, context.output
    text = context.output
    assert "corp:text-embedding-3-small" in text, text
    assert " chunks" in text, text
    assert "estimated tokens" in text, text
    assert "USD" in text, text
    assert "estimate" in text.lower(), text
    assert "4 characters per token" in text, text


@then("nothing is sent to the embedding provider")
def step_nothing_called(context: Context) -> None:
    assert context.endpoint.seen == []
