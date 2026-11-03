"""REST adapter for the catalog (consumed by the web UI)."""

from fastapi import APIRouter

from exactdocs.catalog.dtos import GetLibraryQuery, LibraryList, LibrarySummary
from exactdocs.catalog.ports.driving import GetLibrary, ListLibraries


def build_router(*, list_libraries: ListLibraries, get_library: GetLibrary) -> APIRouter:
    """Expose the catalog's driving ports under ``/libraries``."""
    router = APIRouter(prefix="/libraries", tags=["catalog"])

    @router.get("")
    async def list_all() -> LibraryList:
        return await list_libraries()

    # Library IDs are `/owner/repo`; refs (later: `/versions/{ref:path}`) always come last,
    # because the server decodes `%2F` before routing.
    @router.get("/{owner}/{repo}")
    async def get_one(owner: str, repo: str) -> LibrarySummary:
        return await get_library(GetLibraryQuery(name=f"/{owner}/{repo}"))

    return router
