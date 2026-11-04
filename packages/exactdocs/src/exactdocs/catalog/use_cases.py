"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass

from exactdocs.catalog.dtos import GetLibraryQuery, LibraryList, LibrarySummary, ListLibrariesQuery
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import LibraryName
from exactdocs.catalog.ports.driven import LibraryRepository
from exactdocs_kernel import paginate


@dataclass(frozen=True, slots=True)
class ListLibrariesUseCase:
    """Implements ``ports.driving.ListLibraries``."""

    repository: LibraryRepository

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """List a page of libraries, sorted by name."""
        libraries = sorted(await self.repository.list_all(), key=lambda lib: lib.name)
        page = paginate(libraries, key=lambda lib: lib.name, limit=query.limit, cursor=query.cursor)
        return LibraryList.from_page(page)


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
