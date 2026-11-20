"""Steps for Cloudflare Access as the identity: a fake Access team in the process.

The team is ``fake_cf_access.FakeAccess``: it signs application tokens with a local RSA key and
serves its certs to the server's verifier through an in-process transport. The instance (with the
demo catalog and its admin session) is built lazily, so the steps can still change the Access
settings before the first request. Every request carries exactly the credentials a step names:
the client's cookie jar is emptied before and after it.
"""

import asyncio
import json
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx2
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.identity.constants import SESSION_COOKIE
from steps.http_steps import DEMO_COOKIE, store_demo_catalog

fake_cf_access = import_module("fake_cf_access")  # test support on sys.path (environment.py)

ASSERTION_HEADER = "cf-access-jwt-assertion"
ACCESS_COOKIE = "CF_Authorization"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
PHRASE = "a long enough passphrase"
UNKNOWN_BEARER = "exd_no-such-api-token"


@given('the server is configured with Cloudflare Access team domain "{team}" and audience "{aud}"')
def step_configured(context: Context, team: str, aud: str) -> None:
    context.access = fake_cf_access.FakeAccess(team_domain=team, audience=aud)
    context.access_config = {"team_domain": team, "audience": [aud]}


@given("no Cloudflare Access settings")
def step_not_configured(context: Context) -> None:
    context.access_config = None


def _client(context: Context) -> TestClient:
    """Build and start the instance on first use, with the demo catalog and its admin."""
    if getattr(context, "access_client", None) is None:
        stack = ExitStack()
        context.add_cleanup(stack.close)
        data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
        auth = {} if context.access_config is None else {"cloudflare_access": context.access_config}
        settings = Settings(data_dir=data_dir, auth=auth)
        context.settings = settings
        asyncio.run(store_demo_catalog(settings))
        access = getattr(context, "access", None) or fake_cf_access.FakeAccess()
        context.access = access
        container = Container.build(settings, sign_in=SignInStandIns(transport=access.transport()))
        client = TestClient(create_app(container), base_url="http://localhost")
        context.access_client = stack.enter_context(client)
        for username in getattr(context, "access_accounts", []):
            _create_user(context, username)
        for username, library in getattr(context, "access_grants", []):
            _grant_viewer(context, username, library)
    return context.access_client


def _send(
    context: Context,
    method: str,
    path: str,
    *,
    session: str | None = None,
    assertion: str | None = None,
    cookie_assertion: str | None = None,
    token: str | None = None,
    **options: Any,
) -> httpx2.Response:
    client = _client(context)
    client.cookies.clear()
    request = client.build_request(method, path, **options)
    request.headers.pop("cookie", None)
    cookies = []
    if session:
        cookies.append(f"{SESSION_COOKIE}={session}")
    if cookie_assertion:
        cookies.append(f"{ACCESS_COOKIE}={cookie_assertion}")
    if cookies:
        request.headers["cookie"] = "; ".join(cookies)
    if assertion:
        request.headers[ASSERTION_HEADER] = assertion
    if token:
        request.headers["authorization"] = f"Bearer {token}"
    response = client.send(request)
    client.cookies.clear()
    return response


def _create_user(context: Context, username: str) -> None:
    created = _send(
        context,
        "POST",
        "/api/v1/users",
        session=DEMO_COOKIE,
        json={"username": username, "password": PHRASE},
    )
    assert created.status_code == HTTPStatus.CREATED, created.text


def _grant_viewer(context: Context, username: str, library: str) -> None:
    granted = _send(
        context,
        "PUT",
        f"/api/v1/libraries{library}/grants",
        session=DEMO_COOKIE,
        json={"kind": "user", "subject": username, "role": "viewer"},
    )
    assert granted.status_code == HTTPStatus.OK, granted.text


def _session(context: Context, **credentials: str) -> dict[str, Any]:
    response = _send(context, "GET", "/api/v1/session", **credentials)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _mcp(context: Context, **credentials: str) -> httpx2.Response:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_libraries", "arguments": {}},
    }
    return _send(context, "POST", "/mcp", json=body, headers=MCP_HEADERS, **credentials)


def _mcp_result(response: httpx2.Response) -> dict[str, Any]:
    payload = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        payload = next(
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        )
    return json.loads(payload)["result"]


# --------------------------------------------------------------------------- givens


@given('a valid Access JWT for "{email}" signed by the team\'s key')
def step_person_token(context: Context, email: str) -> None:
    context.email = email
    context.assertion = context.access.person(email)


@given('"{email}" is listed in admin_emails')
def step_admin_email(context: Context, email: str) -> None:
    context.access_config["admin_emails"] = [email]


@given("auto_create_users is off")
def step_no_auto_create(context: Context) -> None:
    context.access_config["auto_create_users"] = False


@given("she has visited once")
def step_visited(context: Context) -> None:
    state = _session(context, assertion=context.assertion)
    assert state["state"] == "signed_in", state
    context.account = state["account"]


@given("an operator disabled her account")
def step_disable(context: Context) -> None:
    disabled = _send(
        context, "POST", f"/api/v1/users/{context.account['id']}/disable", session=DEMO_COOKIE
    )
    assert disabled.status_code == HTTPStatus.OK, disabled.text


@given('service token client ID "{client_id}" is mapped to the account "{username}"')
def step_service_token(context: Context, client_id: str, username: str) -> None:
    context.access_config["service_tokens"] = {client_id: username}
    context.access_accounts = [*getattr(context, "access_accounts", []), username]


@given('"{username}" may view only "{library}"')
def step_viewer_only(context: Context, username: str, library: str) -> None:
    context.access_grants = [*getattr(context, "access_grants", []), (username, library)]
    context.viewer_of = library


