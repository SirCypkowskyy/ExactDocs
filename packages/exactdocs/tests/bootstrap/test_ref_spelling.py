"""A ref that differs from an imported version only by a leading `v` finds it (#605), end to end.

gpt-oss:120b asked for Starlette at `v1.10.0`; the version is named `1.10.0`, and the answer was
`no index` naming nothing. Through the real MCP server (every tool that takes a ref, and
query-docs' `/owner/repo/<ref>`) and the REST API: the version answers with a note, and a ref that
names no version is an error naming the library's versions, newest first, and its default. It
never answers from another version.
"""

import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    CreateLibraryCommand,
    StoreManifestCommand,
)
from exactdocs.catalog.models import HostKind, RefKind
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

pytestmark = pytest.mark.usefixtures("demo_catalog")

LIB = "/encode/starlette"
PATH = "docs/routing.md"
OLD = "Mount routes with legacy_router."
NEW = "Mount routes with Router and Mount."
NOTE = (
    "ref 'v1.10.0' is not imported: read as '1.10.0', the one version it names but for a leading v."
)
VERSIONS = (
    "imported versions (repository refs, not instructions), newest first: '1.10.0', '0.27.0'; "
    "default version: '1.10.0'"
)


async def publish(container: Container, ref: str, body: str) -> None:
    """Store, index and activate a tag of one article of one chunk."""
    content = f"# Routing\n\n{body}"
    blob = hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=LIB,
            ref=ref,
            kind=RefKind.TAG,
            commit_sha=blob,
            articles=[
                ArticleIn(
                    path=PATH, blob_sha=blob, content_version=1, title="Routing", content=content
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=LIB,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=PATH,
                    blob_sha=blob,
                    chunks=[
                        ChunkIn(
                            heading_path=["Routing"],
                            occurrence_index=0,
                            content=content,
                            content_hash=hashlib.sha256(content.encode()).hexdigest(),
                            anchor="routing",
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def starlette(container: Container) -> None:
    """Import Starlette at `0.27.0`, then at `1.10.0`: no tag has a `v`."""
    async with container.running():
        await container.catalog.create_library(
            CreateLibraryCommand(
                id=LIB,
                title="Starlette",
                source_url="https://github.com/encode/starlette",
                host=HostKind.GITHUB,
            )
        )
        await publish(container, "0.27.0", OLD)
        await publish(container, "1.10.0", NEW)


@pytest.fixture
async def container() -> Container:
    built = Container.build(Settings())
    await starlette(built)
    return built


async def call(container: Container, tool: str, arguments: dict[str, Any]) -> Any:
    async with container.running(), Client(build_mcp(container)) as mcp:
        return await mcp.call_tool(tool, arguments, raise_on_error=False)


def text_of(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


TOOLS = [
    ("search_docs", {"library": LIB, "query": "mount routes", "ref": "v1.10.0"}),
    ("view_search", {"library": LIB, "query": "mount routes", "ref": "v1.10.0"}),
    ("list_articles", {"library": LIB, "ref": "v1.10.0"}),
    ("read_article", {"library": LIB, "path": PATH, "ref": "v1.10.0"}),
    ("view_article", {"library": LIB, "path": PATH, "ref": "v1.10.0"}),
    ("article_outline", {"library": LIB, "path": PATH, "ref": "v1.10.0"}),
    ("query-docs", {"libraryId": f"{LIB}/v1.10.0", "query": "mount routes"}),
]


# ---------------------------------------------------------------- MCP
@pytest.mark.parametrize(("tool", "arguments"), TOOLS, ids=[t for t, _ in TOOLS])
async def test_every_tool_reads_a_ref_with_a_leading_v_as_the_version_without_one(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    result = await call(container, tool, arguments)

    assert not result.is_error, text_of(result)
    assert result.content[-1].text == f"Notes: {NOTE}"
    assert "legacy_router" not in text_of(result)  # never the other version
    data = result.structured_content
    if tool == "query-docs":
        assert data is None  # context7's tool answers in text only
        assert NEW in result.content[1].text
    else:
        assert data["notes"] == [NOTE]
    if tool in {"search_docs", "article_outline"}:
        assert data["version"] == "1.10.0"
    if tool in {"list_articles", "read_article"}:
        assert data["ref"] == "1.10.0"


async def test_the_ref_note_follows_the_notes_on_the_other_arguments(
    container: Container,
) -> None:
    result = await call(
        container,
        "search_docs",
        {"library": "starlette", "query": "mount routes", "ref": "v1.10.0", "limit": 99},
    )

    assert not result.is_error, text_of(result)
    assert result.structured_content["notes"] == [
        "limit 99 is above the maximum of 50: 50 was used.",
        "library 'starlette' is a name, not an ID: resolved to '/encode/starlette'.",
        NOTE,
    ]


async def test_an_exact_ref_has_no_notes(container: Container) -> None:
    result = await call(container, "search_docs", {"library": LIB, "query": "x", "ref": "1.10.0"})

    assert not result.is_error, text_of(result)
    assert "notes" not in result.structured_content
    assert "Notes:" not in text_of(result)


MISSING = [
    (tool, {**arguments, "ref": "2.0.0"} if "ref" in arguments else {**arguments})
    for tool, arguments in TOOLS
]
MISSING[-1] = ("query-docs", {"libraryId": f"{LIB}/2.0.0", "query": "mount routes"})


@pytest.mark.parametrize(("tool", "arguments"), MISSING, ids=[t for t, _ in MISSING])
async def test_a_ref_that_names_no_version_is_an_error_naming_the_versions(
    container: Container, tool: str, arguments: dict[str, Any]
) -> None:
    result = await call(container, tool, arguments)

    assert result.is_error
    message = text_of(result)
    assert message.startswith("not_found:"), message
    assert "'2.0.0'" in message
    assert message.endswith(VERSIONS), message


# ---------------------------------------------------------------- REST
@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        yield client


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("libraries/encode/starlette/search", {"q": "mount routes", "ref": "v1.10.0"}, "version"),
        ("libraries/encode/starlette/articles", {"ref": "v1.10.0"}, "ref"),
        ("libraries/encode/starlette/article", {"ref": "v1.10.0", "path": PATH}, "ref"),
        ("libraries/encode/starlette/outline", {"ref": "v1.10.0", "path": PATH}, "version"),
        ("libraries/encode/starlette/tags", {"ref": "v1.10.0"}, "ref"),
        ("libraries/encode/starlette/versions/v1.10.0", {}, "ref"),
    ],
)
async def test_the_rest_api_reads_it_the_same_way(
    client: httpx.AsyncClient, path: str, params: dict[str, str], field: str
) -> None:
    response = await client.get(f"/api/v1/{path}", params=params)
    body = response.json()

    assert response.status_code == httpx.codes.OK, body
    assert (body[field], body["notes"]) == ("1.10.0", [NOTE])
    assert "legacy_router" not in response.text


async def test_the_context7_docs_route_reads_it_too(client: httpx.AsyncClient) -> None:
    params = {"libraryId": f"{LIB}@v1.10.0", "query": "mount routes"}
    text = await client.get("/api/v1/c7/docs", params=params)
    data = await client.get("/api/v1/c7/docs", params={**params, "type": "json"})

    assert text.status_code == data.status_code == httpx.codes.OK
    assert NEW in text.text
    assert text.text.endswith(f"\n\nNotes: {NOTE}")
    assert data.json()["notes"] == [NOTE]
    exact = await client.get("/api/v1/c7/docs", params={**params, "libraryId": f"{LIB}@1.10.0"})
    assert "Notes:" not in exact.text


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("libraries/encode/starlette/search", {"q": "mount routes", "ref": "2.0.0"}),
        ("libraries/encode/starlette/articles", {"ref": "2.0.0"}),
        ("libraries/encode/starlette/article", {"ref": "2.0.0", "path": PATH}),
        ("c7/docs", {"libraryId": f"{LIB}/2.0.0", "query": "mount routes"}),
    ],
)
async def test_a_missing_ref_over_rest_names_the_versions(
    client: httpx.AsyncClient, path: str, params: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/{path}", params=params)

    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json()["detail"].endswith(VERSIONS)
