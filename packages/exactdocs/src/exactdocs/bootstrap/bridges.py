"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import GetLibraryQuery, ResolveVersionQuery
from exactdocs.catalog.ports.driving import GetLibrary, ResolveVersion
from exactdocs.ingestion.models import ProposedId
from exactdocs.retrieval.models import DocTarget
from exactdocs_kernel import NotFoundError


@dataclass(frozen=True, slots=True)
class CatalogIndexedVersions:
    """Implements ``retrieval.ports.driven.IndexedVersions`` using the catalog."""

    resolve_version: ResolveVersion

    async def find_indexed(self, target: DocTarget) -> DocTarget | None:
        """Ask the catalog for this exact ref (a short SHA does not count); return the stored ID."""
        try:
            resolved = await self.resolve_version(
                ResolveVersionQuery(id=f"{target.library}/{target.version}")
            )
        except NotFoundError:
            return None
        if resolved.ref != target.version:
            return None
        return DocTarget(library=resolved.library, version=resolved.ref)


@dataclass(frozen=True, slots=True)
class CatalogLibraryIds:
    """Implements ``ingestion.ports.driven.LibraryIds`` using the catalog."""

    get_library: GetLibrary

    async def is_taken(self, library_id: ProposedId) -> bool:
        """Tell whether a library with this ID is in the catalog."""
        try:
            await self.get_library(GetLibraryQuery(id=library_id))
        except NotFoundError:
            return False
        return True
