"""REST adapter for retrieval."""

from typing import Annotated

from fastapi import APIRouter, Query

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import SearchDocs


def build_router(*, search_docs: SearchDocs) -> APIRouter:
    """Expose retrieval next to the catalog's ``/libraries`` routes."""
    router = APIRouter(prefix="/libraries", tags=["retrieval"])

    # The ref is `?ref=` (it may contain `/`); no ref means the default version.
    @router.get("/{owner}/{repo}/search")
    async def search(
        owner: str,
        repo: str,
        q: Annotated[str, Query(min_length=1, description="Identifier, error or question.")],
        ref: str | None = None,
        tags: Annotated[list[str] | None, Query(description="Repeat or comma-separate.")] = None,
        tags_match: TagMatch = TagMatch.ANY,
        limit: Annotated[int, Query(ge=1, le=50)] = 5,
    ) -> SearchDocsResult:
        wanted = [t.strip() for value in tags or [] for t in value.split(",") if t.strip()]
        return await search_docs(
            SearchDocsQuery(
                library=f"/{owner}/{repo}",
                ref=ref,
                query=q,
                tags=wanted,
                tags_match=tags_match,
                limit=limit,
            )
        )

    return router
