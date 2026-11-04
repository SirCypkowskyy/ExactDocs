"""Who may search: REST accepts a session cookie or a bearer token, MCP only a bearer token."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
SEARCH = "/api/v1/libraries/acme/payments/search"
# The library does not exist, so a caller who got in sees 404 and one who did not sees 401.
ASKING = {"q": "hook"}


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
async def signed_in(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        login = {"username": "ada", "password": HORSE}
        assert (await client.post("/api/v1/session", json=login)).status_code == 201
        yield client


@pytest.fixture
async def token(signed_in: httpx.AsyncClient) -> str:
    response = await signed_in.post("/api/v1/tokens", json={"name": "agent"})
    return response.json()["token"]


@pytest.fixture
async def anonymous(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("credentials", "status"), [("none", 401), ("cookie", 404), ("bearer", 404)]
)
async def test_rest_search_needs_a_cookie_or_a_bearer(
    anonymous: httpx.AsyncClient,
    signed_in: httpx.AsyncClient,
    token: str,
    credentials: str,
    status: int,
) -> None:
    client, headers = {
        "none": (anonymous, {}),
        "cookie": (signed_in, {}),
        "bearer": (anonymous, {"authorization": f"Bearer {token}"}),
    }[credentials]

    response = await client.get(SEARCH, params=ASKING, headers=headers)

    assert response.status_code == status


def mcp_client(app: FastAPI, token: str | None) -> Client[StreamableHttpTransport]:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    transport = StreamableHttpTransport(
        "http://localhost/mcp",
        headers={"authorization": f"Bearer {token}"} if token else None,
        httpx_client_factory=factory,
    )
    return Client(transport)


CALL = {"library": "/acme/payments", "query": "hook"}


@pytest.mark.parametrize("credentials", ["none", "bearer"])
async def test_mcp_search_needs_a_bearer(app: FastAPI, token: str, credentials: str) -> None:
    async with app.router.lifespan_context(app):
        if credentials == "none":
            with pytest.raises(Exception, match="error response"):
                async with mcp_client(app, None) as mcp:
                    await mcp.call_tool("search_docs", CALL)
            return
        async with mcp_client(app, token) as mcp:
            result = await mcp.call_tool("search_docs", CALL, raise_on_error=False)
    assert result.is_error
    assert "not_found" in str(result.content)  # past authentication, into the use case


async def test_a_session_cookie_sent_to_mcp_is_refused(
    app: FastAPI, anonymous: httpx.AsyncClient, signed_in: httpx.AsyncClient
) -> None:
    cookie = {"cookie": f"exactdocs_session={signed_in.cookies['exactdocs_session']}"}
    async with app.router.lifespan_context(app):
        response = await anonymous.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": CALL},
            },
            headers={"accept": "application/json, text/event-stream", **cookie},
        )

    assert response.status_code == 401


CHUNK = "/api/v1/chunks/" + "f" * 32


@pytest.mark.parametrize(
    ("credentials", "status"), [("none", 401), ("cookie", 404), ("bearer", 404)]
)
async def test_rest_chunk_read_needs_a_cookie_or_a_bearer(
    anonymous: httpx.AsyncClient,
    signed_in: httpx.AsyncClient,
    token: str,
    credentials: str,
    status: int,
) -> None:
    client, headers = {
        "none": (anonymous, {}),
        "cookie": (signed_in, {}),
        "bearer": (anonymous, {"authorization": f"Bearer {token}"}),
    }[credentials]

    response = await client.get(CHUNK, headers=headers)

    assert response.status_code == status  # unknown ID: 404 for a caller who got in


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("read_chunk", {"chunk_id": "f" * 32}), ("read_article", {"library": "/a/b", "path": "x.md"})],
)
async def test_mcp_reads_need_a_bearer(
    app: FastAPI, token: str, tool: str, arguments: dict[str, str]
) -> None:
    async with app.router.lifespan_context(app):
        with pytest.raises(Exception, match="error response"):
            async with mcp_client(app, None) as mcp:
                await mcp.call_tool(tool, arguments)
        async with mcp_client(app, token) as mcp:
            result = await mcp.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error
    assert "not_found" in str(result.content)
