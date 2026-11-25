"""External sign-in over HTTP: the settings, the routes, the cookies, and no password for it."""

import asyncio
import io
import os
from collections.abc import AsyncIterator
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsError

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings, read_config_file
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.identity.constants import SESSION_COOKIE, SIGN_IN_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand
from fake_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIssuer

HORSE = "correct horse battery staple"
PUBLIC = "https://docs.example.com"


@dataclass(slots=True)
class Clock:
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.at


def provider(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "oidc",
        "display_name": "Corp SSO",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "allowed_groups": ["docs"],
        "admin_groups": ["docs-admins"],
        **overrides,
    }


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"public_url": PUBLIC, "auth": {"providers": {"corp": provider()}}}
    return Settings(**{**values, **overrides})


@dataclass(slots=True)
class Instance:
    container: Container
    client: httpx.AsyncClient
    issuer: FakeIssuer
    clock: Clock


@pytest.fixture
async def instance() -> AsyncIterator[Instance]:
    clock = Clock()
    issuer = FakeIssuer(now=clock.now)
    issuer.add_user("u-1", "alice", groups=["docs"])
    container = Container.build(
        settings(), sign_in=SignInStandIns(clock=clock, transport=issuer.transport())
    )
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        transport = httpx.ASGITransport(app=create_app(container))
        # HTTPS, as the public URL says: the cookies are `Secure`, and the jar sends them back.
        async with httpx.AsyncClient(transport=transport, base_url="https://localhost") as client:
            yield Instance(container=container, client=client, issuer=issuer, clock=clock)


def cookie(response: httpx.Response, name: str) -> Any:
    for header in response.headers.get_list("set-cookie"):
        jar: SimpleCookie = SimpleCookie()
        jar.load(header)
        if name in jar:
            return jar[name]
    pytest.fail(f"no {name} cookie")


async def start(instance: Instance, **params: str) -> httpx.Response:
    response = await instance.client.get("/api/v1/auth/corp/start", params=params)
    assert response.status_code == 303, response.text
    return response


async def sign_in(instance: Instance, subject: str = "u-1", **params: str) -> httpx.Response:
    instance.client.cookies.clear()
    begun = await start(instance, **params)
    callback = instance.issuer.authorize(begun.headers["location"], subject)
    response = await instance.client.get(callback)
    instance.client.cookies.clear()
    return response


async def admin_session(instance: Instance) -> str:
    response = await instance.client.post(
        "/api/v1/session", json={"username": "ada", "password": HORSE}
    )
    instance.client.cookies.clear()
    return response.cookies[SESSION_COOKIE]


# ---------------------------------------------------------------- the routes


