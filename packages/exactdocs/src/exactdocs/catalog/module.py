"""Wiring of the catalog domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in.
"""

from dataclasses import dataclass
from typing import Self

from exactdocs.catalog.ports.driven import LibraryRepository
from exactdocs.catalog.ports.driving import GetLibrary, ListLibraries, ResolveVersion
from exactdocs.catalog.use_cases import (
    GetLibraryUseCase,
    ListLibrariesUseCase,
    ResolveVersionUseCase,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogModule:
    """The catalog's driving ports, ready to be exposed by driving adapters."""

    list_libraries: ListLibraries
    get_library: GetLibrary
    resolve_version: ResolveVersion

    @classmethod
    def build(cls, *, repository: LibraryRepository) -> Self:
        """Assemble the use cases around the given driven adapters."""
        return cls(
            list_libraries=ListLibrariesUseCase(repository),
            get_library=GetLibraryUseCase(repository),
            resolve_version=ResolveVersionUseCase(repository),
        )
