"""Driving (primary) ports: what the outside world may ask the catalog to do."""

from typing import Protocol

from exactdocs.catalog.dtos import GetLibraryQuery, LibraryList, LibrarySummary, ListLibrariesQuery


class ListLibraries(Protocol):
    """List a page of libraries and their indexed versions."""

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """Run the use case."""
        ...


class GetLibrary(Protocol):
    """Fetch one library; raises ``LibraryNotFoundError`` when it is missing."""

    async def __call__(self, query: GetLibraryQuery) -> LibrarySummary:
        """Run the use case."""
        ...
