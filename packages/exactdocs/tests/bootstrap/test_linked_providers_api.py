"""Linking sign-in providers over HTTP (#506): Account settings, the callback, presets, icons."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.identity.constants import SESSION_COOKIE, SIGN_IN_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand
from fake_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIssuer

HORSE = "correct horse battery staple"
PUBLIC = "https://docs.example.com"
ICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" onload="alert(1)">'
    b'<script>alert(1)</script><path d="M0 0h24v24H0z" fill="#123456"/></svg>'
)
TENANT = "11111111-2222-3333-4444-555555555555"
MICROSOFT = "https://login.microsoftonline.com"
TEMPLATE = f"{MICROSOFT}/{{tenantid}}/v2.0"


@dataclass(slots=True)
class Clock:
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class Instance:
    container: Container
    client: httpx.AsyncClient
    issuer: FakeIssuer
    provider: str


def corp(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "oidc",
        "display_name": "Corp SSO",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "allow_any_user": True,
        **overrides,
    }


@asynccontextmanager
async def running(
    providers: dict[str, dict[str, Any]], issuer: FakeIssuer, provider: str = "corp"
) -> AsyncGenerator[Instance]:
    clock = Clock()
    issuer.now = clock.now
    settings = Settings(public_url=PUBLIC, auth={"providers": providers})
    container = Container.build(
        settings, sign_in=SignInStandIns(clock=clock, transport=issuer.transport())
    )
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        transport = httpx.ASGITransport(app=create_app(container))
        async with httpx.AsyncClient(transport=transport, base_url="https://localhost") as client:
            yield Instance(container=container, client=client, issuer=issuer, provider=provider)


@pytest.fixture
def icon_file(tmp_path: Path) -> Path:
    path = tmp_path / "corp.svg"
    path.write_bytes(ICON)
    return path


@pytest.fixture
async def instance(icon_file: Path) -> AsyncIterator[Instance]:
    issuer = FakeIssuer()
    issuer.add_user("u-1", "ada-at-corp", groups=["docs"])
    issuer.add_user("u-2", "bob", groups=["docs"])
    async with running({"corp": corp(icon_file=str(icon_file))}, issuer) as started:
        yield started


async def password_session(instance: Instance, username: str = "ada") -> str:
    response = await instance.client.post(
        "/api/v1/session", json={"username": username, "password": HORSE}
    )
    assert response.status_code == 201, response.text
    instance.client.cookies.clear()
    return response.cookies[SESSION_COOKIE]


def as_session(session: str | None) -> dict[str, str]:
    return {} if session is None else {"cookie": f"{SESSION_COOKIE}={session}"}


async def start_link(instance: Instance, session: str, **body: str) -> httpx.Response:
    instance.client.cookies.clear()
    return await instance.client.post(
        f"/api/v1/account/providers/{instance.provider}/link",
        json=body or None,
        headers=as_session(session),
    )


async def link(
    instance: Instance, session: str, subject: str, *, back_with: str | None = None, **body: str
) -> httpx.Response:
    """The browser's whole link: start it, sign in at the issuer, come back with a session."""
    begun = await start_link(instance, session, **body)
    assert begun.status_code == 200, begun.text
    binding = begun.cookies[SIGN_IN_COOKIE]
    callback = instance.issuer.authorize(begun.json()["redirect_url"], subject)
    instance.client.cookies.clear()
    cookies = f"{SIGN_IN_COOKIE}={binding}"
    if back := session if back_with is None else back_with:  # "": no session at all
        cookies += f"; {SESSION_COOKIE}={back}"
    return await instance.client.get(callback, headers={"cookie": cookies})


async def sign_in(instance: Instance, subject: str) -> httpx.Response:
    instance.client.cookies.clear()
    begun = await instance.client.get(f"/api/v1/auth/{instance.provider}/start")
    assert begun.status_code == 303, begun.text
    callback = instance.issuer.authorize(begun.headers["location"], subject)
    response = await instance.client.get(callback)
    instance.client.cookies.clear()
    return response


async def whoami(instance: Instance, session: str) -> dict[str, Any]:
    response = await instance.client.get("/api/v1/session", headers=as_session(session))
    return response.json()


async def providers(instance: Instance, session: str) -> dict[str, Any]:
    response = await instance.client.get("/api/v1/account/providers", headers=as_session(session))
    assert response.status_code == 200, response.text
    return response.json()


def location(response: httpx.Response) -> tuple[str, dict[str, list[str]]]:
    assert response.status_code == 303, response.text
    parts = urlsplit(response.headers["location"])
    return parts.path, parse_qs(parts.query)


