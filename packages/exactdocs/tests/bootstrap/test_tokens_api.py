"""API tokens over HTTP: REST routes, bearer auth, MCP auth, and the list of open routes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
LOGIN = {"username": "ada", "password": HORSE}


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield container


@pytest.fixture
def app(container: Container) -> FastAPI:
    return create_app(container)


@pytest.fixture
async def anonymous(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        yield client


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client with its own cookie jar, signed in.

    Yields:
        The signed-in client.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.post("/api/v1/session", json=LOGIN)).status_code == 201
        yield client


async def create(admin: httpx.AsyncClient, **body: object) -> dict[str, str]:
    response = await admin.post("/api/v1/tokens", json={"name": "laptop", **body})
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_secret_comes_back_from_post_only_and_is_stored_hashed(
    admin: httpx.AsyncClient, container: Container
) -> None:
    response = await admin.post("/api/v1/tokens", json={"name": "laptop"})

    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert body["token"].startswith("exd_")
    assert set(body) == {
        "id",
        "name",
        "prefix",
        "created_at",
        "expires_at",
        "last_used_at",
        "token",
    }
    listed = (await admin.get("/api/v1/tokens")).json()
    assert [t["id"] for t in listed["tokens"]] == [body["id"]]
    assert body["token"] not in str(listed)
    async with container.engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM identity_api_tokens"))).all()
    assert body["token"] not in str(rows)


async def test_a_token_authenticates_the_rest_api_and_revoking_ends_it(
    admin: httpx.AsyncClient, anonymous: httpx.AsyncClient
) -> None:
    created = await create(admin)

    ok = await anonymous.get("/api/v1/libraries", headers=bearer(created["token"]))
    assert ok.status_code == 200
    assert (await admin.get("/api/v1/tokens")).json()["tokens"][0]["last_used_at"]

    assert (await admin.delete(f"/api/v1/tokens/{created['id']}")).status_code == 204
    refused = await anonymous.get("/api/v1/libraries", headers=bearer(created["token"]))
    assert refused.status_code == 401
    assert refused.json()["error"] == "unauthenticated"
    gone = await admin.delete(f"/api/v1/tokens/{created['id']}")
    assert (gone.status_code, gone.json()["error"]) == (404, "unknown_token")


async def test_an_expired_token_is_refused_as_unauthenticated(
    admin: httpx.AsyncClient, anonymous: httpx.AsyncClient, container: Container
) -> None:
    created = await create(admin, expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    async with container.engine.begin() as connection:
        await connection.execute(
            text("UPDATE identity_api_tokens SET expires_at = :t"), {"t": past}
        )

    response = await anonymous.get("/api/v1/libraries", headers=bearer(created["token"]))

    assert (response.status_code, response.json()["error"]) == (401, "unauthenticated")


async def test_a_wrong_bearer_is_not_rescued_by_a_valid_cookie(admin: httpx.AsyncClient) -> None:
    response = await admin.get("/api/v1/libraries", headers=bearer("exd_wrong"))

    assert response.status_code == 401


async def test_an_empty_or_foreign_authorization_is_not_rescued_by_a_valid_cookie(
    admin: httpx.AsyncClient,
) -> None:
    for value in ("Bearer ", "Bearer", "Basic abc", "exd_raw"):
        response = await admin.get("/api/v1/libraries", headers={"authorization": value})
        assert response.status_code == 401, value


async def test_another_accounts_token_is_a_404_like_a_missing_one(
    admin: httpx.AsyncClient, container: Container
) -> None:
    async with container.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO identity_accounts VALUES ('bob', 'bob', 'x', 'admin', '2026-01-01');")
        )
        await connection.execute(
            text(
                "INSERT INTO identity_api_tokens (id, account_id, name, token_hash, prefix, "
                "created_at) VALUES ('t-bob', 'bob', 'b', 'h', 'exd_', '2026-01-01')"
            )
        )

    foreign = await admin.delete("/api/v1/tokens/t-bob")
    missing = await admin.delete("/api/v1/tokens/nope")

    assert (foreign.status_code, foreign.json()["error"]) == (404, "unknown_token")
    assert foreign.json() == missing.json()


async def test_the_token_name_has_a_length_limit_in_the_schema(admin: httpx.AsyncClient) -> None:
    response = await admin.post("/api/v1/tokens", json={"name": "x" * 1000})

    assert response.status_code == 422


async def test_creating_a_token_validates_its_input(admin: httpx.AsyncClient) -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    for body, status, code in [
        ({"name": ""}, 422, "invalid_token_name"),
        ({"name": "x", "expires_at": yesterday}, 422, "invalid_token_expiry"),
        ({"name": "x", "expires_at": "2099-01-01T00:00:00"}, 422, "validation_error"),  # naive
        ({"name": "x", "extra": 1}, 422, "validation_error"),
    ]:
        response = await admin.post("/api/v1/tokens", json=body)
        assert (response.status_code, response.json()["error"]) == (status, code)


async def test_tokens_are_managed_with_a_session_not_with_a_token(
    admin: httpx.AsyncClient, anonymous: httpx.AsyncClient
) -> None:
    created = await create(admin)
    headers = bearer(created["token"])

    for method, path in [
        ("POST", "/api/v1/tokens"),
        ("GET", "/api/v1/tokens"),
        ("DELETE", f"/api/v1/tokens/{created['id']}"),
    ]:
        response = await anonymous.request(method, path, headers=headers, json={"name": "x"})
        assert response.status_code == 401, (method, path)
    assert len((await admin.get("/api/v1/tokens")).json()["tokens"]) == 1


# Everything under /api/v1 needs a caller except these. A new open route must be added here
# on purpose, which makes it a review decision.
OPEN_ROUTES = {
    ("POST", "/api/v1/setup"),
    ("GET", "/api/v1/session"),
    ("POST", "/api/v1/session"),
    ("DELETE", "/api/v1/session"),
    ("GET", "/api/v1/openapi.json"),
}


async def test_every_route_needs_a_caller_except_the_listed_ones(
    app: FastAPI, anonymous: httpx.AsyncClient
) -> None:
    routes = {
        (method, ctx.path)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute) and (ctx.path or "").startswith("/api/v1")
        for method in ctx.original_route.methods or ()
        if ctx.path
    }
    assert routes > OPEN_ROUTES

    for method, path in sorted(routes - OPEN_ROUTES):
        concrete = path.replace("{token_id}", "t1").replace("{", "").replace("}", "")
        response = await anonymous.request(method, concrete)
        assert response.status_code == 401, (method, path, response.text)
    # health is outside /api/v1
    assert (await anonymous.get("/api/health")).status_code == 200


def mcp_client(app: FastAPI, token: str | None) -> Client[StreamableHttpTransport]:
    """A FastMCP client that talks to the app in-process, over the real HTTP transport."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:  # the MCP SDK ships its own fork of httpx
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    transport = StreamableHttpTransport(
        "http://localhost/mcp",
        headers=bearer(token) if token else None,
        httpx_client_factory=factory,
    )
    return Client(transport)


