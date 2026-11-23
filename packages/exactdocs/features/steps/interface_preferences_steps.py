"""Steps for interface preferences saved per account, driven over REST as the web UI does.

Two people share one client here, so no step relies on its cookie jar: every request carries
exactly the session cookie (or bearer token) of whoever makes it, and the jar is emptied after
each answer, so one person's sign-in never stands in for the other's session.
"""

from http import HTTPStatus
from typing import Any

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.identity.constants import SESSION_COOKIE

PATH = "/api/v1/account/preferences"
ADMIN = {"username": "ada", "password": "correct horse battery staple"}
DEFAULTS: dict[str, Any] = {
    "theme": "system",
    "contrast": "standard",
    "text_scale": 100,
    "text_spacing": "standard",
    "motion": "system",
    "font": "default",
    "underline_links": False,
    "large_targets": False,
    "language": "system",
    "library_logos": True,
}
ADMINS: dict[str, Any] = {
    **DEFAULTS,
    "theme": "dark",
    "contrast": "more",
    "text_scale": 125,
    "underline_links": True,
    "language": "pl",
}
BOBS: dict[str, Any] = {**DEFAULTS, "theme": "light", "font": "dyslexic", "language": "en"}
LANGUAGES = {"English": "en", "Polish": "pl", "the system's language": "system"}
PROBLEMS: dict[str, dict[str, Any]] = {
    "an unknown setting": {**ADMINS, "theme": "light", "sparkles": True},
    "a text size of 95 percent": {**ADMINS, "theme": "light", "text_scale": 95},
    "a theme it does not offer": {**ADMINS, "theme": "sepia"},
    "a language it does not offer": {**ADMINS, "language": "de"},
    "library logos neither shown nor hidden": {**ADMINS, "library_logos": "no"},
    "a missing setting": {k: v for k, v in {**ADMINS, "theme": "light"}.items() if k != "font"},
}


def _send(
    context: Context,
    method: str,
    *,
    session: str | None = None,
    token: str | None = None,
    json: Any = None,
) -> httpx.Response:
    request = context.client.build_request(method, PATH, json=json)
    request.headers.pop("cookie", None)
    if session:
        request.headers["cookie"] = f"{SESSION_COOKIE}={session}"
    if token:
        request.headers["authorization"] = f"Bearer {token}"
    response = context.client.send(request)
    context.client.cookies.clear()
    return response


def _ok(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _admins_now(context: Context) -> dict[str, Any]:
    return _ok(_send(context, "GET", session=context.session_token))


def _save_admins(context: Context) -> None:
    body = _ok(_send(context, "PUT", session=context.session_token, json=ADMINS))
    assert body == {"saved": True, "preferences": ADMINS}, body


@when("the admin reads their interface preferences")
def step_read(context: Context) -> None:
    context.preferences = _admins_now(context)


@then("they are the default preferences, not saved yet")
def step_defaults(context: Context) -> None:
    assert context.preferences == {"saved": False, "preferences": DEFAULTS}, context.preferences


@when(
    "the browser saves its dark theme, more contrast, text at 125 percent, underlined links"
    " and Polish"
)
def step_browser_saves(context: Context) -> None:
    # What the UI does on a first sign-in: the account has none saved, so the browser's win.
    assert _admins_now(context)["saved"] is False
    _save_admins(context)


@then("the admin's interface preferences are the ones the browser saved")
def step_browser_saved(context: Context) -> None:
    assert _admins_now(context) == {"saved": True, "preferences": ADMINS}


@given(
    "the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish"
)
def step_admin_saved(context: Context) -> None:
    _save_admins(context)


@when("the admin signs in from another browser and reads their interface preferences")
def step_other_browser(context: Context) -> None:
    signed_in = context.client.post("/api/v1/session", json=ADMIN)
    assert signed_in.status_code == HTTPStatus.CREATED, signed_in.text
    other = signed_in.cookies.get(SESSION_COOKIE)
    assert other
    assert other != context.session_token
    context.preferences = _ok(_send(context, "GET", session=other))


@then("they are the preferences the admin saved")
def step_same(context: Context) -> None:
    assert context.preferences == {"saved": True, "preferences": ADMINS}, context.preferences


@when("the admin switches the interface language to {language}")
def step_switch_language(context: Context, language: str) -> None:
    switched = {**_admins_now(context)["preferences"], "language": LANGUAGES[language]}
    body = _ok(_send(context, "PUT", session=context.session_token, json=switched))
    assert body == {"saved": True, "preferences": switched}, body


@then("they are the preferences the admin saved, in {language}")
def step_same_in(context: Context, language: str) -> None:
    expected = {**ADMINS, "language": LANGUAGES[language]}
    assert context.preferences == {"saved": True, "preferences": expected}, context.preferences


@when("the admin hides library logos")
def step_hide_logos(context: Context) -> None:
    assert _admins_now(context)["preferences"]["library_logos"] is True
    hidden = {**_admins_now(context)["preferences"], "library_logos": False}
    body = _ok(_send(context, "PUT", session=context.session_token, json=hidden))
    assert body == {"saved": True, "preferences": hidden}, body


@then("they are the preferences the admin saved, with library logos hidden")
def step_same_without_logos(context: Context) -> None:
    expected = {**ADMINS, "library_logos": False}
    assert context.preferences == {"saved": True, "preferences": expected}, context.preferences


@when("the admin changes the text size to {scale:d} percent")
def step_change_scale(context: Context, scale: int) -> None:
    changed = {**_admins_now(context)["preferences"], "text_scale": scale}
    _ok(_send(context, "PUT", session=context.session_token, json=changed))


@then("the admin's interface preferences have text at {scale:d} percent and the rest as saved")
def step_changed_scale(context: Context, scale: int) -> None:
    expected = {"saved": True, "preferences": {**ADMINS, "text_scale": scale}}
    assert _admins_now(context) == expected


@then("bob's interface preferences are the defaults, with his session and with his API token")
def step_bob_defaults(context: Context) -> None:
    expected = {"saved": False, "preferences": DEFAULTS}
    assert _ok(_send(context, "GET", session=context.user_session)) == expected
    assert _ok(_send(context, "GET", token=context.user_token)) == expected


@when("bob saves a light theme, a dyslexia-friendly font and English with his API token")
def step_bob_saves(context: Context) -> None:
    body = _ok(_send(context, "PUT", token=context.user_token, json=BOBS))
    assert body == {"saved": True, "preferences": BOBS}, body


@then("bob's interface preferences are the ones he saved")
def step_bob_saved(context: Context) -> None:
    assert _ok(_send(context, "GET", session=context.user_session)) == {
        "saved": True,
        "preferences": BOBS,
    }


@then("the admin's interface preferences are still the ones the admin saved")
def step_admin_unchanged(context: Context) -> None:
    assert _admins_now(context) == {"saved": True, "preferences": ADMINS}


@when("the admin saves preferences with {problem}")
def step_save_invalid(context: Context, problem: str) -> None:
    context.response = _send(context, "PUT", session=context.session_token, json=PROBLEMS[problem])


@then('the preferences are refused as invalid, naming "{field}"')
def step_refused_invalid(context: Context, field: str) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    body = response.json()
    assert body["error"] == "validation_error", body
    assert [error["loc"] for error in body["fields"]] == [["body", field]], body


@when("a signed-out client reads interface preferences")
def step_signed_out_read(context: Context) -> None:
    context.response = _send(context, "GET")


@when("a signed-out client saves interface preferences")
def step_signed_out_save(context: Context) -> None:
    context.response = _send(context, "PUT", json=ADMINS)
