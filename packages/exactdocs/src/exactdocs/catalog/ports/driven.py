"""Driven (secondary) ports: what the catalog needs from infrastructure."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from exactdocs.catalog.models import (
    Access,
    ContentKey,
    GarbageCollected,
    ImportedTags,
    Library,
    LibraryId,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestInstruction,
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
from exactdocs_kernel import Sort, SortValue


class LibraryRepository(Protocol):
    """Persistence for catalog entries."""

    async def list_all(self) -> Sequence[Library]:
        """Return every library.

        Returns:
            The libraries with their versions.
        """
        ...

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``.

        Args:
            library_id: The library ID.

        Returns:
            The library with its versions, or ``None``.
        """
        ...

    async def add(self, library: Library) -> None:
        """Store a new library (and its versions). Raises ``LibraryAlreadyExistsError``.

        The ID check and the write are one step, so two callers cannot both succeed.

        Args:
            library: The new library.
        """
        ...

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library and everything stored under it; nothing happens if it is absent.

        Args:
            library_id: The library.
        """
        ...

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same ID.

        The pin is left as stored (``pin_default`` owns it), so saving an older read keeps it.

        Args:
            library: The library, with its versions.
        """
        ...

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        """Set the given fields (not ``None``) and mark them as edited by a user.

        Touches nothing else, so it cannot undo a concurrent change. Absent IDs are ignored.

        Args:
            library_id: The library.
            title: The new title; ``None`` leaves it.
            description: The new description; ``None`` leaves it.
        """
        ...

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        """Pin the default version to ``ref``, or unpin with ``None``; touches nothing else.

        A ref is pinned only if the library has a version with exactly that ref, checked by the
        write itself, so a version removed in between is never pinned. Returns whether anything
        was written (``False``: no such library, or no such version).

        Args:
            library_id: The library.
            ref: The exact ref to pin; ``None`` unpins.

        Returns:
            Whether anything was written.
        """
        ...

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        """Set title and description, except a field a user edited, and the rules, atomically.

        The edited flags are read by the write itself, so a user's edit that lands in between
        is never overwritten. Absent IDs are ignored. Rules are written only here (``add`` and
        ``save`` leave them alone), so a stale ``save`` cannot undo them.

        Args:
            library_id: The library.
            title: The title, unless a user edited it.
            description: The description, unless a user edited it.
            rules: The library's rules.
        """
        ...

    async def set_settings(self, library_id: LibraryId, settings: LibrarySettings) -> None:
        """Replace the library's settings; touches nothing else. Absent IDs are ignored.

        Args:
            library_id: The library.
            settings: The new settings.
        """
        ...

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        """Return the library's manual tags by article path; empty for an unknown library.

        Args:
            library_id: The library.

        Returns:
            The manual tags, by the path they were set on.
        """
        ...

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        """Replace the manual tags of one path; no tags forgets the path. Absent IDs are ignored.

        They go when the library goes.

        Args:
            library_id: The library.
            tags: The path and its new tags.
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

        Args:
            manifest: The pending manifest, with its entries and renames.
            contents: The article texts, by content key.
            images: The image bytes, by blob SHA.
            version_must_exist: Refuse unless the version is already imported.
        """
        ...

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest without its entries (see ``list_entries``), or ``None``.

        Args:
            manifest_id: The manifest.

        Returns:
            The manifest, or ``None``.
        """
        ...

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out.

        Batched, so a caller may pass thousands of IDs.

        Args:
            manifest_ids: The manifests.

        Returns:
            The manifests found, by ID.
        """
        ...

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``.

        Args:
            library_id: The library.
            ref: The exact ref.

        Returns:
            The active manifest, or ``None``.
        """
        ...

    async def get_active_many(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], Manifest]:
        """Return the active manifests (without entries) of these versions, by (library, ref).

        Versions without one are left out. Batched, so a caller may pass thousands of versions.

        Args:
            versions: The versions, as ``(library, ref)``.

        Returns:
            The active manifests found, by version.
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

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            after: Only paths after this one; ``None`` from the start.
            limit: The most entries returned.

        Returns:
            The entries, sorted by path.
        """
        ...

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted, and nothing else.

        Cheap on purpose (no titles, tags or front matter): it feeds "did you mean" suggestions.

        Args:
            manifest_id: The manifest.
            limit: The most paths returned.

        Returns:
            The paths, sorted.
        """
        ...

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name.

        Args:
            manifest_id: The manifest.
            limit: The most tags returned.

        Returns:
            The tags with their article counts.
        """
        ...

    async def list_live(self, library_id: LibraryId) -> Sequence[Manifest]:
        """Return the library's pending and active manifests, without entries.

        Args:
            library_id: The library.

        Returns:
            The pending and active manifests.
        """
        ...

    async def set_manual_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[ManualTag, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Give every entry of the manifest the manual tags ``tags`` names for its path (or none).

        Imported tags are kept. Returns the ``all_tags`` of each entry that has manual tags now or
        had some before, so the copies kept elsewhere can be brought in line with it.

        Args:
            manifest_id: The manifest.
            tags: The manual tags of each path; a path left out gets none.

        Returns:
            The tags of each entry touched, by path.
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

        Args:
            manifest_id: The manifest.
            path: The old path (``FORWARD``) or the new one (``BACK``).
            direction: Which way to follow the path.

        Returns:
            The rename, or ``None``.
        """
        ...

    async def list_renames(
        self, manifest_id: ManifestId, *, limit: int
    ) -> Sequence[ManifestRename]:
        """Return up to ``limit`` renames of the manifest, sorted by old path.

        Args:
            manifest_id: The manifest.
            limit: The most renames returned.

        Returns:
            The renames, sorted by old path.
        """
        ...

    async def replace_renames(
        self,
        manifest_id: ManifestId,
        renames: Sequence[ManifestRename],
        *,
        renamed_from: VersionRef | None,
    ) -> None:
        """Make ``renames`` the manifest's whole rename map, in one transaction.

        Renames whose new path is not an entry of the manifest are left out; so is a second
        rename of an old path (the first one counts). An unknown manifest is left alone.

        Args:
            manifest_id: The manifest.
            renames: The new rename map.
            renamed_from: The version the map was detected against (``Manifest.renamed_from``).
        """
        ...

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``.

        Args:
            library_id: The library.
            ref: The exact ref.
            path: The article's path.

        Returns:
            The article with its text, or ``None``.
        """
        ...

    async def get_image(
        self, library_id: LibraryId, ref: VersionRef, path: str, *, with_data: bool = True
    ) -> StoredImage | None:
        """Return the image at ``path`` of the version's active manifest, or ``None``.

        Without ``with_data`` the bytes are not read (``data`` is empty): enough to compare SHAs.

        Args:
            library_id: The library.
            ref: The exact ref.
            path: The image's path.
            with_data: Whether to read the bytes.

        Returns:
            The image, or ``None``.
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

        Args:
            manifest_id: The manifest.
            at: When it is activated: the version's new ``imported_at``.

        Returns:
            The version as it is now.
        """
        ...

    async def discard_pending(
        self,
        *,
        manifest_id: ManifestId | None,
        library_id: LibraryId | None,
        created_before: datetime | None,
    ) -> int:
        """Delete the pending manifests that match every given filter; return how many.

        Args:
            manifest_id: Only this manifest; ``None``: any.
            library_id: Only manifests of this library; ``None``: any.
            created_before: Only manifests stored before this time; ``None``: any.

        Returns:
            How many manifests were deleted.
        """
        ...

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then texts and images no manifest uses.

        Args:
            superseded_before: The cutoff.

        Returns:
            How many manifests, texts and images were deleted.
        """
        ...

    async def remove_version(self, library_id: LibraryId, ref: VersionRef) -> Sequence[ManifestId]:
        """Delete the version row and every manifest of the ref (any state), in one transaction.

        Returns the deleted manifest IDs. Raises ``VersionNotFoundError`` when the library has no
        such version; the manifests and the version go together, never one without the other.
        A pin on the ref is cleared in the same transaction, so a later import does not re-pin it.

        Args:
            library_id: The library.
            ref: The exact ref.

        Returns:
            The deleted manifest IDs.
        """
        ...

    async def remove_library(self, library_id: LibraryId) -> Sequence[ManifestId]:
        """Delete the library, its versions and all its manifests, in one transaction.

        Returns the deleted manifest IDs. Raises ``LibraryNotFoundError``.

        Args:
            library_id: The library.

        Returns:
            The deleted manifest IDs.
        """
        ...


