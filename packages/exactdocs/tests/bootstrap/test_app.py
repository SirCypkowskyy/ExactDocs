from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import alembic_config
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import LibraryId, RefKind, Version, VersionRef

pytestmark = pytest.mark.usefixtures("demo_catalog")


def alembic_head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head() or ""


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    # ASGITransport does not run the app's lifespan, which is what migrates the database.
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", cookies=demo_catalog
        ) as client,
    ):
        yield client


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_reports_the_schema_revision(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.json()["schema_revision"] == alembic_head()


async def test_lists_demo_libraries(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries")

    assert response.status_code == 200
    assert {lib["id"] for lib in response.json()["libraries"]} == {
        "/acme/ledger",
        "/acme/payments",
    }


async def test_a_library_is_shown_with_its_default_version(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/Acme/Payments")

    body = response.json()
    assert response.status_code == 200
    assert (body["id"], body["host"], body["default_version"]) == (
        "/acme/payments",
        "github",
        "v1.4.0",
    )
    assert {v["ref"]: v["is_default"] for v in body["versions"]} == {
        "main": False,
        "next": False,
        "v1.3.0": False,
        "v1.4.0": True,
    }
    assert body["settings"]["chunking"] == {"split_level": 6, "min_chars": 0, "max_chars": None}


@pytest.mark.parametrize("ref", ["v1.3.0", "v1.4.0", "main"])
async def test_a_version_is_addressed_by_its_ref(client: httpx.AsyncClient, ref: str) -> None:
    response = await client.get(f"/api/v1/libraries/acme/payments/versions/{ref}")

    assert response.status_code == 200
    assert (response.json()["library"], response.json()["ref"]) == ("/acme/payments", ref)


async def test_the_ref_is_everything_after_versions_even_with_slashes_or_a_short_sha(
    client: httpx.AsyncClient, container: Container
) -> None:
    repository = SqliteLibraryRepository(container.engine)
    payments = await repository.get(LibraryId("/acme/payments"))
    assert payments is not None
    imported_at = datetime(2026, 11, 4, tzinfo=UTC)
    extra = {
        Version(
            ref=VersionRef("release/1.4"),
            kind=RefKind.BRANCH,
            commit_sha="d" * 40,
            imported_at=imported_at,
        ),
        Version(
            ref=VersionRef("fedcba98"),
            kind=RefKind.COMMIT,
            commit_sha="fedcba9876" + "0" * 30,
            imported_at=imported_at,
        ),
    }
    await repository.save(replace(payments, versions=payments.versions | extra))
    base = "/api/v1/libraries/acme/payments/versions"

    for path, ref in [
        ("release/1.4", "release/1.4"),
        ("release%2F1.4", "release/1.4"),
        ("fedcba98", "fedcba98"),
        ("fedcba9876", "fedcba98"),
    ]:
        response = await client.get(f"{base}/{path}")

        assert response.status_code == 200, path
        assert response.json()["ref"] == ref


async def test_a_trailing_slash_after_the_ref_is_another_url_not_found(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/libraries/acme/payments/versions/v1.4.0/")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/libraries/vuejs/docs",
        "/api/v1/libraries/vuejs/docs/versions/v1",
        "/api/v1/libraries/acme/payments/versions/v9.9.9",
        "/api/v1/libraries/acme/payments/versions/V1.4.0",
    ],
)
async def test_unknown_libraries_and_versions_are_not_found(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/libraries/acme/pay$ments", "/api/v1/libraries/acme/payments/versions/a%20b"],
)
async def test_a_malformed_id_or_ref_is_a_validation_error(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_domain_errors_map_to_http_status(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/vuejs/docs")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_search_for_unindexed_version_is_404_not_another_version(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/search",
        params={"ref": "v1.2.0", "q": "hook"},
    )

    assert response.status_code == 404


async def test_mcp_exposes_read_only_tools(container: Container) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        result = await mcp.call_tool("list_libraries", {})

    assert set(tools) == {"list_libraries", "search_docs"}
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert result.structured_content is not None


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
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def localhost_client(container: Container) -> Iterator[TestClient]:
    # TestClient runs the app (and the MCP session manager's lifespan) in one event loop.
    with TestClient(create_app(container), base_url="http://localhost") as client:
        yield client


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_endpoint_answers_on_both_paths_without_redirect(
    localhost_client: TestClient, path: str
) -> None:
    response = localhost_client.post(
        path, json=INITIALIZE, headers=MCP_HEADERS, follow_redirects=False
    )

    # Reached (not redirected, not 404) and asking for an API token.
    assert response.status_code == 401


def test_mcp_rejects_unknown_hosts(localhost_client: TestClient) -> None:
    response = localhost_client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "host": "evil.example"}
    )

    assert response.status_code in {400, 403, 421}


def test_settings_defaults_are_local_and_private(tmp_path_factory: pytest.TempPathFactory) -> None:
    data_dir = tmp_path_factory.mktemp("data")
    settings = Settings(data_dir=data_dir)

    assert settings.telemetry == "off"
    assert settings.metrics is False
    assert settings.effective_database_url == (
        f"sqlite+aiosqlite:///{(data_dir / 'exactdocs.db').as_posix()}"
    )


def test_unknown_host_is_rejected_app_wide(localhost_client: TestClient) -> None:
    response = localhost_client.get("/api/health", headers={"host": "evil.example"})

    assert response.status_code == 400


def test_unsafe_request_from_foreign_origin_is_rejected(localhost_client: TestClient) -> None:
    response = localhost_client.post(
        "/api/v1/libraries", headers={"origin": "https://evil.example"}
    )

    assert response.status_code == 403


def test_configured_host_is_accepted(container: Container) -> None:
    settings = Settings(allowed_hosts="docs.example.com, *.corp.example")
    app = create_app(Container.build(settings))

    with TestClient(app, base_url="http://docs.example.com") as client:
        assert client.get("/api/health").status_code == 200
    assert settings.allowed_hosts == ["docs.example.com", "*.corp.example"]
    assert container.settings.allowed_hosts == []


async def test_mcp_domain_errors_become_tool_errors(container: Container) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        result = await mcp.call_tool(
            "search_docs",
            {"library": "/acme/payments", "ref": "v1.2.0", "query": "hook"},
            raise_on_error=False,
        )

    assert result.is_error
    assert "not_found" in str(result.content)


async def test_a_blank_or_malformed_ref_is_not_found_not_a_validation_error(
    client: httpx.AsyncClient,
) -> None:
    for ref in ("", "v 1"):
        response = await client.get(
            "/api/v1/libraries/acme/payments/search", params={"ref": ref, "q": "hook"}
        )
        assert response.status_code == 404, ref
        assert response.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x" * 1001},
        {"q": "x", "ref": "r" * 257},
        {"q": "x", "tags": [f"t{i}" for i in range(21)]},
        {"q": "x", "tags": ["t" * 101]},
        {"q": "x", "tags": ",".join(f"t{i}" for i in range(21))},
    ],
)
async def test_rest_search_input_is_capped(
    client: httpx.AsyncClient, params: dict[str, Any]
) -> None:
    response = await client.get("/api/v1/libraries/acme/payments/search", params=params)

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


@pytest.mark.parametrize(
    "arguments",
    [
        {"library": "/acme/payments", "query": "x" * 1001},
        {"library": "/acme/payments", "query": "x", "ref": "r" * 257},
        {"library": "/acme/payments", "query": "x", "tags": [f"t{i}" for i in range(21)]},
        {"library": "/acme/payments", "query": "x", "tags": ["t" * 101]},
        {"library": "/" + "a" * 256 + "/b", "query": "x"},
        {"library": "/acme/payments/v1", "query": "x"},
        {"library": "react", "query": "x"},
    ],
)
async def test_mcp_search_input_is_capped_and_the_library_shape_checked(
    container: Container, arguments: dict[str, Any]
) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        result = await mcp.call_tool("search_docs", arguments, raise_on_error=False)

    assert result.is_error
    assert "not_found" not in str(result.content)


async def test_mcp_search_accepts_a_blank_ref_as_the_default_version(container: Container) -> None:
    async with container.running(), Client(build_mcp(container)) as mcp:
        result = await mcp.call_tool(
            "search_docs",
            {"library": "/acme/payments", "ref": "", "query": "hook"},
            raise_on_error=False,
        )

    assert "not_found" in str(result.content)
