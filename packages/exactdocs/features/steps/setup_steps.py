"""Steps for the first-run setup: a fresh instance, driven over HTTP and by the real CLI."""

import asyncio
import io
import os
import tempfile
from contextlib import ExitStack, redirect_stdout
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from pydantic import SecretStr

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import AuthenticateQuery
from exactdocs.identity.errors import InvalidCredentialsError


@given("a fresh instance")
def step_fresh(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir)
    context.client = stack.enter_context(
        TestClient(create_app(Container.build(context.settings)), base_url="http://localhost")
    )


@when("a client lists the libraries over the REST API")
def step_list(context: Context) -> None:
    context.response = context.client.get("/api/v1/libraries")


@when('a client sets the instance up with the username "{username}" and the password "{password}"')
def step_setup(context: Context, username: str, password: str) -> None:
    body = {"username": username, "password": password}
    context.response = context.client.post("/api/v1/setup", json=body)


@when(
    'the operator runs "exactdocs admin create" with the username "{username}" '
    'and the password "{password}"'
)
def step_cli(context: Context, username: str, password: str) -> None:
    tokens = ["admin", "create", "--username", username, "--password-stdin"]
    env = {"EXACTDOCS_DATA_DIR": str(context.settings.data_dir)}
    output = io.StringIO()
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", io.StringIO(password + "\n")),
        redirect_stdout(output),
    ):
        cli.app(tokens, exit_on_error=False, result_action="return_value")
    assert password not in output.getvalue()


async def _authenticate(settings: Settings, username: str, password: str) -> str | None:
    container = Container.build(settings)
    async with container.running():
        query = AuthenticateQuery(username=username, password=SecretStr(password))
        try:
            return (await container.identity.authenticate(query)).role
        except InvalidCredentialsError:
            return None


@then('the admin "{username}" can sign in with the password "{password}"')
def step_can_sign_in(context: Context, username: str, password: str) -> None:
    assert asyncio.run(_authenticate(context.settings, username, password)) == "admin"


@then('the admin cannot sign in with the password "{password}"')
def step_cannot_sign_in(context: Context, password: str) -> None:
    assert asyncio.run(_authenticate(context.settings, "ada", password)) is None


@then("the setup endpoint is no longer available")
def step_setup_closed(context: Context) -> None:
    body = {"username": "mallory", "password": "another strong password"}
    response = context.client.post("/api/v1/setup", json=body)
    assert response.status_code == HTTPStatus.CONFLICT, response.text
    assert response.json()["error"] == "already_set_up"


@then('the request is refused with "{code}"')
def step_refused(context: Context, code: str) -> None:
    assert context.response.status_code == HTTPStatus.FORBIDDEN, context.response.text
    assert context.response.json()["error"] == code


@then("the instance still needs its setup")
def step_needs_setup(context: Context) -> None:
    assert context.client.get("/api/v1/libraries").json()["error"] == "setup_required"
