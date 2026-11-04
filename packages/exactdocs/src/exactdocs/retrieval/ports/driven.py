"""Driven (secondary) ports of retrieval."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.retrieval.models import (
    CatalogLibrary,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    IndexedManifest,
    ManifestChunk,
    ManifestHit,
    ManifestStatus,
    Removed,
    SearchableVersion,
    SearchHit,
    StoredChunk,
    TagFilter,
    VersionCounts,
)


class SearchableVersions(Protocol):
    """Which version a search runs on, in retrieval's own terms (the catalog answers).

    Version is a hard filter: an unknown version is ``None``, never another version.
    """

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        """Return the exact ``ref`` (the default version when ``None``) and the manifest it serves.

        ``None`` when there is no such version or it has no active manifest.
        """
        ...


class DefaultVersions(Protocol):
    """Every library's default version that has an active manifest, in one call."""

    async def all(self) -> Sequence[SearchableVersion]:
        """Return them sorted by library ID; libraries with nothing readable are left out."""
        ...


class Libraries(Protocol):
    """The libraries the catalog lists, in retrieval's own terms."""

    async def all(self) -> Sequence[CatalogLibrary]:
        """Return every library that has a default version; the rest cannot be queried."""
        ...


class ActiveManifests(Protocol):
    """What the catalog says about manifests. Retrieval holds manifest IDs by value only.

    The order is: the catalog stores the manifest (pending), retrieval indexes it, the catalog
    activates it. So a manifest the catalog does not know is one it already dropped, or one
    whose Store call has not been answered yet; only an old one is safe to remove.
    """

    async def active_id(self, target: DocTarget) -> str | None:
        """Return the ID of the version's active manifest, or ``None`` when it has none."""
        ...

    async def statuses(self, manifest_ids: Collection[str]) -> Mapping[str, ManifestStatus]:
        """Return the status of each ID the catalog knows; unknown IDs are left out.

        A status this domain has no name for is ``ManifestStatus.OTHER``.
        """
        ...


class RenamedPaths(Protocol):
    """Renames git saw, in retrieval's terms (the catalog answers)."""

    async def new_path(self, target: DocTarget, old_path: str) -> str | None:
        """Return where ``old_path`` of the version before is in the target version, or ``None``.

        ``None`` also when nothing is known (no map, no active manifest): never an error.
        """
        ...


class ChunkRepository(Protocol):
    """Chunk sets (shared by content) and the per-manifest chunk rows that point at them."""

    async def add(
        self,
        manifest: IndexedManifest,
        chunk_sets: Mapping[ChunkSetKey, ChunkSet],
        rows: Sequence[ManifestChunk],
    ) -> int | None:
        """Store the manifest's rows and the chunk sets it needs, in one transaction.

        A chunk set whose key is already stored is left as it is, but its digest must match
        (``ChunkSetMismatchError`` otherwise, nothing is stored). Returns how many chunk sets
        were new, or ``None`` without changing anything when this manifest ID is already indexed.
        """
        ...

    async def get_sets(self, keys: Sequence[ChunkSetKey]) -> Mapping[ChunkSetKey, ChunkSet]:
        """Return the stored chunk sets among ``keys``, chunks in order; the rest is left out.

        Batched, so a caller may pass thousands of keys.
        """
        ...

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        ...

    async def get_many(
        self, manifest_id: str, chunk_ids: Sequence[ChunkId]
    ) -> Mapping[ChunkId, StoredChunk]:
        """Return the chunks of the manifest that exist, by ID, in one query."""
        ...

    async def get_across(
        self, wanted: Mapping[str, Collection[ChunkId]]
    ) -> Mapping[tuple[str, ChunkId], StoredChunk]:
        """Return the chunks that exist, by (manifest ID, chunk ID), for several manifests at once.

        One query, whatever the number of manifests; missing pairs are left out.
        """
        ...

    async def article(self, manifest_id: str, article_path: str) -> Sequence[StoredChunk]:
        """Return all chunks of one article of the manifest in order; empty if it has none."""
        ...

    async def counts(self, manifest_id: str) -> VersionCounts:
        """Count the manifest's articles and chunks; zeros for an unknown manifest."""
        ...

    async def manifests_with_chunk(self, chunk_id: ChunkId) -> Sequence[IndexedManifest]:
        """Return every indexed manifest that has a row for this chunk ID (any status)."""
        ...

    async def find_manifests(
        self, *, manifest_id: str | None, library: str | None, indexed_before: datetime | None
    ) -> Sequence[IndexedManifest]:
        """Return the indexed manifests that match every given filter."""
        ...

    async def remove(self, manifest_ids: Collection[str]) -> Removed:
        """Delete these manifests' rows, then every chunk set no manifest points at."""
        ...


class SearchIndex(Protocol):
    """Full-text (BM25) search over stored chunk sets; SQLite FTS5 now, ParadeDB later.

    Every engine behaves the same: see ``tests/retrieval/test_search_index.py``. The index holds
    one entry per chunk of a chunk set, so a set shared by several manifests is indexed once.
    Which chunks a search may return is decided by the manifest's chunk rows, not by the index.
    Entries die with their chunk rows: when ``ChunkRepository.remove`` deletes a chunk set its
    index entries go in the same step, so discard and collect need no call here.
    """

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index a chunk set that ``ChunkRepository.add`` stored. Idempotent; indexes only gaps."""
        ...

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return at most ``limit`` chunks of this manifest, best first.

        ``query`` is plain text: quotes, ``NEAR``, ``*`` and ``(`` are ordinary characters, never
        syntax. Its words are alternatives (see ``identifier_tokens``). Snippets are verbatim text
        of the chunk with offsets from ``highlights``. ``tag_filter`` is applied
        before ranking: the best ``limit`` of the chunks that pass, not the passing part of the
        best ``limit``. An unknown manifest or a query without words gives no hits.
        """
        ...

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return at most ``limit`` chunks of any of these manifests, best first, in one search.

        Same rules as ``search``. Scores are comparable across manifests: the statistics are
        global over the stored chunks, never per manifest. A chunk set shared by two manifests
        is a hit for each (they are different library versions), with the same score.
        """
        ...

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Return how many chunks of each manifest match, uncapped; zero counts are left out."""
        ...
