"""Steps for the access log: changes made over REST by one person each, read back over REST.

People and their credentials, and who is an admin or the creator of a library, come from
``library_roles_steps`` (as does the transfer itself); the operator is the demo admin.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any
from uuid import uuid7

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.constants import DATABASE_MEMBER
from steps.http_steps import DEMO_COOKIE
from steps.library_roles_steps import get_person, send_as

RECENT = timedelta(minutes=5)
DAY = timedelta(days=1)
COLUMNS = ("days ago", "actor", "change", "kind", "subject", "role")


def _library_path(library: str) -> str:
    return f"/api/v1/libraries{library}"


def _grant_as(context: Context, session: str, library: str, username: str, role: str) -> None:
    granted = send_as(
        context,
        "PUT",
        f"{_library_path(library)}/grants",
        session=session,
        json={"kind": "user", "subject": username, "role": role},
    )
    assert granted.status_code == HTTPStatus.OK, granted.text


def _log(context: Context, library: str, session: str) -> list[dict[str, object]]:
    response = send_as(context, "GET", f"{_library_path(library)}/access-log", session=session)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()["events"]


@when('"{actor}" grants "{username}" the {role} role on "{library}"')
def step_grants(context: Context, actor: str, username: str, role: str, library: str) -> None:
    get_person(context, username)
    _grant_as(context, get_person(context, actor)["session"], library, username, role)


@when('"{actor}" takes the role of "{username}" on "{library}" away')
def step_revokes(context: Context, actor: str, username: str, library: str) -> None:
    revoked = send_as(
        context,
        "DELETE",
        f"{_library_path(library)}/grants/user/{username}",
        session=get_person(context, actor)["session"],
    )
    assert revoked.status_code == HTTPStatus.OK, revoked.text


@then('the library\'s audit log shows actor "{actor}", the grant and the time')
def step_shows_grant(context: Context, actor: str) -> None:
    newest = _log(context, "/fixture/docs-repo", get_person(context, actor)["session"])[0]
    assert newest["actor"] == actor, newest
    assert (newest["change"], newest["kind"], newest["subject"], newest["role"]) == (
        "granted",
        "user",
        "bob",
        "viewer",
    ), newest
    at = datetime.fromisoformat(str(newest["at"]))
    assert abs(datetime.now(UTC) - at) < RECENT, newest


@then(
    'the library\'s audit log shows actor "{actor}", the ownership transfer to "{username}" '
    "and the time"
)
def step_shows_transfer(context: Context, actor: str, username: str) -> None:
    newest = _log(context, context.library, get_person(context, username)["session"])[0]
    assert (newest["actor"], newest["change"], newest["kind"], newest["subject"]) == (
        actor,
        "ownership_transferred",
        "user",
        username,
    ), newest
    assert newest["role"] == "creator", newest
    at = datetime.fromisoformat(str(newest["at"]))
    assert abs(datetime.now(UTC) - at) < RECENT, newest


@then('"{reader}" reads in the audit log of "{library}", newest first:')
def step_reads_log(context: Context, reader: str, library: str) -> None:
    events = _log(context, library, get_person(context, reader)["session"])
    shown = [
        [
            str(e["actor"]),
            str(e["change"]),
            str(e["subject"]),
            str(e["role"]),
            str(e["previous_role"] or ""),
        ]
        for e in events
    ]
    assert context.table is not None
    expected = [list(row.cells) for row in context.table]
    assert shown == expected, shown


@then('"{username}", a viewer of "{library}", asking for its audit log is refused')
def step_log_refused(context: Context, username: str, library: str) -> None:
    session = get_person(context, username)["session"]
    _grant_as(context, DEMO_COOKIE, library, username, "viewer")
    response = send_as(context, "GET", f"{_library_path(library)}/access-log", session=session)
    assert response.status_code == HTTPStatus.FORBIDDEN, response.text
    assert "events" not in response.json(), response.text


@when('the operator removes the library "{library}"')
def step_operator_removes(context: Context, library: str) -> None:
    removed = send_as(context, "DELETE", _library_path(library), session=DEMO_COOKIE)
    assert removed.status_code == HTTPStatus.OK, removed.text


@then('the operator\'s access log shows that "{actor}" deleted "{library}"')
def step_operator_log(context: Context, actor: str, library: str) -> None:
    gone = send_as(context, "GET", f"{_library_path(library)}/access-log", session=DEMO_COOKIE)
    assert gone.status_code == HTTPStatus.NOT_FOUND, gone.text
    response = send_as(
        context, "GET", "/api/v1/access-log", session=DEMO_COOKIE, params={"library": library}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    newest = response.json()["events"][0]
    assert (newest["actor"], newest["change"], newest["library"]) == (
        actor,
        "library_deleted",
        library,
    ), newest
    assert any(e["change"] == "granted" for e in response.json()["events"]), response.text


@given('these access changes to "{library}" were recorded:')
def step_recorded(context: Context, library: str) -> None:
    """Store the table's events as made that many days ago, in the table's order."""
    assert context.table is not None
    now = datetime.now(UTC)
    rows = []
    for row in context.table:
        subject = row["subject"]
        if row["kind"] == "user":
            subject = get_person(context, subject)["id"]
        at = (now - int(row["days ago"]) * DAY).isoformat(timespec="microseconds")
        actor = get_person(context, row["actor"])["id"]
        change, kind, role = row["change"], row["kind"], row["role"]
        rows.append((str(uuid7()), library.casefold(), at, actor, change, kind, subject, role))
    # As the log stores them (UTC ISO 8601, microseconds); the API has no way to backdate one.
    with closing(sqlite3.connect(context.settings.data_dir / DATABASE_MEMBER)) as database:
        database.executemany(
            "INSERT INTO identity_access_events"
            " (id, library, at, actor, change, kind, subject, role)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        database.commit()
    context.log_library = library


def _filtered(context: Context, path: str, session: str) -> dict[str, Any]:
    response = send_as(context, "GET", path, session=session, params=context.log_filters)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _shown(events: list[dict[str, Any]]) -> list[list[str]]:
    now = datetime.now(UTC)
    return [
        [
            str(round((now - datetime.fromisoformat(e["at"])) / DAY)),
            str(e["actor"]),
            str(e["change"]),
            str(e["kind"]),
            str(e["subject"]),
            str(e["role"]),
        ]
        for e in events
    ]


@when(
    'the operator filters the access log by actor "{actor}", subject "{subject}" and the last '
    "{days:d} days, oldest first"
)
def step_operator_filters(context: Context, actor: str, subject: str, days: int) -> None:
    since = datetime.now(UTC) - days * DAY
    context.log_filters = {
        "actor": actor,
        "subject": subject,
        "at_after": since.isoformat(),
        "at_before": datetime.now(UTC).isoformat(),
        "sort": "at",
    }
    context.log_page = _filtered(context, "/api/v1/access-log", DEMO_COOKIE)


@then("the operator gets these entries, with a total of {total:d}:")
def step_operator_gets(context: Context, total: int) -> None:
    assert context.table is not None
    expected = [[row[c] for c in COLUMNS] for row in context.table]
    assert _shown(context.log_page["events"]) == expected, context.log_page
    assert context.log_page["total"] == total, context.log_page
    assert context.log_page["next_cursor"] is None, context.log_page


@then('"{username}", an admin of "{library}", gets the same entries from its access log')
def step_admin_gets_the_same(context: Context, username: str, library: str) -> None:
    _grant_as(context, DEMO_COOKIE, library, username, "admin")
    session = get_person(context, username)["session"]
    page = _filtered(context, f"{_library_path(library)}/access-log", session)
    assert page == context.log_page, page


@when("the operator reads the access log one entry at a time, oldest first")
def step_one_at_a_time(context: Context) -> None:
    response = send_as(
        context,
        "GET",
        "/api/v1/access-log",
        session=DEMO_COOKIE,
        params={"limit": 1, "sort": "at", "library": context.log_library},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    context.log_page = response.json()
    assert context.log_page["next_cursor"] is not None, context.log_page


@when("the operator asks for the next page newest first with that cursor")
def step_cursor_other_sort(context: Context) -> None:
    context.response = send_as(
        context,
        "GET",
        "/api/v1/access-log",
        session=DEMO_COOKIE,
        params={"limit": 1, "sort": "-at", "cursor": context.log_page["next_cursor"]},
    )
