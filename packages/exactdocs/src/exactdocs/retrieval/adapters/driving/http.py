from typing import Annotated

from fastapi import APIRouter, Query

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.ports.driving import SearchDocs


def build_router(*, search_docs: SearchDocs) -> APIRouter:
    """Expose retrieval under ``/search``."""
    router = APIRouter(prefix="/search", tags=["retrieval"])

    @router.get("")
    async def search(query: Annotated[SearchDocsQuery, Query()]) -> SearchDocsResult:
        return await search_docs(query)

    return router
