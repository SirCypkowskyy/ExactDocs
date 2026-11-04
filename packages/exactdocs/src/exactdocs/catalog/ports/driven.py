"""Driven (secondary) ports: what the catalog needs from infrastructure."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.catalog.models import (
    ContentKey,
    GarbageCollected,
    Library,
    LibraryId,
    Manifest,
    ManifestEntry,
    ManifestId,
    StoredArticle,
    Version,
    VersionRef,
)


class LibraryRepository(Protocol):
    """Persistence for catalog entries."""

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        ...

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``."""
        ...

    async def add(self, library: Library) -> None:
        """Store a new library (and its versions). Raises ``LibraryAlreadyExistsError``.

        The ID check and the write are one step, so two callers cannot both succeed.
        """
        ...

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library and everything stored under it; nothing happens if it is absent."""
        ...

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same ID."""
        ...


class ManifestRepository(Protocol):
    """Persistence for manifests and the article texts they share, keyed by content key."""

    async def add(self, manifest: Manifest, contents: Mapping[ContentKey, str]) -> None:
        """Store a pending manifest with its entries and the texts it needs.

        One transaction. A text whose key is already stored is left as it is (idempotent).
        """
        ...

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest without its entries (see ``list_entries``), or ``None``."""
        ...

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out.

        Batched, so a caller may pass thousands of IDs.
        """
        ...

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``."""
        ...

    async def list_entries(
        self, manifest_id: ManifestId, *, prefix: str, after: str | None, limit: int
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` entries sorted by path, starting after the path ``after``.

        ``prefix`` is directory-aware: ``guide`` matches ``guide`` and ``guide/...``, not
        ``guide-old/...``; empty matches everything.
        """
        ...

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``."""
        ...

    async def activate(self, manifest_id: ManifestId, *, at: datetime) -> Version:
        """Make a pending manifest the version's active one, atomically.

        In one transaction: the previous active manifest becomes superseded, this one active,
        and the version is created or moved to the manifest's commit (``imported_at`` is
        ``at``). Activating the manifest that is already active changes nothing and returns the
        version (a replay after a crash succeeds). Raises ``ManifestNotFoundError``,
        ``ManifestNotPendingError`` (superseded), or ``ManifestOutdatedError`` when the active
        manifest was created after this one. On any failure the previous manifest stays active.
        """
        ...

    async def discard_pending(
        self,
        *,
        manifest_id: ManifestId | None,
        library_id: LibraryId | None,
        created_before: datetime | None,
    ) -> int:
        """Delete the pending manifests that match every given filter; return how many."""
        ...

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then texts no manifest uses."""
        ...
