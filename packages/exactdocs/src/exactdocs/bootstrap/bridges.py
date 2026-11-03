"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import ResolveVersionQuery
from exactdocs.catalog.ports.driving import ResolveVersion
from exactdocs.retrieval.models import DocTarget
from exactdocs_kernel import NotFoundError


@dataclass(frozen=True, slots=True)
class CatalogIndexedVersions:
    """Implements ``retrieval.ports.driven.IndexedVersions`` using the catalog."""

    resolve_version: ResolveVersion

    async def is_indexed(self, target: DocTarget) -> bool:
        """Ask the catalog whether this exact ref has an index (a short SHA does not count)."""
        try:
            resolved = await self.resolve_version(
                ResolveVersionQuery(id=f"{target.library}/{target.version}")
            )
        except NotFoundError:
            return False
        return resolved.ref == target.version
