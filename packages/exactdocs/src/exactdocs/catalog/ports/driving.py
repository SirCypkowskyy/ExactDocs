"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import (
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    ListLibrariesQuery,
    ResolvedVersion,
    ResolveVersionQuery,
)


class ListLibraries(Protocol):
    """List a page of libraries and their indexed versions."""

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """Run the use case."""
        ...


class GetLibrary(Protocol):
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Run the use case."""
        ...


class ResolveVersion(Protocol):
    """Resolve a context7-style ID to the one version it names.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` for unknown targets and a
    validation error for a malformed ID or an ambiguous short SHA. Never falls back to another
    version.
    """

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Run the use case."""
        ...