async def test_the_start_binds_the_attempt_to_the_browser(instance: Instance) -> None:
    response = await start(instance, return_to="/libraries")

    binding = cookie(response, SIGN_IN_COOKIE)
    assert binding["path"] == "/api/v1/auth"
    assert binding["httponly"]
    assert binding["samesite"].lower() == "lax"
    assert binding["max-age"] == "600"
    assert response.headers["cache-control"] == "no-store"
    location = urlsplit(response.headers["location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    assert query["redirect_uri"] == [f"{PUBLIC}/api/v1/auth/corp/callback"]
    assert binding.value not in response.headers["location"]


@pytest.mark.parametrize(
    ("public_url", "secure"), [(PUBLIC, True), ("http://localhost:3000", False)]
)
async def test_an_https_public_url_makes_the_cookies_secure(public_url: str, secure: bool) -> None:
    """The request arrives over plain HTTP (a proxy that does not forward the scheme)."""
    issuer = FakeIssuer()
    issuer.add_user("u-1", "alice", groups=["docs"])
    container = Container.build(
        settings(public_url=public_url), sign_in=SignInStandIns(transport=issuer.transport())
    )
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        transport = httpx.ASGITransport(app=create_app(container))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            begun = await client.get("/api/v1/auth/corp/start")
            binding = cookie(begun, SIGN_IN_COOKIE)
            callback = issuer.authorize(begun.headers["location"], "u-1")
            finished = await client.get(
                callback, headers={"cookie": f"{SIGN_IN_COOKIE}={binding.value}"}
            )
            client.cookies.clear()
            password = await client.post(
                "/api/v1/session", json={"username": "ada", "password": HORSE}
            )

    assert finished.headers["location"] == "/"
    for response, name in [
        (begun, SIGN_IN_COOKIE),
        (finished, SIGN_IN_COOKIE),
        (finished, SESSION_COOKIE),
        (password, SESSION_COOKIE),
    ]:
        assert bool(cookie(response, name)["secure"]) is secure, name


async def test_the_redirect_uri_never_follows_the_host_header(instance: Instance) -> None:
    response = await instance.client.get(
        "/api/v1/auth/corp/start", headers={"host": "localhost:9999"}
    )

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_uri"] == [f"{PUBLIC}/api/v1/auth/corp/callback"]


async def test_a_callback_signs_in_with_the_session_cookie(instance: Instance) -> None:
    response = await sign_in(instance, return_to="/libraries/acme/pay?v=1")

    assert response.status_code == 303
    assert response.headers["location"] == "/libraries/acme/pay?v=1"
    session = cookie(response, SESSION_COOKIE)
    assert session["path"] == "/api"
    assert session["httponly"]
    assert cookie(response, SIGN_IN_COOKIE)["max-age"] == "0"  # the binding is cleared
    state = await instance.client.get(
        "/api/v1/session", headers={"cookie": f"{SESSION_COOKIE}={session.value}"}
    )
    assert state.json()["account"]["username"] == "alice"


async def test_return_to_another_host_lands_on_the_home_page(instance: Instance) -> None:
    response = await sign_in(instance, return_to="https://evil.example/phish")

    assert response.headers["location"] == "/"


async def test_a_refusal_goes_back_to_the_sign_in_page_with_its_code(instance: Instance) -> None:
    instance.issuer.add_user("u-2", "bob", groups=["other"])

    response = await sign_in(instance, "u-2")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in?error=not_allowed"
    assert SESSION_COOKIE not in response.cookies


async def test_a_callback_without_the_binding_cookie_is_refused(instance: Instance) -> None:
    begun = await start(instance)
    callback = instance.issuer.authorize(begun.headers["location"], "u-1")
    instance.client.cookies.clear()

    response = await instance.client.get(callback)

    assert response.headers["location"] == "/sign-in?error=sign_in_failed"


async def test_an_unknown_provider_is_not_found(instance: Instance) -> None:
    response = await instance.client.get("/api/v1/auth/nope/start")

    assert response.status_code == 404
    assert response.json()["error"] == "unknown_provider"


async def test_signing_out_ends_only_the_exactdocs_session(instance: Instance) -> None:
    session = cookie(await sign_in(instance), SESSION_COOKIE).value
    headers = {"cookie": f"{SESSION_COOKIE}={session}"}

    assert (await instance.client.delete("/api/v1/session", headers=headers)).status_code == 204

    state = await instance.client.get("/api/v1/session", headers=headers)
    assert state.json()["state"] == "signed_out"
    assert instance.issuer.refresh_tokens  # nothing was revoked at the provider


async def test_the_session_state_lists_the_providers(instance: Instance) -> None:
    state = (await instance.client.get("/api/v1/session")).json()

    assert state["providers"] == [
        {"name": "corp", "display_name": "Corp SSO", "icon": None, "icon_url": None}
    ]


async def test_the_users_page_shows_provider_and_groups(instance: Instance) -> None:
    instance.issuer.users["u-1"].groups = ["docs", "docs-admins"]
    await sign_in(instance)
    headers = {"cookie": f"{SESSION_COOKIE}={await admin_session(instance)}"}

    users = (await instance.client.get("/api/v1/users", headers=headers)).json()["users"]

    by_name = {u["username"]: u for u in users}
    assert (by_name["ada"]["provider"], by_name["ada"]["groups"]) == (None, [])
    assert by_name["alice"]["provider"] == "corp"
    assert by_name["alice"]["groups"] == ["docs", "docs-admins"]
    assert by_name["alice"]["role"] == "admin"


# ---------------------------------------------------------------- no password


async def test_an_external_account_cannot_sign_in_with_a_password(instance: Instance) -> None:
    await sign_in(instance)

    for path, extra in [("/api/v1/session", {}), ("/api/v1/tokens/login", {"name": "cli"})]:
        body = {"username": "alice", "password": HORSE, **extra}
        response = await instance.client.post(path, json=body)
        assert response.status_code == 401, path
        assert response.json()["error"] == "invalid_credentials"


async def test_an_external_accounts_password_cannot_be_reset(instance: Instance) -> None:
    await sign_in(instance)
    headers = {"cookie": f"{SESSION_COOKIE}={await admin_session(instance)}"}
    users = (await instance.client.get("/api/v1/users", headers=headers)).json()["users"]
    alice = next(u for u in users if u["username"] == "alice")

    response = await instance.client.put(
        f"/api/v1/users/{alice['id']}/password", json={"password": HORSE}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"] == "external_account"


async def test_an_external_account_creates_api_tokens_in_the_ui(instance: Instance) -> None:
    session = cookie(await sign_in(instance), SESSION_COOKIE).value
    headers = {"cookie": f"{SESSION_COOKIE}={session}"}

    created = await instance.client.post("/api/v1/tokens", json={"name": "laptop"}, headers=headers)
    token = created.json()["token"]
    libraries = await instance.client.get(
        "/api/v1/libraries", headers={"authorization": f"Bearer {token}"}
    )

    assert created.status_code == 201
    assert libraries.status_code == 200


async def test_a_revalidation_ends_the_session_of_a_lost_member(instance: Instance) -> None:
    session = cookie(await sign_in(instance), SESSION_COOKIE).value
    instance.issuer.users["u-1"].groups = []
    instance.clock.at += timedelta(minutes=61)

    report = await instance.container.identity.revalidate_external_accounts()

    assert report.revoked == 1
    state = await instance.client.get(
        "/api/v1/session", headers={"cookie": f"{SESSION_COOKIE}={session}"}
    )
    assert state.json()["state"] == "signed_out"


def test_the_cli_refuses_to_reset_an_external_accounts_password(tmp_path: Path) -> None:
    async def make_alice() -> None:
        clock = Clock()
        issuer = FakeIssuer(now=clock.now)
        issuer.add_user("u-1", "alice", groups=["docs"])
        stand_ins = SignInStandIns(clock=clock, transport=issuer.transport())
        container = Container.build(settings(data_dir=tmp_path), sign_in=stand_ins)
        async with container.running(jobs=False):
            await container.identity.create_first_admin(
                CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
            )
            transport = httpx.ASGITransport(app=create_app(container))
            async with httpx.AsyncClient(
                transport=transport, base_url="https://localhost"
            ) as client:
                inst = Instance(container=container, client=client, issuer=issuer, clock=clock)
                assert (await sign_in(inst)).headers["location"] == "/"

    asyncio.run(make_alice())
    tokens = ["user", "reset-password", "alice", "--password-stdin"]
    with (
        patch.dict(os.environ, {"EXACTDOCS_DATA_DIR": str(tmp_path)}),
        patch("sys.stdin", io.StringIO(HORSE + "\n")),
        redirect_stdout(io.StringIO()),
        pytest.raises(SystemExit, match="signs in through an identity provider"),
    ):
        cli.app(tokens, exit_on_error=False, result_action="return_value")


async def test_before_the_setup_no_external_sign_in_starts() -> None:
    issuer = FakeIssuer()
    container = Container.build(settings(), sign_in=SignInStandIns(transport=issuer.transport()))
    async with container.running():
        transport = httpx.ASGITransport(app=create_app(container))
        async with httpx.AsyncClient(transport=transport, base_url="https://localhost") as client:
            response = await client.get("/api/v1/auth/corp/start")

    assert response.status_code == 403
    assert response.json()["error"] == "setup_required"


# ---------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"public_url": None}, "EXACTDOCS_PUBLIC_URL is required"),
        ({"public_url": "https://docs.example.com/exactdocs"}, "no path"),
        ({"public_url": "docs.example.com"}, "no path"),
        (
            {"auth": {"providers": {"Corp": provider()}}},
            "lower-case letters, digits and hyphens",
        ),
        (
            {"auth": {"providers": {"password": provider()}}},
            "it names local \\(password\\) accounts",
        ),
        (
            {"auth": {"providers": {"corp": provider(issuer="http://idp.example.com")}}},
            "issuer must be an https:// URL",
        ),
        (
            {"auth": {"providers": {"corp": provider(allowed_groups=[])}}},
            "set allowed_groups, or allow_any_user",
        ),
        (
            {"auth": {"providers": {"corp": provider(scopes=["profile"])}}},
            "scopes must include openid",
        ),
        (
            {"auth": {"providers": {"corp": provider(client_secret_file="/run/secret")}}},
            "not both",
        ),
        ({"auth": {"providers": {"corp": provider(kind="saml")}}}, "kind"),
        (
            {"auth": {"providers": {"corp": provider(kind="oauth2")}}},
            "oauth2 requires secure authorization_url, token_url and userinfo_url",
        ),
        ({"auth": {"providers": {"corp": provider(scope="x")}}}, "scope"),
    ],
)
def test_an_invalid_provider_setting_stops_the_start_naming_it(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        settings(**overrides)


def test_a_provider_that_admits_anyone_says_so() -> None:
    config = provider(allowed_groups=[], allow_any_user=True)

    assert settings(auth={"providers": {"corp": config}}).auth.providers["corp"].allow_any_user


def test_the_public_url_loses_its_trailing_slash() -> None:
    assert settings(public_url="https://docs.example.com/").public_url == PUBLIC


def test_the_config_file_may_not_hold_a_client_secret(tmp_path: Path) -> None:
    path = tmp_path / "exactdocs.toml"
    path.write_text(
        '[auth.providers.corp]\nkind = "oidc"\nissuer = "https://idp.example.com"\n'
        'client_id = "x"\nclient_secret = "leaked"\n'
    )

    with pytest.raises(SettingsError, match=r"auth\.providers\.corp\.client_secret") as raised:
        read_config_file(path)
    assert "leaked" not in str(raised.value)


def test_providers_come_from_the_config_file_and_the_secret_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "exactdocs.toml"
    path.write_text(
        'public_url = "https://docs.example.com"\n'
        "[auth.providers.corp]\n"
        'kind = "oidc"\nissuer = "https://idp.example.com/adfs"\nclient_id = "x"\n'
        'username_claim = "upn"\ngroups_claim = "group"\nallowed_groups = ["docs"]\n'
    )
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(path))
    monkeypatch.setenv("EXACTDOCS_AUTH__PROVIDERS__CORP__CLIENT_SECRET", "from-the-env")

    corp = Settings().auth.providers["corp"]

    assert corp.issuer == "https://idp.example.com/adfs"
    assert (corp.username_claim, corp.groups_claim) == ("upn", "group")
    assert corp.client_secret is not None
    assert corp.client_secret.get_secret_value() == "from-the-env"
