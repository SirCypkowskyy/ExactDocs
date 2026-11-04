"""REST adapter for retrieval."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from exactdocs.retrieval.dtos import (
    MAX_NAME,
    MAX_QUERY,
    MAX_TAG,
    MAX_TAGS,
    ChunkOut,
    ReadChunkQuery,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import ReadChunk, SearchDocs


def build_router(*, search_docs: SearchDocs, read_chunk: ReadChunk) -> APIRouter:
    """Expose retrieval: search next to the catalog's ``/libraries`` routes, and ``/chunks``."""
    router = APIRouter(tags=["retrieval"])

    # The ref is `?ref=` (it may contain `/`); no ref means the default version.
    @router.get("/libraries/{owner}/{repo}/search")
    async def search(
        owner: str,
        repo: str,
        q: Annotated[
            str,
            Query(min_length=1, max_length=MAX_QUERY, description="Identifier, error or question."),
        ],
        ref: Annotated[str | None, Query(max_length=MAX_NAME)] = None,
        tags: Annotated[
            list[Annotated[str, Query(max_length=MAX_TAG)]] | None,
            Query(max_length=MAX_TAGS, description="Repeat or comma-separate."),
        ] = None,
        tags_match: TagMatch = TagMatch.ANY,
        limit: Annotated[int, Query(ge=1, le=50)] = 5,
    ) -> SearchDocsResult:
        try:
            query = SearchDocsQuery(
                library=f"/{owner}/{repo}",
                ref=ref,
                query=q,
                tags=tags or [],
                tags_match=tags_match,
                limit=limit,
            )
        except ValidationError as error:  # what the Query() bounds above cannot see
            raise RequestValidationError(error.errors()) from error
        return await search_docs(query)

    @router.get("/chunks/{chunk_id}")
    async def get_chunk(chunk_id: Annotated[str, Path(max_length=MAX_NAME)]) -> ChunkOut:
        """Read a chunk verbatim by the ID of a search result.

        404 `not_found` when no version serves the ID; 409 `stale_chunk` when its version was
        re-synced since: search the version again for current IDs.
        """
        return await read_chunk(ReadChunkQuery(chunk_id=chunk_id))

    return router
