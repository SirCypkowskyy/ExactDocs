"""Steps that drive the MCP tools through an in-process FastMCP client."""

import asyncio
import json
from typing import Any

from behave import then, when
from behave.runner import Context
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs_kernel import NOTICE

LIBRARY = "/fixture/docs-repo"
SHA_LENGTH = 40


def call_tool(
    context: Context, tool: str, arguments: dict[str, Any], *, raise_on_error: bool = True
) -> None:
    async def go() -> Any:
        container = Container.build(context.settings)
        async with container.running(), Client(build_mcp(container)) as mcp:
            return await mcp.call_tool(tool, arguments, raise_on_error=raise_on_error)

    result = asyncio.run(go())
    context.mcp_result = result
    context.mcp_data = result.structured_content


@when('an agent calls "list_libraries"')
def step_list_libraries(context: Context) -> None:
    call_tool(context, "list_libraries", {})


@when('an agent calls "list_articles" for "{library}" with limit {limit:d}')
def step_list_articles_limit(context: Context, library: str, limit: int) -> None:
    context.mcp_arguments = {"library": library, "limit": limit}
    call_tool(context, "list_articles", context.mcp_arguments)


@when('an agent calls "list_articles"')
def step_list_articles(context: Context) -> None:
    call_tool(context, "list_articles", {"library": LIBRARY})


@when("it calls again with that cursor")
def step_next_page(context: Context) -> None:
    context.first_page = context.mcp_data
    call_tool(
        context,
        "list_articles",
        {**context.mcp_arguments, "cursor": context.first_page["next_cursor"]},
    )


@then(
    '"{library}" is listed with title, description and versions with commit SHAs',
)
def step_listed(context: Context, library: str) -> None:
    (found,) = [lib for lib in context.mcp_data["libraries"] if lib["id"] == library]
    assert found["title"], found
    assert "description" in found, found
    assert "tags" in found, found
    assert {v["ref"] for v in found["refs"]} == {"v1.3.0", "v1.4.0"}, found
    assert all(len(v["commit_sha"]) == SHA_LENGTH for v in found["refs"]), found
    context.listed = found


@then('"{ref}" is marked as the default version')
def step_default(context: Context, ref: str) -> None:
    defaults = [v["ref"] for v in context.listed["refs"] if v["is_default"]]
    assert defaults == [ref], defaults


@then("it gets {count:d} articles of the default version and a cursor")
def step_first_page(context: Context, count: int) -> None:
    data = context.mcp_data
    assert len(data["articles"]) == count, data
    assert data["ref"] == "v1.4.0", data
    assert data["next_cursor"], data


@then("it gets the next articles")
def step_second_page(context: Context) -> None:
    first = {a["path"] for a in context.first_page["articles"]}
    second = [a["path"] for a in context.mcp_data["articles"]]
    assert second, context.mcp_data
    assert not first & set(second), (first, second)
    assert min(second) > max(first), (first, second)


@then('its structured result has a "notice" field and the version used')
def step_notice(context: Context) -> None:
    data = context.mcp_data
    assert data["notice"] == NOTICE, data
    assert data["library"] == LIBRARY, data
    assert data["ref"] == "v1.4.0", data
    assert len(data["commit_sha"]) == SHA_LENGTH, data


@then("the text the agent reads starts with the notice")
def step_text_first(context: Context) -> None:
    text = context.mcp_result.content[0].text
    body = json.loads(text)
    assert next(iter(body)) == "notice", text[:200]
    assert body["notice"] == NOTICE


@when('an agent calls "search_docs" for "{library}" version "{ref}" and "{query}"')
def step_search(context: Context, library: str, ref: str, query: str) -> None:
    call_tool(
        context,
        "search_docs",
        {"library": library, "ref": ref, "query": query},
        raise_on_error=False,
    )


@when('an agent calls "search_docs" with mode "{mode}"')
def step_search_mode(context: Context, mode: str) -> None:
    call_tool(
        context,
        "search_docs",
        {"library": LIBRARY, "query": "retry_policy", "mode": mode},
        raise_on_error=False,
    )


@then('the result is explicitly empty for "{ref}" with retrieval mode "{mode}"')
def step_empty(context: Context, ref: str, mode: str) -> None:
    data = context.mcp_data
    assert data["version"] == ref, data
    assert data["results"] == [], data
    assert data["retrieval_mode"] == mode, data
    assert data["coverage"]["complete"] is True, data


@then('the tool error says there is no index for "{target}"')
def step_no_index(context: Context, target: str) -> None:
    assert context.mcp_result.is_error, context.mcp_result
    assert f"no index for {target}" in context.mcp_result.content[0].text


@then('the tool error lists the available modes "{modes}"')
def step_modes(context: Context, modes: str) -> None:
    assert context.mcp_result.is_error, context.mcp_result
    assert f"available modes: {modes}" in context.mcp_result.content[0].text


@then("the search result has the notice and every result has a source link and a commit SHA")
def step_search_shape(context: Context) -> None:
    data = context.mcp_data
    assert data["notice"] == NOTICE, data
    assert data["results"], data
    for result in data["results"]:
        assert result["source_url"], result
        assert len(result["commit_sha"]) == SHA_LENGTH, result
