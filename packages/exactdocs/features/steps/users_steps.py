"""Steps for local user accounts: created by the operator's CLI, managed in the UI over REST.

Two people use one client here, so no step relies on its cookie jar: every request carries
exactly the session cookie (or bearer token) of whoever makes it, and the jar is emptied after
each answer, so one person's sign-in never ends or stands in for the other's session.
"""

import io
import os
from contextlib import redirect_stdout
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap import cli
from exactdocs.identity.constants import SESSION_COOKIE

OPERATOR = ("ada", "correct horse battery staple")
BOB_PHRASE = "bob's long passphrase"
LIST_LIBRARIES = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "list_libraries", "arguments": {}},
}
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def _send(
    context: Context,
    method: str,
    path: str,
    *,
    session: str | None = None,
    token: str | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = context.client.build_request(method, path, json=json, headers=headers or {})
    request.headers.pop("cookie", None)
    if session:
        request.headers["cookie"] = f"{SESSION_COOKIE}={session}"
    if token:
        request.headers["authorization"] = f"Bearer {token}"
    response = context.client.send(request)
    context.client.cookies.clear()
    return response


def _sign_in(context: Context, username: str, password: str) -> httpx.Response:
    body = {"username": username, "password": password}
    return _send(context, "POST", "/api/v1/session", json=body)


def _session_of(response: httpx.Response) -> str:
    assert response.status_code == HTTPStatus.CREATED, response.text
    token = response.cookies.get(SESSION_COOKIE)
    assert token
    return token


def _operator(context: Context) -> str:
    if not getattr(context, "operator_session", None):
        context.operator_session = _session_of(_sign_in(context, *OPERATOR))
    return context.operator_session


def _user_id(context: Context, username: str) -> str:
    response = _send(context, "GET", "/api/v1/users", session=_operator(context))
    assert response.status_code == HTTPStatus.OK, response.text
    return next(u["id"] for u in response.json()["users"] if u["username"] == username)


def _run_cli(context: Context, tokens: list[str], password: str) -> str:
    env = {"EXACTDOCS_DATA_DIR": str(context.settings.data_dir)}
    output = io.StringIO()
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", io.StringIO(password + "\n")),
        redirect_stdout(output),
    ):
        cli.app(tokens, exit_on_error=False, result_action="return_value")
    assert password not in output.getvalue()
    return output.getvalue()


@when('the operator runs "exactdocs user create {username}" with the password "{password}"')
def step_cli_create(context: Context, username: str, password: str) -> None:
    out = _run_cli(context, ["user", "create", username, "--password-stdin"], password)
    assert f"Created user {username!r}" in out, out


@then('"{username}" can sign in with the password "{password}"')
def step_can_sign_in(context: Context, username: str, password: str) -> None:
    session = _session_of(_sign_in(context, username, password))
    state = _send(context, "GET", "/api/v1/session", session=session).json()
    assert state["state"] == "signed_in", state
    assert (state["account"]["username"], state["account"]["role"]) == (username, "user"), state


@then('"{username}" cannot sign in with the password "{password}"')
def step_cannot_sign_in(context: Context, username: str, password: str) -> None:
    response = _sign_in(context, username, password)
    assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text
    # The same answer as a wrong password: a disabled account is not told apart.
    assert response.json()["error"] == "invalid_credentials"


@then("there is no sign-up page")
def step_no_sign_up(context: Context) -> None:
    # Signed out, nothing creates an account: setup is over, and the users routes need an operator.
    body = {"username": "mallory", "password": "mallory's own passphrase"}
    assert _send(context, "POST", "/api/v1/setup", json=body).status_code == HTTPStatus.CONFLICT
    for path in ["/api/v1/users", "/api/v1/signup", "/api/v1/register", "/api/v1/accounts"]:
        status = _send(context, "POST", path, json=body).status_code
        assert status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND}, (path, status)
    assert _sign_in(context, "mallory", body["password"]).status_code == HTTPStatus.UNAUTHORIZED
    # And the API publishes no open operation but setup, the session and the token login.
    spec = _send(context, "GET", "/api/v1/openapi.json").json()
    open_operations = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if "security" not in operation
    }
    assert open_operations == {
        ("POST", "/api/v1/setup"),
        ("GET", "/api/v1/session"),
        ("POST", "/api/v1/session"),
        ("DELETE", "/api/v1/session"),
        ("POST", "/api/v1/tokens/login"),
    }, open_operations