class ImportedTagWriter(Protocol):
    """Rewrites the imported tags of manifest entries (after a library's tag rules changed).

    Split from ``ManifestRepository`` only to keep that port within ruff's public-method limit
    (PLR0904): same tables, same transaction rules. Do not fold it back in.
    """

    async def set_imported_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, ImportedTags]
    ) -> Mapping[str, tuple[str, ...]]:
        """Replace the imported tags of the entries at these paths, in one transaction.

        Only entries whose tags or their sources differ are written; manual tags are kept; paths
        the manifest lacks are ignored. Returns the ``all_tags`` of every given entry the manifest
        has, changed or not, so copies kept elsewhere can be brought in line (also after a crash
        between this write and theirs).

        Args:
            manifest_id: The manifest.
            tags: The new imported tags with their sources, by path.

        Returns:
            The tags of each given entry the manifest has, by path.
        """
        ...


class ArticleTitleFinder(Protocol):
    """Titles of a manifest's articles by path, for other domains (one query per batch)."""

    async def titles(self, manifest_id: ManifestId, paths: Collection[str]) -> Mapping[str, str]:
        """Return the title of each of these paths of the manifest.

        Args:
            manifest_id: The manifest (any state).
            paths: The article paths.

        Returns:
            The titles found; paths the manifest does not have are left out, and an unknown
            manifest has none.
        """
        ...


