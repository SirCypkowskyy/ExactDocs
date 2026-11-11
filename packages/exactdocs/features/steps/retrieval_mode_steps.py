"""Steps for choosing the retrieval mode. Model roles are set directly, and the hybrid pipeline
is a stand-in (the real one is in ``hybrid_search_steps``): these scenarios are about which mode
answers, not what it finds."""

from contextlib import ExitStack
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.models import ModelRole, PipelineAnswer, PipelineRequest, RetrievalMode
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE

SEARCH = "/api/v1/libraries/fixture/docs-repo/search"
SETTING = "/api/v1/libraries/fixture/docs-repo/retrieval"


class StandInHybrid:
    """Answers `hybrid` with no hits: what matters here is which mode was chosen."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        del request
        return PipelineAnswer(
            mode=RetrievalMode.HYBRID, hits=(), candidates=0, reranked=0, complete=True
        )


def _restart(context: Context, instance: str | None, roles: frozenset[ModelRole]) -> None:
    """Serve the same data again with this instance mode and these configured model roles."""
    # A process runs one job worker: the instance served so far stops first.
    context.client.__exit__(None, None, None)
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(
        update={"ai": AiSettings(mode=RetrievalMode(instance) if instance else None)}
    )
    container = Container.build(
        settings,
        model_roles=StaticModelRoles(roles=roles),
        pipelines={RetrievalMode.HYBRID: StandInHybrid()},
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given('the instance mode is "{instance}" and the library\'s mode is "{library}"')
def step_instance_and_library(context: Context, instance: str, library: str) -> None:
    _restart(context, instance, frozenset({ModelRole.EMBEDDING}))
    response = context.client.put(SETTING, json={"mode": library})
    assert response.status_code == HTTPStatus.OK, response.text


@given('the instance mode is "{instance}" and an embedding model is configured')
def step_instance_only(context: Context, instance: str) -> None:
    _restart(context, instance, frozenset({ModelRole.EMBEDDING}))


@given("no embedding model is configured")
def step_no_embedding(context: Context) -> None:
    _restart(context, None, frozenset())


@when('an agent searches with mode "{mode}"')
def step_search_with_mode(context: Context, mode: str) -> None:
    context.response = context.client.get(SEARCH, params={"q": "retry_policy", "mode": mode})


@when("an agent searches without a mode")
def step_search_without_mode(context: Context) -> None:
    context.response = context.client.get(SEARCH, params={"q": "retry_policy"})


@when('the admin sets the library\'s mode to "{mode}"')
def step_set_library_mode(context: Context, mode: str) -> None:
    context.response = context.client.put(SETTING, json={"mode": mode})


@then('the result says retrieval mode "{mode}"')
def step_result_mode(context: Context, mode: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert body["retrieval_mode"] == mode, body
    assert body["fallback_reason"] is None, body


@then('the call fails with "{code}" naming the missing role "{role}"')
def step_fails(context: Context, code: str, role: str) -> None:
    assert context.response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, context.response.text
    body = context.response.json()
    assert body["error"] == code, body
    assert f"needs the {role} role" in body["detail"], body


@then("the library has no mode of its own")
def step_no_library_mode(context: Context) -> None:
    shown = context.client.get(SETTING).json()
    assert shown["mode"] is None, shown
