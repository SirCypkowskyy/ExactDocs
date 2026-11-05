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
    ManifestRename,
    ManualTag,
    ManualTags,
    RenameDirection,
    StoredArticle,
    StoredImage,
    TagSelection,
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
        """Store the library, replacing any earlier entry with the same ID.

        The pin is left as stored (``pin_default`` owns it), so saving an older read keeps it.
        """
        ...

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        """Set the given fields (not ``None``) and mark them as edited by a user.

        Touches nothing else, so it cannot undo a concurrent change. Absent IDs are ignored.
        """
        ...

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        """Pin the default version to ``ref``, or unpin with ``None``; touches nothing else.

        A ref is pinned only if the library has a version with exactly that ref, checked by the
        write itself, so a version removed in between is never pinned. Returns whether anything
        was written (``False``: no such library, or no such version).
        """
        ...

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        """Set title and description, except a field a user edited, and the rules, atomically.

        The edited flags are read by the write itself, so a user's edit that lands in between
        is never overwritten. Absent IDs are ignored. Rules are written only here (``add`` and
        ``save`` leave them alone), so a stale ``save`` cannot undo them.
        """
        ...

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        """Return the library's manual tags by article path; empty for an unknown library."""
        ...

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        """Replace the manual tags of one path; no tags forgets the path. Absent IDs are ignored.

        They go when the library goes.
        """
        ...


class ManifestRepository(Protocol):
    """Persistence for manifests and the article texts they share, keyed by content key."""

    async def add(
        self,
        manifest: Manifest,
        contents: Mapping[ContentKey, str],
        *,
        images: Mapping[str, StoredImage] | None = None,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest with its entries, renames, texts and image blobs.

        One transaction. A text whose key is already stored is left as it is (idempotent); so
        is an image blob (``images`` is keyed by blob SHA; the manifest lists which path holds
        which blob).
        With ``version_must_exist`` the version row is checked in the same transaction and
        ``VersionNotFoundError`` raised when it is missing: a removal either comes first (this
        fails) or later (it deletes this pending manifest, so activating it fails). Either way a
        re-sync cannot bring back a removed version.
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

    async def get_active_many(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], Manifest]:
        """Return the active manifests (without entries) of these versions, by (library, ref).

        Versions without one are left out. Batched, so a caller may pass thousands of versions.
        """
        ...

    async def list_entries(
        self,
        manifest_id: ManifestId,
        *,
        prefix: str,
        tags: TagSelection,
        after: str | None,
        limit: int,
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` entries sorted by path, starting after the path ``after``.

        Only entries that pass ``tags`` count, so ``limit`` and ``after`` page over the matches.

        ``prefix`` is directory-aware: ``guide`` matches ``guide`` and ``guide/...``, not
        ``guide-old/...``; empty matches everything.
        """
        ...

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted, and nothing else.

        Cheap on purpose (no titles, tags or front matter): it feeds "did you mean" suggestions.
        """
        ...

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name."""
        ...

    async def list_live(self, library_id: LibraryId) -> Sequence[Manifest]:
        """Return the library's pending and active manifests, without entries."""
        ...

    async def set_manual_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[ManualTag, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Give every entry of the manifest the manual tags ``tags`` names for its path (or none).

        Imported tags are kept. Returns the ``all_tags`` of each entry that has manual tags now or
        had some before, so the copies kept elsewhere can be brought in line with it.
        """
        ...

    async def find_rename(
        self,
        manifest_id: ManifestId,
        path: str,
        direction: RenameDirection = RenameDirection.FORWARD,
    ) -> ManifestRename | None:
        """Return the rename stored with the manifest that ``path`` is on, or ``None``.

        ``FORWARD``: ``path`` is an old path. ``BACK``: a new path, and the rename that made it
        is returned (the first by old path).
        """
        ...

    async def list_renames(
        self, manifest_id: ManifestId, *, limit: int
    ) -> Sequence[ManifestRename]:
        """Return up to ``limit`` renames of the manifest, sorted by old path."""
        ...

    async def replace_renames(
        self, manifest_id: ManifestId, renames: Sequence[ManifestRename]
    ) -> None:
        """Make ``renames`` the manifest's whole rename map, in one transaction.

        Renames whose new path is not an entry of the manifest are left out; so is a second
        rename of an old path (the first one counts). An unknown manifest is left alone.
        """
        ...

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``."""
        ...

    async def get_image(
        self, library_id: LibraryId, ref: VersionRef, path: str, *, with_data: bool = True
    ) -> StoredImage | None:
        """Return the image at ``path`` of the version's active manifest, or ``None``.

        Without ``with_data`` the bytes are not read (``data`` is empty): enough to compare SHAs.
        """
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
        """Delete manifests superseded before the cutoff, then texts and images no manifest uses."""
        ...

    async def remove_version(self, library_id: LibraryId, ref: VersionRef) -> Sequence[ManifestId]:
        """Delete the version row and every manifest of the ref (any state), in one transaction.

        Returns the deleted manifest IDs. Raises ``VersionNotFoundError`` when the library has no
        such version; the manifests and the version go together, never one without the other.
        A pin on the ref is cleared in the same transaction, so a later import does not re-pin it.
        """
        ...

    async def remove_library(self, library_id: LibraryId) -> Sequence[ManifestId]:
        """Delete the library, its versions and all its manifests, in one transaction.

        Returns the deleted manifest IDs. Raises ``LibraryNotFoundError``.
        """
        ...
