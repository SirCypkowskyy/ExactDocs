"""MCP adapter for retrieval. All tools are read-only."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from exactdocs.retrieval.dtos import (
    MAX_NAME,
    MAX_QUERY,
    MAX_TAGS,
    SearchDocsQuery,
    SearchDocsResult,
    Tag,
)
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import SearchDocs
from exactdocs_kernel import LIBRARY_ID_PATTERN, TOOL_HINTS


def register_tools(mcp: FastMCP, *, search_docs: SearchDocs) -> None:
    """Register retrieval's MCP tools on ``mcp``."""

    @mcp.tool(
        name="search_docs",
        annotations=ToolAnnotations(title="Search a library version", **TOOL_HINTS),
    )
    async def search_docs_tool(
        library: Annotated[
            str,
            Field(
                pattern=LIBRARY_ID_PATTERN,
                max_length=MAX_NAME,
                description="Library ID, e.g. '/facebook/react'",
            ),
        ],
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_QUERY,
                description="Identifier, error message or question",
            ),
        ],
        ref: Annotated[
            str | None,
            Field(
                max_length=MAX_NAME,
                description="Exact imported ref, e.g. 'v19.1'; default version if empty",
            ),
        ] = None,
        tags: Annotated[
            list[Tag] | None,
            Field(max_length=MAX_TAGS, description="Only articles with these tags"),
        ] = None,
        tags_match: Annotated[TagMatch, Field(description="'any' or 'all' of tags")] = TagMatch.ANY,
        limit: Annotated[int, Field(ge=1, le=50)] = 5,
        mode: Annotated[
            str | None,
            Field(
                max_length=MAX_NAME,
                description="Retrieval mode, e.g. 'bm25'; empty means the best one configured",
            ),
        ] = None,
    ) -> SearchDocsResult:
        """Search one library version. Returns verbatim chunks with location and source link.

        An empty result with coverage.complete true means the version holds no match; it never
        falls back to another version. Pass ``ref`` to pin a version.
        """
        return await search_docs(
            SearchDocsQuery(
                library=library,
                ref=ref,
                query=query,
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
                mode=mode,
            )
        )
