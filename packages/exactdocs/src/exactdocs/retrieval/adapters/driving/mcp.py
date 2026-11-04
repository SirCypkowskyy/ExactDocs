"""MCP adapter for retrieval. All tools are read-only."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import SearchDocs

READ_ONLY = ToolAnnotations(read_only_hint=True)


def register_tools(mcp: FastMCP, *, search_docs: SearchDocs) -> None:
    """Register retrieval's MCP tools on ``mcp``."""

    @mcp.tool(name="search_docs", annotations=READ_ONLY)
    async def search_docs_tool(
        library: Annotated[str, Field(description="Library name, e.g. 'react'")],
        query: Annotated[str, Field(description="Identifier, error message or question")],
        ref: Annotated[
            str | None,
            Field(description="Exact imported ref, e.g. 'v19.1'; default version if empty"),
        ] = None,
        tags: Annotated[
            list[str] | None, Field(description="Only articles with these tags")
        ] = None,
        tags_match: Annotated[TagMatch, Field(description="'any' or 'all' of tags")] = TagMatch.ANY,
        limit: Annotated[int, Field(ge=1, le=50)] = 5,
    ) -> SearchDocsResult:
        """Search one library version. Returns verbatim chunks with location and source link."""
        return await search_docs(
            SearchDocsQuery(
                library=library,
                ref=ref,
                query=query,
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
            )
        )
