"""MCP adapter for the catalog. All tools are read-only."""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from exactdocs.catalog.dtos import LibraryList
from exactdocs.catalog.ports.driving import ListLibraries

READ_ONLY = ToolAnnotations(read_only_hint=True)


def register_tools(mcp: FastMCP, *, list_libraries: ListLibraries) -> None:
    """Register the catalog's MCP tools on ``mcp``."""

    @mcp.tool(name="list_libraries", annotations=READ_ONLY)
    async def list_libraries_tool() -> LibraryList:
        """List indexed libraries and their versions."""
        return await list_libraries()