# ---------------------------------------------------------------- linking


async def test_account_settings_list_the_providers_to_link(instance: Instance) -> None:
    session = await password_session(instance)

    listed = await providers(instance, session)

    [corp_listed] = listed["providers"]
    assert listed["has_password"] is True
    assert corp_listed["name"] == "corp"
    assert (corp_listed["linked"], corp_listed["can_link"], corp_listed["can_unlink"]) == (
        False,
        True,
        False,
    )
    assert corp_listed["icon_url"].startswith("/api/v1/auth/corp/icon?v=")


async def test_a_link_comes_back_to_account_settings_and_keeps_the_session(
    instance: Instance,
) -> None:
    session = await password_session(instance)

    begun = await start_link(instance, session)
    binding = begun.cookies[SIGN_IN_COOKIE]
    assert begun.headers["cache-control"] == "no-store"
    assert binding not in begun.json()["redirect_url"]
    assert urlsplit(begun.json()["redirect_url"]).path == "/authorize"
    response = await link(instance, session, "u-1")

    assert location(response) == ("/account", {"linked": ["corp"]})
    assert SESSION_COOKIE not in response.cookies  # no new session, the old one stays
    assert (await whoami(instance, session))["account"]["username"] == "ada"
    [linked] = (await providers(instance, session))["providers"]
    assert (linked["linked"], linked["origin"], linked["can_unlink"]) == (True, False, True)
    # From now on the identity signs ada in.
    signed_in = await sign_in(instance, "u-1")
    assert location(signed_in)[0] == "/"
    assert (await whoami(instance, signed_in.cookies[SESSION_COOKIE]))["account"]["role"] == (
        "admin"
    )


async def test_a_link_returns_to_a_path_on_this_server_only(instance: Instance) -> None:
    session = await password_session(instance)

    back = await link(instance, session, "u-1", return_to="/account?tab=sign-in")
    await instance.client.delete("/api/v1/account/providers/corp", headers=as_session(session))
    away = await link(instance, session, "u-1", return_to="https://evil.example/x")

    assert location(back) == ("/account", {"tab": ["sign-in"], "linked": ["corp"]})
    assert location(away) == ("/", {"linked": ["corp"]})


async def test_a_link_finished_by_another_session_is_refused(instance: Instance) -> None:
    session = await password_session(instance)
    other = await sign_in(instance, "u-2")  # bob, through corp
    bob = other.cookies[SESSION_COOKIE]

    for back_with in (bob, ""):
        refused = await link(instance, session, "u-1", back_with=back_with)
        assert location(refused) == ("/account", {"link_error": ["sign_in_failed"]})
    assert not (await providers(instance, session))["providers"][0]["linked"]


async def test_an_identity_of_another_account_is_refused(instance: Instance) -> None:
    await sign_in(instance, "u-2")  # bob's account is created through u-2
    session = await password_session(instance)

    refused = await link(instance, session, "u-2")

    assert location(refused) == ("/account", {"link_error": ["identity_linked_elsewhere"]})


async def test_linking_twice_or_with_an_api_token_is_refused(instance: Instance) -> None:
    session = await password_session(instance)
    await link(instance, session, "u-1")
    token = await instance.client.post(
        "/api/v1/tokens", json={"name": "cli"}, headers=as_session(session)
    )
    bearer = {"authorization": f"Bearer {token.json()['token']}"}

    again = await start_link(instance, session)
    with_token = await instance.client.post("/api/v1/account/providers/corp/link", headers=bearer)
    unknown = await instance.client.post(
        "/api/v1/account/providers/nope/link", headers=as_session(session)
    )

    assert (again.status_code, again.json()["error"]) == (409, "provider_linked")
    assert with_token.status_code == 401
    assert (unknown.status_code, unknown.json()["error"]) == (404, "unknown_provider")


async def test_unlinking_ends_the_sign_in_and_the_origin_stays(instance: Instance) -> None:
    session = await password_session(instance)
    await link(instance, session, "u-1")

    unlinked = await instance.client.delete(
        "/api/v1/account/providers/corp", headers=as_session(session)
    )
    again = await instance.client.delete(
        "/api/v1/account/providers/corp", headers=as_session(session)
    )
    bob = (await sign_in(instance, "u-2")).cookies[SESSION_COOKIE]
    last = await instance.client.delete("/api/v1/account/providers/corp", headers=as_session(bob))

    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["providers"][0]["linked"] is False
    assert (again.status_code, again.json()["error"]) == (404, "provider_not_linked")
    assert (last.status_code, last.json()["error"]) == (409, "last_sign_in_method")
    # u-1 no longer reaches ada: its sign-in now creates an account of its own.
    stranger = await sign_in(instance, "u-1")
    assert (await whoami(instance, stranger.cookies[SESSION_COOKIE]))["account"]["username"] == (
        "ada-at-corp"
    )


