"""Catalog use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass

from exactdocs.catalog.dtos import (
    GetLibraryQuery,
    LibraryDetail,
    LibraryList,
    ListLibrariesQuery,
    ResolvedVersion,
    ResolveVersionQuery,
)
from exactdocs.catalog.errors import LibraryNotFoundError, VersionNotFoundError
from exactdocs.catalog.models import LibraryId, ParsedId
from exactdocs.catalog.ports.driven import LibraryRepository
from exactdocs_kernel import paginate


@dataclass(frozen=True, slots=True)
class ListLibrariesUseCase:
    """Implements ``ports.driving.ListLibraries``."""

    repository: LibraryRepository

    async def __call__(self, query: ListLibrariesQuery) -> LibraryList:
        """List a page of libraries, sorted by ID."""
        libraries = sorted(await self.repository.list_all(), key=lambda lib: lib.id.value)
        page = paginate(
            libraries, key=lambda lib: lib.id.value, limit=query.limit, cursor=query.cursor
        )
        return LibraryList.from_page(page)


@dataclass(frozen=True, slots=True)
class GetLibraryUseCase:
    """Implements ``ports.driving.GetLibrary``."""

    repository: LibraryRepository

    async def __call__(self, query: GetLibraryQuery) -> LibraryDetail:
        """Fetch one library by ID."""
        library = await self.repository.get(LibraryId(query.id))
        if library is None:
            raise LibraryNotFoundError(query.id)
        return LibraryDetail.from_model(library)


@dataclass(frozen=True, slots=True)
class ResolveVersionUseCase:
    """Implements ``ports.driving.ResolveVersion``."""

    repository: LibraryRepository

    async def __call__(self, query: ResolveVersionQuery) -> ResolvedVersion:
        """Resolve `/owner/repo[/ref]` to exactly one version."""
        target = ParsedId.parse(query.id)
        library = await self.repository.get(target.library)
        if library is None:
            raise LibraryNotFoundError(str(target.library))
        version = library.find_version(target.ref) if target.ref else library.default_version()
        if version is None:
            ref = None if target.ref is None else str(target.ref)
            raise VersionNotFoundError(str(library.id), ref)
        return ResolvedVersion.from_library(library, version)
