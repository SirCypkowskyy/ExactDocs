"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import GetLibraryQuery
from exactdocs.catalog.ports.driving import GetLibrary
from exactdocs.retrieval.models import DocTarget
from exactdocs_kernel import NotFoundError


@dataclass(frozen=True, slots=True)
class CatalogIndexedVersions:
    """Implements ``retrieval.ports.driven.IndexedVersions`` using the catalog."""

    get_library: GetLibrary

    async def is_indexed(self, target: DocTarget) -> bool:
        """Ask the catalog whether this exact version has an index."""
        try:
            library = await self.get_library(GetLibraryQuery(name=target.library))
        except NotFoundError:
            return False
        return target.version in library.versions
