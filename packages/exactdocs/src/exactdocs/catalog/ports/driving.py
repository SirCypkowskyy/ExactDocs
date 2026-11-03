"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import GetLibraryQuery, LibraryList, LibrarySummary


class ListLibraries(Protocol):
    """List every library and its indexed versions."""

    async def __call__(self) -> LibraryList:
        """Run the use case."""
        ...


class GetLibrary(Protocol):
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""

    async def __call__(self, query: GetLibraryQuery) -> LibrarySummary:
        """Run the use case."""
        ...
