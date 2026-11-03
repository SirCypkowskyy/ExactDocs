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

    @router.get("/{name}")
    async def get_one(name: str) -> LibrarySummary:
        return await get_library(GetLibraryQuery(name=name))

    return router
