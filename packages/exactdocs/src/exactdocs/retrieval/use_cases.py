import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from exactdocs.retrieval.dtos import (
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    CoverageOut,
    DiscardPendingChunksCommand,
    GetChunkSetsQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    ReadChunkQuery,
    RemovedChunks,
    SearchDocsQuery,
    SearchDocsResult,
    SearchResultOut,
    SetChunkOut,
)
from exactdocs.retrieval.errors import (
    ChunkNotFoundError,
    UnavailableModeError,
    StaleChunkError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    Chunk,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    IndexedManifest,
    ManifestChunk,
    ManifestStatus,
    RetrievalMode,
    SearchText,
    TagFilter,
    article_chunk_rows,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    SearchableVersions,
    SearchIndex,
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
    """Import asyncioPick the manifests safe to remove, asking the catalog twice.

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

    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Search the active manifest of one exact version; never fall back to another version."""
        # Built only to refuse a whitespace-only query (EmptySearchTextError).
        text = SearchText(value=query.query)
        # E11: replace with the modes this instance has configured.
        available = [m.value for m in RetrievalMode]
        if query.mode is not None and query.mode.strip().lower() not in available:
            raise UnavailableModeError(query.mode, available)
        version = await self.versions.find(query.library, query.ref)
        if version is None:
            raise VersionNotIndexedError(query.library, query.ref or "(default version)")
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        # One more than asked for tells whether the answer was cut short.
        found = await self.search.search(
            version.manifest_id, text.value, tag_filter, query.limit + 1
        )
        shown = found[: query.limit]
        stored = await self.chunks.get_many(version.manifest_id, [h.chunk_id for h in shown])
        # A chunk gone since the search (the manifest was collected) leaves no result, and is not
        # counted as a candidate either, so results and coverage stay consistent.
        results = [
            SearchResultOut.from_models(version, stored[hit.chunk_id], hit)
            for hit in shown
            if hit.chunk_id in stored
        ]
        vanished = len(shown) - len(results)
        return SearchDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=RetrievalMode.BM25,
            reranked=False,
            coverage=CoverageOut(
                candidates=len(found) - vanished, reranked=0, complete=len(found) <= query.limit
            ),
            results=results,
        )


@dataclass(frozen=True, slots=True)
class IndexManifestUseCase:
    """Implements ``ports.driving.IndexManifest``."""

    chunks: ChunkRepository
    search: SearchIndex
    clock: Clock

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Compute the chunk IDs, store the rows plus the new chunk sets, and make them searchable.

        Call it between the catalog's store (pending) and its activate, never after.
        """
        library = command.library.lower()
        manifest = IndexedManifest(
            manifest_id=command.manifest_id,
            version_id=f"{library}/{command.ref}",
            library=library,
            indexed_at=self.clock.now(),
        )
        chunk_sets, rows = await asyncio.to_thread(self._build, command, manifest)
        stored = await self.chunks.add(manifest, chunk_sets, rows)
        # Also when the manifest was already indexed: a crash between the two calls above and
        # below leaves sets without index entries, and indexing only fills gaps.
        for chunk_set in chunk_sets.values():
            await self.search.index(chunk_set)
        ids: dict[str, list[str]] = {a.path: [] for a in command.articles}
        for row in rows:
            ids[row.article_path].append(row.chunk_id)
        return IndexedManifestOut(
            manifest_id=command.manifest_id,
            chunk_ids=ids,
            chunk_sets_stored=stored or 0,
            already_indexed=stored is None,
        )

    @staticmethod
    def _build(
        command: IndexManifestCommand, manifest: IndexedManifest
    ) -> tuple[dict[ChunkSetKey, ChunkSet], list[ManifestChunk]]:
        """Make the chunk sets and rows: CPU-bound (chunk IDs are hashed), so run in a thread."""
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
        return chunk_sets, rows


@dataclass(frozen=True, slots=True)
class ReadChunkUseCase:
    """Implements ``ports.driving.ReadChunk``."""

    versions: SearchableVersions
    manifests: ActiveManifests
    chunks: ChunkRepository

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Serve the chunk from its version's active manifest, or say why it cannot be served."""
        chunk_id = ChunkId(query.chunk_id)
        holders = await self.chunks.manifests_with_chunk(chunk_id)
        if not holders:
            raise ChunkNotFoundError(query.chunk_id)
        # The ID is a hash of the version it was issued for, so every holder is that version's.
        first = holders[0]
        ref = first.version_id.removeprefix(f"{first.library}/")
        version = await self.versions.find(first.library, ref)
        ids = {m.manifest_id for m in holders}
        if version is not None and version.manifest_id in ids:
            stored = await self.chunks.get(version.manifest_id, chunk_id)
            if stored is not None and stored.version_id == first.version_id:
                return ChunkOut.from_stored(version, stored)
        statuses = await self.manifests.statuses(ids)
        if ManifestStatus.SUPERSEDED in statuses.values():
            raise StaleChunkError(query.chunk_id, first.library, ref)
        raise ChunkNotFoundError(query.chunk_id)  # only pending manifests hold it: not served yet


@dataclass(frozen=True, slots=True)
class GetChunkSetsUseCase:
    """Implements ``ports.driving.GetChunkSets``."""

    chunks: ChunkRepository

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Look the sets up by (blob, config); sets that were never stored are left out."""
        found = await self.chunks.get_sets(
            [(sha, query.config_hash) for sha in dict.fromkeys(query.blob_shas)]
        )
        return ChunkSetsOut(
            chunks={
                sha: [
                    SetChunkOut(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
                        content=c.content,
                        content_hash=c.content_hash,
                        anchor=c.anchor,
                        code_languages=list(c.code_languages),
                    )
                    for c in chunk_set.chunks
                ]
                for (sha, _), chunk_set in found.items()
            }
        )


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
