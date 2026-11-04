"""The admin's browser session over HTTP: cookie attributes, expiry on the server, CSRF, MCP."""

from collections.abc import AsyncIterator, Iterator
from http.cookies import SimpleCookie
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driving.http import SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
LOGIN = {"username": "ada", "password": HORSE}
FOREIGN = {"origin": "https://evil.example"}


async def create_admin(container: Container) -> None:
    command = CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    await container.identity.create_first_admin(command)


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running():
        yield container


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    await create_admin(container)
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        yield client


def set_cookie(response: httpx.Response) -> Any:
    jar: SimpleCookie = SimpleCookie()
    jar.load(response.headers["set-cookie"])
    return jar[SESSION_COOKIE]


def cookie_of(token: str) -> dict[str, str]:
    """A request header carrying exactly this session cookie (whatever the client's jar holds)."""
    return {"cookie": f"{SESSION_COOKIE}={token}"}


async def sign_in(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/v1/session", json=LOGIN)
    assert response.status_code == 201
    return set_cookie(response).value


async def test_signing_in_sets_an_httponly_lax_cookie_scoped_to_the_api(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/v1/session", json=LOGIN)

    assert response.status_code == 201
    cookie = set_cookie(response)
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/api"  # not sent to /mcp, nor to the UI's own pages
    assert cookie["max-age"] == str(30 * 24 * 3600)
    assert not cookie["secure"]  # plain http://localhost
    assert not cookie["domain"]  # host-only
    assert len(cookie.value) >= 43
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert (body["state"], body["account"]["username"]) == ("signed_in", "ada")
    assert cookie.value not in response.text
    assert HORSE not in response.text


async def test_the_cookie_is_secure_over_https_and_when_forced(container: Container) -> None:
    await create_admin(container)
    secure_app = create_app(container)
    forced_app = create_app(Container.build(Settings(secure_cookies=True)))
    for app, url in ((secure_app, "https://localhost"), (forced_app, "http://localhost")):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=url) as client:
            response = await client.post("/api/v1/session", json=LOGIN)

            assert response.status_code == 201
            assert set_cookie(response)["secure"] is True


async def test_the_server_stores_only_a_hash_of_the_token(
    client: httpx.AsyncClient, container: Container
) -> None:
    token = await sign_in(client)

    async with container.engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM identity_sessions"))).all()

    assert len(rows) == 1
    assert token not in "".join(str(value) for value in rows[0])


async def test_a_session_unlocks_the_api_and_names_the_admin(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/libraries")).status_code == 401
    await sign_in(client)

    assert (await client.get("/api/v1/libraries")).status_code == 200
    state = (await client.get("/api/v1/session")).json()
    assert (state["state"], state["account"]["username"]) == ("signed_in", "ada")


async def test_without_a_valid_cookie_the_api_answers_401_in_the_envelope(
    client: httpx.AsyncClient,
) -> None:
    for headers in ({}, cookie_of("forged"), cookie_of("")):
        response = await client.get("/api/v1/libraries", headers=headers)

        assert response.status_code == 401
        assert response.json()["error"] == "unauthenticated"
        assert response.json()["detail"]
        assert "set-cookie" not in response.headers


async def test_session_state_before_setup_and_when_signed_out(container: Container) -> None:
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        fresh = (await client.get("/api/v1/session")).json()
        await create_admin(container)
        signed_out = await client.get("/api/v1/session")

    assert fresh == {"state": "setup_required", "account": None}
    assert signed_out.json() == {"state": "signed_out", "account": None}
    assert signed_out.headers["cache-control"] == "no-store"


async def test_wrong_password_and_unknown_user_are_the_same_response(
    client: httpx.AsyncClient,
) -> None:
    wrong = await client.post("/api/v1/session", json={**LOGIN, "password": "wrong password!"})
    unknown = await client.post("/api/v1/session", json={**LOGIN, "username": "nobody"})
    invalid_name = await client.post("/api/v1/session", json={**LOGIN, "username": "a b"})

    for response in (wrong, unknown, invalid_name):
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    assert wrong.json() == unknown.json() == invalid_name.json()
    assert wrong.json()["error"] == "invalid_credentials"


async def test_signing_out_ends_the_session_on_the_server(client: httpx.AsyncClient) -> None:
    token = await sign_in(client)

    response = await client.delete("/api/v1/session")

    assert response.status_code == 204
    assert set_cookie(response)["max-age"] == "0"  # the browser drops it
    assert (await client.get("/api/v1/session")).json()["state"] == "signed_out"
    # A copy of the cookie (a thief's, or one the browser kept) is dead too.
    replay = await client.get("/api/v1/libraries", headers=cookie_of(token))
    assert replay.status_code == 401


async def test_signing_out_while_signed_out_is_fine(client: httpx.AsyncClient) -> None:
    assert (await client.delete("/api/v1/session")).status_code == 204
    gone = await client.delete("/api/v1/session", headers=cookie_of("forged"))
    assert gone.status_code == 204


async def test_each_sign_in_is_a_new_session(client: httpx.AsyncClient) -> None:
    first = await sign_in(client)
    client.cookies.clear()
    second = await sign_in(client)

    assert first != second
    assert (await client.get("/api/v1/libraries", headers=cookie_of(first))).status_code == 200


@pytest.mark.parametrize(
    ("method", "body"), [("POST", LOGIN), ("DELETE", None)], ids=["sign-in", "sign-out"]
)
async def test_a_foreign_origin_can_neither_sign_in_nor_out(
    client: httpx.AsyncClient, method: str, body: dict[str, str] | None
) -> None:
    token = await sign_in(client)

    response = await client.request(method, "/api/v1/session", json=body, headers=FOREIGN)

    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    still = await client.get("/api/v1/libraries", headers=cookie_of(token))
    assert still.status_code == 200  # the foreign sign-out did nothing


async def test_the_apps_own_origin_may_sign_in_and_out(client: httpx.AsyncClient) -> None:
    own = {"origin": "http://localhost:5173"}

    assert (await client.post("/api/v1/session", json=LOGIN, headers=own)).status_code == 201
    assert (await client.delete("/api/v1/session", headers=own)).status_code == 204


async def test_only_setup_and_the_session_routes_are_open(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    methods = {"get", "put", "post", "delete", "patch"}

    open_operations = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in methods and "security" not in operation
    }

    assert open_operations == {
        ("POST", "/api/v1/setup"),
        ("GET", "/api/v1/session"),
        ("POST", "/api/v1/session"),
        ("DELETE", "/api/v1/session"),
    }
    assert spec["components"]["securitySchemes"]["SessionCookie"]["in"] == "cookie"


MCP_HEADERS = {"accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


@pytest.fixture
def browser(container: Container) -> Iterator[TestClient]:
    # TestClient runs the app (and the MCP session manager's lifespan) in one event loop.
    with TestClient(create_app(container), base_url="http://localhost") as client:
        yield client


async def test_mcp_ignores_the_session_cookie(
    client: httpx.AsyncClient, browser: TestClient
) -> None:
    token = await sign_in(client)

    with_cookie = browser.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **cookie_of(token)})
    without = browser.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    # Whatever MCP answers an anonymous client (it is open until API tokens, E2-03), the
    # cookie changes nothing: it is not a credential there, so it grants no more.
    assert with_cookie.status_code == without.status_code == 200
    assert with_cookie.text == without.text
    assert token not in with_cookie.text
