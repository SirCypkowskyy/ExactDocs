from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from exactdocs.retrieval.dtos import (
    ChunkOut,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    GetChunkQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    RemovedChunks,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.errors import ChunkNotFoundError, VersionNotIndexedError
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    IndexedManifest,
    ManifestChunk,
    ManifestStatus,
    SearchText,
    article_chunk_rows,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    ExcerptIndex,
    IndexedVersions,
)
from exactdocs_kernel import Clock

# A manifest the catalog does not know may just not have been stored there yet (the order is
# Store -> Index -> Activate, but the calls are not one transaction), so it is removed only once
# it is this old.
UNKNOWN_MANIFEST_GRACE = timedelta(minutes=5)


async def _confirmed_removals(
    manifests: ActiveManifests,
    candidates: Sequence[IndexedManifest],
    *,
    now: datetime,
    pending_too: bool,
) -> list[str]:
    """Pick the manifests safe to remove, asking the catalog twice.

    Removable: pending in the catalog (when ``pending_too``), or unknown to it and older than
    the grace period. Everything else stays, including a status we cannot name. The second
    question comes right before the delete and narrows the window in which a manifest could
    be activated; it cannot close it, as that would take a transaction across both domains.
    """
    unknown_before = now - UNKNOWN_MANIFEST_GRACE
    survivors = list(candidates)
    for _ in range(2):
        statuses = await manifests.statuses([m.manifest_id for m in survivors])
        survivors = [
            m
            for m in survivors
            if ((status := statuses.get(m.manifest_id)) is None and m.indexed_at < unknown_before)
            or (pending_too and status is ManifestStatus.PENDING)
        ]
        if not survivors:
            break
    return [m.manifest_id for m in survivors]


@dataclass(frozen=True, slots=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: IndexedVersions
    index: ExcerptIndex

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Search one exact version; never fall back to another version."""
        target = DocTarget(library=query.library, version=query.version)
        indexed = await self.versions.find_indexed(target)
        if indexed is None:
            raise VersionNotIndexedError(target.library, target.version)
        excerpts = await self.index.search(indexed, SearchText(value=query.query), query.limit)
        return SearchDocsResult.from_models(excerpts)


@dataclass(frozen=True, slots=True)
class IndexManifestUseCase:
    """Implements ``ports.driving.IndexManifest``."""

    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Compute the chunk IDs and store the rows plus the chunk sets that are new.

        Call it between the catalog's store (pending) and its activate, never after.
        """
        library = command.library.lower()
        manifest = IndexedManifest(
            manifest_id=command.manifest_id,
            version_id=f"{library}/{command.ref}",
            library=library,
            indexed_at=self.clock.now(),
        )
        chunk_sets: dict[ChunkSetKey, ChunkSet] = {}
        rows: list[ManifestChunk] = []
        for article in command.articles:
            chunk_set = chunk_sets.setdefault(
                (article.blob_sha, command.config_hash),
                ChunkSet(
                    blob_sha=article.blob_sha,
                    config_hash=command.config_hash,
                    chunks=tuple(
                        Chunk(
                            heading_path=tuple(c.heading_path),
                            occurrence_index=c.occurrence_index,
                            content=c.content,
                            content_hash=c.content_hash,
                            anchor=c.anchor,
                            code_languages=tuple(c.code_languages),
                        )
                        for c in article.chunks
                    ),
                ),
            )
            rows += article_chunk_rows(
                manifest.version_id, article.path, chunk_set, tuple(article.tags)
            )
        stored = await self.chunks.add(manifest, chunk_sets, rows)
        ids: dict[str, list[str]] = {a.path: [] for a in command.articles}
        for row in rows:
            ids[row.article_path].append(row.chunk_id)
        return IndexedManifestOut(
            manifest_id=command.manifest_id,
            chunk_ids=ids,
            chunk_sets_stored=stored or 0,
            already_indexed=stored is None,
        )


@dataclass(frozen=True, slots=True)
class GetChunkUseCase:
    """Implements ``ports.driving.GetChunk``."""

    versions: IndexedVersions
    manifests: ActiveManifests
    chunks: ChunkRepository

    async def __call__(self, query: GetChunkQuery) -> ChunkOut:
        """Look the chunk up in the version's active manifest only."""
        target = DocTarget(library=query.library, version=query.version)
        indexed = await self.versions.find_indexed(target)
        active = None if indexed is None else await self.manifests.active_id(indexed)
        if indexed is None or active is None:
            raise VersionNotIndexedError(target.library, target.version)
        stored = await self.chunks.get(active, ChunkId(query.chunk_id))
        if stored is None or stored.version_id != f"{indexed.library}/{indexed.version}":
            raise ChunkNotFoundError(indexed.library, indexed.version, query.chunk_id)
        return ChunkOut.from_stored(indexed.library, indexed.version, stored)


@dataclass(frozen=True, slots=True)
class DiscardPendingChunksUseCase:
    """Implements ``ports.driving.DiscardPendingChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Delete rows of matching manifests the catalog holds as pending, or dropped long ago."""
        now = self.clock.now()
        older = command.older_than_seconds
        candidates = await self.chunks.find_manifests(
            manifest_id=command.manifest_id,
            library=None if command.library is None else command.library.lower(),
            indexed_before=None if older is None else now - timedelta(seconds=older),
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=True)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))


@dataclass(frozen=True, slots=True)
class CollectChunksUseCase:
    """Implements ``ports.driving.CollectChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run after the catalog's collection: its superseded manifests are gone, so are ours."""
        now = self.clock.now()
        cutoff = now - timedelta(seconds=command.grace_seconds)
        candidates = await self.chunks.find_manifests(
            manifest_id=None, library=None, indexed_before=cutoff
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=False)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))
