"""Steps for MCP over OAuth: a web host drives FastMCP's proxy against the fake issuer."""

import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from http import HTTPStatus
from importlib import import_module
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.catalog.dtos import CreateLibraryCommand

fake_oidc = import_module("fake_oidc")  # test support on sys.path (environment.py)
host = import_module("mcp_oauth_host")

ADMIN = ("ada", "correct horse battery staple")


@given('MCP OAuth is served through provider "{name}", which allows only group "{group}"')
def step_served(context: Context, name: str, group: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    # The proxy and the app run on the real clock, not the movable one of the shared Background.
    context.issuer.now = lambda: datetime.now(UTC)
    stack.enter_context(host.fake_issuer(context.issuer))
    config = {**context.provider_config, "allow_any_user": False, "allowed_groups": [group]}
    container = Container.build(
        Settings(
            data_dir=data_dir,
            public_url="http://localhost",
            auth={"providers": {name: config}},
            mcp_oauth_provider=name,
        ),
        sign_in=SignInStandIns(transport=context.issuer.transport()),
    )
    context.container = container
    context.client = stack.enter_context(
        TestClient(create_app(container), base_url="http://localhost")
    )


def _connect(context: Context, name: str, group: str) -> None:
    subject = f"u-{name}"
    context.issuer.add_user(subject, name, groups=[group])
    metadata = context.client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == HTTPStatus.OK, metadata.text
    context.granted = host.connect(context.client, context.issuer, subject)
    assert context.granted.status_code == HTTPStatus.OK, context.granted.text
    context.token = context.granted.json()["access_token"]


@when('a web MCP host discovers the OAuth metadata and signs "{name}" (group "{group}") in')
def step_discovers_and_signs_in(context: Context, name: str, group: str) -> None:
    _connect(context, name, group)


@when('a web MCP host signs "{name}" (group "{group}") in')
def step_signs_in(context: Context, name: str, group: str) -> None:
    _connect(context, name, group)


@then('it can call "{tool}" as that user')
def step_can_call(context: Context, tool: str) -> None:
    response = host.call_tool(context.client, context.token, tool)
    assert response.status_code == HTTPStatus.OK, response.text
    assert host.tool_result(response)["isError"] is False


@then("API tokens keep working")
def step_api_tokens(context: Context) -> None:
    client = context.client
    username, password = ADMIN
    setup = client.post("/api/v1/setup", json={"username": username, "password": password})
    assert setup.status_code == HTTPStatus.CREATED, setup.text
    login = client.post("/api/v1/session", json={"username": username, "password": password})
    assert login.status_code == HTTPStatus.CREATED, login.text
    created = client.post("/api/v1/tokens", json={"name": "cli"})
    assert created.status_code == HTTPStatus.CREATED, created.text
    client.cookies.clear()
    response = host.call_tool(client, created.json()["token"], "list_libraries")
    assert response.status_code == HTTPStatus.OK, response.text


@then("the token is refused and no tool can be called")
def step_refused(context: Context) -> None:
    for tool in ("list_libraries", "list_articles"):
        response = host.call_tool(context.client, context.token, tool)
        assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text


@given('the library "{library}" is shared with OAuth group "{group}"')
def step_oauth_library(context: Context, library: str, group: str) -> None:
    client = context.client
    username, password = ADMIN
    assert (
        client.post("/api/v1/setup", json={"username": username, "password": password}).status_code
        == HTTPStatus.CREATED
    )
    assert (
        client.post(
            "/api/v1/session", json={"username": username, "password": password}
        ).status_code
        == HTTPStatus.CREATED
    )
    client.portal.call(
        context.container.catalog.create_library,
        CreateLibraryCommand(
            id=library,
            title="Docs",
            source_url="https://example.com/acme/docs.git",
            default_branch="main",
            host="git",
        ),
    )
    granted = client.put(
        f"/api/v1/libraries{library}/grants",
        json={"kind": "group", "subject": group, "role": "viewer"},
    )
    assert granted.status_code == HTTPStatus.OK, granted.text
    client.cookies.clear()


@then('the OAuth host lists the library "{library}"')
def step_oauth_library_listed(context: Context, library: str) -> None:
    response = host.call_tool(context.client, context.token, "list_libraries")
    assert response.status_code == HTTPStatus.OK, response.text
    result = host.tool_result(response)
    assert [item["id"] for item in result["structuredContent"]["libraries"]] == [library], result
