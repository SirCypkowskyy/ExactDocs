"""Steps for the agentic answer cache (#100): the real pipeline and cache, a scripted LLM.

The ``llm`` role is a pydantic-ai ``FunctionModel`` (``scripted_explorer``): ``ScriptedModels``
lists every chat model it builds, one per agent run, so a step can tell whether the agent ran.
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
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from scripted_explorer import ScriptedModels, browsing, scripted_ai
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit
from steps.import_steps import wait_for_job
from steps.search_steps import LIBRARY

FIRST = "how do I configure retries"
"""The question answered first."""
SIMILAR = "how to configure retry behaviour"
"""The same question in other words."""


def ask(context: Context, question: str, ref: str) -> dict[str, Any]:
    """Ask the fixture library a question in agentic mode.

    Args:
        context: The behave context.
        question: The question.
        ref: The version.

    Returns:
        The search result.
    """
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"q": question, "ref": ref, "mode": "agentic"}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given('"{question}" was answered agentically for "{ref}"')
def step_answered(context: Context, question: str, ref: str) -> None:
    body = ask(context, question, ref)
    assert (body["retrieval_mode"], body["cache_hit"]) == ("agentic", False), body
    assert body["results"], body
    context.agent_runs = len(context.models.chat_models)
    assert context.agent_runs == 1, context.models.chat_models


@when('an agent asks "{question}" for "{ref}"')
def step_ask(context: Context, question: str, ref: str) -> None:
    context.result = ask(context, question, ref)


@then('the cached result is returned with "cache_hit: true"')
def step_cache_hit(context: Context) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["cache_hit"], body["fallback_reason"]) == (
        "agentic",
        True,
        None,
    ), body
    assert body["results"], body
    for result in body["results"]:
        assert result["justification"], result
        assert result["explored_path"], result


@then("the agent did not run again")
def step_not_again(context: Context) -> None:
    assert len(context.models.chat_models) == context.agent_runs, context.models.chat_models


@then('the agent runs again and the result says "cache_hit: false"')
def step_ran_again(context: Context) -> None:
    body = context.result
    assert (body["retrieval_mode"], body["cache_hit"]) == ("agentic", False), body
    assert len(context.models.chat_models) == context.agent_runs + 1, context.models.chat_models


@given('a cached agentic answer for "{ref}"')
def step_cached_for(context: Context, ref: str) -> None:
    # The instance imported the library itself: serve it again with the scripted LLM, keeping
    # the offline git it fetches with, so a sync still works.
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(
        update={"ai": AiSettings.model_validate(scripted_ai("agentic"))}
    )
    context.models = ScriptedModels(model=browsing())
    context.container = Container.build(
        settings,
        remote=OfflineGit(GitCli.locate()),
        gateway=context.git,
        renames=context.renames,
        chunker=context.chunker,
        model_factory=context.models,
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    step_answered(context, FIRST, ref)
    assert ask(context, SIMILAR, ref)["cache_hit"] is True, "the answer is cached"
    assert len(context.models.chat_models) == context.agent_runs
    context.cached_ref = ref


@when('"{ref}" is re-synced to a new commit')
def step_resynced(context: Context, ref: str) -> None:
    repo = context.fixture_repo.path

    def git(*args: str) -> str:
        """Run git in the private copy.

        Args:
            args: The git arguments.

        Returns:
            Its output.
        """
        return context.fixture_git(*args, cwd=repo)

    git("checkout", "-q", ref)
    with (repo / "docs/guide/resilience.md").open("a", encoding="utf-8") as article:
        article.write("\n## Jitter\n\nEach wait between retries is randomized a little.\n")
    git("-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
        "commit", "-q", "-am", "docs: retries are jittered")  # fmt: skip
    head = git("rev-parse", "HEAD")
    response = context.client.post(f"/api/v1/libraries{LIBRARY}/sync")
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    job = wait_for_job(context, response.headers["Location"].rsplit("/", 1)[-1])
    assert job["state"] == "succeeded", job
    version = context.client.get(f"/api/v1/libraries{LIBRARY}/versions/{ref}").json()
    assert version["commit_sha"] == head, version


@then("the next similar question runs the agent again")
def step_runs_again(context: Context) -> None:
    body = ask(context, SIMILAR, context.cached_ref)
    assert (body["retrieval_mode"], body["cache_hit"]) == ("agentic", False), body
    assert len(context.models.chat_models) == context.agent_runs + 1, context.models.chat_models