class StoredArticleFinder(Protocol):
    """Finds stored articles by what they were imported from, across a library's manifests.

    Split from ``ManifestRepository`` only to keep that port within ruff's public-method limit
    (PLR0904), like ``ImportedTagWriter``: same tables.
    """

    async def find_articles(
        self,
        library_id: LibraryId,
        ref: VersionRef | None,
        content_version: int,
        files: Collection[tuple[str, str]],
    ) -> Sequence[StoredArticle]:
        """Return one stored article per ``(path, blob SHA)`` stored with ``content_version``.

        The active manifest of ``ref`` (the version being refreshed) is looked in first, then
        any manifest of the library (pending, active or superseded); files no manifest holds
        that way are left out. Batched and indexed, so a caller may pass thousands of files
        whatever the size of the catalog.

        Args:
            library_id: The library.
            ref: The version being imported, looked in first; ``None``: none.
            content_version: The parser version the texts must be stored by.
            files: The files, as ``(path, blob SHA)``.

        Returns:
            One stored article per file found.
        """
        ...


class InstructionFileReader(Protocol):
    """Reads the instruction files kept with a manifest (RET-08).

    Split from ``ManifestRepository`` for the same reason as ``ImportedTagWriter`` (PLR0904):
    same tables; ``ManifestRepository.add`` stores them, ``ManifestCopier`` copies them.
    """

    async def list_instructions(self, manifest_id: ManifestId) -> Sequence[ManifestInstruction]:
        """Return the instruction files kept with the manifest, sorted by path.

        Args:
            manifest_id: The manifest (any state).

        Returns:
            Its files; none for an unknown manifest.
        """
        ...


class ManifestCopier(Protocol):
    """Copies a version's active manifest into a new pending one (re-chunking what it serves).

    Split from ``ManifestRepository`` for the same reason as ``ImportedTagWriter`` (PLR0904):
    same tables, same transaction rules.
    """

    async def copy_active(
        self,
        library_id: LibraryId,
        ref: VersionRef,
        new_id: ManifestId,
        *,
        at: datetime,
        content_version: int,
    ) -> tuple[Manifest, Sequence[StoredArticle]] | None:
        """Store a pending copy of the version's active manifest, in one transaction.

        The copy, ``new_id`` created ``at``, has the same commit, entries (tags, manual tags and
        front matter included), images, renames and instruction files. Returns it (without
        entries) with each article as a reader gets it, by path; ``None`` when the version has no
        active manifest. Raises ``StoredContentOutdatedError`` and copies nothing when an entry was
        stored by another parser version than ``content_version``.

        Args:
            library_id: The library.
            ref: The exact ref.
            new_id: The copy's ID.
            at: The copy's creation time.
            content_version: The parser version the texts must be stored by.

        Returns:
            The copy and its articles, or ``None``.
        """
        ...


class AccessPolicy(Protocol):
    """Library roles: what the caller may do with a library (a bridge to identity)."""

    async def can_create(self, library: str | None = None) -> bool:
        """Tell whether the caller has the instance-wide library creation permission.

        Args:
            library: Proposed ID when known; None before one is available.

        Returns:
            Whether creation is permitted.
        """
        ...

    async def allows(self, library: str, access: Access) -> bool:
        """Tell whether the caller may do what ``access`` stands for with the library.

        Args:
            library: The library ID (``/owner/repo``), any case.
            access: The role the action needs.

        Returns:
            ``True`` when the caller's effective role on the library is that or higher.
        """
        ...

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Return the libraries the caller may read.

        Args:
            libraries: Library IDs.

        Returns:
            The lower-case IDs among them the caller may read.
        """
        ...

    async def claim(self, library: str) -> None:
        """Record the caller, if there is one, as the creator of a library just created.

        Args:
            library: The library ID.
        """
        ...

    async def forget(self, library: str) -> None:
        """Drop everything granted on a library that was removed.

        Args:
            library: The library ID.
        """
        ...


class AiSwitches(Protocol):
    """Which libraries have AI turned off, for the libraries list's `ai_enabled` filter."""

    async def disabled(self) -> frozenset[str]:
        """Return the libraries whose AI is turned off.

        Returns:
            Their lower-case IDs; a library that is not in the set has AI on.
        """
        ...


class EntrySearch(Protocol):
    """Filters, sorts and pages the entries of a manifest in the store.

    A read of the same tables as ``ManifestRepository``, split from it for ``PLR0904``.
    """

    async def search(
        self,
        manifest_id: ManifestId,
        *,
        prefix: str,
        tags: TagSelection,
        text: str | None,
        sort: Sort,
        after: tuple[SortValue, str] | None,
        limit: int,
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` filtered entries in ``sort`` order, after the ``after`` key.

        The filters are those of ``ManifestRepository.list_entries`` plus ``text``.
        ``sort.field`` is ``path``, ``title`` (compared lower-cased, by code point) or ``size``;
        the path breaks ties, in the sort's direction.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            text: Only entries whose path or title contains this text, any case; ``None``: all.
            sort: The order.
            after: The sort value and path of the last entry of the previous page.
            limit: The most entries returned.

        Returns:
            The entries in order.
        """
        ...

    async def count(
        self, manifest_id: ManifestId, *, prefix: str, tags: TagSelection, text: str | None
    ) -> int:
        """Count the entries that ``search`` pages over.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            text: Only entries whose path or title contains this text, any case; ``None``: all.

        Returns:
            How many entries match.
        """
        ...
