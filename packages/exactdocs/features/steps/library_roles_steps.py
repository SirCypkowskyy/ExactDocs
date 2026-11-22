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
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.constants import DATABASE_MEMBER
from exactdocs.identity.constants import SESSION_COOKIE
from steps.http_steps import DEMO_COOKIE

PHRASE = "a long enough passphrase"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def send_as(
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
    created = send_as(
        context,
        "POST",
        "/api/v1/users",
        session=DEMO_COOKIE,
        json={"username": username, "password": PHRASE},
    )
    assert created.status_code == HTTPStatus.CREATED, created.text
    signed_in = send_as(
        context, "POST", "/api/v1/session", json={"username": username, "password": PHRASE}
    )
    assert signed_in.status_code == HTTPStatus.CREATED, signed_in.text
    session = signed_in.cookies[SESSION_COOKIE]
    made = send_as(context, "POST", "/api/v1/tokens", session=session, json={"name": "agent"})
    assert made.status_code == HTTPStatus.CREATED, made.text
    context.people = getattr(context, "people", {})
    context.people[username] = {
        "id": created.json()["id"],
        "session": session,
        "token": made.json()["token"],
    }


def get_person(context: Context, username: str) -> dict[str, str]:
    if username not in getattr(context, "people", {}):
        _create_user(context, username)
    return context.people[username]


def _grant(context: Context, library: str, kind: str, subject: str, role: str) -> None:
    granted = send_as(
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
    response = send_as(
        context,
        "POST",
        "/mcp",
        token=get_person(context, username)["token"],
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
    get_person(context, username)
    _grant(context, library, "user", username, "viewer")


@given('"{username}" has no role on "{library}"')
def step_no_role(context: Context, username: str, library: str) -> None:
    del library
    get_person(context, username)


@given('"{username}" is in the group "{group}" that is a contributor of "{library}"')
def step_group(context: Context, username: str, group: str, library: str) -> None:
    person = get_person(context, username)
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
    person = get_person(context, username)
    library = "/fixture/docs-repo"
    base = _library_path(library)
    for path, params in [
        (base, {}),
        (f"{base}/search", {"q": "retry_policy"}),
        (f"{base}/articles", {}),
    ]:
        answer = send_as(context, "GET", path, session=person["session"], params=params)
        assert answer.status_code == HTTPStatus.OK, (path, answer.text)
    assert send_as(
        context, "GET", f"{base}/search", session=person["session"], params={"q": "retry_policy"}
    ).json()["results"]
    first = send_as(context, "GET", f"{base}/articles", session=person["session"]).json()
    article = first["articles"][0]["path"]
    read = send_as(
        context, "GET", f"{base}/article", session=person["session"], params={"path": article}
    )
    assert read.status_code == HTTPStatus.OK, read.text
    found = _mcp(context, username, "search_docs", {"library": library, "query": "retry_policy"})
    assert not found.get("isError"), found
    shown = _mcp(context, username, "read_article", {"library": library, "path": article})
    assert not shown.get("isError"), shown
    for tool, arguments in [  # the MCP App tools: the same reads, as UI
        ("view_search", {"library": library, "query": "retry_policy"}),
        ("view_article", {"library": library, "path": article}),
    ]:
        viewed = _mcp(context, username, tool, arguments)
        assert not viewed.get("isError"), viewed


@then('"{username}" is refused when searching and reading it in the UI and over MCP')
def step_refused_reading(context: Context, username: str) -> None:
    person = get_person(context, username)
    base = _library_path("/fixture/docs-repo")
    for path, params in [
        (base, {}),
        (f"{base}/search", {"q": "retry_policy"}),
        (f"{base}/articles", {}),
    ]:
        answer = send_as(context, "GET", path, session=person["session"], params=params)
        assert (answer.status_code, answer.json()["error"]) == (404, "not_found"), answer.text
    for tool, arguments in [
        ("search_docs", {"library": "/fixture/docs-repo", "query": "retry_policy"}),
        ("list_articles", {"library": "/fixture/docs-repo"}),
        ("view_search", {"library": "/fixture/docs-repo", "query": "retry_policy"}),
        ("view_article", {"library": "/fixture/docs-repo", "path": "docs/guide/install.md"}),
    ]:
        refused = _mcp(context, username, tool, arguments)
        assert refused["isError"], refused
        assert "not_found" in json.dumps(refused), refused


@then("changing its paths is refused")
def step_cannot_edit(context: Context) -> None:
    person = get_person(context, "bob")
    base = _library_path("/fixture/docs-repo")
    changed = send_as(
        context,
        "PUT",
        f"{base}/settings",
        session=person["session"],
        json={"include_paths": ["docs/guide/"]},
    )
    assert (changed.status_code, changed.json()["error"]) == (403, "forbidden"), changed.text
    stored = send_as(context, "GET", base, session=DEMO_COOKIE).json()
    assert stored["settings"]["include_paths"] != ["docs/guide/"], stored["settings"]


@then('"{username}" may tag an article of it but not change its paths')
def step_contributor(context: Context, username: str) -> None:
    person = get_person(context, username)
    base = _library_path("/fixture/docs-repo")
    path = send_as(context, "GET", f"{base}/articles", session=DEMO_COOKIE).json()["articles"][0][
        "path"
    ]
    tagged = send_as(
        context,
        "PUT",
        f"{base}/tags",
        session=person["session"],
        params={"path": path},
        json={"tags": ["reviewed"]},
    )
    assert tagged.status_code == HTTPStatus.OK, tagged.text
    changed = send_as(
        context, "PUT", f"{base}/settings", session=person["session"], json={"include_paths": []}
    )
    assert (changed.status_code, changed.json()["error"]) == (403, "forbidden"), changed.text


@given('"{username}" has an agent token limited to "{library}"')
def step_narrow_agent(context: Context, username: str, library: str) -> None:
    person = get_person(context, username)
    response = send_as(
        context,
        "POST",
        "/api/v1/tokens",
        session=person["session"],
        json={"name": "limited agent", "library_ids": [library]},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    person["token"] = response.json()["token"]


@then('"{username}" cannot discover "{library}"')
def step_cannot_discover(context: Context, username: str, library: str) -> None:
    token = get_person(context, username)["token"]
    response = send_as(context, "GET", "/api/v1/libraries", token=token)
    assert response.status_code == HTTPStatus.OK, response.text
    assert library not in response.text
    listing = _mcp(context, username, "list_libraries", {})
    assert library not in str(listing)
    resolved = _mcp(
        context, username, "resolve-library-id", {"libraryName": "docs-repo", "query": "retry"}
    )
    assert library not in str(resolved)
    for tool, arguments in [  # the MCP App tools are scoped like the rest
        ("view_search", {"library": library, "query": "retry_policy"}),
        ("view_article", {"library": library, "path": "docs/guide/install.md"}),
    ]:
        refused = _mcp(context, username, tool, arguments)
        assert refused["isError"], refused
        assert "not_found" in json.dumps(refused), refused


@then('"{username}" sees the same query error for a hidden and a missing library')
def step_hidden_query(context: Context, username: str) -> None:
    hidden = "/fixture/docs-repo"
    missing = "/missing/docs-repo"
    answers = [
        _mcp(context, username, "query-docs", {"libraryId": library, "query": "retry"})
        for library in (hidden, missing)
    ]
    assert all(answer.get("isError") and "not_found" in str(answer) for answer in answers), answers
    assert str(answers[0]).replace(hidden, missing) == str(answers[1]), answers


@given('"{username}" is a contributor of "{library}"')
def step_contributor_of(context: Context, username: str, library: str) -> None:
    get_person(context, username)
    _grant(context, library, "user", username, "contributor")


@when(
    'the operator lists the viewers and contributors of "{library}" by name from Z to A, '
    "{limit:d} at a time"
)
def step_list_grants(context: Context, library: str, limit: int) -> None:
    context.grant_pages = []
    params: dict[str, Any] = {"role": ["viewer", "contributor"], "sort": "-subject", "limit": limit}
    while True:
        response = send_as(
            context, "GET", f"{_library_path(library)}/grants", session=DEMO_COOKIE, params=params
        )
        assert response.status_code == HTTPStatus.OK, response.text
        context.grant_pages.append(response.json())
        if response.json()["next_cursor"] is None:
            break
        params["cursor"] = response.json()["next_cursor"]


@then('the grant pages show "{first}" then "{second}", each counting {total:d} grants')
def step_grant_pages(context: Context, first: str, second: str, total: int) -> None:
    shown = [[g["subject"] for g in page["grants"]] for page in context.grant_pages]
    assert shown == [[first], [second]], shown
    assert {page["total"] for page in context.grant_pages} == {total}


@then('"{username}" asking for the grants is refused before any page')
def step_grants_refused(context: Context, username: str) -> None:
    session = get_person(context, username)["session"]
    path = f"{_library_path('/fixture/docs-repo')}/grants"
    response = send_as(context, "GET", path, session=session, params={"limit": 1})
    assert response.status_code == HTTPStatus.FORBIDDEN, response.text
    assert "total" not in response.json(), response.text
