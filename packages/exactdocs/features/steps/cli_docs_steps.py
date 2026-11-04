"""Steps for ``exactdocs library`` and ``exactdocs docs``: the real CLI on a loopback server."""

import json
import re
import shlex

from behave import given, then
from behave.runner import Context

from exactdocs.bootstrap.client import ClientConfig, store
from exactdocs_kernel import NOTICE
from steps.mcp_steps import call_tool


@given('the CLI holds the token "{name}"')
def step_holds(context: Context, name: str) -> None:
    assert name == "integration"  # the token the Background created
    store(context.config_file, ClientConfig(url=context.server_url, token=context.token))


@then('the output equals the text of "query-docs" for the same arguments')
def step_equals(context: Context) -> None:
    assert context.exit_code == 0, (context.exit_code, context.errors)
    _, library, *query = shlex.split(context.line)[1:]
    library = library.replace("@", "/")  # MCP spells a pinned version with a slash
    call_tool(context, "query-docs", {"libraryId": library, "query": " ".join(query)})
    notice, payload = context.mcp_result.content[0].text, context.mcp_result.content[1].text
    assert notice == NOTICE
    expected = f"{NOTICE}\n\n{payload}"
    assert context.output.rstrip("\n") == expected.rstrip("\n"), (context.output, expected)
    assert payload.startswith("### "), payload[:200]


@then('the library IDs listed equal the "resolve-library-id" list for "{name}" and "{query}"')
def step_library(context: Context, name: str, query: str) -> None:
    assert context.output.startswith(NOTICE)
    call_tool(context, "resolve-library-id", {"libraryName": name, "query": query})
    listing = context.mcp_result.content[1].text
    mcp_ids = re.findall(r"^- Context7-compatible library ID: (.+)$", listing, re.MULTILINE)
    ours = re.findall(r"^ +Context7-compatible library ID: (.+)$", context.output, re.MULTILINE)
    assert ours == mcp_ids
    assert ours[0] == "/fixture/docs-repo"


@then("stdout is JSON with the notice and at least one info snippet")
def step_json(context: Context) -> None:
    body = json.loads(context.output)
    assert body["notice"] == NOTICE
    assert body["infoSnippets"]


@then("the output is empty")
def step_empty(context: Context) -> None:
    assert not context.output, context.output
