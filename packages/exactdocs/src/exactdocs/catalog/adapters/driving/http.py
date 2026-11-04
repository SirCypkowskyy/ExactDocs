"""REST adapter for the catalog (consumed by the web UI)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from exactdocs.catalog.dtos import (
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    ListLibrariesQuery,
    ResolvedVersion,
    ResolveVersionQuery,
)
from exactdocs.catalog.ports.driving import GetLibrary, ListLibraries, ResolveVersion


def build_router(
    *, list_libraries: ListLibraries, get_library: GetLibrary, resolve_version: ResolveVersion
) -> APIRouter:
    """Expose the catalog's driving ports under ``/libraries``."""
    router = APIRouter(prefix="/libraries", tags=["catalog"])

    @router.get("")
    async def list_all(query: Annotated[ListLibrariesQuery, Query()]) -> LibraryList:
        return await list_libraries(query)

    # Library IDs are `/owner/repo`; the ref comes last because it may contain slashes
    # (`release/1.4`) and the server decodes `%2F` before routing.
    @router.get("/{owner}/{repo}")
    async def get_one(owner: str, repo: str) -> LibraryDetail:
        return await get_library(GetLibraryQuery(id=f"/{owner}/{repo}"))

    @router.get("/{owner}/{repo}/versions/{ref:path}")
    async def get_version(owner: str, repo: str, ref: str) -> ResolvedVersion:
        if ref.endswith("/"):  # `/versions/v1.4.0/` is another URL, not a malformed ref
            raise HTTPException(status_code=404)
        return await resolve_version(ResolveVersionQuery(id=f"/{owner}/{repo}/{ref}"))

    return router
