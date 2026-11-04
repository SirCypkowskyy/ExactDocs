"""Steps for reading articles and chunks verbatim, over MCP and REST."""

import asyncio
from typing import Any
from urllib.parse import quote

from behave import given, then, when
from behave.runner import Context
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.ingestion.models import parse_article
from exactdocs_kernel import NOTICE
from steps.search_steps import REPOSITORY, _read_version

SHA_LENGTH = 40


def _call(context: Context, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    async def go() -> CallToolResult:
        container = Container.build(context.settings)
        async with container.running(), Client(build_mcp(container)) as mcp:
            return await mcp.call_tool(tool, arguments, raise_on_error=False)

    context.mcp_result = asyncio.run(go())
    return context.mcp_result


def _split(target: str) -> tuple[str, str]:
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    return f"/{owner}/{repo}", ref


@when('an agent reads "{path}" of "{target}"')
def step_read_article(context: Context, path: str, target: str) -> None:
    library, ref = _split(target)
    context.read_path, context.read_ref = path, ref
    _call(context, "read_article", {"library": library, "ref": ref, "path": path})


@then("the Markdown arrives as a plain text block, identical to the imported file")
def step_markdown(context: Context) -> None:
    result = context.mcp_result
    assert not result.is_error, result
    _, files = _read_version(context, context.read_ref)
    expected = parse_article(context.read_path, dict(files)[context.read_path]).body
    assert [c.type for c in result.content] == ["text"], result.content
    assert result.content[0].text == expected, result.content[0].text[:200]


@then("the structured content has its front matter, commit SHA and source link")
def step_structured(context: Context) -> None:
    data = context.mcp_result.structured_content
    commit = context.commits[context.read_ref]
    assert data["front_matter"]["title"], data
    assert data["commit_sha"] == commit and len(commit) == SHA_LENGTH, data
    assert data["source_url"] == f"{REPOSITORY}/blob/{commit}/{quote(context.read_path)}", data
    assert (data["ref"], data["path"]) == (context.read_ref, context.read_path), data
    assert "content" not in data, "the text is the text block, not repeated"


@then("the structured content carries the untrusted-content notice")
def step_notice(context: Context) -> None:
    assert context.mcp_result.structured_content["notice"] == NOTICE


@then('the tool error lists "{path}" as a close match')
def step_close(context: Context, path: str) -> None:
    result = context.mcp_result
    assert result.is_error, result
    assert path in result.content[0].text, result.content[0].text


@then('the tool error code is "{code}"')
def step_error_code(context: Context, code: str) -> None:
    result = context.mcp_result
    assert result.is_error, result
    assert result.content[0].text.startswith(f"{code}:"), result.content[0].text


@given('a search result for "{query}" in "{target}"')
def step_search_result(context: Context, query: str, target: str) -> None:
    library, ref = _split(target)
    owner, repo = library.removeprefix("/").split("/")
    response = context.client.get(
        f"/api/v1/libraries/{owner}/{repo}/search", params={"q": query, "ref": ref}
    )
    assert response.status_code == 200, response.text
    # The first hit with a next chunk, so the neighbor read has somewhere to go.
    context.hit = next(r for r in response.json()["results"] if r["next_chunk_id"])
    context.hit_ref = ref


@when("the agent reads its next chunk ID")
def step_read_next(context: Context) -> None:
    _call(context, "read_chunk", {"chunk_id": context.hit["next_chunk_id"]})


@then("it gets that chunk verbatim with its location and the IDs of its own neighbors")
def step_neighbor(context: Context) -> None:
    result, hit = context.mcp_result, context.hit
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["chunk_id"] == hit["next_chunk_id"], data
    assert data["article_path"] == hit["article_path"], data
    assert data["position"] == hit["position"] + 1, data
    assert data["total"] == hit["total"], data
    assert data["prev_chunk_id"] == hit["chunk_id"], data
    assert "next_chunk_id" in data, data
    assert data["notice"] == NOTICE, data
    # The text block is the chunk's stored text, nothing added around it.
    assert [c.type for c in result.content] == ["text"], result.content
    assert result.content[0].text == data["content"], data
    # Chunk text is cut from the article body, so it appears in it unchanged.
    _, files = _read_version(context, context.hit_ref)
    body = parse_article(data["article_path"], dict(files)[data["article_path"]]).body
    assert data["content"].strip() in body, data["content"]


@when("a client reads the chunk of that result over REST")
def step_rest_chunk(context: Context) -> None:
    context.response = context.client.get(f"/api/v1/chunks/{context.hit['chunk_id']}")


@when('a client reads the chunk "{chunk_id}" over REST')
def step_rest_unknown(context: Context, chunk_id: str) -> None:
    context.response = context.client.get(f"/api/v1/chunks/{chunk_id}")


@then("the chunk is that result's text with its commit SHA and source link")
def step_rest_chunk_body(context: Context) -> None:
    body, hit = context.response.json(), context.hit
    assert hit["snippet"] in body["content"], body
    assert body["commit_sha"] == hit["commit_sha"], body
    assert body["source_url"] == hit["source_url"], body
    assert body["notice"] == NOTICE, body
