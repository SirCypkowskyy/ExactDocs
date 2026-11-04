"""The context7 tools' names and arguments, pinned to a vendored copy (see the README there)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings

CONTRACTS = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((Path(__file__).parents[1] / "contracts" / "context7").glob("*.json"))
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
        assert ours["properties"][name]["type"] == spec["type"], name
    # Same required arguments: a client that sends only context7's arguments must be accepted.
    assert set(ours.get("required", [])) == set(theirs["required"])
