"""Steps for the arguments agents send loosely (#573): normalized, clamped, resolved or refused."""

import asyncio

from behave import then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.retrieval.adapters.driving.mcp import format_library
from exactdocs.retrieval.dtos import ResolveLibraryIdQuery
from steps.mcp_steps import call_tool

MAX_ARTICLES = 200


def _text(context: Context) -> str:
    return "\n".join(getattr(c, "text", "") for c in context.mcp_result.content)


@when('an agent calls "resolve-library-id" with libraryName "{name}" and an empty query')
def step_resolve_empty(context: Context, name: str) -> None:
    context.resolved_name = name
    call_tool(context, "resolve-library-id", {"libraryName": name, "query": ""})


@then("the tool answers as if no query was given")
def step_as_if_no_query(context: Context) -> None:
    async def without_query() -> str:
        container = Container.build(context.settings)
        async with container.running(jobs=False):
            found = await container.retrieval.resolve_library_id(
                ResolveLibraryIdQuery(library_name=context.resolved_name)
            )
        return "Available Libraries:\n\n" + "\n----------\n".join(
            format_library(m) for m in found.matches
        )

    result = context.mcp_result
    assert not result.is_error, result
    assert result.content[1].text == asyncio.run(without_query()), result.content[1].text
    assert "/fixture/docs-repo" in result.content[1].text


@then("the tool returns at most 200 articles and says the limit was capped")
def step_capped(context: Context) -> None:
    result = context.mcp_result
    assert not result.is_error, result
    assert 0 < len(context.mcp_data["articles"]) <= MAX_ARTICLES, context.mcp_data
    assert context.mcp_data["notes"] == ["limit 1000 is above the maximum of 200: 200 was used."], (
        context.mcp_data
    )


@when('an agent calls "search_docs" for "{library}" and "{query}" with path_prefix "{prefix}"')
def step_search_prefix(context: Context, library: str, query: str, prefix: str) -> None:
    call_tool(context, "search_docs", {"library": library, "query": query, "limit": 50})
    context.unfiltered = {r["article_path"] for r in context.mcp_data["results"]}
    call_tool(context, "search_docs", {"library": library, "query": query, "path_prefix": prefix})


@then('only hits under "{prefix}" are returned')
def step_only_under(context: Context, prefix: str) -> None:
    paths = {r["article_path"] for r in context.mcp_data["results"]}
    assert paths, context.mcp_data
    assert all(p.startswith(prefix) for p in paths), paths
    assert any(not p.startswith(prefix) for p in context.unfiltered), context.unfiltered


@when('an agent calls "{tool}" with library "{name}" and query "{query}"')
def step_named(context: Context, tool: str, name: str, query: str) -> None:
    context.named = name
    call_tool(context, tool, {"library": name, "query": query}, raise_on_error=False)


@then('the results come from "{library}" and a note says the name was resolved')
def step_resolved(context: Context, library: str) -> None:
    result = context.mcp_result
    assert not result.is_error, _text(context)
    data = context.mcp_data
    assert data["results"], data
    assert all(r.get("library", data.get("library")) == library for r in data["results"]), data
    assert data["notes"] == [
        f"library {context.named!r} is a name, not an ID: resolved to {library!r}."
    ], data


@then('the tool error lists the candidate IDs "{first}" and "{second}"')
def step_candidates(context: Context, first: str, second: str) -> None:
    result = context.mcp_result
    assert result.is_error, result
    text = _text(context)
    assert text.startswith("ambiguous_library:"), text
    assert f"{first!r}, {second!r}" in text, text


@when('an agent calls "{tool}" with an argument "{name}" it does not have')
def step_unknown_argument(context: Context, tool: str, name: str) -> None:
    call_tool(context, tool, {"query": "retry_policy", name: "v1.4.0"}, raise_on_error=False)


@then('the tool error names the real arguments "{first}", "{second}" and "{third}"')
def step_real_arguments(context: Context, first: str, second: str, third: str) -> None:
    result = context.mcp_result
    assert result.is_error, result
    text = _text(context)
    assert text.startswith("invalid_arguments: search_all_docs has no argument 'ref'"), text
    for name in (first, second, third):
        assert f" {name} (" in text, text
