"""Cloudflare Access over HTTP: the settings, REST and MCP callers, and what still wins over it."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.catalog.dtos import CreateLibraryCommand
from exactdocs.identity.constants import ACCESS_ASSERTION_HEADER, ACCESS_COOKIE, SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand, CreateUserCommand
from fake_cf_access import AUDIENCE, TEAM_DOMAIN, FakeAccess

HORSE = "correct horse battery staple"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def access_config(**overrides: Any) -> dict[str, Any]:
    return {
        "team_domain": TEAM_DOMAIN,
        "audience": [AUDIENCE],
        "service_tokens": {"abc.access": "ci-bot"},
        **overrides,
    }


@dataclass(slots=True)
class Instance:
    container: Container
    client: httpx.AsyncClient
    access: FakeAccess


@pytest.fixture
async def instance(tmp_path: Path) -> AsyncIterator[Instance]:
    access = FakeAccess()
    settings = Settings(data_dir=tmp_path, auth={"cloudflare_access": access_config()})
    container = Container.build(settings, sign_in=SignInStandIns(transport=access.transport()))
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await container.identity.create_user(
            CreateUserCommand(username="ci-bot", password=SecretStr(HORSE))
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield Instance(container=container, client=client, access=access)


async def send(
    instance: Instance,
    method: str,
    path: str,
    *,
    assertion: str | None = None,
    cookie: str | None = None,
    bearer: str | None = None,
    session: str | None = None,
    **options: Any,
) -> httpx.Response:
    instance.client.cookies.clear()
    headers = dict(options.pop("headers", {}))
    cookies = []
    if assertion:
        headers[ACCESS_ASSERTION_HEADER] = assertion
    if cookie:
        cookies.append(f"{ACCESS_COOKIE}={cookie}")
    if session:
        cookies.append(f"{SESSION_COOKIE}={session}")
    if cookies:
        headers["cookie"] = "; ".join(cookies)
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    return await instance.client.request(method, path, headers=headers, **options)


async def test_rest_routes_take_the_access_token_from_the_header_or_the_cookie(
    instance: Instance,
) -> None:
    token = instance.access.person("alice@example.com")

    by_header = await send(instance, "GET", "/api/v1/libraries", assertion=token)
    by_cookie = await send(instance, "GET", "/api/v1/libraries", cookie=token)
    nobody = await send(instance, "GET", "/api/v1/libraries")

    assert (by_header.status_code, by_cookie.status_code, nobody.status_code) == (200, 200, 401)


async def test_a_person_from_access_manages_her_api_tokens_without_a_session(
    instance: Instance,
) -> None:
    token = instance.access.person("alice@example.com")

    made = await send(instance, "POST", "/api/v1/tokens", assertion=token, json={"name": "cli"})

    assert made.status_code == 201, made.text
    secret = made.json()["token"]
    me = await send(instance, "GET", "/api/v1/tokens", bearer=secret)
    assert me.status_code == 401  # the token routes take a browser's sign-in, never a token


async def test_a_wrong_api_token_is_refused_even_with_a_valid_access_token(
    instance: Instance,
) -> None:
    token = instance.access.person("alice@example.com")

    refused = await send(instance, "GET", "/api/v1/libraries", assertion=token, bearer="exd_nope")

    assert refused.status_code == 401


async def test_an_explicit_api_token_acts_as_its_own_account_over_mcp(instance: Instance) -> None:
    alice = instance.access.person("alice@example.com")
    made = await send(instance, "POST", "/api/v1/tokens", assertion=alice, json={"name": "mcp"})
    secret = made.json()["token"]
    bot = instance.access.service("abc.access")

    with_token = await send(
        instance, "POST", "/mcp", assertion=bot, bearer=secret, json=LIST_TOOLS, headers=MCP_HEADERS
    )
    only_access = await send(
        instance, "POST", "/mcp", assertion=bot, json=LIST_TOOLS, headers=MCP_HEADERS
    )
    from_cookie = await send(
        instance, "POST", "/mcp/", cookie=bot, json=LIST_TOOLS, headers=MCP_HEADERS
    )
    nothing = await send(instance, "POST", "/mcp", json=LIST_TOOLS, headers=MCP_HEADERS)

    assert with_token.status_code == 200, with_token.text
    assert only_access.status_code == 200, only_access.text
    assert from_cookie.status_code == 200, from_cookie.text
    assert nothing.status_code == 401


async def test_a_token_library_scope_narrows_only_that_token_never_the_access_caller(
    instance: Instance,
) -> None:
    libraries = ("/acme/api", "/acme/docs")
    for library in libraries:
        await instance.container.catalog.create_library(
            CreateLibraryCommand(
                id=library, title=library, source_url="https://example.com/a/b.git", host="git"
            )
        )
    signed_in = await send(
        instance, "POST", "/api/v1/session", json={"username": "ada", "password": HORSE}
    )
    session = signed_in.cookies[SESSION_COOKIE]
    for library in libraries:
        granted = await send(
            instance,
            "PUT",
            f"/api/v1/libraries{library}/grants",
            session=session,
            json={"kind": "user", "subject": "ci-bot", "role": "viewer"},
        )
        assert granted.status_code == 200, granted.text
    bot = instance.access.service("abc.access")
    made = await send(
        instance,
        "POST",
        "/api/v1/tokens",
        assertion=bot,
        json={"name": "docs only", "library_ids": ["/acme/docs"]},
    )
    assert made.status_code == 201, made.text
    scoped = made.json()["token"]

    async def rest(**credentials: str) -> list[str]:
        response = await send(instance, "GET", "/api/v1/libraries", **credentials)
        assert response.status_code == 200, response.text
        return sorted(library["id"] for library in response.json()["libraries"])

    async def mcp(**credentials: str) -> list[str]:
        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_libraries", "arguments": {}},
        }
        response = await send(
            instance, "POST", "/mcp", json=call, headers=MCP_HEADERS, **credentials
        )
        assert response.status_code == 200, response.text
        data = next(
            line.removeprefix("data:")
            for line in response.text.splitlines()
            if line.startswith("data:")
        )
        found = json.loads(data)["result"]["structuredContent"]["libraries"]
        return sorted(library["id"] for library in found)

    # Access callers carry no token, so no selection: they keep their account's live grants.
    assert await rest(assertion=bot) == list(libraries)
    assert await mcp(assertion=bot) == list(libraries)
    # The scoped token narrows itself, also when an Access token rides along (the bearer wins).
    assert await rest(bearer=scoped) == ["/acme/docs"]
    assert await rest(bearer=scoped, assertion=bot) == ["/acme/docs"]
    assert await mcp(bearer=scoped, assertion=bot) == ["/acme/docs"]
    assert await mcp(assertion=bot) == list(libraries)


async def test_a_session_cookie_wins_over_the_access_token(instance: Instance) -> None:
    signed_in = await send(
        instance, "POST", "/api/v1/session", json={"username": "ada", "password": HORSE}
    )
    session = signed_in.cookies[SESSION_COOKIE]
    token = instance.access.person("alice@example.com")

    state = await send(instance, "GET", "/api/v1/session", session=session, assertion=token)

    body = state.json()
    assert (body["account"]["username"], body["source"]) == ("ada", "session")


async def test_without_the_setting_the_access_token_is_ignored(tmp_path: Path) -> None:
    access = FakeAccess()
    container = Container.build(Settings(data_dir=tmp_path))
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            token = access.person("ada@example.com")
            headers = {ACCESS_ASSERTION_HEADER: token}
            state = await client.get("/api/v1/session", headers=headers)
            listed = await client.get("/api/v1/libraries", headers=headers)
            mcp = await client.post("/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, **headers})

    assert state.json()["state"] == "signed_out"
    assert (listed.status_code, mcp.status_code) == (401, 401)
    assert access.certs_fetches == 0  # nothing even looked at it


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"team_domain": "http://team.cloudflareaccess.com"}, "team_domain"),
        ({"team_domain": "https://team.cloudflareaccess.com/app"}, "team_domain"),
        ({"audience": []}, "audience"),
        ({"audience": [" "]}, "audience"),
        ({"admin_emails": ["not-an-email"]}, "admin_emails"),
        ({"service_tokens": {"abc.access": "has space"}}, "service_tokens"),
        ({"service_tokens": {" ": "ci-bot"}}, "service_tokens"),
        ({"unknown": True}, "unknown"),
    ],
)
def test_an_invalid_access_setting_stops_the_start_naming_it(
    overrides: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationError, match=rf"cloudflare_access\.{field}"):
        Settings(auth={"cloudflare_access": access_config(**overrides)})


def test_the_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = "EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__"
    monkeypatch.setenv(f"{prefix}TEAM_DOMAIN", "https://team.cloudflareaccess.com/")
    monkeypatch.setenv(f"{prefix}AUDIENCE", '["aud-1", "aud-2"]')
    monkeypatch.setenv(f"{prefix}ADMIN_EMAILS", '["boss@example.com"]')
    monkeypatch.setenv(f"{prefix}AUTO_CREATE_USERS", "false")
    monkeypatch.setenv(f"{prefix}SERVICE_TOKENS", '{"abc.access": "ci-bot"}')

    config = Settings().auth.cloudflare_access

    assert config is not None
    assert config.team_domain == "https://team.cloudflareaccess.com"
    assert config.audience == ["aud-1", "aud-2"]
    assert config.admin_emails == ["boss@example.com"]
    assert config.auto_create_users is False
    assert config.service_tokens == {"abc.access": "ci-bot"}


def test_one_audience_tag_may_be_given_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "exactdocs.toml"
    path.write_text(
        '[auth.cloudflare_access]\nteam_domain = "https://team.cloudflareaccess.com"\n'
        'audience = "aud-1"\n'
        '[auth.cloudflare_access.service_tokens]\n"abc.access" = "ci-bot"\n'
    )
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(path))

    config = Settings().auth.cloudflare_access

    assert config is not None
    assert (config.audience, config.auto_create_users) == (["aud-1"], True)
    assert config.service_tokens == {"abc.access": "ci-bot"}
