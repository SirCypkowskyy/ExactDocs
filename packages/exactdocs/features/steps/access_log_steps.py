"""Steps for the access log: changes made over REST by one person each, read back over REST.

People and their credentials, and who is an admin or the creator of a library, come from
``library_roles_steps`` (as does the transfer itself); the operator is the demo admin.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from behave import then, when
from behave.runner import Context

from steps.http_steps import DEMO_COOKIE
from steps.library_roles_steps import get_person, send_as

RECENT = timedelta(minutes=5)


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
