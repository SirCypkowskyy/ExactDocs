"""Steps for context7's REST API: compared with what the MCP tools return for the same call."""

import re
from http import HTTPStatus

from behave import then, when
from behave.runner import Context

from exactdocs_kernel import NOTICE
from steps.mcp_steps import call_tool


def _get(context: Context, path: str, params: dict[str, str], *, token: bool) -> None:
    headers = {"authorization": f"Bearer {context.token}"} if token else {}
    request = context.client.build_request("GET", path, params=params, headers=headers)
    request.headers.pop("cookie", None)  # the token alone must be what lets the call in
    context.response = context.client.send(request)


@when('a client with an API token calls the docs endpoint for "{library}" and "{query}"')
def step_docs(context: Context, library: str, query: str) -> None:
    context.c7_args = {"libraryId": library, "query": query}
    _get(context, "/api/v1/c7/docs", context.c7_args, token=True)


@when('a client without a token calls the docs endpoint for "{library}" and "{query}"')
def step_docs_anonymous(context: Context, library: str, query: str) -> None:
    _get(context, "/api/v1/c7/docs", {"libraryId": library, "query": query}, token=False)


@when('a client with an API token calls the search endpoint for "{name}" and "{query}"')
def step_search(context: Context, name: str, query: str) -> None:
    context.c7_args = {"libraryName": name, "query": query}
    _get(context, "/api/v1/c7/search", context.c7_args, token=True)


@then('the payload equals the "query-docs" payload')
def step_equals(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    call_tool(context, "query-docs", context.c7_args)
    notice, _, payload = context.response.text.partition("\n\n")
    assert notice == NOTICE
    assert payload == context.mcp_result.content[1].text
    assert payload.startswith("### "), payload[:200]


@then("the response carries the untrusted-content notice")
def step_notice(context: Context) -> None:
    assert context.response.headers["x-exactdocs-notice"] == NOTICE


@then('the first result is "{library}" and the list equals the "resolve-library-id" list')
def step_search_equals(context: Context, library: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert body["notice"] == NOTICE
    call_tool(context, "resolve-library-id", context.c7_args)
    listing = context.mcp_result.content[1].text
    mcp_ids = re.findall(r"^- Context7-compatible library ID: (.+)$", listing, re.MULTILINE)
    assert [r["id"] for r in body["results"]] == mcp_ids
    assert mcp_ids[0] == library
