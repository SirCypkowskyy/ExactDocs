"""Steps for private repositories: a token-protected fixture server and the secret key."""

import asyncio
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from steps.http_steps import DEMO_COOKIE, store_demo_catalog
from steps.import_steps import LIBRARY, wait_for_job


def _start(context: Context, secret: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.app_stack = stack
    settings = Settings(data_dir=context.data_dir, secret_key=SecretStr(secret))
    context.client = stack.enter_context(
        TestClient(
            create_app(Container.build(settings)),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@given("the fixture HTTP git server requires a token")
def step_private(context: Context) -> None:
    context.token = context.fixture_repo.token
    context.private_url = context.fixture_repo.private_url


@given('ExactDocs runs with the secret key "{secret}"')
def step_start(context: Context, secret: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    asyncio.run(
        store_demo_catalog(Settings(data_dir=context.data_dir, secret_key=SecretStr(secret)))
    )
    _start(context, secret)


def _add(context: Context, *, token: bool) -> None:
    body: dict[str, object] = {
        "url": context.private_url,
        "include_paths": ["docs/"],
        "ref": "v1.3.0",
    }
    if token:
        body["credential"] = {"kind": "token", "token": context.token}
    context.response = context.client.post("/api/v1/libraries", json=body)


@when("a user adds it with that token")
@given("a private library was imported")
def step_add(context: Context) -> None:
    _add(context, token=True)
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    context.transcript = [context.response.text]
    job = wait_for_job(context, context.response.json()["job_id"])
    assert job["state"] == "succeeded", job
    context.transcript.append(str(job))


@when("a user adds it without a token")
def step_add_without(context: Context) -> None:
    _add(context, token=False)


@then("the library imports")
def step_imports(context: Context) -> None:
    assert context.job["state"] == "succeeded", context.job
    assert context.job["done"] == context.job["total"] > 0


@then("the token is never returned by the API")
def step_never_returned(context: Context) -> None:
    pages = [
        context.client.get(f"/api/v1/libraries{LIBRARY}").text,
        context.client.get(f"/api/v1/libraries{LIBRARY}/jobs").text,
        context.client.get("/api/v1/jobs/latest").text,
        *context.transcript,
    ]
    assert all(context.token not in page for page in pages)


@given("ExactDocs restarts with a different secret key")
@when("ExactDocs restarts with a different secret key")
def step_restart(context: Context) -> None:
    context.app_stack.close()
    _start(context, "second-secret-key-of-at-least-32-chars")


@then("the library is still readable")
def step_readable(context: Context) -> None:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/articles", params={"ref": "v1.3.0", "limit": 100}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["articles"]


@then('adding a version to it fails with "{code}"')
def step_add_version_fails(context: Context, code: str) -> None:
    response = context.client.post(f"/api/v1/libraries{LIBRARY}/versions", json={"ref": "v1.4.0"})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert response.json()["error"] == code, response.text


@when("a user adds a version with the token again")
def step_add_version_again(context: Context) -> None:
    response = context.client.post(
        f"/api/v1/libraries{LIBRARY}/versions",
        json={"ref": "v1.4.0", "credential": {"kind": "token", "token": context.token}},
    )
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    wait_for_job(context, response.json()["job_id"])


@then("the version imports")
def step_version_imports(context: Context) -> None:
    assert context.job["state"] == "succeeded", context.job


@then("the library is reported as private")
def step_reported_private(context: Context) -> None:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}/access")
    assert response.json() == {"private": True}, response.text
    assert context.token not in response.text
