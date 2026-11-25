"""Steps for the operator's view of activity and tokens (#515), with a fake OIDC provider.

The instance, its movable identity clock and the provider come from the external sign-in steps.
Times in the scenarios are of the clock's day (2026-11-13, UTC).
"""

from datetime import datetime, time, timedelta
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context

from steps.external_sign_in_steps import admin_session, person, send, session_of, sign_in

TOKENS = "/api/v1/users/tokens"


def _at(context: Context, clock_time: str) -> datetime:
    """The clock's day at ``clock_time`` (``HH:MM``)."""
    return datetime.combine(
        context.clock.at.date(), time.fromisoformat(clock_time), context.clock.at.tzinfo
    )


def _operator_get(context: Context, path: str, **params: Any) -> dict[str, Any]:
    response = send(context, "GET", path, session=admin_session(context), params=params)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given('"{name}" signed in through "{provider}" at {clock_time} and holds 2 API tokens')
def step_signed_in_with_tokens(context: Context, name: str, provider: str, clock_time: str) -> None:
    assert provider == context.provider
    context.clock.at = _at(context, clock_time)
    person(context, name, f"subject-of-{name}", email=f"{name}@example.com")
    context.session = session_of(sign_in(context, context.people[name]))
    context.expires_at = context.clock.at + timedelta(days=30)
    context.secrets = {}
    for token_name, expires in [("laptop", context.expires_at), ("ci", None)]:
        body = {"name": token_name, "expires_at": expires.isoformat() if expires else None}
        response = send(context, "POST", "/api/v1/tokens", session=context.session, json=body)
        assert response.status_code == HTTPStatus.CREATED, response.text
        context.secrets[token_name] = response.json()["token"]


@given('at {clock_time} "{name}" used one of her tokens')
def step_used_token(context: Context, clock_time: str, name: str) -> None:
    context.clock.at = _at(context, clock_time)
    context.used_at = context.clock.at
    headers = {"authorization": f"Bearer {context.secrets['laptop']}"}
    response = send(context, "GET", "/api/v1/libraries", headers=headers)
    assert response.status_code == HTTPStatus.OK, (name, response.text)


@when('an operator lists the users filtered by provider "{provider}"')
def step_users_by_provider(context: Context, provider: str) -> None:
    context.users = _operator_get(context, "/api/v1/users", provider=provider)


@then('only "{name}" is listed, signing in through "{provider}", with {count:d} tokens')
def step_only_listed(context: Context, name: str, provider: str, count: int) -> None:
    users = context.users["users"]
    assert [(u["username"], u["provider"], u["token_count"]) for u in users] == [
        (name, provider, count)
    ], users
    assert context.users["total"] == 1, context.users


@then("her last activity shows as {clock_time}, to the hour")
def step_last_active(context: Context, clock_time: str) -> None:
    shown = datetime.fromisoformat(context.users["users"][0]["last_active_at"])
    assert shown == _at(context, clock_time), shown


@then('filtering by provider "{provider}" lists only the local accounts "{names}"')
def step_local_accounts(context: Context, provider: str, names: str) -> None:
    users = _operator_get(context, "/api/v1/users", provider=provider, sort="username")["users"]
    assert ", ".join(u["username"] for u in users) == names, users
    assert all(u["provider"] is None for u in users), users


@when("an operator lists all tokens")
def step_all_tokens(context: Context) -> None:
    context.tokens = _operator_get(context, TOKENS, sort="name")


@then('each token shows its owner "{name}", its prefix, its expiry and its last use')
def step_token_details(context: Context, name: str) -> None:
    tokens = {t["name"]: t for t in context.tokens["tokens"]}
    assert set(tokens) == {"ci", "laptop"}, tokens
    assert {t["owner"] for t in tokens.values()} == {name}, tokens
    for token_name, token in tokens.items():
        assert context.secrets[token_name].startswith(token["prefix"]), token
    laptop, ci = tokens["laptop"], tokens["ci"]
    assert datetime.fromisoformat(laptop["expires_at"]) == context.expires_at, laptop
    assert datetime.fromisoformat(laptop["last_used_at"]) == context.used_at, laptop
    assert (ci["expires_at"], ci["last_used_at"]) == (None, None), ci


@then("no token shows its secret or its hash")
def step_no_secret(context: Context) -> None:
    text = str(context.tokens)
    for secret in context.secrets.values():
        assert secret not in text
        assert secret[len("exd_") + 4 :] not in text
    assert not any("token" in t or "token_hash" in t for t in context.tokens["tokens"])


@then("filtering for unused tokens lists only the one she never used")
def step_unused(context: Context) -> None:
    tokens = _operator_get(context, TOKENS, unused="true")["tokens"]
    assert [t["name"] for t in tokens] == ["ci"], tokens


@then('"{name}" cannot list all tokens: it is forbidden')
def step_forbidden(context: Context, name: str) -> None:
    response = send(context, "GET", TOKENS, session=context.session)
    assert response.status_code == HTTPStatus.FORBIDDEN, (name, response.text)
    assert response.json()["error"] == "forbidden", response.text
