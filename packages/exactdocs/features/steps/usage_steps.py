"""Steps for usage counts and leaderboards (#510), over REST and MCP as clients use them.

Each person's requests carry only their own session or API token (``library_roles_steps``); the
operator is the demo admin. Counts of past weeks cannot be made by requests, so they are written
to the database directly, as an earlier week of use would have left them.
"""

import asyncio
import json
import re
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.constants import DATABASE_MEMBER
from exactdocs.bootstrap.settings import Settings, UsageSettings
from steps.http_steps import DEMO_COOKIE, running_with
from steps.library_roles_steps import get_person, send_as
from steps.search_steps import import_versions

ARTICLES = ["docs/guide/install.md", "docs/guide/auth.md"]
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
COLUMNS = {"day", "account_id", "token_id", "library", "operation", "requests"}


def _start(context: Context, libraries: list[str], *, people_board: bool = False) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)  # runs the app's shutdown after the scenario
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    settings = Settings(data_dir=data_dir, usage=UsageSettings(people_leaderboard=people_board))
    running_with(context, stack, settings)
    for library in libraries:
        title = library.rsplit("/", 1)[-1].replace("-", " ").title()
        asyncio.run(import_versions(context, ["v1.4.0"], library, title))


def _ok(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _as(context: Context, username: str, route: str, **params: Any) -> httpx.Response:
    if username == "the operator":
        return send_as(context, "GET", f"/api/v1{route}", session=DEMO_COOKIE, params=params)
    session = get_person(context, username)["session"]
    return send_as(context, "GET", f"/api/v1{route}", session=session, params=params)


def _mcp(context: Context, username: str, tool: str, arguments: dict[str, Any]) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    token = get_person(context, username)["token"]
    response = send_as(context, "POST", "/mcp", token=token, json=body, headers=MCP_HEADERS)
    assert response.status_code == HTTPStatus.OK, response.text
    payload = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        payload = next(
            line.removeprefix("data:").strip()
            for line in payload.splitlines()
            if line.startswith("data:")
        )
    result = json.loads(payload)["result"]
    assert not result.get("isError"), result


def _read(context: Context, username: str, library: str, times: int) -> None:
    for n in range(times):
        path = ARTICLES[n % len(ARTICLES)]
        _ok(_as(context, username, f"/libraries{library}/article", path=path))


def _rows(context: Context) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(context.settings.data_dir / DATABASE_MEMBER)) as database:
        database.row_factory = sqlite3.Row
        return [dict(row) for row in database.execute("SELECT * FROM usage_daily_counts")]


def _people_board(context: Context, username: str, **params: Any) -> httpx.Response:
    return _as(context, username, "/stats/leaderboard", subject="people", **params)


@given("ExactDocs is running with the fixture docs repository imported as {libraries}")
def step_running(context: Context, libraries: str) -> None:
    _start(context, re.findall(r'"([^"]+)"', libraries))


@given(
    "ExactDocs is running with the people leaderboard turned on and the fixture docs repository"
    ' imported as "{library}"'
)
def step_running_people_board(context: Context, library: str) -> None:
    _start(context, [library], people_board=True)


@when('an agent reads two articles of "{library}" over MCP with alice\'s token')
def step_mcp_reads(context: Context, library: str) -> None:
    for path in ARTICLES:
        _mcp(context, "alice", "read_article", {"library": library, "path": path})
    context.library = library


@when('the agent searches "{library}" for "{query}" over MCP with alice\'s token')
def step_mcp_search(context: Context, library: str, query: str) -> None:
    _mcp(context, "alice", "search_docs", {"library": library, "query": query})
    context.query = query


@then('the usage counts for today show {reads:d} reads for alice, that token and "{library}"')
def step_counts_today(context: Context, reads: int, library: str) -> None:
    alice = get_person(context, "alice")
    tokens = _ok(send_as(context, "GET", "/api/v1/tokens", session=alice["session"]))["tokens"]
    (token_id,) = [token["id"] for token in tokens if token["name"] == "agent"]
    today = datetime.now(UTC).date().isoformat()
    by_token = _ok(_as(context, "alice", "/account/usage", by="token", period="day", periods=1))
    by_library = _ok(_as(context, "alice", "/account/usage", by="library", period="day"))

    assert by_token["series"] == [
        {"start": today, "end": today, "reads": reads, "searches": 1, "answers": 0}
    ], by_token
    assert [(g["token_id"], g["reads"]) for g in by_token["groups"]] == [(token_id, reads)]
    assert [(g["library"], g["reads"]) for g in by_library["groups"]] == [(library, reads)]
    stored = {
        (r["day"], r["account_id"], r["token_id"], r["library"], r["operation"]): r["requests"]
        for r in _rows(context)
    }
    assert stored == {
        (today, alice["id"], token_id, library, "read"): reads,
        (today, alice["id"], token_id, library, "search"): 1,
    }, stored


@then("no query text or content is stored, only counts")
def step_only_counts(context: Context) -> None:
    rows = _rows(context)
    assert rows
    assert all(set(row) == COLUMNS for row in rows), rows
    stored = json.dumps(rows)
    for text in [context.query, "retry", *ARTICLES, "guide", "install", "auth"]:
        assert text not in stored, (text, stored)


