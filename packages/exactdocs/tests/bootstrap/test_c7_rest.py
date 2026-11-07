"""context7's REST API over the MCP tools' use cases: same text, same auth, pinned shapes."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.rest import v1_openapi
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.retrieval.constants import CHARS_PER_TOKEN
from exactdocs_kernel import NOTICE
from next_library import LIBRARY, REF, import_next

PIN = json.loads(
    (
        Path(__file__).parents[1] / "contracts" / "context7" / "rest" / "openapi-excerpt.json"
    ).read_text("utf-8")
)
HORSE = "correct horse battery staple"
JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await import_next(container)
        yield container


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as http:
        await http.post("/api/v1/session", json={"username": "ada", "password": HORSE})
        token = (await http.post("/api/v1/tokens", json={"name": "agent"})).json()["token"]
        http.cookies.clear()  # a token alone, like an integration
        http.headers["authorization"] = f"Bearer {token}"
        yield http


async def test_docs_text_equals_the_query_docs_payload(
    container: Container, client: httpx.AsyncClient
) -> None:
    arguments = {
        "libraryId": f"{LIBRARY}/{REF}",
        "query": "protect routes",
        "language": "typescript",
    }
    async with Client(build_mcp(container)) as mcp:
        mcp_result = await mcp.call_tool("query-docs", arguments)

    response = await client.get("/api/v1/c7/docs", params=arguments)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == f"{NOTICE}\n\n{mcp_result.content[1].text}"
    assert response.headers["x-exactdocs-notice"] == NOTICE == mcp_result.content[0].text


async def test_an_at_version_id_answers_like_the_slash_form(client: httpx.AsyncClient) -> None:
    ask = {"query": "protect routes"}
    slash = await client.get("/api/v1/c7/docs", params={**ask, "libraryId": f"{LIBRARY}/{REF}"})
    at = await client.get("/api/v1/c7/docs", params={**ask, "libraryId": f"{LIBRARY}@{REF}"})

    assert at.status_code == 200
    assert at.text == slash.text


async def test_search_lists_the_same_libraries_as_resolve_library_id(
    container: Container, client: httpx.AsyncClient
) -> None:
    arguments = {"libraryName": "next", "query": "middleware"}
    async with Client(build_mcp(container)) as mcp:
        mcp_text = (await mcp.call_tool("resolve-library-id", arguments)).content[1].text

    body = (await client.get("/api/v1/c7/search", params=arguments)).json()

    assert body["notice"] == NOTICE
    assert [r["id"] for r in body["results"]] == [LIBRARY]
    assert f"- Context7-compatible library ID: {LIBRARY}\n" in mcp_text
    (found,) = body["results"]
    assert (found["title"], found["versions"], found["branch"]) == ("Next.js", [REF], REF)
    assert found["lastUpdateDate"]


async def test_json_docs_hold_the_same_chunks_as_the_text(client: httpx.AsyncClient) -> None:
    params = {"libraryId": LIBRARY, "query": "protect routes"}
    text = (await client.get("/api/v1/c7/docs", params=params)).text

    body = (await client.get("/api/v1/c7/docs", params={**params, "type": "json"})).json()

    assert body["notice"] == NOTICE
    assert body["codeSnippets"] == []
    (snippet,) = body["infoSnippets"]
    assert snippet["rank"] == 1
    assert snippet["breadcrumb"] == "Middleware"
    assert snippet["content"] in text


async def test_the_responses_have_context7s_shapes(client: httpx.AsyncClient) -> None:
    found = (
        await client.get("/api/v1/c7/search", params={"libraryName": "n", "query": "x"})
    ).json()
    assert set(PIN["search"]["required"]) <= set(found)
    (library,) = found["results"]
    pinned = PIN["search"]["libraryProperties"]
    for name, value in library.items():
        if name in pinned:  # the rest are ExactDocs' own extras
            assert isinstance(value, JSON_TYPES[pinned[name]]), name

    docs = (
        await client.get(
            "/api/v1/c7/docs", params={"libraryId": LIBRARY, "query": "routes", "type": "json"}
        )
    ).json()
    for name, kind in PIN["context"]["properties"].items():
        if name in docs:
            assert isinstance(docs[name], JSON_TYPES[kind]), name
    for snippet in docs["infoSnippets"]:
        for name, kind in PIN["context"]["infoSnippetProperties"].items():
            assert isinstance(snippet[name], JSON_TYPES[kind]), name


def test_the_openapi_document_accepts_context7s_parameters(container: Container) -> None:
    paths = v1_openapi(create_app(container))["paths"]
    for key, path in (("search", "/api/v1/c7/search"), ("context", "/api/v1/c7/docs")):
        ours = {p["name"]: p for p in paths[path]["get"]["parameters"]}
        for name, pinned in PIN[key]["parameters"].items():
            if name == "fast":  # no LLM reranking here: FastAPI ignores it, any value is fine
                continue
            assert name in ours, name
            assert ours[name]["required"] == pinned["required"], name
        if "type" in ours:
            assert ours["type"]["schema"]["enum"] == ["txt", "json"]
            assert ours["type"]["schema"]["default"] == "txt"


async def test_a_caller_without_a_token_is_refused(container: Container) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as anonymous:
        for path, params in (
            ("search", {"libraryName": "next", "query": "x"}),
            ("docs", {"libraryId": LIBRARY, "query": "x"}),
        ):
            assert (await anonymous.get(f"/api/v1/c7/{path}", params=params)).status_code == 401


async def test_errors_use_the_api_envelope(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/c7/docs", params={"libraryId": "/a/b", "query": "x"})
    assert (missing.status_code, missing.json()["error"]) == (404, "not_found")
    # context7 clients read `message`; it says what `detail` says.
    assert missing.json()["message"] == missing.json()["detail"]

    bad = await client.get("/api/v1/c7/docs", params={"libraryId": "nope", "query": "x"})
    assert (bad.status_code, bad.json()["error"]) == (422, "validation_error")

    kind = await client.get(
        "/api/v1/c7/docs", params={"libraryId": LIBRARY, "query": "x", "type": "xml"}
    )
    assert kind.status_code == 422


async def test_content_tokens_count_the_text_that_is_sent(client: httpx.AsyncClient) -> None:
    body = (
        await client.get(
            "/api/v1/c7/docs", params={"libraryId": LIBRARY, "query": "routes", "type": "json"}
        )
    ).json()

    for snippet in body["infoSnippets"]:
        assert snippet["contentTokens"] == len(snippet["content"]) // CHARS_PER_TOKEN