@given('"{username}" is signed in and has an API token')
def step_signed_in_with_token(context: Context, username: str) -> None:
    body = {"username": username, "password": BOB_PHRASE, "role": "user"}
    created = _send(context, "POST", "/api/v1/users", session=_operator(context), json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    context.user_session = _session_of(_sign_in(context, username, BOB_PHRASE))
    response = _send(
        context, "POST", "/api/v1/tokens", session=context.user_session, json={"name": "laptop"}
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    context.user_token = response.json()["token"]
    # Both work before the operator steps in.
    libraries = _send(context, "GET", "/api/v1/libraries", session=context.user_session)
    assert libraries.status_code == HTTPStatus.OK, libraries.text
    mcp = _send(
        context, "POST", "/mcp", token=context.user_token, json=LIST_LIBRARIES, headers=MCP_HEADERS
    )
    assert mcp.status_code == HTTPStatus.OK, mcp.text


@when('the operator disables "{username}" in the UI')
def step_disable(context: Context, username: str) -> None:
    user_id = _user_id(context, username)
    response = _send(
        context, "POST", f"/api/v1/users/{user_id}/disable", session=_operator(context)
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["disabled"] is True


@when('the operator resets the password of "{username}" to "{password}" in the UI')
def step_reset(context: Context, username: str, password: str) -> None:
    user_id = _user_id(context, username)
    response = _send(
        context,
        "PUT",
        f"/api/v1/users/{user_id}/password",
        session=_operator(context),
        json={"password": password},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["throttle"] == "cleared"


@then("bob's session and token are refused")
def step_refused(context: Context) -> None:
    libraries = _send(context, "GET", "/api/v1/libraries", session=context.user_session)
    assert libraries.status_code == HTTPStatus.UNAUTHORIZED, libraries.text
    rest = _send(context, "GET", "/api/v1/libraries", token=context.user_token)
    assert rest.status_code == HTTPStatus.UNAUTHORIZED, rest.text
    mcp = _send(
        context, "POST", "/mcp", token=context.user_token, json=LIST_LIBRARIES, headers=MCP_HEADERS
    )
    assert mcp.status_code == HTTPStatus.UNAUTHORIZED, mcp.text


@then("bob cannot list, create, disable or reset users: each is forbidden")
def step_forbidden(context: Context) -> None:
    ada = _user_id(context, "ada")
    attempts = [
        ("GET", "/api/v1/users", None),
        ("POST", "/api/v1/users", {"username": "eve", "password": "eve's long passphrase"}),
        ("POST", f"/api/v1/users/{ada}/disable", None),
        ("POST", f"/api/v1/users/{ada}/enable", None),
        ("PUT", f"/api/v1/users/{ada}/password", {"password": "taken over by bob"}),
    ]
    for method, path, body in attempts:
        response = _send(context, method, path, session=context.user_session, json=body)
        assert response.status_code == HTTPStatus.FORBIDDEN, (path, response.text)
        assert response.json()["error"] == "forbidden", response.text
    # Nothing changed: the operator still signs in with the old password, and eve does not exist.
    assert _sign_in(context, *OPERATOR).status_code == HTTPStatus.CREATED
    users = _send(context, "GET", "/api/v1/users", session=_operator(context)).json()["users"]
    assert [u["username"] for u in users] == ["ada", "bob"], users


@then("bob's token cannot list users either")
def step_token_refused(context: Context) -> None:
    response = _send(context, "GET", "/api/v1/users", token=context.user_token)
    # Managing users takes a session: a token is not one (401), whoever it belongs to.
    assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text