@given('last week "{first}" was read {first_reads:d} times and "{second}" {second_reads:d} times')
def step_last_week(
    context: Context, first: str, first_reads: int, second: str, second_reads: int
) -> None:
    last_week = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    with closing(sqlite3.connect(context.settings.data_dir / DATABASE_MEMBER)) as database:
        for library, reads in [(first, first_reads), (second, second_reads)]:
            database.execute(
                "INSERT INTO usage_daily_counts"
                " (day, account_id, token_id, library, operation, requests)"
                " VALUES (?, '', '', ?, 'read', ?)",
                (last_week, library, reads),
            )
        database.commit()


@when('alice reads "{first}" {first_reads:d} times and "{second}" once this week')
def step_reads_this_week(context: Context, first: str, first_reads: int, second: str) -> None:
    _read(context, "alice", first, first_reads)
    _read(context, "alice", second, 1)


@when("an operator asks for the most-read libraries this week")
def step_operator_board(context: Context) -> None:
    context.board = _ok(
        _as(context, "the operator", "/stats/leaderboard", subject="libraries", period="week")
    )


@then(
    'they get "{first}" ranked 1st, 2nd the week before, and "{second}" ranked 2nd, 1st the'
    " week before"
)
def step_ranked(context: Context, first: str, second: str) -> None:
    board = context.board
    assert (board["metric"], board["period"]) == ("reads", "week"), board
    assert [
        (e["library"], e["rank"], e["previous_rank"], e["value"]) for e in board["entries"]
    ] == [
        (first, 1, 2, 3),
        (second, 2, 1, 1),
    ], board


@given("alice opted in to the people leaderboard")
def step_alice_opts_in(context: Context) -> None:
    session = get_person(context, "alice")["session"]
    path = "/api/v1/account/preferences"
    chosen = {**_ok(send_as(context, "GET", path, session=session))["preferences"]}
    chosen["leaderboard_opt_in"] = True
    _ok(send_as(context, "PUT", path, session=session, json=chosen))


@given("bob did not opt in")
def step_bob_did_not(context: Context) -> None:
    session = get_person(context, "bob")["session"]
    saved = _ok(send_as(context, "GET", "/api/v1/account/preferences", session=session))
    assert saved["preferences"]["leaderboard_opt_in"] is False, saved


@when('alice reads "{library}" once and bob reads it twice')
def step_alice_and_bob_read(context: Context, library: str) -> None:
    context.reads = {"alice": 1, "bob": 2}
    for username, times in context.reads.items():
        _read(context, username, library, times)


@when('alice reads "{library}" once')
def step_alice_reads(context: Context, library: str) -> None:
    context.reads = {"alice": 1}
    _read(context, "alice", library, 1)


@then("bob appears on no people leaderboard")
def step_bob_on_no_board(context: Context) -> None:
    bob = get_person(context, "bob")
    for viewer in ("alice", "bob", "the operator"):
        for period in ("day", "week", "month", "year"):
            for metric in ("reads", "searches", "answers"):
                board = _ok(_people_board(context, viewer, period=period, metric=metric))
                assert bob["id"] not in json.dumps(board), board
                assert all(e["username"] == "alice" for e in board["entries"]), board
    reads = _ok(_people_board(context, "bob", period="day"))
    assert [(e["username"], e["value"], e["you"]) for e in reads["entries"]] == [
        ("alice", 1, False)
    ], reads


@then("nobody sees his counts except operators in aggregate")
def step_bob_in_aggregate(context: Context) -> None:
    bob = get_person(context, "bob")
    for viewer in ("alice", "bob"):
        refused = _as(context, viewer, "/stats/usage", by="account")
        assert refused.status_code == HTTPStatus.FORBIDDEN, refused.text
    alices = _ok(_as(context, "alice", "/account/usage"))
    assert alices["total"]["reads"] == 1, alices
    for by in ("account", "token"):
        usage = _ok(_as(context, "the operator", "/stats/usage", by=by))
        assert usage["total"]["reads"] == sum(context.reads.values()), usage
        assert bob["id"] not in json.dumps(usage), usage
        groups = [(g["username"], g["reads"], g["others"]) for g in usage["groups"]]
        assert groups == [("alice", 1, False), (None, context.reads["bob"], True)], groups


@then("the people leaderboard is refused to alice and to the operator")
def step_people_board_off(context: Context) -> None:
    for viewer in ("alice", "the operator"):
        refused = _people_board(context, viewer)
        assert refused.status_code == HTTPStatus.FORBIDDEN, refused.text
        assert refused.json()["error"] == "people_leaderboard_off", refused.text
    settings = _ok(_as(context, "alice", "/stats/settings"))
    assert settings == {"people_leaderboard": False, "retention_months": 13}, settings
    usage = _ok(_as(context, "the operator", "/stats/usage", by="account"))
    assert all(g["others"] and g["username"] is None for g in usage["groups"]), usage


@then('the libraries leaderboard ranks "{library}" for alice')
def step_libraries_board_open(context: Context, library: str) -> None:
    board = _ok(_as(context, "alice", "/stats/leaderboard", period="day"))
    assert [(e["library"], e["rank"], e["value"]) for e in board["entries"]] == [(library, 1, 1)], (
        board
    )