# ---------------------------------------------------------------- icons


async def test_the_operators_icon_is_served_sanitised_from_this_server(
    instance: Instance,
) -> None:
    state = (await instance.client.get("/api/v1/session")).json()
    [listed] = state["providers"]
    assert listed["icon"] is None

    served = await instance.client.get(listed["icon_url"])

    assert served.status_code == 200
    assert served.headers["content-type"] == "image/svg+xml"
    assert b"script" not in served.content
    assert b"onload" not in served.content
    assert b'fill="#123456"' in served.content
    assert "sandbox" in served.headers["content-security-policy"]
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "public, max-age=86400"
    version = parse_qs(urlsplit(listed["icon_url"]).query)["v"][0]
    assert served.headers["etag"] == f'"{version}"'
    cached = await instance.client.get(
        "/api/v1/auth/corp/icon", headers={"if-none-match": served.headers["etag"]}
    )
    assert (cached.status_code, cached.content) == (304, b"")


async def test_only_an_operators_icon_is_served() -> None:
    issuer = FakeIssuer()
    async with running({"corp": corp(icon="google")}, issuer) as instance:
        built_in = await instance.client.get("/api/v1/auth/corp/icon")
        unknown = await instance.client.get("/api/v1/auth/nope/icon")
        state = (await instance.client.get("/api/v1/session")).json()

    assert (built_in.status_code, built_in.json()["error"]) == (404, "no_icon")
    assert (unknown.status_code, unknown.json()["error"]) == (404, "unknown_provider")
    assert [(p["icon"], p["icon_url"]) for p in state["providers"]] == [("google", None)]


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"<svg><script/></svg>", "root must be"),
        (b"GIF89a....", "not a PNG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>' + b" " * 70_000, "larger than"),
    ],
)
def test_an_unacceptable_icon_file_stops_the_start(
    tmp_path: Path, content: bytes, reason: str
) -> None:
    path = tmp_path / "icon.svg"
    path.write_bytes(content)
    settings = Settings(
        data_dir=tmp_path,
        public_url=PUBLIC,
        auth={"providers": {"corp": corp(icon_file=str(path))}},
    )

    with pytest.raises(StartupError, match=f"'corp'.*{reason}"):
        Container.build(settings)


# ---------------------------------------------------------------- presets


async def test_google_needs_only_its_client_and_asks_for_a_refresh_token() -> None:
    issuer = FakeIssuer(issuer="https://accounts.google.com")
    google = {"kind": "google", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    async with running({"google": google}, issuer, "google") as instance:
        state = (await instance.client.get("/api/v1/session")).json()
        begun = await instance.client.get("/api/v1/auth/google/start")

    assert state["providers"] == [
        {"name": "google", "display_name": "Google", "icon": "google", "icon_url": None}
    ]
    query = parse_qs(urlsplit(begun.headers["location"]).query)
    assert query["access_type"] == ["offline"]
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]


async def test_microsoft_for_any_organization_links_each_tenants_people() -> None:
    issuer = FakeIssuer(
        issuer=f"{MICROSOFT}/organizations/v2.0", discovered_issuer=TEMPLATE, token_issuer=TEMPLATE
    )
    issuer.add_user("m-1", "ada@contoso.com", tenant=TENANT)
    microsoft = {
        "kind": "microsoft",
        "tenant": "organizations",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    async with running({"microsoft": microsoft}, issuer, "microsoft") as instance:
        # Nobody gets an account through a preset: only a linked identity signs in.
        stranger = await sign_in(instance, "m-1")
        session = await password_session(instance)
        linked = await link(instance, session, "m-1")
        signed_in = await sign_in(instance, "m-1")
        ada = await instance.container.identity.identify_caller(session)
        identity = await instance.container.identity.list_account_providers(ada)

    assert location(stranger) == ("/sign-in", {"error": ["not_linked"]})
    assert location(linked) == ("/account", {"linked": ["microsoft"]})
    assert location(signed_in)[0] == "/"
    [listed] = identity.providers
    assert (listed.name, listed.icon, listed.linked) == ("microsoft", "microsoft", True)
