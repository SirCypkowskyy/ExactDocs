"""Steps for `[auth].default_library_role`: the role every account holds on every library."""

import asyncio
import json
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then
from behave.runner import Context

from exactdocs.bootstrap.settings import Settings
from steps.http_steps import DEMO_COOKIE, running_with
from steps.library_roles_steps import MCP_HEADERS, get_person, send_as
from steps.search_steps import import_versions

DEFAULT_RULE = "config:default_library_role"


@given(
    'ExactDocs is running with "{role}" as the default library role, library creation left to'
    ' operators, and the fixture docs repository imported at "{first}" and "{second}"'
)
def step_running_with_default(context: Context, role: str, first: str, second: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    auth = {"default_library_role": role, "library_creation": {}}
    running_with(context, stack, Settings(data_dir=data_dir, auth=auth))
    asyncio.run(import_versions(context, [first, second]))


@then('"{username}" is not offered the MCP tools that add libraries')
def step_no_write_tools(context: Context, username: str) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    response = send_as(
        context,
        "POST",
        "/mcp",
        token=get_person(context, username)["token"],
        json=body,
        headers=MCP_HEADERS,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    payload = next(
        (
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        ),
        response.text,
    )
    tools = {tool["name"] for tool in json.loads(payload)["result"]["tools"]}
    assert "search_docs" in tools, tools
    assert not tools & {"add_docs", "import_status"}, tools


@then('the Users page says "{username}"\'s role comes from the default library role, read-only')
def step_users_page(context: Context, username: str) -> None:
    person = get_person(context, username)
    users = send_as(context, "GET", "/api/v1/users", session=DEMO_COOKIE)
    assert users.status_code == HTTPStatus.OK, users.text
    (listed,) = [u for u in users.json()["users"] if u["id"] == person["id"]]
    assert listed["rules"] == [DEFAULT_RULE], listed
    rules = send_as(context, "GET", "/api/v1/role-rules", session=DEMO_COOKIE)
    assert rules.status_code == HTTPStatus.OK, rules.text
    (rule,) = [r for r in rules.json()["rules"] if r["id"] == DEFAULT_RULE]
    assert (rule["source"], rule["grant"], rule["configured"]) == ("everyone", "viewer", True)
    removed = send_as(context, "DELETE", f"/api/v1/role-rules/{DEFAULT_RULE}", session=DEMO_COOKIE)
    assert removed.status_code >= HTTPStatus.BAD_REQUEST, removed.text
