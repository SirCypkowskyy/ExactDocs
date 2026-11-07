"""The `/api/v1` conventions: OpenAPI description, error envelope, pagination, route rules."""

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.rest import v1_openapi_json
from exactdocs.bootstrap.settings import Settings

pytestmark = pytest.mark.usefixtures("demo_catalog")

COMMITTED_SPEC = Path(__file__).parents[4] / "web" / "openapi.json"
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
def app(container: Container):
    return create_app(container)


@pytest.fixture
async def client(
    app, container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    # ASGITransport does not run the app's lifespan, which is what migrates the database.
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        yield client


@pytest.fixture
async def spec(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    return response.json()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


async def test_every_operation_has_a_stable_id_and_documents_the_error_envelope(
    spec: dict[str, Any],
) -> None:
    ops = operations(spec)
    ids = [op["operationId"] for _, _, op in ops]

    assert ops
    assert len(set(ids)) == len(ids)
    for path, _, op in ops:
        assert path.startswith("/api/v1/")
        assert op["operationId"] == f"{op['tags'][0]}-{op['operationId'].split('-', 1)[1]}"
        assert re.fullmatch(r"[a-z]+-[a-z_]+", op["operationId"])
        for status in ("400", "404", "409", "422"):
            schema = op["responses"][status]["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


async def test_only_v1_operations_are_published(spec: dict[str, Any]) -> None:
    assert not any(path.startswith(("/mcp", "/api/health")) for path in spec["paths"])


async def test_the_preview_documents_its_429_and_retry_after(spec: dict[str, Any]) -> None:
    busy = spec["paths"]["/api/v1/repositories/preview"]["post"]["responses"]["429"]

    assert busy["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert "preview_busy" in busy["description"]
    assert "Retry-After" in busy["headers"]


def test_operation_descriptions_leave_out_the_python_docstring_sections(app) -> None:
    document = json.loads(v1_openapi_json(app))
    descriptions = [
        op["description"]
        for ops in document["paths"].values()
        for op in ops.values()
        if "description" in op
    ]
    assert descriptions
    assert not [
        d for d in descriptions if re.search(r"^\s*(Args|Returns|Raises):", d, re.MULTILINE)
    ]


def test_committed_openapi_file_is_up_to_date(app) -> None:
    """If this fails the API changed: run `just api` and commit `web/openapi.json` + types."""
    assert COMMITTED_SPEC.read_text() == v1_openapi_json(app)


async def test_domain_errors_use_the_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/vuejs/docs")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "detail": "library '/vuejs/docs' is not in the catalog",
        "message": "library '/vuejs/docs' is not in the catalog",
        "fields": [],
        "close_matches": [],
    }


async def test_validation_errors_are_422_with_field_details(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert body["fields"][0]["loc"] == ["query", "limit"]


async def test_list_endpoints_paginate_with_limit_and_opaque_cursor(
    client: httpx.AsyncClient,
) -> None:
    first = (await client.get("/api/v1/libraries", params={"limit": 1})).json()
    second = (
        await client.get("/api/v1/libraries", params={"limit": 1, "cursor": first["next_cursor"]})
    ).json()

    assert [lib["id"] for lib in first["libraries"]] == ["/acme/ledger"]
    assert [lib["id"] for lib in second["libraries"]] == ["/acme/payments"]
    assert second["next_cursor"] is None


async def test_a_cursor_the_api_did_not_issue_is_a_422(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries", params={"cursor": "***"})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_cursor"


async def test_refs_only_ever_come_last_and_article_paths_are_query_parameters(
    spec: dict[str, Any],
) -> None:
    for path, _, op in operations(spec):
        segments = path.split("/")
        for i, segment in enumerate(segments):
            assert not segment.startswith("{path"), f"{path}: article paths go in `?path=`"
            if segment.startswith("{ref"):
                assert i == len(segments) - 1, f"{path}: the ref must be the last segment"
        if any(p["name"] == "path" for p in op.get("parameters", [])):
            assert all(p["in"] == "query" for p in op["parameters"] if p["name"] in {"path", "ref"})


@pytest.mark.parametrize(
    ("method", "path", "status", "error"),
    [
        ("GET", "/api/v1/nope", 404, "not_found"),
        ("DELETE", "/api/v1/libraries", 405, "method_not_allowed"),
        ("GET", "/api/nope", 404, "not_found"),
    ],
)
async def test_framework_errors_under_api_use_the_envelope(
    client: httpx.AsyncClient, method: str, path: str, status: int, error: str
) -> None:
    response = await client.request(method, path)

    assert response.status_code == status
    assert response.json()["error"] == error
    assert response.json()["detail"]


async def test_unhandled_errors_under_api_are_500_envelopes(app) -> None:
    async def boom() -> None:
        msg = "secret internals"
        raise RuntimeError(msg)

    app.add_api_route("/api/v1/boom", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/v1/boom")

    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json() == {
        "error": "internal_error",
        "detail": "internal server error",
        "message": "internal server error",
        "fields": [],
        "close_matches": [],
    }


async def test_ui_paths_keep_the_spa_fallback_and_default_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "index.html").write_text("<div id=root></div>")
    monkeypatch.setattr("exactdocs.bootstrap.http.WEB_DIST", tmp_path)
    app = create_app(Container.build(Settings()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        page = await client.get("/libraries/x", headers={"accept": "text/html"})
        missing = await client.get("/assets/missing.js")

    assert page.status_code == 200
    assert "id=root" in page.text
    assert missing.status_code == 404
    assert "error" not in missing.text
