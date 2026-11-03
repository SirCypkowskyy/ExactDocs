"""MCP adapter for retrieval. All tools are read-only."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.ports.driving import SearchDocs

READ_ONLY = ToolAnnotations(read_only_hint=True)


def register_tools(mcp: FastMCP, *, search_docs: SearchDocs) -> None:
    """Register retrieval's MCP tools on ``mcp``."""

    @mcp.tool(name="search_docs", annotations=READ_ONLY)
    async def search_docs_tool(
        library: Annotated[str, Field(description="Library name, e.g. 'react'")],
        version: Annotated[str, Field(description="Exact indexed version, e.g. '19.1'")],
        query: Annotated[str, Field(description="Identifier, error message or question")],
        limit: Annotated[int, Field(ge=1, le=50)] = 5,
    ) -> SearchDocsResult:
        """Search one library version. Returns verbatim excerpts with source URLs."""
        return await search_docs(
            SearchDocsQuery(library=library, version=version, query=query, limit=limit)
        )
