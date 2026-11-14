"""The context7 tools' names and arguments, pinned to a vendored copy (see the README there)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.constants import MAX_QUERY
from exactdocs_kernel import MAX_NAME

CONTRACT_DIR = Path(__file__).parents[1] / "contracts" / "context7"
# Every tool file; `session.json` is the recorded session, replayed in its own test.
CONTRACTS = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(CONTRACT_DIR.glob("*.json"))
    if path.stem != "session"
}


@pytest.mark.parametrize("pinned", CONTRACTS.values(), ids=CONTRACTS)
async def test_the_tool_name_and_arguments_are_a_superset_of_context7s(
    pinned: dict[str, Any],
) -> None:
    container = Container.build(Settings())
    async with container.running(), Client(build_mcp(container)) as mcp:
        tool = next((t for t in await mcp.list_tools() if t.name == pinned["name"]), None)

    assert tool is not None, f"ExactDocs has no tool {pinned['name']}"
    ours, theirs = tool.input_schema, pinned["inputSchema"]
    for name, spec in theirs["properties"].items():
        ours_spec = ours["properties"][name]
        # An optional argument is `string | null` on our side (anyOf); a client sending the
        # string must still be accepted.
        types = (
            {ours_spec["type"]} if "type" in ours_spec else {a["type"] for a in ours_spec["anyOf"]}
        )
        assert spec["type"] in types, name
    # Same required arguments: a client that sends only context7's arguments must be accepted.
    assert set(ours.get("required", [])) == set(theirs["required"])


async def test_the_longest_realistic_context7_arguments_are_accepted() -> None:
    # context7 puts no cap on `query`; a long task description plus a long library name must pass.
    container = Container.build(Settings())
    arguments = {"libraryName": "n" * MAX_NAME, "query": "How do I set up retries? " * 40}
    assert len(arguments["query"]) <= MAX_QUERY
    async with container.running(), Client(build_mcp(container)) as mcp:
        result = await mcp.call_tool("resolve-library-id", arguments)

    assert not result.is_error
    assert result.content[1].text == "No libraries found matching the provided name."


async def test_arguments_context7_never_sends_are_refused_not_ignored() -> None:
    container = Container.build(Settings())
    async with container.running(), Client(build_mcp(container)) as mcp:
        result = await mcp.call_tool(
            "resolve-library-id",
            {"libraryName": "x", "query": "y", "userQuery": "z"},
            raise_on_error=False,
        )

    assert (
        result.is_error
    )  # the context7 aliases (userQuery, question) are not mirrored: see README
