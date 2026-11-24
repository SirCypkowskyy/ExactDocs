"""Steps for sign-in through an OpenID Connect provider: a fake issuer in the process.

The browser is the TestClient (its cookie jar carries the sign-in binding cookie from the start
to the callback); the issuer is ``fake_oidc.FakeIssuer``, reached by the server's OIDC adapter
through an in-process transport, and it approves whichever person a step names. The instance is
built lazily, so a step can still change the provider's settings before the first request.
Time is the identity domain's clock, which steps move forward.
"""

import tempfile
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.identity.constants import SESSION_COOKIE, SIGN_IN_COOKIE

fake_oidc = import_module("fake_oidc")  # test support on sys.path (environment.py)

ADMIN = ("ada", "correct horse battery staple")
START = "/api/v1/auth/{}/start"


@dataclass(slots=True)
class MovableClock:
    """The identity domain's time, moved forward by the steps."""

    at: datetime = field(default_factory=lambda: datetime(2026, 11, 13, 9, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.at

    def advance(self, delta: timedelta) -> None:
        self.at += delta


@given('sign-in provider "{name}" of kind "{kind}" with issuer "{issuer}"')
def step_provider(context: Context, name: str, kind: str, issuer: str) -> None:
    context.clock = MovableClock()
    context.issuer = fake_oidc.FakeIssuer(issuer=issuer, now=context.clock.now)
    context.provider = name
    context.provider_config = {
        "kind": kind,
        "issuer": issuer,
        "client_id": fake_oidc.CLIENT_ID,
        "client_secret": fake_oidc.CLIENT_SECRET,
        "allow_any_user": True,
        "revalidate_minutes": 60,
        "revalidate_grace_minutes": 1440,
    }
    context.people = {}  # name -> subject


def _client(context: Context) -> TestClient:
    """Build and start the instance on first use; the first admin is set up locally."""
    if getattr(context, "external_client", None) is None:
        stack = ExitStack()
        context.add_cleanup(stack.close)
        data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
        settings = Settings(
            data_dir=data_dir,
            public_url="http://localhost",
            auth={"providers": {context.provider: context.provider_config}},
        )
        context.container = Container.build(
            settings,
            sign_in=SignInStandIns(clock=context.clock, transport=context.issuer.transport()),
        )
        client = TestClient(create_app(context.container), base_url="http://localhost")
        context.external_client = stack.enter_context(client)
        context.client = context.external_client  # shared steps (and the portal) use it
        username, password = ADMIN
        setup = client.post("/api/v1/setup", json={"username": username, "password": password})
        assert setup.status_code == HTTPStatus.CREATED, setup.text
    return context.external_client


def send(
    context: Context, method: str, path: str, *, session: str | None = None, **kwargs: Any
) -> httpx2.Response:
    """A request with exactly this session (the jar's cookies are not sent)."""
    client = _client(context)
    request = client.build_request(method, path, **kwargs)
    request.headers.pop("cookie", None)
    if session:
        request.headers["cookie"] = f"{SESSION_COOKIE}={session}"
    response = client.send(request)
    client.cookies.clear()
    return response


def admin_session(context: Context) -> str:
    username, password = ADMIN
    response = send(
        context, "POST", "/api/v1/session", json={"username": username, "password": password}
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    return response.cookies[SESSION_COOKIE]


def _users(context: Context) -> dict[str, dict[str, Any]]:
    response = send(context, "GET", "/api/v1/users", session=admin_session(context))
    assert response.status_code == HTTPStatus.OK, response.text
    return {user["username"]: user for user in response.json()["users"]}


def person(
    context: Context,
    name: str,
    subject: str,
    *,
    username: str | None = None,
    email: str | None = None,
    groups: list[str] | None = None,
) -> None:
    context.issuer.add_user(subject, username or name, email=email, groups=groups or [])
    context.people[name] = subject


def _start(context: Context) -> str:
    """Start a sign-in in the browser; return the issuer's authorization URL."""
    response = _client(context).get(
        START.format(context.provider), params={"return_to": "/libraries"}, follow_redirects=False
    )
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text
    assert SIGN_IN_COOKIE in response.cookies
    return response.headers["location"]


def _callback(context: Context, url: str) -> httpx2.Response:
    """Deliver the issuer's callback to the browser; keep what came back."""
    context.response = _client(context).get(url, follow_redirects=False)
    _client(context).cookies.clear()
    return context.response


def sign_in(context: Context, subject: str) -> httpx2.Response:
    """The whole browser flow for ``subject``, from a browser holding no session."""
    _client(context).cookies.clear()
    callback = context.issuer.authorize(_start(context), subject)
    return _callback(context, callback)


def session_of(response: httpx2.Response) -> str:
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text
    assert response.headers["location"] == "/libraries", response.headers["location"]
    token = response.cookies.get(SESSION_COOKIE)
    assert token, response.headers
    return token


def _whoami(context: Context, session: str) -> dict[str, Any]:
    response = send(context, "GET", "/api/v1/session", session=session)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _refusal(response: httpx2.Response) -> str:
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == "/sign-in", location
    return parse_qs(location.query)["error"][0]


def _revalidate(context: Context) -> Any:
    _client(context)
    return context.client.portal.call(context.container.identity.revalidate_external_accounts)


# ---------------------------------------------------------------- first sign-in


@given('no ExactDocs account is linked to subject "{subject}" of that issuer')
def step_no_link(context: Context, subject: str) -> None:
    assert subject not in context.people.values()
    assert not any(user["provider"] for user in _users(context).values())


@when('"{name}" (subject "{subject}", group "{group}") signs in through "{provider}"')
def step_signs_in(context: Context, name: str, subject: str, group: str, provider: str) -> None:
    assert provider == context.provider
    person(context, name, subject, email=f"{name}@example.com", groups=[group])
    context.session = session_of(sign_in(context, subject))


@then('an account "{name}" with role "{role}" is created and linked to that issuer and subject')
def step_created(context: Context, name: str, role: str) -> None:
    user = _users(context)[name]
    assert user["role"] == role, user
    assert user["provider"] == context.provider, user
    # Linked by (issuer, subject): the same subject reaches the same account again.
    again = _whoami(context, session_of(sign_in(context, context.people[name])))
    assert again["account"]["id"] == user["id"], again


@then("she is signed in with the usual session cookie")
def step_usual_cookie(context: Context) -> None:
    cookie = next(
        c for c in context.response.headers.get_list("set-cookie") if SESSION_COOKIE in c
    ).lower()
    assert "httponly" in cookie, cookie
    assert "samesite=lax" in cookie, cookie
    assert "path=/api" in cookie, cookie
    state = _whoami(context, context.session)
    assert state["state"] == "signed_in", state
    assert state["account"]["username"] == "alice", state


# ---------------------------------------------------------------- linking by subject only


@given('"{name}" signed in through "{provider}" once as subject "{subject}"')
def step_signed_in_once(context: Context, name: str, provider: str, subject: str) -> None:
    assert provider == context.provider
    person(context, name, subject, email=f"{name}@example.com")
    context.account_id = _whoami(context, session_of(sign_in(context, subject)))["account"]["id"]


@when('subject "{subject}" signs in again with another email and username')
def step_new_email(context: Context, subject: str) -> None:
    user = context.issuer.users[subject]
    user.username, user.email = "alice.renamed", "alice.renamed@example.com"
    context.session = session_of(sign_in(context, subject))


@then("she reaches the same account")
def step_same_account(context: Context) -> None:
    account = _whoami(context, context.session)["account"]
    assert account["id"] == context.account_id, account
    assert account["username"] == "alice", account  # set when created, never renamed


@then("a different subject with alice's old email gets an account of its own")
def step_other_subject(context: Context) -> None:
    context.issuer.add_user("u-999", None, email="alice@example.com")
    account = _whoami(context, session_of(sign_in(context, "u-999")))["account"]
    assert account["id"] != context.account_id, account
    assert account["username"] == "alice@corp", account


# ---------------------------------------------------------------- no takeover by name


@given('a local account "{name}" exists')
def step_local_account(context: Context, name: str) -> None:
    body = {"username": name, "password": f"{name}'s long passphrase"}
    response = send(context, "POST", "/api/v1/users", session=admin_session(context), json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    context.local_id = response.json()["id"]


@when('subject "{subject}" with username "{username}" signs in through "{provider}"')
def step_same_name(context: Context, subject: str, username: str, provider: str) -> None:
    assert provider == context.provider
    person(context, f"{username} at {provider}", subject, username=username)
    context.session = session_of(sign_in(context, subject))


@then('the local account "{name}" is unchanged and still signs in with its password')
def step_local_unchanged(context: Context, name: str) -> None:
    local = _users(context)[name]
    assert local["id"] == context.local_id, local
    assert local["provider"] is None, local
    body = {"username": name, "password": f"{name}'s long passphrase"}
    response = send(context, "POST", "/api/v1/session", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    assert response.json()["account"]["id"] == context.local_id


@then('the new account is named "{username}"')
def step_named(context: Context, username: str) -> None:
    account = _whoami(context, context.session)["account"]
    assert account["username"] == username, account
    assert account["id"] != context.local_id


# ---------------------------------------------------------------- groups and roles


@given('the IdP puts "{name}" in group "{group}"')
def step_in_group(context: Context, name: str, group: str) -> None:
    person(context, name, f"subject-of-{name}", groups=[group])


@when('"{name}" signs in through OIDC')
def step_signs_in_oidc(context: Context, name: str) -> None:
    context.session = session_of(sign_in(context, context.people[name]))


@then('she is a member of ExactDocs group "{group}"')
def step_member(context: Context, group: str) -> None:
    assert _users(context)["alice"]["groups"] == [group]


@then("when the IdP removes her from it, her next sign-in removes her membership")
def step_membership_removed(context: Context) -> None:
    context.issuer.users[context.people["alice"]].groups = []
    session_of(sign_in(context, context.people["alice"]))
    assert _users(context)["alice"]["groups"] == []


@given('provider "{name}" maps group "{group}" to the admin role')
def step_admin_group(context: Context, name: str, group: str) -> None:
    assert name == context.provider
    context.provider_config["admin_groups"] = [group]


@given('provider "{name}" allows only group "{group}"')
def step_allowed_group(context: Context, name: str, group: str) -> None:
    assert name == context.provider
    context.provider_config["allow_any_user"] = False
    context.provider_config["allowed_groups"] = [group]


@given('"{name}" signed in as a member of "{group}" and is an admin')
def step_admin_member(context: Context, name: str, group: str) -> None:
    person(context, name, f"subject-of-{name}", groups=[group])
    context.session = session_of(sign_in(context, context.people[name]))
    assert _whoami(context, context.session)["account"]["role"] == "admin"


@when('the IdP removes her from "{group}"')
def step_removed(context: Context, group: str) -> None:
    for subject in context.people.values():
        user = context.issuer.users[subject]
        user.groups = [g for g in user.groups if g != group]


@then('at her next sign-in or revalidation she is a "{role}"')
def step_demoted(context: Context, role: str) -> None:
    # Revalidation first: no sign-in needed, and no other admin has to agree.
    context.clock.advance(timedelta(minutes=61))
    report = _revalidate(context)
    assert report.extended == 1, report
    assert _whoami(context, context.session)["account"]["role"] == role
    session = session_of(sign_in(context, context.people["alice"]))
    assert _whoami(context, session)["account"]["role"] == role


@given('"{name}" signed in as a member of "{group}" and has an API token')
def step_member_with_token(context: Context, name: str, group: str) -> None:
    person(context, name, f"subject-of-{name}", groups=[group])
    context.session = session_of(sign_in(context, context.people[name]))
    response = send(
        context, "POST", "/api/v1/tokens", session=context.session, json={"name": "laptop"}
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    context.api_token = response.json()["token"]
    assert _libraries_with_token(context) == HTTPStatus.OK


def _libraries_with_token(context: Context) -> int:
    headers = {"authorization": f"Bearer {context.api_token}"}
    return send(context, "GET", "/api/v1/libraries", headers=headers).status_code


@then("after the revalidation interval her session ends and her API token is refused")
def step_lost_access(context: Context) -> None:
    assert _whoami(context, context.session)["state"] == "signed_in"  # not checked yet
    context.clock.advance(timedelta(minutes=61))
    report = _revalidate(context)
    assert report.revoked == 1, report
    assert _whoami(context, context.session)["state"] == "signed_out"
    assert _libraries_with_token(context) == HTTPStatus.UNAUTHORIZED


@then('her next sign-in is refused with "{code}"')
def step_next_refused(context: Context, code: str) -> None:
    response = sign_in(context, context.people["carol"])
    assert _refusal(response) == code
    assert SESSION_COOKIE not in response.cookies
    assert _libraries_with_token(context) == HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------- disabled accounts


@given('an operator disabled the account linked to subject "{subject}"')
def step_disabled(context: Context, subject: str) -> None:
    person(context, "alice", subject)
    session_of(sign_in(context, subject))
    user = _users(context)["alice"]
    response = send(
        context, "POST", f"/api/v1/users/{user['id']}/disable", session=admin_session(context)
    )
    assert response.status_code == HTTPStatus.OK, response.text


@when('subject "{subject}" signs in through "{provider}"')
def step_subject_signs_in(context: Context, subject: str, provider: str) -> None:
    assert provider == context.provider
    sign_in(context, subject)


@then('the external sign-in is refused with "{code}"')
def step_external_refused(context: Context, code: str) -> None:
    assert _refusal(context.response) == code, context.response.headers


@then("no session is created")
def step_no_session(context: Context) -> None:
    assert SESSION_COOKIE not in context.response.cookies
    assert not any(
        SESSION_COOKIE in c and "max-age=0" not in c.lower()
        for c in context.response.headers.get_list("set-cookie")
    )


# ---------------------------------------------------------------- forged callbacks


@when("the callback arrives with {forgery}")
def step_forged(context: Context, forgery: str) -> None:
    person(context, "mallory", "u-666")
    issuer = context.issuer
    client = _client(context)
    tampers = {
        "a wrong nonce": lambda _, claims: claims.update(nonce="forged"),
        "an ID token not signed by a key of the issuer's JWKS": fake_oidc.signed_by_stranger,
        "an ID token signed with HS256 and the issuer's public key": (
            fake_oidc.hs256_with_public_key(issuer)
        ),
        "an unsigned ID token": fake_oidc.unsigned,
    }
    if forgery in tampers:
        issuer.tamper = tampers[forgery]
        sign_in(context, "u-666")
    elif forgery == "a state that was not issued to this browser":
        # The attacker's own sign-in, finished in the victim's browser (login CSRF).
        client.cookies.clear()
        attackers = issuer.authorize(_start(context), "u-666")
        client.cookies.clear()
        _start(context)  # the victim's browser holds a binding of its own attempt
        _callback(context, attackers)
    elif forgery == "no browser binding at all":
        client.cookies.clear()
        callback = issuer.authorize(_start(context), "u-666")
        client.cookies.clear()
        _callback(context, callback)
    elif forgery == "a code and state that were already used":
        client.cookies.clear()
        callback = issuer.authorize(_start(context), "u-666")
        binding = client.cookies[SIGN_IN_COOKIE]
        session_of(client.get(callback, follow_redirects=False))
        client.cookies.clear()
        context.response = client.get(
            callback, headers={"cookie": f"{SIGN_IN_COOKIE}={binding}"}, follow_redirects=False
        )
    else:
        raise AssertionError(forgery)


# ---------------------------------------------------------------- no refresh token


@given("an OIDC provider that issues no refresh token")
def step_no_refresh(context: Context) -> None:
    context.issuer.issue_refresh_tokens = False


@when('"{name}" signs in through it')
def step_signs_in_through_it(context: Context, name: str) -> None:
    person(context, name, f"subject-of-{name}")
    context.session = session_of(sign_in(context, context.people[name]))


@then("her session ends after the revalidation grace period and she signs in again")
def step_short_session(context: Context) -> None:
    context.clock.advance(timedelta(minutes=1439))
    assert _whoami(context, context.session)["state"] == "signed_in"
    report = _revalidate(context)
    assert (report.extended, report.revoked) == (0, 0), report  # nothing to refresh with
    context.clock.advance(timedelta(minutes=2))
    assert _whoami(context, context.session)["state"] == "signed_out"
    again = session_of(sign_in(context, context.people["erin"]))
    assert _whoami(context, again)["state"] == "signed_in"


# ---------------------------------------------------------------- break-glass


@given("a sign-in provider is configured and cannot be reached")
def step_down(context: Context) -> None:
    _client(context)
    context.issuer.down = True


@when("the local admin signs in with username and password")
def step_admin_password(context: Context) -> None:
    username, password = ADMIN
    context.response = send(
        context, "POST", "/api/v1/session", json={"username": username, "password": password}
    )


@then("the sign-in succeeds")
def step_succeeds(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    assert context.response.json()["account"]["role"] == "admin"


@then('a sign-in through the provider is refused with "{code}"')
def step_provider_refused(context: Context, code: str) -> None:
    response = _client(context).get(START.format(context.provider), follow_redirects=False)
    assert _refusal(response) == code


@given("a generic OAuth2 provider maps a nested subject and groups")
def generic_provider(context: Context) -> None:
    step_provider(context, "corp2", "oauth2", "https://idp.example.com")
    context.issuer = import_module("fake_oauth2").FakeOAuth2(
        now=context.clock.now, nested_claims=True
    )
    context.provider_config.update(
        {
            "authorization_url": "https://idp.example.com/authorize",
            "token_url": "https://idp.example.com/token",
            "userinfo_url": "https://idp.example.com/userinfo",
            "subject_claim": "person.subject",
            "username_claim": "person.name",
            "groups_claim": "person.groups",
        }
    )
    context.issuer.add_user("u-123", "alice", groups=["payments"])


@when("Alice completes the generic OAuth2 sign-in")
def generic_sign_in(context: Context) -> None:
    context.session = session_of(sign_in(context, "u-123"))


@then("her OAuth2 account is linked to the configured subject and groups")
def generic_account(context: Context) -> None:
    result = _whoami(context, context.session)
    assert result["account"]["username"] == "alice", result
    assert _users(context)["alice"]["groups"] == ["payments"], result


@given('GitHub Enterprise provider "ghe" allows team "acme/docs-readers"')
def github_provider(context: Context) -> None:
    step_provider(context, "ghe", "github", "https://github.example.com")
    context.issuer = import_module("fake_github").FakeGithub(
        issuer="https://github.example.com", now=context.clock.now
    )
    context.issuer.add_user("123", "carol")
    context.provider_config.pop("issuer")
    context.provider_config.update(
        {
            "base_url": context.issuer.issuer,
            "allowed_orgs": ["acme"],
            "allowed_teams": ["acme/docs-readers"],
            "allow_any_user": False,
        }
    )


@given("the GitHub user has organization access but no allowed team")
def github_no_team(context: Context) -> None:
    context.issuer.teams.clear()


@given("the GitHub organization requires {restriction}")
def github_restricted(context: Context, restriction: str) -> None:
    context.issuer.restricted = {"app approval": "app", "SSO authorization": "sso"}[restriction]


@when("the GitHub user completes external sign-in")
def github_sign_in(context: Context) -> None:
    context.github_response = sign_in(context, "123")


@then('GitHub sign-in is refused with code "{code}"')
def github_refused(context: Context, code: str) -> None:
    location = urlsplit(context.github_response.headers["location"])
    assert location.path == "/sign-in"
    assert parse_qs(location.query)["error"] == [code]


@given("the GitHub user has an active session and API token")
def github_session_token(context: Context) -> None:

    context.session = session_of(sign_in(context, "123"))
    response = send(
        context, "POST", "/api/v1/tokens", session=context.session, json={"name": "cli"}
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    context.api_token = response.json()["token"]


@when("the GitHub user loses the allowed team")
def github_loses_team(context: Context) -> None:

    context.issuer.teams.clear()
    context.clock.advance(timedelta(minutes=61))
    assert _revalidate(context).revoked == 1


@then("both the GitHub session and API token are refused")
def github_credentials_refused(context: Context) -> None:

    assert _whoami(context, context.session)["state"] == "signed_out"
    response = send(
        context,
        "GET",
        "/api/v1/libraries",
        headers={"Authorization": f"Bearer {context.api_token}"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text
    github_sign_in(context)
    github_refused(context, "github_team_required")


# ---------------------------------------------------------------- shared with other features


def signed_in_through_provider(context: Context, name: str, subject: str) -> str:
    """Sign ``name`` in through the configured provider in a fresh browser; return the session.

    For features about something else that need an account of an identity provider (no password).
    """
    person(context, name, subject, email=f"{name}@example.com", groups=[])
    return session_of(sign_in(context, subject))


# Shared with other features (linked providers): the instance, the browser and the people
# (`send`, `admin_session`, `person`, `sign_in` and `session_of` are shared under their own names).
instance_client = _client
send_as = send
add_person = person
browser_sign_in = sign_in
whoami = _whoami
