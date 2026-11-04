"""Adapters that connect one domain's driven port to another domain's driving port.

This is how domains talk to each other without importing each other: the consumer declares a
port in its own language, and a bridge here translates to the provider's public use case.
"""

import asyncio
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ApplyReadmeCommand,
    ArticleIn,
    CollectGarbageCommand,
    CreateLibraryCommand,
    DiscardLibraryCommand,
    DiscardPendingManifestsCommand,
    GetActiveManifestQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    HostKind,
    ListLibrariesQuery,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    StoreManifestCommand,
    TagRuleIn,
)
from exactdocs.catalog.dtos import (
    RefKind as CatalogRefKind,
)
from exactdocs.catalog.dtos import (
    Removal as CatalogRemoval,
)
from exactdocs.catalog.models import ManifestState
from exactdocs.catalog.ports.driving import (
    ActivateManifest,
    ApplyReadme,
    CollectGarbage,
    CreateLibrary,
    DiscardLibrary,
    DiscardPendingManifests,
    GetActiveManifest,
    GetLibrary,
    GetManifestStates,
    ListLibraries,
    RemoveLibrary,
    RemoveVersion,
    StoreManifest,
)
from exactdocs.ingestion.models import (
    PARSER_VERSION,
    ArticleChunk,
    Collected,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    NewLibrary,
    PathSelection,
    ProposedId,
    RefKind,
    Removed,
    RepositoryUrl,
    TagRule,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    GetChunkSetsQuery,
    IndexManifestCommand,
    RemoveChunksCommand,
)
from exactdocs.retrieval.models import (
    CatalogLibrary,
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.ports.driving import (
    CollectChunks,
    DiscardPendingChunks,
    GetChunkSets,
    IndexManifest,
    RemoveChunks,
)
from exactdocs_kernel import MAX_LIMIT, NotFoundError, ValidationError


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
class CatalogLibraries:
    """Implements ``retrieval.ports.driven.Libraries`` using the catalog."""

    list_libraries: ListLibraries

    async def all(self) -> Sequence[CatalogLibrary]:
        """Read every page of the catalog's list, skipping libraries with no default version."""
        found: list[CatalogLibrary] = []
        cursor = None
        while True:
            page = await self.list_libraries(ListLibrariesQuery(limit=MAX_LIMIT, cursor=cursor))
            found += [
                CatalogLibrary(
                    id=lib.id,
                    title=lib.title,
                    description=lib.description,
                    source_url=lib.source_url,
                    default_version=lib.default_version,
                    versions=tuple(r.ref for r in lib.refs),
                    version_count=lib.version_count,
                    last_imported_at=lib.last_imported_at,
                )
                for lib in page.libraries
                if lib.default_version is not None
            ]
            cursor = page.next_cursor
            if cursor is None:
                return found


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


@dataclass(frozen=True, slots=True)
class CatalogLibrarySources:
    """Implements ``ingestion.ports.driven.LibrarySources`` using the catalog."""

    get_library: GetLibrary

    async def get(self, library: str) -> ImportSource:
        """Read the library's repository, selection and tag rules; ``NotFoundError`` if unknown."""
        detail = await self.get_library(GetLibraryQuery(id=library))
        settings = detail.settings
        return ImportSource(
            url=RepositoryUrl.parse(detail.source_url),
            selection=PathSelection.of(settings.include_paths, settings.exclude_paths),
            tag_rules=TagRule.many([(r.pattern, r.tag) for r in settings.tag_rules]),
        )

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        """Return the library's imported versions with their kind and commit."""
        detail = await self.get_library(GetLibraryQuery(id=library))
        return [
            ImportedRef(ref=v.ref, kind=RefKind(v.kind.value), commit_sha=v.commit_sha)
            for v in detail.versions
        ]


@dataclass(frozen=True, slots=True)
class CatalogVersionPublisher:
    """Implements ``ingestion.ports.driven.VersionPublisher`` using the catalog."""

    store_manifest: StoreManifest
    activate_manifest: ActivateManifest
    discard_pending_manifests: DiscardPendingManifests
    apply_readme: ApplyReadme

    async def store(self, version: ImportedVersion) -> str:
        """Store the articles as a pending manifest."""
        command = await asyncio.to_thread(_store_command, version)
        stored = await self.store_manifest(command)
        return stored.manifest_id

    async def activate(self, manifest_id: str) -> None:
        """Make the manifest what its version serves."""
        await self.activate_manifest(ActivateManifestCommand(manifest_id=manifest_id))

    async def describe(
        self, *, library: str, ref: str, title: str | None, description: str | None
    ) -> None:
        """Offer the README's text to the catalog, which decides whether it applies."""
        await self.apply_readme(
            ApplyReadmeCommand(library=library, ref=ref, title=title, description=description)
        )

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete one pending manifest, or the library's pending manifests."""
        await self.discard_pending_manifests(
            DiscardPendingManifestsCommand(
                manifest_id=manifest_id, library=None if manifest_id else library
            )
        )


@dataclass(frozen=True, slots=True)
class RetrievalChunkIndex:
    """Implements ``ingestion.ports.driven.ChunkIndex`` using retrieval."""

    index_manifest: IndexManifest
    get_chunk_sets: GetChunkSets
    discard_pending_chunks: DiscardPendingChunks
    remove_chunks: RemoveChunks

    async def known(
        self, config_hash: str, blob_shas: Sequence[str]
    ) -> Mapping[str, tuple[ArticleChunk, ...]]:
        """Read back the chunks stored for these blobs."""
        found = await self.get_chunk_sets(
            GetChunkSetsQuery(config_hash=config_hash, blob_shas=list(blob_shas))
        )
        return {
            sha: tuple(
                ArticleChunk(
                    heading_path=tuple(c.heading_path),
                    occurrence_index=c.occurrence_index,
                    position=position,
                    content=c.content,
                    content_hash=c.content_hash,
                    anchor=c.anchor,
                    code_languages=tuple(c.code_languages),
                )
                for position, c in enumerate(chunks)
            )
            for sha, chunks in found.chunks.items()
        }

    async def index(self, manifest_id: str, version: ImportedVersion) -> None:
        """Store and index the chunks of the pending manifest."""
        command = await asyncio.to_thread(_index_command, manifest_id, version)
        await self.index_manifest(command)

    async def discard(self, *, manifest_id: str | None, library: str) -> None:
        """Delete one pending manifest's chunks, or the library's pending chunks."""
        await self.discard_pending_chunks(
            DiscardPendingChunksCommand(
                manifest_id=manifest_id, library=None if manifest_id else library
            )
        )

    async def remove(self, manifest_ids: Sequence[str]) -> None:
        """Delete the chunks of manifests the catalog has just deleted."""
        await self.remove_chunks(RemoveChunksCommand(manifest_ids=list(manifest_ids)))


@dataclass(frozen=True, slots=True)
class CatalogRemovals:
    """Implements ``ingestion.ports.driven.Removals`` using the catalog."""

    version_remover: RemoveVersion
    library_remover: RemoveLibrary

    async def remove_version(self, library: str, ref: str) -> Removed:
        """Remove the version from the catalog."""
        return _removed(await self.version_remover(RemoveVersionCommand(library=library, ref=ref)))

    async def remove_library(self, library: str) -> Removed:
        """Remove the library from the catalog."""
        return _removed(await self.library_remover(RemoveLibraryCommand(library=library)))


def _removed(result: CatalogRemoval) -> Removed:
    return Removed(
        library=result.library,
        ref=result.ref,
        manifest_ids=tuple(result.manifest_ids),
        default_ref=result.default_ref,
    )


@dataclass(frozen=True, slots=True)
class CatalogCollector:
    """Implements ``ingestion.ports.driven.Collector`` using the catalog."""

    collect_garbage: CollectGarbage

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete superseded manifests past the grace period and the texts nothing uses."""
        done = await self.collect_garbage(CollectGarbageCommand(grace_seconds=grace_seconds))
        return Collected(deleted=done.manifests + done.contents)


@dataclass(frozen=True, slots=True)
class RetrievalCollector:
    """Implements ``ingestion.ports.driven.Collector`` using retrieval."""

    collect_chunks: CollectChunks

    async def collect(self, *, grace_seconds: int) -> Collected:
        """Delete chunk rows of manifests the catalog no longer knows, and unused chunk sets.

        The job's grace period keeps superseded *catalog* manifests; the catalog is already
        done with them, so retrieval asks for none beyond its own five minutes of doubt about
        a manifest the catalog has not answered for yet. That also sweeps the rows of a removal
        whose ``RemoveChunks`` failed.
        """
        del grace_seconds
        done = await self.collect_chunks(CollectChunksCommand(grace_seconds=0))
        return Collected(deleted=done.manifests + done.chunk_sets)


def _store_command(version: ImportedVersion) -> StoreManifestCommand:
    """Build the catalog's command (validates every article: off the event loop)."""
    return StoreManifestCommand(
        library=version.library,
        ref=version.ref,
        kind=CatalogRefKind(version.kind.value),
        commit_sha=version.commit_sha,
        must_exist=version.refresh,
        articles=[
            ArticleIn(
                path=a.path,
                blob_sha=a.blob_sha,
                content_version=PARSER_VERSION,
                title=a.title,
                tags=list(a.tags),
                front_matter=a.front_matter,
                content=a.content,
            )
            for a in version.articles
        ],
    )


def _index_command(manifest_id: str, version: ImportedVersion) -> IndexManifestCommand:
    """Build retrieval's command (validates every chunk: off the event loop)."""
    return IndexManifestCommand(
        manifest_id=manifest_id,
        library=version.library,
        ref=version.ref,
        config_hash=version.config_hash,
        articles=[
            ArticleChunksIn(
                path=a.path,
                blob_sha=a.blob_sha,
                tags=list(a.tags),
                chunks=[
                    ChunkIn(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
                        content=c.content,
                        content_hash=c.content_hash,
                        anchor=c.anchor,
                        code_languages=list(c.code_languages),
                    )
                    for c in a.chunks
                ],
            )
            for a in version.articles
        ],
    )
