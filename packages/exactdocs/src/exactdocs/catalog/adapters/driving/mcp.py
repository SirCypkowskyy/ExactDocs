"""MCP adapter for the catalog. All tools are read-only."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from exactdocs.catalog.dtos import LibraryList, ListLibrariesQuery
from exactdocs.catalog.ports.driving import ListLibraries
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT

READ_ONLY = ToolAnnotations(read_only_hint=True)


def register_tools(mcp: FastMCP, *, list_libraries: ListLibraries) -> None:
    """Register the catalog's MCP tools on ``mcp``."""

    @mcp.tool(name="list_libraries", annotations=READ_ONLY)
    async def list_libraries_tool(
        limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> LibraryList:
        """List indexed libraries and their versions; pass `next_cursor` as `cursor` for more."""
        return await list_libraries(ListLibrariesQuery(limit=limit, cursor=cursor))
