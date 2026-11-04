"""Driven (secondary) ports of retrieval."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    Excerpt,
    IndexedManifest,
    ManifestChunk,
    ManifestStatus,
    Removed,
    SearchText,
    StoredChunk,
)


class IndexedVersions(Protocol):
    """Which library versions have an index.

    The catalog domain owns this knowledge. Retrieval states what it needs in its own terms
    and the composition root plugs in an adapter, so neither domain imports the other.
    """

    async def find_indexed(self, target: DocTarget) -> DocTarget | None:
        """Return ``target`` in its canonical spelling, or ``None`` unless that version exists.

        Canonical means the library ID as stored (`/Acme/Payments` is `/acme/payments`); the
        version is never altered or approximated.
        """
        ...


class ExcerptIndex(Protocol):
    """Search backend (BM25 + vectors + rerank) scoped to one library version."""

    async def search(self, target: DocTarget, text: SearchText, limit: int) -> Sequence[Excerpt]:
        """Return at most ``limit`` excerpts from ``target`` only, best first."""
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

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        ...

    async def find_manifests(
        self, *, manifest_id: str | None, library: str | None, indexed_before: datetime | None
    ) -> Sequence[IndexedManifest]:
        """Return the indexed manifests that match every given filter."""
        ...

    async def remove(self, manifest_ids: Collection[str]) -> Removed:
        """Delete these manifests' rows, then every chunk set no manifest points at."""
        ...
