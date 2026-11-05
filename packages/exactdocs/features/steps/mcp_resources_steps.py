"""Steps for the article resources, over the fixture repository imported in search_steps."""

import asyncio
import json
from typing import Any

from behave import then, when
from behave.runner import Context
from fastmcp import Client
from mcp.types import ListResourcesResult

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.catalog.adapters.driving.mcp import ARTICLE_TEMPLATE, RESOURCE_PAGE_SIZE
from exactdocs_kernel import NOTICE
from steps.mcp_stdio_steps import FRAMES, rpc, start
from steps.mcp_steps import call_tool

DEFAULT_REF = "v1.4.0"


async def _with_client(context: Context, action: Any) -> Any:
    container = Container.build(context.settings)
    async with container.running(), Client(build_mcp(container)) as mcp:
        return await action(mcp)


def _first_article(context: Context, library: str, ref: str | None) -> str:
    arguments = {"library": library} | ({"ref": ref} if ref else {})
    call_tool(context, "list_articles", arguments)
    return context.mcp_data["articles"][0]["path"]


def _read(context: Context, library: str, ref: str | None) -> None:
    path = _first_article(context, library, ref)
    owner, repo = library.removeprefix("/").split("/")
    uri = f"exactdocs://{owner}/{repo}/{path}" + (f"?ref={ref}" if ref else "")
    context.article_path = path
    context.resource = asyncio.run(_with_client(context, lambda mcp: mcp.read_resource(uri)))
    call_tool(context, "read_article", {"library": library, "path": path, "ref": ref})
    context.tool_markdown = context.mcp_result.content[1].text


@when('a client reads the first article of "{library}" at "{ref}" as a resource')
def step_read_pinned(context: Context, library: str, ref: str) -> None:
    _read(context, library, ref)
    context.expected_ref = ref


@when('a client reads the first article of "{library}" as a resource without a ref')
def step_read_default(context: Context, library: str) -> None:
    _read(context, library, None)
    context.expected_ref = DEFAULT_REF


@then('it gets the same Markdown as "read_article"')
@then('it gets the same Markdown as "read_article" at "{ref}"')
def step_same_markdown(context: Context, ref: str = DEFAULT_REF) -> None:
    assert context.resource[1].text == context.tool_markdown
    assert context.resource[1].meta["ref"] == ref, context.resource[1].meta


@then("the notice is the first thing it reads")
def step_notice_first(context: Context) -> None:
    assert context.resource[0].text == NOTICE


@when("a client lists the resources")
def step_list(context: Context) -> None:
    async def action(mcp: Client) -> list[Any]:
        pages: list[ListResourcesResult] = [await mcp.list_resources_mcp()]
        while pages[-1].next_cursor:
            pages.append(await mcp.list_resources_mcp(cursor=pages[-1].next_cursor))
        reads = [
            await mcp.read_resource(
                next(r for r in pages[0].resources if str(r.uri).startswith("exactdocs://")).uri
            )
        ]
        return [pages, reads]

    context.pages, context.listed_reads = asyncio.run(_with_client(context, action))


@then('every listed resource carries a "ref" and is one page of at most {size:d}')
def step_listed(context: Context, size: int) -> None:
    assert size == RESOURCE_PAGE_SIZE
    assert context.pages[0].resources
    for page in context.pages:
        assert len(page.resources) <= size
        # only `exactdocs://` articles carry a ref; first-party resources (skill://) do not
        for resource in page.resources:
            if str(resource.uri).startswith("exactdocs://"):
                assert f"?ref={DEFAULT_REF}" in str(resource.uri), resource.uri


@then("reading a listed resource gives the notice first")
def step_listed_read(context: Context) -> None:
    assert context.listed_reads[0][0].text == NOTICE


@when('a client reads a resource whose path climbs out with ".."')
def step_traversal(context: Context) -> None:
    uri = f"exactdocs://fixture/docs-repo/guide/..%2f..%2f..%2fREADME.md?ref={DEFAULT_REF}"
    context.resource_error = None

    async def action(mcp: Client) -> Any:
        return await mcp.read_resource(uri)

    try:
        context.resource = asyncio.run(_with_client(context, action))
    except Exception as exc:  # ruff: ignore[blind-except]
        context.resource_error = exc


@then("the read fails and no article is returned")
def step_failed(context: Context) -> None:
    assert context.resource_error is not None


@when('an agent starts "exactdocs serve --stdio" and lists resources')
def step_stdio(context: Context) -> None:
    process = start(context.settings.data_dir)
    assert process.stdin is not None
    rpc(process, FRAMES[0])
    process.stdin.write(json.dumps(FRAMES[1]) + "\n")
    context.stdio_templates = rpc(
        process, {"jsonrpc": "2.0", "id": 5, "method": "resources/templates/list"}
    )
    process.stdin.close()
    process.communicate(timeout=60)


@then("the article template is listed without any token")
def step_stdio_listed(context: Context) -> None:
    templates = context.stdio_templates["result"]["resourceTemplates"]
    assert [t["uriTemplate"] for t in templates] == [ARTICLE_TEMPLATE], templates
