"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from exactdocs.catalog.dtos import (
    GetActiveManifestQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    ResolveVersionQuery,
)
from exactdocs.catalog.models import ManifestState
from exactdocs.catalog.ports.driving import (
    GetActiveManifest,
    GetLibrary,
    GetManifestStates,
    ResolveVersion,
)
from exactdocs.ingestion.models import ProposedId
from exactdocs.retrieval.models import DocTarget, ManifestStatus
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


# Explicit, so a state the catalog adds later cannot crash retrieval: it maps to OTHER (keep).
_STATUSES = {
    ManifestState.PENDING: ManifestStatus.PENDING,
    ManifestState.ACTIVE: ManifestStatus.ACTIVE,
    ManifestState.SUPERSEDED: ManifestStatus.SUPERSEDED,
}


@dataclass(frozen=True, slots=True)
class CatalogActiveManifests:
    """Implements ``retrieval.ports.driven.ActiveManifests`` using the catalog."""

    get_active_manifest: GetActiveManifest
    get_manifest_states: GetManifestStates

    async def active_id(self, target: DocTarget) -> str | None:
        """Return the manifest the catalog serves for this version, or ``None`` when it has none."""
        try:
            found = await self.get_active_manifest(
                GetActiveManifestQuery(library=target.library, ref=target.version)
            )
        except NotFoundError:
            return None
        return found.manifest_id

    async def statuses(self, manifest_ids: Collection[str]) -> Mapping[str, ManifestStatus]:
        """Ask the catalog; IDs it does not know are left out."""
        found = await self.get_manifest_states(
            GetManifestStatesQuery(manifest_ids=list(manifest_ids))
        )
        return {i: _STATUSES.get(state, ManifestStatus.OTHER) for i, state in found.states.items()}
