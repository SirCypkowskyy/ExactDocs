"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass

from exactdocs.catalog.dtos import GetLibraryQuery, LibraryList, LibrarySummary
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import LibraryName
from exactdocs.catalog.ports.driven import LibraryRepository


@dataclass(frozen=True, slots=True)
class ListLibrariesUseCase:
    """Implements ``ports.driving.ListLibraries``."""

    repository: LibraryRepository

    async def __call__(self) -> LibraryList:
        """List every library."""
        return LibraryList.from_models(await self.repository.list_all())


@dataclass(frozen=True, slots=True)
class GetLibraryUseCase:
    """Implements ``ports.driving.GetLibrary``."""

    repository: LibraryRepository

    async def __call__(self, query: GetLibraryQuery) -> LibrarySummary:
        """Fetch one library by its exact name."""
        library = await self.repository.get(LibraryName(query.name))
        if library is None:
            raise LibraryNotFoundError(query.name)
        return LibrarySummary.from_model(library)
