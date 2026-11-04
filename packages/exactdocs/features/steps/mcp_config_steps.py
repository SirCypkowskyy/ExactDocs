"""Steps for ``exactdocs config``: the printed Claude Code snippet drives a real MCP client."""

import asyncio
import io
import json
import os
from contextlib import redirect_stdout
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StreamableHttpTransport

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.client import ClientConfig

HORSE = "correct horse battery staple"


@given('the user is logged in with "exactdocs login"')
def step_logged_in(context: Context) -> None:
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}
    args = ["login", context.server_url, "--username", "ada", "--password-stdin"]
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", io.StringIO(HORSE + "\n")),
        redirect_stdout(io.StringIO()),
    ):
        cli.app(args, exit_on_error=False, result_action="return_value")
        context.stored_token = ClientConfig.resolve().token


@when('the user runs "exactdocs config {options}"')
def step_config(context: Context, options: str) -> None:
    output = io.StringIO()
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}
    with patch.dict(os.environ, env), redirect_stdout(output):
        cli.app(["config", *options.split()], exit_on_error=False, result_action="return_value")
    context.output = output.getvalue()


@when('the user runs "exactdocs config {options}" with the admin\'s password')
def step_config_password(context: Context, options: str) -> None:
    output = io.StringIO()
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", io.StringIO(HORSE + "\n")),
        redirect_stdout(output),
    ):
        cli.app(["config", *options.split()], exit_on_error=False, result_action="return_value")
    context.output = output.getvalue()


@then("a JSON snippet with the server URL and a new token is printed")
def step_new_snippet(context: Context) -> None:
    context.server = json.loads(context.output)["mcpServers"]["exactdocs"]
    assert context.server["url"] == f"{context.server_url}/mcp"
    assert context.server["headers"]["Authorization"].startswith("Bearer ")


@then("the new token is not the one the user logged in with")
def step_other_token(context: Context) -> None:
    assert context.stored_token not in context.output


@then("a JSON snippet with the server URL and the token is printed")
def step_snippet(context: Context) -> None:
    context.server = json.loads(context.output)["mcpServers"]["exactdocs"]
    assert context.server["url"] == f"{context.server_url}/mcp"
    assert context.server["headers"]["Authorization"] == f"Bearer {context.stored_token}"


@then("an MCP client configured with it can list libraries")
def step_client(context: Context) -> None:
    async def work() -> CallToolResult:
        transport = StreamableHttpTransport(
            context.server["url"], headers=context.server["headers"]
        )
        async with Client(transport) as client:
            return await client.call_tool("list_libraries", {})

    assert not asyncio.run(work()).is_error


@then("the stored token is not in the output")
def step_hidden(context: Context) -> None:
    assert context.stored_token not in context.output


@then("the output refers to the EXACTDOCS_TOKEN environment variable")
def step_env(context: Context) -> None:
    assert "${EXACTDOCS_TOKEN}" in context.output


@then('the output starts "exactdocs serve --stdio" through uvx')
def step_stdio(context: Context) -> None:
    server = json.loads(context.output)["mcpServers"]["exactdocs"]
    assert [server["command"], *server["args"]] == ["uvx", "exactdocs", "serve", "--stdio"]
