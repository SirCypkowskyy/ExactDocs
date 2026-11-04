"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from exactdocs.catalog.dtos import (
    CreateLibraryCommand,
    DiscardLibraryCommand,
    GetActiveManifestQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    HostKind,
    ResolveVersionQuery,
    TagRuleIn,
)
from exactdocs.catalog.models import ManifestState
from exactdocs.catalog.ports.driving import (
    CreateLibrary,
    DiscardLibrary,
    GetActiveManifest,
    GetLibrary,
    GetManifestStates,
    ResolveVersion,
)
from exactdocs.ingestion.models import NewLibrary, ProposedId
from exactdocs.retrieval.models import DocTarget, ManifestStatus, SearchableVersion, SourceHost
from exactdocs_kernel import NotFoundError, ValidationError


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
class CatalogSearchableVersions:
    """Implements ``retrieval.ports.driven.SearchableVersions`` using the catalog."""

    get_library: GetLibrary
    get_active_manifest: GetActiveManifest

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        """Resolve the exact ref (the default version without one) and name its active manifest.

        The manifest answer carries the commit, so the ref, the manifest and the commit come
        from one catalog call and cannot disagree.
        """
        try:
            active = await self.get_active_manifest(
                GetActiveManifestQuery(library=library, ref=ref)
            )
            if ref is not None and active.ref != ref:  # a short SHA does not count
                return None
            detail = await self.get_library(GetLibraryQuery(id=active.library))
        except NotFoundError, ValidationError:  # e.g. a ref git would not accept
            return None
        if active.manifest_id is None:
            return None
        return SearchableVersion(
            library=active.library,
            version=active.ref,
            manifest_id=active.manifest_id,
            commit_sha=active.commit_sha,
            repository_url=detail.source_url,
            host=SourceHost(detail.host.value),
        )


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


@dataclass(frozen=True, slots=True)
class CatalogNewLibraries:
    """Implements ``ingestion.ports.driven.NewLibraries`` using the catalog."""

    create_library: CreateLibrary
    discard_library: DiscardLibrary

    async def add(self, library: NewLibrary) -> str:
        """Create the library in the catalog; return its canonical ID."""
        created = await self.create_library(
            CreateLibraryCommand(
                id=library.library_id,
                title=library.title,
                source_url=library.source_url,
                host=HostKind(library.host.value),
                default_branch=library.default_branch,
                include_paths=list(library.selection.include),
                exclude_paths=list(library.selection.exclude),
                tag_rules=[TagRuleIn(pattern=r.pattern, tag=r.tag) for r in library.tag_rules],
            )
        )
        return created.id

    async def discard(self, library_id: str) -> None:
        """Remove the library from the catalog again."""
        await self.discard_library(DiscardLibraryCommand(id=library_id))