async def test_an_mcp_client_with_the_token_lists_the_libraries_until_it_is_revoked(
    app: FastAPI, admin: httpx.AsyncClient
) -> None:
    created = await create(admin)
    async with app.router.lifespan_context(app):
        async with mcp_client(app, created["token"]) as mcp:
            result = await mcp.call_tool("list_libraries", {})
            assert result.structured_content is not None

        assert (await admin.delete(f"/api/v1/tokens/{created['id']}")).status_code == 204
        with pytest.raises(Exception, match="error response"):
            async with mcp_client(app, created["token"]) as mcp:
                await mcp.call_tool("list_libraries", {})


async def test_mcp_refuses_callers_without_a_valid_token_even_with_a_session_cookie(
    app: FastAPI, anonymous: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    # Sent by hand: the jar would not send a cookie scoped to `/api` to `/mcp` anyway.
    cookie = {"cookie": f"exactdocs_session={admin.cookies['exactdocs_session']}"}
    async with app.router.lifespan_context(app):
        for extra in ({}, cookie):
            for auth in ({}, bearer("exd_wrong"), bearer(""), {"authorization": "Basic abc"}):
                response = await anonymous.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers={"accept": "application/json, text/event-stream", **extra, **auth},
                )
                assert response.status_code == 401, (extra.keys(), auth)
