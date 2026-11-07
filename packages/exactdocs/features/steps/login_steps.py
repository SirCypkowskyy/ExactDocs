"""Steps for the admin's browser session, driven over HTTP like the web UI does."""

import io
import os
from http import HTTPStatus
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap import cli
from exactdocs.identity.constants import SESSION_COOKIE

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def _sign_in(context: Context, username: str, password: str) -> None:
    body = {"username": username, "password": password}
    context.response = context.client.post("/api/v1/session", json=body)


def _libraries_status(context: Context, token: str | None) -> int:
    """Ask for the libraries with exactly this cookie header (the client's jar is not used)."""
    headers = {"Cookie": f"{SESSION_COOKIE}={token}"} if token else {}
    return context.client.get("/api/v1/libraries", headers=headers).status_code


@given('the admin "{username}" was set up with the password "{password}"')
def step_set_up(context: Context, username: str, password: str) -> None:
    body = {"username": username, "password": password}
    response = context.client.post("/api/v1/setup", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text


@given("the admin is signed in to the UI")
def step_signed_in(context: Context) -> None:
    _sign_in(context, "ada", "correct horse battery staple")
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    context.session_token = context.client.cookies.get(SESSION_COOKIE)
    assert context.session_token


@when('the admin signs in with the password "{password}"')
def step_admin_signs_in(context: Context, password: str) -> None:
    _sign_in(context, "ada", password)
    context.session_token = context.client.cookies.get(SESSION_COOKIE)


@when('"{username}" signs in with the password "{password}"')
def step_user_signs_in(context: Context, username: str, password: str) -> None:
    _sign_in(context, username, password)


@when("the admin signs out")
def step_sign_out(context: Context) -> None:
    context.response = context.client.delete("/api/v1/session")
    assert context.response.status_code == HTTPStatus.NO_CONTENT, context.response.text


@then('the UI session is active for "{username}"')
def step_active(context: Context, username: str) -> None:
    state = context.client.get("/api/v1/session").json()
    assert state["state"] == "signed_in", state
    assert state["account"]["username"] == username, state


@then("the UI session is not active")
def step_not_active(context: Context) -> None:
    assert context.client.get("/api/v1/session").json() == {"state": "signed_out", "account": None}


@then("the session cookie is HttpOnly and SameSite=Lax")
def step_flags(context: Context) -> None:
    cookie = context.response.headers["set-cookie"].lower()
    assert "httponly" in cookie, cookie
    assert "samesite=lax" in cookie, cookie
    assert context.session_token not in context.response.text  # never in the body, script-readable


@then("no session cookie was set")
def step_no_cookie(context: Context) -> None:
    assert "set-cookie" not in context.response.headers


@then('the sign-in is refused with "{code}"')
def step_refused(context: Context, code: str) -> None:
    assert context.response.status_code == HTTPStatus.UNAUTHORIZED, context.response.text
    assert context.response.json()["error"] == code


@then("the libraries are reachable")
def step_reachable(context: Context) -> None:
    status = context.client.get("/api/v1/libraries").status_code
    assert status == HTTPStatus.OK, status


@then("the libraries are not reachable")
def step_not_reachable(context: Context) -> None:
    status = context.client.get("/api/v1/libraries").status_code
    assert status == HTTPStatus.UNAUTHORIZED, status


@then("the libraries are no longer reachable with that session")
def step_gone(context: Context) -> None:
    # Replay the old cookie by hand: the server must refuse it, not just the browser forget it.
    status = _libraries_status(context, context.session_token)
    assert status == HTTPStatus.UNAUTHORIZED, status


@when("the browser calls the MCP endpoint with the session cookie only")
def step_mcp(context: Context) -> None:
    cookie = {"Cookie": f"{SESSION_COOKIE}={context.session_token}"}
    with_cookie = context.client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **cookie})
    without = context.client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    context.mcp = (with_cookie, without)


@then("the MCP endpoint treats the call exactly like one without the cookie")
def step_mcp_same(context: Context) -> None:
    with_cookie, without = context.mcp
    assert with_cookie.status_code == without.status_code, (with_cookie, without)
    assert with_cookie.text == without.text
    assert SESSION_COOKIE not in with_cookie.text


@when('a page on "{origin}" signs the admin out')
def step_foreign_sign_out(context: Context, origin: str) -> None:
    context.response = context.client.delete("/api/v1/session", headers={"Origin": origin})


@when('a page on "{origin}" signs in with the password "{password}"')
def step_foreign_sign_in(context: Context, origin: str, password: str) -> None:
    body = {"username": "ada", "password": password}
    context.response = context.client.post("/api/v1/session", json=body, headers={"Origin": origin})


@then("the request is forbidden")
def step_forbidden(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.FORBIDDEN, context.response.text


@when(
    'the operator runs "exactdocs admin reset-password" with the username "{username}" '
    'and the password "{password}"'
)
def step_reset(context: Context, username: str, password: str) -> None:
    tokens = ["admin", "reset-password", "--username", username, "--password-stdin"]
    env = {"EXACTDOCS_DATA_DIR": str(context.settings.data_dir)}
    with patch.dict(os.environ, env), patch("sys.stdin", io.StringIO(password + "\n")):
        cli.app(tokens, exit_on_error=False, result_action="return_value")
