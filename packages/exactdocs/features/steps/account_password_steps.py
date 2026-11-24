"""Steps for changing one's own password from Account settings (over REST, as the UI does).

The local person is "bob", created by the operator "ada". Every request carries exactly the
session cookie of whoever makes it, and the client's jar is emptied after each answer, so one
session never stands in for another (as in ``users_steps``).
"""

from http import HTTPStatus
from typing import Any

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.identity.constants import FREE_FAILURES, SESSION_COOKIE
from steps.external_sign_in_steps import signed_in_through_provider

OPERATOR = ("ada", "correct horse battery staple")
BOB_PHRASE = "bob's long passphrase"
NEW_PHRASE = "bob's brand new passphrase"
WRONG_PHRASE = "not bob's passphrase"
ROUTE = "/api/v1/account/password"


def _send(
    context: Context, method: str, path: str, *, session: str | None = None, json: Any = None
) -> httpx.Response:
    request = context.client.build_request(method, path, json=json)
    request.headers.pop("cookie", None)
    if session:
        request.headers["cookie"] = f"{SESSION_COOKIE}={session}"
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


def _change(context: Context, session: str, current: str) -> httpx.Response:
    body = {"current_password": current, "new_password": NEW_PHRASE}
    return _send(context, "PUT", ROUTE, session=session, json=body)


@given("a person signed in with a local account, on a laptop and on a phone")
def step_signed_in_twice(context: Context) -> None:
    operator = _session_of(_sign_in(context, *OPERATOR))
    body = {"username": "bob", "password": BOB_PHRASE}
    created = _send(context, "POST", "/api/v1/users", session=operator, json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    context.laptop = _session_of(_sign_in(context, "bob", BOB_PHRASE))
    context.phone = _session_of(_sign_in(context, "bob", BOB_PHRASE))
    state = _send(context, "GET", "/api/v1/session", session=context.laptop).json()
    # The UI shows the Password section because the account has one.
    assert state["account"]["has_password"] is True, state


@when("they give their current password and a new one in Account settings on the laptop")
def step_change(context: Context) -> None:
    response = _change(context, context.laptop, BOB_PHRASE)
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text


@then("the new password works for the next sign-in and the old one no longer does")
def step_new_password_works(context: Context) -> None:
    old = _sign_in(context, "bob", BOB_PHRASE)
    assert old.status_code == HTTPStatus.UNAUTHORIZED, old.text
    assert old.json()["error"] == "invalid_credentials"
    _session_of(_sign_in(context, "bob", NEW_PHRASE))


@then("their other sessions are signed out, this one stays")
def step_other_sessions_end(context: Context) -> None:
    laptop = _send(context, "GET", "/api/v1/libraries", session=context.laptop)
    assert laptop.status_code == HTTPStatus.OK, laptop.text
    phone = _send(context, "GET", "/api/v1/libraries", session=context.phone)
    assert phone.status_code == HTTPStatus.UNAUTHORIZED, phone.text


@when("they give a wrong current password")
def step_wrong_password(context: Context) -> None:
    context.response = _change(context, context.laptop, WRONG_PHRASE)


@then("the change is refused, and repeated failures are throttled like sign-ins")
def step_refused_and_throttled(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.FORBIDDEN, context.response.text
    assert context.response.json()["error"] == "wrong_password"
    for _ in range(FREE_FAILURES - 1):
        response = _change(context, context.laptop, WRONG_PHRASE)
        assert response.status_code == HTTPStatus.FORBIDDEN, response.text
    # Past the free failures even the right password must wait, and so must a sign-in from the
    # same address: the change and the sign-in share one throttle.
    throttled = _change(context, context.laptop, BOB_PHRASE)
    assert throttled.status_code == HTTPStatus.TOO_MANY_REQUESTS, throttled.text
    assert int(throttled.headers["retry-after"]) > 0
    sign_in = _sign_in(context, "bob", BOB_PHRASE)
    assert sign_in.status_code == HTTPStatus.TOO_MANY_REQUESTS, sign_in.text
    # A refused change is no sign-out.
    still = _send(context, "GET", "/api/v1/libraries", session=context.laptop)
    assert still.status_code == HTTPStatus.OK, still.text


@then("their other session is untouched")
def step_untouched(context: Context) -> None:
    phone = _send(context, "GET", "/api/v1/libraries", session=context.phone)
    assert phone.status_code == HTTPStatus.OK, phone.text


@given("a person who only signs in through an identity provider")
def step_external_person(context: Context) -> None:
    context.external_session = signed_in_through_provider(context, "erin", "u-77")


@then("Account settings does not offer a password change")
def step_no_password_change(context: Context) -> None:
    session = context.external_session
    state = _send(context, "GET", "/api/v1/session", session=session).json()
    assert state["account"]["username"] == "erin", state
    assert state["account"]["has_password"] is False, state
    response = _change(context, session, "anything at all")
    assert response.status_code == HTTPStatus.CONFLICT, response.text
    assert response.json()["error"] == "external_account"
    # A local account on the same instance does have one.
    admin = _session_of(_sign_in(context, *OPERATOR))
    admin_state = _send(context, "GET", "/api/v1/session", session=admin).json()
    assert admin_state["account"]["has_password"] is True, admin_state
