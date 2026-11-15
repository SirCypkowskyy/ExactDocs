"""Steps for library roles: one client, and every request carries exactly one person's credentials.

The operator (the demo admin the other features use) creates the users and shares the library;
a user's session or API token is then the only credential of that user's requests, the jar being
emptied after each answer (as in ``users_steps``).
"""

import json
import sqlite3
from contextlib import closing
from http import HTTPStatus
from typing import Any

import httpx
from behave import given, then
from behave.runner import Context

from exactdocs.bootstrap.constants import DATABASE_MEMBER
from exactdocs.identity.constants import SESSION_COOKIE
from steps.http_steps import DEMO_COOKIE

PHRASE = "a long enough passphrase"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def _send(
    context: Context,
    method: str,
    path: str,
    *,
    session: str | None = None,
    token: str | None = None,
    **options: Any,
) -> httpx.Response:
    request = context.client.build_request(method, path, **options)
    request.headers.pop("cookie", None)
    if session:
        request.headers["cookie"] = f"{SESSION_COOKIE}={session}"
    if token:
        request.headers["authorization"] = f"Bearer {token}"
    response = context.client.send(request)
    context.client.cookies.clear()
    return response


def _library_path(library: str) -> str:
    return f"/api/v1/libraries{library}"


def _create_user(context: Context, username: str) -> None:
    created = _send(
        context,
        "POST",
        "/api/v1/users",
        session=DEMO_COOKIE,
        json={"username": username, "password": PHRASE},
    )
    assert created.status_code == HTTPStatus.CREATED, created.text
    signed_in = _send(
        context, "POST", "/api/v1/session", json={"username": username, "password": PHRASE}
    )
    assert signed_in.status_code == HTTPStatus.CREATED, signed_in.text
    session = signed_in.cookies[SESSION_COOKIE]
    made = _send(context, "POST", "/api/v1/tokens", session=session, json={"name": "agent"})
    assert made.status_code == HTTPStatus.CREATED, made.text
    context.people = getattr(context, "people", {})
    context.people[username] = {
        "id": created.json()["id"],
        "session": session,
        "token": made.json()["token"],
    }


def _person(context: Context, username: str) -> dict[str, str]:
    if username not in getattr(context, "people", {}):
        _create_user(context, username)
    return context.people[username]


def _grant(context: Context, library: str, kind: str, subject: str, role: str) -> None:
    granted = _send(
        context,
        "PUT",
        f"{_library_path(library)}/grants",
        session=DEMO_COOKIE,
        json={"kind": kind, "subject": subject, "role": role},
    )
    assert granted.status_code == HTTPStatus.OK, granted.text


def _mcp(context: Context, username: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    response = _send(
        context,
        "POST",
        "/mcp",
        token=_person(context, username)["token"],
        json=body,
        headers=MCP_HEADERS,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    payload = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        payload = next(
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        )
    return json.loads(payload)["result"]


@given('"{username}" is a viewer of "{library}"')
def step_viewer(context: Context, username: str, library: str) -> None:
    _person(context, username)
    _grant(context, library, "user", username, "viewer")


@given('"{username}" has no role on "{library}"')
def step_no_role(context: Context, username: str, library: str) -> None:
    del library
    _person(context, username)


@given('"{username}" is in the group "{group}" that is a contributor of "{library}"')
def step_group(context: Context, username: str, group: str, library: str) -> None:
    person = _person(context, username)
    # Groups come from an identity provider; here the stored membership is written directly.
    with closing(sqlite3.connect(context.settings.data_dir / DATABASE_MEMBER)) as database:
        database.execute(
            "INSERT INTO identity_account_groups (account_id, name) VALUES (?, ?)",
            (person["id"], group),
        )
        database.commit()
    _grant(context, library, "group", group, "contributor")


@then('"{username}" can search and read it in the UI and over MCP')
def step_can_read(context: Context, username: str) -> None:
    person = _person(context, username)
    library = "/fixture/docs-repo"
    base = _library_path(library)
    for path, params in [
        (base, {}),
        (f"{base}/search", {"q": "retry_policy"}),
        (f"{base}/articles", {}),
    ]:
        answer = _send(context, "GET", path, session=person["session"], params=params)
        assert answer.status_code == HTTPStatus.OK, (path, answer.text)
    assert _send(
        context, "GET", f"{base}/search", session=person["session"], params={"q": "retry_policy"}
    ).json()["results"]
    first = _send(context, "GET", f"{base}/articles", session=person["session"]).json()
    article = first["articles"][0]["path"]
    read = _send(
        context, "GET", f"{base}/article", session=person["session"], params={"path": article}
    )
    assert read.status_code == HTTPStatus.OK, read.text
    found = _mcp(context, username, "search_docs", {"library": library, "query": "retry_policy"})
    assert not found.get("isError"), found
    shown = _mcp(context, username, "read_article", {"library": library, "path": article})
    assert not shown.get("isError"), shown


@then('"{username}" is refused when searching and reading it in the UI and over MCP')
def step_refused_reading(context: Context, username: str) -> None:
    person = _person(context, username)
    base = _library_path("/fixture/docs-repo")
    for path, params in [
        (base, {}),
        (f"{base}/search", {"q": "retry_policy"}),
        (f"{base}/articles", {}),
    ]:
        answer = _send(context, "GET", path, session=person["session"], params=params)
        assert (answer.status_code, answer.json()["error"]) == (403, "forbidden"), answer.text
    for tool, arguments in [
        ("search_docs", {"library": "/fixture/docs-repo", "query": "retry_policy"}),
        ("list_articles", {"library": "/fixture/docs-repo"}),
    ]:
        refused = _mcp(context, username, tool, arguments)
        assert refused["isError"], refused
        assert "forbidden" in json.dumps(refused), refused


@then("changing its paths is refused")
def step_cannot_edit(context: Context) -> None:
    person = _person(context, "bob")
    base = _library_path("/fixture/docs-repo")
    changed = _send(
        context,
        "PUT",
        f"{base}/settings",
        session=person["session"],
        json={"include_paths": ["docs/guide/"]},
    )
    assert (changed.status_code, changed.json()["error"]) == (403, "forbidden"), changed.text
    stored = _send(context, "GET", base, session=DEMO_COOKIE).json()
    assert stored["settings"]["include_paths"] != ["docs/guide/"], stored["settings"]


@then('"{username}" may tag an article of it but not change its paths')
def step_contributor(context: Context, username: str) -> None:
    person = _person(context, username)
    base = _library_path("/fixture/docs-repo")
    path = _send(context, "GET", f"{base}/articles", session=DEMO_COOKIE).json()["articles"][0][
        "path"
    ]
    tagged = _send(
        context,
        "PUT",
        f"{base}/tags",
        session=person["session"],
        params={"path": path},
        json={"tags": ["reviewed"]},
    )
    assert tagged.status_code == HTTPStatus.OK, tagged.text
    changed = _send(
        context, "PUT", f"{base}/settings", session=person["session"], json={"include_paths": []}
    )
    assert (changed.status_code, changed.json()["error"]) == (403, "forbidden"), changed.text