PROBLEMS = {
    "is signed by an unknown key": lambda access: fake_cf_access.signed_by_stranger(
        access, {"email": "mallory@example.com", "sub": "sub-mallory", "type": "app"}
    ),
    "has another audience": lambda access: access.person("mallory@example.com", aud=["other"]),
    "has another issuer": lambda access: access.person(
        "mallory@example.com", iss="https://other.cloudflareaccess.com"
    ),
    "has expired": lambda access: access.person(
        "mallory@example.com", exp=int(access.now().timestamp()) - 3600
    ),
    "is not valid yet": lambda access: access.person(
        "mallory@example.com", nbf=int(access.now().timestamp()) + 3600
    ),
    "belongs to an unmapped service token": lambda access: access.service("unknown.access"),
}


@given("an Access JWT that {problem}")
def step_bad_token(context: Context, problem: str) -> None:
    context.assertion = PROBLEMS[problem](context.access)


# --------------------------------------------------------------------------- whens


@when("the browser asks for its session with it in the assertion header")
def step_session_header(context: Context) -> None:
    context.state = _session(context, assertion=context.assertion)


@when("the browser asks for its session with it in the Access cookie")
def step_session_cookie(context: Context) -> None:
    context.state = _session(context, cookie_assertion=context.assertion)


@when("she visits again with a new Access JWT")
@when("she arrives with a valid Access JWT")
def step_visit_again(context: Context) -> None:
    context.state = _session(context, assertion=context.access.person(context.email))


@when(
    'an MCP client calls /mcp with a valid Access JWT whose common_name is "{client_id}" '
    "and no Authorization header"
)
def step_mcp_service(context: Context, client_id: str) -> None:
    context.mcp = _mcp(context, assertion=context.access.service(client_id))


@when(
    'an MCP client calls /mcp with a valid Access JWT whose common_name is "{client_id}" '
    "and a wrong API token"
)
def step_mcp_service_wrong_token(context: Context, client_id: str) -> None:
    context.mcp = _mcp(context, assertion=context.access.service(client_id), token=UNKNOWN_BEARER)


@when("it is sent to the session and to /mcp")
def step_send_both(context: Context) -> None:
    context.state = _session(context, assertion=context.assertion)
    context.mcp = _mcp(context, assertion=context.assertion)


@when("a request carries any Cf-Access-Jwt-Assertion header")
def step_any_header(context: Context) -> None:
    access = fake_cf_access.FakeAccess()
    context.assertion = access.person("alice@example.com")
    context.state = _session(context, assertion=context.assertion)
    context.cookie_state = _session(context, cookie_assertion=context.assertion)
    context.mcp = _mcp(context, assertion=context.assertion)


# --------------------------------------------------------------------------- thens


@then('the state is "signed_in" as an account linked to "{email}"')
def step_signed_in(context: Context, email: str) -> None:
    assert context.state["state"] == "signed_in", context.state
    assert context.state["account"]["username"] == email, context.state


@then("no password was asked for")
def step_no_password(context: Context) -> None:
    users = _send(context, "GET", "/api/v1/users", session=DEMO_COOKIE).json()["users"]
    account = next(u for u in users if u["id"] == context.state["account"]["id"])
    assert account["provider"] == "cloudflare-access", account


@then("the session is reported as coming from Cloudflare Access, with its sign-out address")
def step_source(context: Context) -> None:
    assert context.state["source"] == "cloudflare_access", context.state
    team = context.access.team_domain
    assert context.state["sign_out_url"] == f"{team}/cdn-cgi/access/logout", context.state


@then("she reaches the account of her first visit")
def step_same_account(context: Context) -> None:
    assert context.state["account"]["id"] == context.account["id"], context.state


@then('her account has the role "{role}"')
def step_role(context: Context, role: str) -> None:
    assert context.state["state"] == "signed_in", context.state
    assert context.state["account"]["role"] == role, context.state


@then('the session state is "{state}"')
def step_session_state(context: Context, state: str) -> None:
    assert context.state["state"] == state, context.state


@then('the call runs as "{username}" with that account\'s library permissions')
def step_runs_as(context: Context, username: str) -> None:
    del username
    assert context.mcp.status_code == HTTPStatus.OK, context.mcp.text
    result = _mcp_result(context.mcp)
    assert not result.get("isError"), result
    listed = {library["id"] for library in result["structuredContent"]["libraries"]}
    assert listed == {context.viewer_of}, listed


@then("/mcp answers 401")
def step_mcp_401(context: Context) -> None:
    assert context.mcp.status_code == HTTPStatus.UNAUTHORIZED, context.mcp.text


@then('the session state is "signed_out" and /mcp answers 401')
def step_untrusted(context: Context) -> None:
    assert context.state["state"] == "signed_out", context.state
    assert context.mcp.status_code == HTTPStatus.UNAUTHORIZED, context.mcp.text


@then("it is ignored and sign-in works as before")
def step_ignored(context: Context) -> None:
    for state in (context.state, context.cookie_state):
        assert state["state"] == "signed_out", state
        assert state.get("source") is None, state
    assert context.mcp.status_code == HTTPStatus.UNAUTHORIZED, context.mcp.text
    signed_in = _send(
        context,
        "POST",
        "/api/v1/users",
        session=DEMO_COOKIE,
        json={"username": "bob", "password": PHRASE},
    )
    assert signed_in.status_code == HTTPStatus.CREATED, signed_in.text
    session = _send(
        context, "POST", "/api/v1/session", json={"username": "bob", "password": PHRASE}
    )
    assert session.status_code == HTTPStatus.CREATED, session.text
    assert session.json()["state"] == "signed_in", session.text
