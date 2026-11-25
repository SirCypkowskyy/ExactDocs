"""Steps for linking sign-in providers from Account settings (over REST, as the UI does).

The provider is ``fake_oidc.FakeIssuer`` in the process (as in ``external_sign_in_steps``, whose
instance, clock and browser helpers these steps share). The browser is the TestClient; every
request carries exactly the cookies a step gives it, and the jar is emptied after each answer.
"""

import shutil
import tempfile
from http import HTTPStatus
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE, SIGN_IN_COOKIE
from steps.external_sign_in_steps import (
    MovableClock,
    add_person,
    admin_session,
    browser_sign_in,
    instance_client,
    send_as,
    whoami,
)

fake_oidc = import_module("fake_oidc")  # test support on sys.path (environment.py)

LENA = ("lena", "lena's long passphrase")
GOOGLE = "https://accounts.google.com"
TENANT = "11111111-2222-3333-4444-555555555555"
ICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<script>alert(1)</script><path d="M0 0h24v24H0z" onclick="steal()" fill="#0a7"/></svg>'
)


def _configure(context: Context, name: str, config: dict[str, Any], issuer: str) -> None:
    """Configure one provider, in place of ``step_provider``'s generic OIDC one."""
    context.clock = MovableClock()
    context.issuer = fake_oidc.FakeIssuer(issuer=issuer, now=context.clock.now)
    context.provider = name
    context.provider_config = {
        "client_id": fake_oidc.CLIENT_ID,
        "client_secret": fake_oidc.CLIENT_SECRET,
        **config,
    }
    context.people = {}


