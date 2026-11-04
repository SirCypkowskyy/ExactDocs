"""Driven (secondary) ports: what the catalog needs from infrastructure."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.catalog.models import (
    GarbageCollected,
    Library,
    LibraryId,
    Manifest,
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

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same ID."""
        ...


class ManifestRepository(Protocol):
    """Persistence for manifests and the article content they share, keyed by blob SHA."""

    async def add(self, manifest: Manifest, contents: Mapping[str, str]) -> None:
        """Store a pending manifest and the contents it needs (blob SHA to text).

        One transaction. A content that is already stored is left as it is (idempotent).
        """
        ...

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest with its entries sorted by path, or ``None``."""
        ...

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the active manifest of this version, or ``None``."""
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
        ``at``). Raises ``ManifestNotFoundError`` / ``ManifestNotPendingError``; on any failure
        the previous manifest stays active.
        """
        ...

    async def discard_pending(self, manifest_id: ManifestId | None) -> int:
        """Delete one pending manifest, or every pending one for ``None``; return how many."""
        ...

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then contents no manifest uses."""
        ...
