from collections.abc import AsyncIterator

import httpx
import pytest
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_lists_demo_libraries(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries")

    assert response.status_code == 200
    assert {lib["name"] for lib in response.json()["libraries"]} == {"fastapi", "react"}


async def test_domain_errors_map_to_http_status(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/vue")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_search_for_unindexed_version_is_404_not_another_version(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/search", params={"library": "react", "version": "18.3", "query": "hook"}
    )

    assert response.status_code == 404


async def test_mcp_exposes_read_only_tools(container: Container) -> None:
    async with Client(build_mcp(container)) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        result = await mcp.call_tool("list_libraries", {})

    assert set(tools) == {"list_libraries", "search_docs"}
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert result.structured_content is not None
