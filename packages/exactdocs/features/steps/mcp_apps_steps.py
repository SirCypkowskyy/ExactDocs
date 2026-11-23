"""Steps for the MCP App tools: view_article and view_search render as UI, with a text fallback."""

import asyncio
from collections.abc import Iterator
from typing import Any

from behave import then, when
from behave.runner import Context
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.ingestion.models import parse_article
from exactdocs_kernel import NOTICE
from steps.search_steps import read_version

APP_MIME_TYPE = "text/html;profile=mcp-app"


def _split(target: str) -> tuple[str, str]:
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    return f"/{owner}/{repo}", ref


def _as_app_host(context: Context, tool: str, arguments: dict[str, Any]) -> None:
    """Do what an MCP Apps host does: read the tool's UI resource, then call the tool."""

    async def go() -> tuple[str | None, CallToolResult, dict[str, Any] | None]:
        container = Container.build(context.settings)
        async with container.running(jobs=False), Client(build_mcp(container)) as mcp:
            listed = next(t for t in await mcp.list_tools() if t.name == tool)
            (renderer,) = await mcp.read_resource(listed.meta["ui"]["resourceUri"])
            result = await mcp.call_tool(tool, arguments, raise_on_error=False)
            searched = None
            if tool == "view_search":
                searched = (await mcp.call_tool("search_docs", arguments)).structured_content
            return renderer.mime_type, result, searched

    context.renderer_mime_type, context.mcp_result, context.searched = asyncio.run(go())


def _nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("children", []):
        yield from _nodes(child)


def _shown(app: dict[str, Any], component: str, field: str = "content") -> list[str]:
    """What the renderer shows in ``field`` of each ``component``: the state value it names."""
    state = app["state"]
    return [
        state[node[field].removeprefix("{{ ").removesuffix(" }}")]
        for node in _nodes(app["view"])
        if node["type"] == component
    ]


@when('a host that supports MCP Apps calls "view_article" for "{path}" of "{target}"')
def step_view_article(context: Context, path: str, target: str) -> None:
    library, ref = _split(target)
    context.read_library, context.read_path, context.read_ref = library, path, ref
    _as_app_host(context, "view_article", {"library": library, "ref": ref, "path": path})


@when('a host that supports MCP Apps calls "view_search" for "{query}" in "{target}"')
def step_view_search(context: Context, query: str, target: str) -> None:
    library, ref = _split(target)
    context.search_query = query
    _as_app_host(context, "view_search", {"library": library, "ref": ref, "query": query})


def _article(context: Context) -> str:
    _, files = read_version(context, context.read_ref)
    return parse_article(context.read_path, dict(files)[context.read_path]).body


@then("it renders the article with headings and code")
def step_renders_article(context: Context) -> None:
    result = context.mcp_result
    assert not result.is_error, result
    assert context.renderer_mime_type == APP_MIME_TYPE
    app = result.structured_content
    body = _article(context)
    assert "\n## " in body, "the fixture article has headings"
    assert "```bash" in body, "and code"
    assert _shown(app, "Markdown") == [body]  # the host renders the Markdown: headings and code
    (title,) = _shown(app, "Heading")
    assert title
    assert NOTICE in str(app["view"]), "the UI shows the untrusted-content notice"


@then("hosts without Apps support get a text fallback")
def step_article_fallback(context: Context) -> None:
    notice, header, text = (block.text for block in context.mcp_result.content)
    commit = context.commits[context.read_ref]
    assert notice == NOTICE
    assert f"- Version: {context.read_ref}\n- Commit: {commit}" in header, header
    assert text == _article(context)


@then('"read_article" is unchanged')
def step_read_article_unchanged(context: Context) -> None:
    async def go() -> tuple[dict[str, Any] | None, CallToolResult]:
        container = Container.build(context.settings)
        async with container.running(jobs=False), Client(build_mcp(container)) as mcp:
            listed = next(t for t in await mcp.list_tools() if t.name == "read_article")
            arguments = {
                "library": context.read_library,
                "ref": context.read_ref,
                "path": context.read_path,
            }
            return listed.meta, await mcp.call_tool("read_article", arguments)

    meta, result = asyncio.run(go())
    assert not (meta or {}).get("ui"), meta
    assert all(isinstance(block, TextContent) for block in result.content), result.content
    assert [getattr(block, "text", None) for block in result.content] == [
        NOTICE,
        _article(context),
    ]
    data = result.structured_content
    assert data is not None
    assert data["notice"] == NOTICE
    assert "$prefab" not in data


@then("it renders each result with its heading path and a link to its source")
def step_renders_results(context: Context) -> None:
    result = context.mcp_result
    assert not result.is_error, result
    assert context.renderer_mime_type == APP_MIME_TYPE
    app = result.structured_content
    found = context.searched["results"]
    assert found, "the fixture has matches"
    titles = [" > ".join(r["heading_path"]) or r["article_path"] for r in found]
    assert _shown(app, "CardTitle") == titles
    assert _shown(app, "Link", "href") == [r["source_url"] for r in found]
    assert _shown(app, "Markdown") == [r["snippet"] for r in found]


@then("hosts without Apps support get the same results as text after the notice")
def step_results_fallback(context: Context) -> None:
    notice, text = (block.text for block in context.mcp_result.content)
    assert notice == NOTICE
    positions = [text.index(f"Chunk: {r['chunk_id']}") for r in context.searched["results"]]
    assert positions == sorted(positions), "best first, as search_docs ranks them"