def _signed_in_locally(context: Context) -> str:
    username, password = LENA
    body = {"username": username, "password": password}
    created = send_as(context, "POST", "/api/v1/users", session=admin_session(context), json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    response = send_as(context, "POST", "/api/v1/session", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text
    return response.cookies[SESSION_COOKIE]


def _providers(context: Context, session: str) -> dict[str, Any]:
    response = send_as(context, "GET", "/api/v1/account/providers", session=session)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


def _listed(context: Context, session: str) -> dict[str, Any]:
    [provider] = [
        p for p in _providers(context, session)["providers"] if p["name"] == context.provider
    ]
    return provider


def _link(context: Context, session: str, subject: str) -> httpx2.Response:
    """Link Google in the browser: Account settings, the provider, back with the session."""
    client = instance_client(context)
    path = f"/api/v1/account/providers/{context.provider}/link"
    begun = send_as(context, "POST", path, session=session)
    assert begun.status_code == HTTPStatus.OK, begun.text
    binding = begun.cookies[SIGN_IN_COOKIE]
    callback = context.issuer.authorize(begun.json()["redirect_url"], subject)
    cookies = f"{SIGN_IN_COOKIE}={binding}; {SESSION_COOKIE}={session}"
    response = client.get(callback, headers={"cookie": cookies}, follow_redirects=False)
    client.cookies.clear()
    return response


def _back_in_account_settings(response: httpx2.Response) -> dict[str, list[str]]:
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == "/account", location
    assert SESSION_COOKIE not in response.cookies  # a link signs nobody in
    return parse_qs(location.query)


def _signed_in_as(context: Context, subject: str) -> str | None:
    """Sign in through the provider in a fresh browser; the account's username, or None."""
    response = browser_sign_in(context, subject)
    session = response.cookies.get(SESSION_COOKIE)
    context.response = response
    return whoami(context, session)["account"]["username"] if session else None


# ---------------------------------------------------------------- linking


@given("the server has Google configured and a person is signed in with a local account")
def step_google_and_lena(context: Context) -> None:
    _configure(context, "google", {"kind": "google"}, GOOGLE)
    add_person(context, "lena at google", "g-lena", email="lena@gmail.example")
    context.session = _signed_in_locally(context)


@when('they choose "Link Google" in Account settings and complete Google\'s sign-in')
def step_link_google(context: Context) -> None:
    assert _listed(context, context.session)["can_link"] is True
    linked = _back_in_account_settings(_link(context, context.session, "g-lena"))
    assert linked == {"linked": ["google"]}, linked


@given("they linked Google to their account")
def step_linked_google(context: Context) -> None:
    step_link_google(context)


@then("their account lists Google as linked")
def step_lists_google(context: Context) -> None:
    google = _listed(context, context.session)
    assert (google["display_name"], google["icon"]) == ("Google", "google"), google
    assert (google["linked"], google["origin"], google["can_unlink"]) == (True, False, True)
    assert google["linked_at"] is not None
    assert whoami(context, context.session)["account"]["username"] == "lena"  # still signed in


@then("they can sign in with Google from then on")
def step_google_signs_in(context: Context) -> None:
    assert _signed_in_as(context, "g-lena") == "lena"


@when("they unlink Google after confirming")
def step_unlink(context: Context) -> None:
    response = send_as(
        context, "DELETE", "/api/v1/account/providers/google", session=context.session
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["has_password"] is True


@then("Google no longer signs them in")
def step_no_longer(context: Context) -> None:
    assert _listed(context, context.session)["linked"] is False
    assert _signed_in_as(context, "g-lena") is None
    location = urlsplit(context.response.headers["location"])
    assert parse_qs(location.query) == {"error": ["not_linked"]}, location


@then("they keep their password to sign in with")
def step_password_stays(context: Context) -> None:
    username, password = LENA
    body = {"username": username, "password": password}
    response = send_as(context, "POST", "/api/v1/session", json=body)
    assert response.status_code == HTTPStatus.CREATED, response.text


# ---------------------------------------------------------------- the last way in


@given('a person who only signs in through "{provider}"')
def step_only_external(context: Context, provider: str) -> None:
    assert provider == context.provider
    add_person(context, "alice", "u-alice", email="alice@example.com")
    response = browser_sign_in(context, "u-alice")
    context.session = response.cookies[SESSION_COOKIE]
    listed = _providers(context, context.session)
    assert listed["has_password"] is False, listed


@when('they try to unlink "{provider}"')
def step_try_unlink(context: Context, provider: str) -> None:
    path = f"/api/v1/account/providers/{provider}"
    context.response = send_as(context, "DELETE", path, session=context.session)


@then('the unlink is refused with "{code}"')
def step_unlink_refused(context: Context, code: str) -> None:
    assert context.response.status_code == HTTPStatus.CONFLICT, context.response.text
    assert context.response.json()["error"] == code
    assert _listed(context, context.session)["can_unlink"] is False


@then('"{provider}" still signs them in')
def step_still_signs_in(context: Context, provider: str) -> None:
    assert provider == context.provider
    assert _signed_in_as(context, "u-alice") == "alice"


# ---------------------------------------------------------------- linked elsewhere


@given("another person linked their Google identity to their own account")
def step_other_linked(context: Context) -> None:
    body = {"username": "otto", "password": "otto's long passphrase"}
    created = send_as(context, "POST", "/api/v1/users", session=admin_session(context), json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    otto = send_as(context, "POST", "/api/v1/session", json=body).cookies[SESSION_COOKIE]
    add_person(context, "otto at google", "g-otto", email="otto@gmail.example")
    assert _back_in_account_settings(_link(context, otto, "g-otto")) == {"linked": ["google"]}


@when("the person links that same Google identity")
def step_link_ottos(context: Context) -> None:
    context.response = _link(context, context.session, "g-otto")


@then('they are back in Account settings with the link refused as "{code}"')
def step_link_refused(context: Context, code: str) -> None:
    assert _back_in_account_settings(context.response) == {"link_error": [code]}
    assert _listed(context, context.session)["linked"] is False


@then("that Google identity still signs the other person in")
def step_still_otto(context: Context) -> None:
    assert _signed_in_as(context, "g-otto") == "otto"


# ---------------------------------------------------------------- no accounts created


@when("someone signs in with a Google identity nobody linked")
def step_nobody_linked(context: Context) -> None:
    add_person(context, "stranger", "g-stranger", email="stranger@gmail.example")
    assert _signed_in_as(context, "g-stranger") is None


# ---------------------------------------------------------------- presets and icons


@given("an operator configures {kind} with only its client ID and secret")
def step_preset(context: Context, kind: str) -> None:
    config: dict[str, Any] = {"kind": kind}
    if kind == "microsoft":
        config["tenant"] = TENANT
    _configure(context, kind, config, f"https://{kind}.example.com")
    context.session = _signed_in_locally(context)


@then('the sign-in page and Account settings show "{name}" with the built-in "{icon}" icon')
def step_preset_shown(context: Context, name: str, icon: str) -> None:
    [offered] = send_as(context, "GET", "/api/v1/session").json()["providers"]
    listed = _listed(context, context.session)
    for provider in (offered, listed):
        assert (provider["display_name"], provider["icon"], provider["icon_url"]) == (
            name,
            icon,
            None,
        ), provider
    assert listed["can_link"] is True


@given("an operator configures a generic OIDC provider with an icon file of their own")
def step_generic_with_icon(context: Context) -> None:
    folder = Path(tempfile.mkdtemp(prefix="exactdocs-icon-"))
    context.add_cleanup(shutil.rmtree, folder, ignore_errors=True)
    context.icon_file = folder / "corp.svg"
    context.icon_file.write_bytes(ICON)
    _configure(
        context,
        "corp",
        {
            "kind": "oidc",
            "issuer": fake_oidc.ISSUER,
            "display_name": "Corp SSO",
            "allow_any_user": True,
            "icon_file": str(context.icon_file),
        },
        fake_oidc.ISSUER,
    )
    context.session = _signed_in_locally(context)


@then("the sign-in page and Account settings show its icon from ExactDocs' own origin")
def step_icon_shown(context: Context) -> None:
    [offered] = send_as(context, "GET", "/api/v1/session").json()["providers"]
    listed = _listed(context, context.session)
    assert offered["icon"] is None
    assert offered["icon_url"] == listed["icon_url"]
    url = urlsplit(offered["icon_url"])
    assert (url.scheme, url.netloc, url.path) == ("", "", "/api/v1/auth/corp/icon"), url
    context.icon_url = offered["icon_url"]


@then("the icon is sanitised and may be cached")
def step_icon_served(context: Context) -> None:
    served = send_as(context, "GET", context.icon_url)
    assert served.status_code == HTTPStatus.OK, served.text
    assert served.headers["content-type"] == "image/svg+xml"
    assert b"script" not in served.content
    assert b"onclick" not in served.content
    assert b'fill="#0a7"' in served.content
    assert served.headers["cache-control"].startswith("public, max-age=")
    assert "sandbox" in served.headers["content-security-policy"]


@then("an icon file that is not a small PNG, WebP or SVG stops the server at start")
def step_bad_icon(context: Context) -> None:
    for content in (b"GIF89a not accepted", ICON + b" " * 70_000):
        context.icon_file.write_bytes(content)
        settings = Settings(
            data_dir=context.icon_file.parent,
            public_url="http://localhost",
            auth={"providers": {"corp": context.provider_config}},
        )
        refusal = ""
        try:
            Container.build(settings)
        except StartupError as error:
            refusal = str(error)
        assert "icon_file" in refusal, (content[:20], refusal)
