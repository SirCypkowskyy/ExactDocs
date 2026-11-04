"""Steps for resolve-library-id: libraries are the fixture repository imported under other IDs."""

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any

from behave import given, then, when
from behave.runner import Context
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs_kernel import NOTICE
from steps.mcp_steps import call_tool

TWO_BLOCKS = 2


def _import_as(context: Context, library: str, refs: list[str]) -> None:
    if not hasattr(context, "settings"):
        directory = tempfile.TemporaryDirectory(prefix="exactdocs-")
        context.add_cleanup(directory.cleanup)
        context.settings = Settings(data_dir=Path(directory.name))
    title = library.rsplit("/", 1)[-1].replace("-", " ").title()
    asyncio.run(import_versions(context, refs, library, title))


@given('the fixture repository is imported as "{library}" at "{ref}"')
def step_import_as(context: Context, library: str, ref: str) -> None:
    _import_as(context, library, [ref])


@given('the fixture repository is also imported as "{library}"')
def step_import_also(context: Context, library: str) -> None:
    _import_as(context, library, ["v1.3.0", "v1.4.0"])


@given('only "{library}" documents "{text}" in its default version')
def step_only(context: Context, library: str, text: str) -> None:
    del library  # the Background imported it at the version that has the text
    present, absent = "v1.4.0", "v1.3.0"
    args = ("grep", "-Il", "-F", text)
    git = context.fixture_git
    repo = context.fixture_repo.path
    assert git(*args, present, "--", "docs", cwd=repo, check=False)
    assert not git(*args, absent, "--", "docs", cwd=repo, check=False)


@when('an agent calls "resolve-library-id" with libraryName "{name}" and query "{query}"')
@when('the agent calls it with libraryName "{name}" and query "{query}"')
def step_resolve(context: Context, name: str, query: str) -> None:
    call_tool(context, "resolve-library-id", {"libraryName": name, "query": query})


def _payload(context: Context) -> str:
    return context.mcp_result.content[1].text


def _matches(context: Context) -> list[str]:
    return re.findall(r"^- Context7-compatible library ID: (\S+)$", _payload(context), re.MULTILINE)


@then(
    '"{library}" is the first match with its title, description, versions, article and chunk counts'
)
def step_first_match(context: Context, library: str) -> None:
    assert _matches(context)[0] == library, _payload(context)
    first = _payload(context).split("\n----------\n")[0]
    assert "- Title: Docs Repo" in first, first
    assert "- Description: " in first, first
    assert "- Versions: v1.3.0, v1.4.0" in first, first
    assert "- Default version: v1.4.0" in first, first
    for field in ("Articles", "Chunks"):
        (count,) = re.findall(rf"^- {field}: (\d+)$", first, re.MULTILINE)
        assert int(count) > 0, first


@then('"{library}" is ranked first')
@then('"{library}" is ranked first again')
def step_ranked_first(context: Context, library: str) -> None:
    assert _matches(context)[0] == library, _payload(context)


@then("the payload says no library was found")
def step_none(context: Context) -> None:
    assert not context.mcp_result.is_error
    assert _payload(context) == "No libraries found matching the provided name."


@then("the result has two text blocks: the notice with the version, then the payload")
def step_two_blocks(context: Context) -> None:
    content = context.mcp_result.content
    assert len(content) == TWO_BLOCKS, content
    assert content[0].text == NOTICE
    assert _payload(context).startswith("Available Libraries:\n\n- Title: ")


@then("the tool has no output schema")
def step_no_schema(context: Context) -> None:
    async def tool() -> Any:
        container = Container.build(context.settings)
        async with container.running(), Client(build_mcp(container)) as mcp:
            return next(t for t in await mcp.list_tools() if t.name == "resolve-library-id")

    found = asyncio.run(tool())
    assert found.output_schema is None, found.output_schema
    assert context.mcp_data is None, context.mcp_data
