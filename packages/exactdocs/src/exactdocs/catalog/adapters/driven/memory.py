from collections import Counter
from collections.abc import Collection, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Self

from exactdocs.catalog.errors import (
    LibraryAlreadyExistsError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
    ManifestOutdatedError,
    StoredContentOutdatedError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ContentKey,
    GarbageCollected,
    ImportedTags,
    Library,
    LibraryId,
    LibraryLogo,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestInstruction,
    ManifestRename,
    ManifestState,
    ManualTag,
    ManualTags,
    RenameDirection,
    StoredArticle,
    StoredImage,
    TagSelection,
    Version,
    VersionRef,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests."""

    libraries: MutableMapping[LibraryId, Library] = field(default_factory=dict)
    """The libraries, by ID."""
    manual_tags: dict[LibraryId, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    """Each library's manual tags, by the path they were set on."""
    logos: dict[LibraryId, LibraryLogo] = field(default_factory=dict)
    """Each library's logo (``InMemoryLibraryLogos`` writes them; reads give their digest)."""

    @classmethod
    def of(cls, libraries: Iterable[Library]) -> Self:
        """Create a repository pre-filled with ``libraries``.

        Args:
            libraries: The libraries.

        Returns:
            The repository.
        """
        return cls(libraries={lib.id: lib for lib in libraries})

    async def list_all(self) -> Sequence[Library]:
        """Return every library.

        Returns:
            The libraries with their versions.
        """
        return tuple(self._shown(library) for library in self.libraries.values())

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``.

        Args:
            library_id: The library ID.

        Returns:
            The library with its versions, or ``None``.
        """
        library = self.libraries.get(library_id)
        return None if library is None else self._shown(library)

    def _shown(self, library: Library) -> Library:
        """Give a stored library the digest of its logo now, as the SQL adapter's join does.

        Args:
            library: The library as stored.

        Returns:
            The library with ``logo`` set from ``logos``.
        """
        logo = self.logos.get(library.id)
        return replace(library, logo=None if logo is None else logo.digest)

    async def add(self, library: Library) -> None:
        """Store a new library; raises ``LibraryAlreadyExistsError`` if the ID is taken.

        Args:
            library: The new library.

        Raises:
            LibraryAlreadyExistsError: The library ID is taken.
        """
        if library.id in self.libraries:
            raise LibraryAlreadyExistsError(library.id.value)
        # pinned and given rules only later
        self.libraries[library.id] = replace(library, pinned_version=None, rules=())

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library, if present.

        Args:
            library_id: The library.
        """
        self.libraries.pop(library_id, None)
        self.manual_tags.pop(library_id, None)
        self.logos.pop(library_id, None)

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        """Return the library's manual tags by path.

        Args:
            library_id: The library.

        Returns:
            The manual tags, by the path they were set on.
        """
        return dict(self.manual_tags.get(library_id, {}))

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        """Replace one path's manual tags; none forgets the path.

        Args:
            library_id: The library.
            tags: The path and its new tags.
        """
        if library_id not in self.libraries:
            return
        by_path = self.manual_tags.setdefault(library_id, {})
        if tags.tags:
            by_path[tags.path] = tags.tags
        else:
            by_path.pop(tags.path, None)

    async def save(self, library: Library) -> None:
        """Store the library; versions it already has are kept as they are, new ones are added.

        Args:
            library: The library, with its versions.
        """
        stored = self.libraries.get(library.id)
        known = {v.ref: v for v in stored.versions} if stored else {}
        merged = known | {v.ref: v for v in library.versions if v.ref not in known}
        self.libraries[library.id] = replace(
            library,
            versions=frozenset(merged.values()),
            pinned_version=stored.pinned_version if stored else None,
            rules=stored.rules if stored else (),
        )

    async def set_settings(self, library_id: LibraryId, settings: LibrarySettings) -> None:
        """Replace the library's settings.

        Args:
            library_id: The library.
            settings: The new settings.
        """
        if (stored := self.libraries.get(library_id)) is not None:
            self.libraries[library_id] = replace(stored, settings=settings)

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        """Set the given fields and mark them as edited.

        Args:
            library_id: The library.
            title: The new title; ``None`` leaves it.
            description: The new description; ``None`` leaves it.
        """
        if (stored := self.libraries.get(library_id)) is None:
            return
        changes: dict[str, str | bool] = {}
        if title is not None:
            changes |= {"title": title, "title_edited": True}
        if description is not None:
            changes |= {"description": description, "description_edited": True}
        self.libraries[library_id] = replace(stored, **changes)

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        """Pin ``ref`` if the library has that version; ``None`` unpins.

        Args:
            library_id: The library.
            ref: The exact ref to pin; ``None`` unpins.

        Returns:
            Whether anything was written.
        """
        stored = self.libraries.get(library_id)
        if stored is None or (ref is not None and all(v.ref != ref for v in stored.versions)):
            return False
        self.libraries[library_id] = replace(stored, pinned_version=ref)
        return True

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        """Set the fields no user edited, and the rules.

        Args:
            library_id: The library.
            title: The title, unless a user edited it.
            description: The description, unless a user edited it.
            rules: The library's rules.
        """
        if (stored := self.libraries.get(library_id)) is None:
            return
        self.libraries[library_id] = replace(
            stored,
            title=stored.title if stored.title_edited else title,
            description=stored.description if stored.description_edited else description,
            rules=tuple(rules),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraryLogos:
    """Implements ``ports.driven.LibraryLogos`` over an ``InMemoryLibraryRepository``. For tests."""

    libraries: InMemoryLibraryRepository
    """The libraries; their ``logos`` hold what this store keeps."""

    async def get(self, library_id: LibraryId) -> LibraryLogo | None:
        """Return the library's logo.

        Args:
            library_id: The library.

        Returns:
            The logo, or ``None``.
        """
        return self.libraries.logos.get(library_id)

    async def put(self, library_id: LibraryId, logo: LibraryLogo) -> None:
        """Make ``logo`` the library's logo; nothing happens for an unknown library.

        Args:
            library_id: The library.
            logo: Its new logo.
        """
        if library_id in self.libraries.libraries:
            self.libraries.logos[library_id] = logo

    async def remove(self, library_id: LibraryId) -> None:
        """Forget the library's logo.

        Args:
            library_id: The library.
        """
        self.libraries.logos.pop(library_id, None)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryManifestRepository:
    """Implements ``ports.driven.ManifestRepository``. For tests; activation moves a version."""

    libraries: InMemoryLibraryRepository
    """The libraries the manifests belong to; activation moves their versions."""
    manifests: dict[ManifestId, Manifest] = field(default_factory=dict)
    """The manifests, by ID, with their entries, renames and images."""
    contents: dict[ContentKey, str] = field(default_factory=dict)
    """The article texts, by content key."""
    images: dict[str, StoredImage] = field(default_factory=dict)
    """The image bytes, by blob SHA."""

    async def add(
        self,
        manifest: Manifest,
        contents: Mapping[ContentKey, str],
        *,
        images: Mapping[str, StoredImage] | None = None,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest, its texts and image blobs; stored ones stay as they are.

        Args:
            manifest: The pending manifest, with its entries and renames.
            contents: The article texts, by content key.
            images: The image bytes, by blob SHA.
            version_must_exist: Refuse unless the version is already imported.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The library has no such version.
        """
        library = self.libraries.libraries.get(manifest.library)
        if library is None:
            raise LibraryNotFoundError(str(manifest.library))
        if version_must_exist and all(v.ref != manifest.ref for v in library.versions):
            raise VersionNotFoundError(str(manifest.library), str(manifest.ref))
        for key, text in contents.items():
            self.contents.setdefault(key, text)
        for sha, image in (images or {}).items():
            self.images.setdefault(sha, image)
        self.manifests[manifest.id] = manifest

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest without its entries, or ``None``.

        Args:
            manifest_id: The manifest.

        Returns:
            The manifest, or ``None``.
        """
        found = self.manifests.get(manifest_id)
        return _light(found) if found else None

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out.

        Args:
            manifest_ids: The manifests.

        Returns:
            The manifests found, by ID.
        """
        return {i: _light(self.manifests[i]) for i in manifest_ids if i in self.manifests}

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``.

        Args:
            library_id: The library.
            ref: The exact ref.

        Returns:
            The active manifest, or ``None``.
        """
        found = self._active(library_id, ref)
        return _light(found) if found else None

    async def get_active_many(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], Manifest]:
        """Return the active manifests (without entries) of these versions, by (library, ref).

        Args:
            versions: The versions, as ``(library, ref)``.

        Returns:
            The active manifests found, by version.
        """
        found = {v: await self.get_active(*v) for v in versions}
        return {v: m for v, m in found.items() if m is not None}

    async def list_entries(
        self,
        manifest_id: ManifestId,
        *,
        prefix: str,
        tags: TagSelection,
        after: str | None,
        limit: int,
    ) -> Sequence[ManifestEntry]:
        """Return up to ``limit`` entries inside ``prefix`` sorted by path, after the path.

        Args:
            manifest_id: The manifest.
            prefix: Only paths inside this directory; empty: every path.
            tags: Only entries that pass this filter.
            after: Only paths after this one; ``None`` from the start.
            limit: The most entries returned.

        Returns:
            The entries, sorted by path.
        """
        found = self.manifests.get(manifest_id)
        entries = found.entries if found else ()
        inside = (
            e
            for e in entries
            if (not prefix or e.path == prefix or e.path.startswith(f"{prefix}/"))
            and tags.keeps(e.all_tags)
        )
        later = sorted((e for e in inside if after is None or e.path > after), key=lambda e: e.path)
        return tuple(later[:limit])

    async def list_live(self, library_id: LibraryId) -> Sequence[Manifest]:
        """Return the library's pending and active manifests, without entries.

        Args:
            library_id: The library.

        Returns:
            The pending and active manifests.
        """
        live = {ManifestState.PENDING, ManifestState.ACTIVE}
        return tuple(
            _light(m)
            for m in self.manifests.values()
            if m.library == library_id and m.state in live
        )

    async def set_manual_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[ManualTag, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Set each entry's manual tags; report the entries that have or had some.

        Args:
            manifest_id: The manifest.
            tags: The manual tags of each path; a path left out gets none.

        Returns:
            The tags of each entry touched, by path.
        """
        found = self.manifests.get(manifest_id)
        if found is None:
            return {}
        entries = tuple(replace(e, manual_tags=tags.get(e.path, ())) for e in found.entries)
        touched = {
            new.path: new.all_tags
            for old, new in zip(found.entries, entries, strict=True)
            if old.manual_tags or new.manual_tags
        }
        self.manifests[manifest_id] = replace(found, entries=entries)
        return touched

    async def find_rename(
        self,
        manifest_id: ManifestId,
        path: str,
        direction: RenameDirection = RenameDirection.FORWARD,
    ) -> ManifestRename | None:
        """Return the rename of the old path, or (``BACK``) the first one into the new path.

        Args:
            manifest_id: The manifest.
            path: The old path (``FORWARD``) or the new one (``BACK``).
            direction: Which way to follow the path.

        Returns:
            The rename, or ``None``.
        """
        found = self.manifests.get(manifest_id)
        renames = sorted(found.renames, key=lambda r: r.old_path) if found else []
        back = direction is RenameDirection.BACK
        return next((r for r in renames if (r.new_path if back else r.old_path) == path), None)

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
        found = self.manifests.get(manifest_id)
        return tuple(sorted(found.renames, key=lambda r: r.old_path))[:limit] if found else ()

    async def replace_renames(
        self,
        manifest_id: ManifestId,
        renames: Sequence[ManifestRename],
        *,
        renamed_from: VersionRef | None,
    ) -> None:
        """Keep the renames into the manifest's entries, one per old path, as its whole map.

        Args:
            manifest_id: The manifest.
            renames: The new rename map.
            renamed_from: The version the map was detected against.
        """
        found = self.manifests.get(manifest_id)
        if found is None:
            return
        paths = {e.path for e in found.entries}
        kept: dict[str, ManifestRename] = {}
        for r in renames:
            if r.new_path in paths:
                kept.setdefault(r.old_path, r)
        self.manifests[manifest_id] = replace(
            found, renames=tuple(kept.values()), renamed_from=renamed_from
        )

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted.

        Args:
            manifest_id: The manifest.
            limit: The most paths returned.

        Returns:
            The paths, sorted.
        """
        found = self.manifests.get(manifest_id)
        return tuple(sorted(e.path for e in found.entries))[:limit] if found else ()

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name.

        Args:
            manifest_id: The manifest.
            limit: The most tags returned.

        Returns:
            The tags with their article counts.
        """
        found = self.manifests.get(manifest_id)
        counts = Counter(tag for e in found.entries for tag in e.all_tags) if found else Counter()
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))[:limit]

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
        manifest = self._active(library_id, ref)
        entry = next((e for e in manifest.entries if e.path == path), None) if manifest else None
        if manifest is None or entry is None:
            return None
        return StoredArticle(
            manifest_id=manifest.id,
            commit_sha=manifest.commit_sha,
            entry=entry,
            content=self.contents[entry.content_key],
        )

    async def get_image(
        self, library_id: LibraryId, ref: VersionRef, path: str, *, with_data: bool = True
    ) -> StoredImage | None:
        """Return the image at ``path`` of the version's active manifest, or ``None``.

        Args:
            library_id: The library.
            ref: The exact ref.
            path: The image's path.
            with_data: Whether to read the bytes.

        Returns:
            The image, or ``None``.
        """
        manifest = self._active(library_id, ref)
        held = next((i for i in manifest.images if i.path == path), None) if manifest else None
        found = self.images.get(held.blob_sha) if held else None
        return found if found is None or with_data else replace(found, data=b"")

    async def activate(self, manifest_id: ManifestId, *, at: datetime) -> Version:
        """Make a pending manifest the version's active one; all or nothing.

        Args:
            manifest_id: The manifest.
            at: When it is activated: the version's new ``imported_at``.

        Returns:
            The version as it is now.

        Raises:
            ManifestNotFoundError: No manifest has this ID.
            LibraryNotFoundError: The library is not in the catalog.
            ManifestNotPendingError: The manifest was superseded.
            ManifestOutdatedError: A newer manifest of the version is active.
        """
        manifest = self.manifests.get(manifest_id)
        if manifest is None:
            raise ManifestNotFoundError(manifest_id)
        library = self.libraries.libraries.get(manifest.library)
        if library is None:
            raise LibraryNotFoundError(str(manifest.library))
        if manifest.state is ManifestState.ACTIVE:
            return next(v for v in library.versions if v.ref == manifest.ref)
        if manifest.state is not ManifestState.PENDING:
            raise ManifestNotPendingError(manifest_id, manifest.state)
        current = self._active(manifest.library, manifest.ref)
        if current is not None and current.created_at > manifest.created_at:
            raise ManifestOutdatedError(manifest_id)
        earlier = next((v for v in library.versions if v.ref == manifest.ref), None)
        version = Version(
            ref=manifest.ref,
            kind=manifest.kind,
            commit_sha=manifest.commit_sha,
            imported_at=at,
            origin=manifest.origin if earlier is None else earlier.origin,
        )
        changed = {manifest_id: replace(manifest, state=ManifestState.ACTIVE)}
        if current is not None:
            changed[current.id] = replace(current, state=ManifestState.SUPERSEDED, superseded_at=at)
        moved = replace(
            library,
            versions=frozenset({v for v in library.versions if v.ref != manifest.ref} | {version}),
        )
        before = dict(self.manifests)
        try:
            self.manifests.update(changed)
            self.libraries.libraries[library.id] = moved
        except BaseException:
            self.manifests.clear()
            self.manifests.update(before)
            raise
        return version

    async def discard_pending(
        self,
        *,
        manifest_id: ManifestId | None,
        library_id: LibraryId | None,
        created_before: datetime | None,
    ) -> int:
        """Delete the pending manifests that match every given filter.

        Args:
            manifest_id: Only this manifest; ``None``: any.
            library_id: Only manifests of this library; ``None``: any.
            created_before: Only manifests stored before this time; ``None``: any.

        Returns:
            How many manifests were deleted.
        """
        doomed = [
            m.id
            for m in self.manifests.values()
            if m.state is ManifestState.PENDING
            and manifest_id in {None, m.id}
            and library_id in {None, m.library}
            and (created_before is None or m.created_at < created_before)
        ]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        return len(doomed)

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then texts no manifest uses.

        Args:
            superseded_before: The cutoff.

        Returns:
            How many manifests, texts and images were deleted.
        """
        old = [
            m.id
            for m in self.manifests.values()
            if m.state is ManifestState.SUPERSEDED
            and m.superseded_at is not None
            and m.superseded_at < superseded_before
        ]
        for old_id in old:
            del self.manifests[old_id]
        used = {e.content_key for m in self.manifests.values() for e in m.entries}
        unused = [key for key in self.contents if key not in used]
        for key in unused:
            del self.contents[key]
        shown = {i.blob_sha for m in self.manifests.values() for i in m.images}
        loose = [sha for sha in self.images if sha not in shown]
        for sha in loose:
            del self.images[sha]
        return GarbageCollected(manifests=len(old), contents=len(unused), images=len(loose))

    async def remove_version(self, library_id: LibraryId, ref: VersionRef) -> Sequence[ManifestId]:
        """Delete the version row and every manifest of the ref.

        Args:
            library_id: The library.
            ref: The exact ref.

        Returns:
            The deleted manifest IDs.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
            VersionNotFoundError: The library has no such version.
        """
        library = self.libraries.libraries.get(library_id)
        if library is None:
            raise LibraryNotFoundError(str(library_id))
        if all(v.ref != ref for v in library.versions):
            raise VersionNotFoundError(str(library_id), str(ref))
        doomed = [m.id for m in self.manifests.values() if (m.library, m.ref) == (library_id, ref)]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        kept = frozenset(v for v in library.versions if v.ref != ref)
        pinned = None if library.pinned_version == ref else library.pinned_version
        self.libraries.libraries[library_id] = replace(
            library, versions=kept, pinned_version=pinned
        )
        return doomed

    async def remove_library(self, library_id: LibraryId) -> Sequence[ManifestId]:
        """Delete the library and all its manifests.

        Args:
            library_id: The library.

        Returns:
            The deleted manifest IDs.

        Raises:
            LibraryNotFoundError: The library is not in the catalog.
        """
        if library_id not in self.libraries.libraries:
            raise LibraryNotFoundError(str(library_id))
        doomed = [m.id for m in self.manifests.values() if m.library == library_id]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        del self.libraries.libraries[library_id]
        self.libraries.manual_tags.pop(library_id, None)
        self.libraries.logos.pop(library_id, None)
        return doomed

    def _active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Find the version's active manifest, with its entries.

        Args:
            library_id: The library.
            ref: The exact ref.

        Returns:
            The active manifest, or ``None``.
        """
        return next(
            (
                m
                for m in self.manifests.values()
                if (m.library, m.ref, m.state) == (library_id, ref, ManifestState.ACTIVE)
            ),
            None,
        )


def _light(manifest: Manifest) -> Manifest:
    """Return the manifest as ``get`` does: without entries, renames and images.

    Args:
        manifest: The manifest as stored.

    Returns:
        The manifest without entries, renames, images or instruction files.
    """
    return replace(manifest, entries=(), renames=(), images=(), instructions=())


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryImportedTags:
    """Implements ``ports.driven.ImportedTagWriter`` on an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository
    """The manifests."""

    async def set_imported_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, ImportedTags]
    ) -> Mapping[str, tuple[str, ...]]:
        """Replace the imported tags and their sources of the named entries; report every one.

        Args:
            manifest_id: The manifest.
            tags: The new imported tags with their sources, by path.

        Returns:
            The tags of each given entry the manifest has, by path.
        """
        found = self.repository.manifests.get(manifest_id)
        if found is None:
            return {}
        entries = tuple(
            replace(e, tags=tags[e.path].tags, sources=tags[e.path].sources)
            if e.path in tags
            else e
            for e in found.entries
        )
        self.repository.manifests[manifest_id] = replace(found, entries=entries)
        return {e.path: e.all_tags for e in entries if e.path in tags}


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryArticleTitles:
    """Implements ``ports.driven.ArticleTitleFinder`` on an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository
    """The manifests."""

    async def titles(self, manifest_id: ManifestId, paths: Collection[str]) -> Mapping[str, str]:
        """Return the titles of these paths of the manifest.

        Args:
            manifest_id: The manifest.
            paths: The article paths.

        Returns:
            The title of each path found.
        """
        found = self.repository.manifests.get(manifest_id)
        wanted = set(paths)
        return {e.path: e.title for e in found.entries if e.path in wanted} if found else {}


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryStoredArticles:
    """Implements ``ports.driven.StoredArticleFinder`` on an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository
    """The manifests and their texts."""

    async def find_articles(
        self,
        library_id: LibraryId,
        ref: VersionRef | None,
        content_version: int,
        files: Collection[tuple[str, str]],
    ) -> Sequence[StoredArticle]:
        """Return the first entry of the library's manifests stored for each file.

        Args:
            library_id: The library.
            ref: The version being imported, looked in first; ``None``: none.
            content_version: The parser version the texts must be stored by.
            files: The files, as ``(path, blob SHA)``.

        Returns:
            One stored article per file found.
        """
        del ref  # an optimisation of the SQL lookup: any manifest gives the same article
        wanted, found = set(files), {}
        for manifest in self.repository.manifests.values():
            if manifest.library != library_id:
                continue
            for entry in manifest.entries:
                key = (entry.path, entry.blob_sha)
                if key in wanted and entry.content_version == content_version:
                    found.setdefault(
                        key,
                        StoredArticle(
                            manifest_id=manifest.id,
                            commit_sha=manifest.commit_sha,
                            entry=entry,
                            content=self.repository.contents[entry.content_key],
                        ),
                    )
        return list(found.values())


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryManifestCopier:
    """Implements ``ports.driven.ManifestCopier`` on an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository
    """The manifests and their texts."""

    async def copy_active(
        self,
        library_id: LibraryId,
        ref: VersionRef,
        new_id: ManifestId,
        *,
        at: datetime,
        content_version: int,
    ) -> tuple[Manifest, Sequence[StoredArticle]] | None:
        """Store a pending copy of the active manifest; see the port.

        Args:
            library_id: The library.
            ref: The exact ref.
            new_id: The copy's ID.
            at: The copy's creation time.
            content_version: The parser version the texts must be stored by.

        Returns:
            The copy and its articles, or ``None``.

        Raises:
            StoredContentOutdatedError: An entry was stored by another parser version.
        """
        found = next(
            (
                m
                for m in self.repository.manifests.values()
                if (m.library, m.ref, m.state) == (library_id, ref, ManifestState.ACTIVE)
            ),
            None,
        )
        if found is None:
            return None
        if any(e.content_version != content_version for e in found.entries):
            raise StoredContentOutdatedError(str(library_id), str(ref))
        copy = replace(
            found, id=new_id, created_at=at, state=ManifestState.PENDING, superseded_at=None
        )
        self.repository.manifests[new_id] = copy
        return _light(copy), tuple(
            StoredArticle(
                manifest_id=new_id,
                commit_sha=copy.commit_sha,
                entry=e,
                content=self.repository.contents[e.content_key],
            )
            for e in copy.entries
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryInstructionFiles:
    """Implements ``ports.driven.InstructionFileReader`` over an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository
    """Holds the manifests and the files kept with them."""

    async def list_instructions(self, manifest_id: ManifestId) -> Sequence[ManifestInstruction]:
        """Return the files kept with the manifest.

        Args:
            manifest_id: The manifest (any state).

        Returns:
            Its files, sorted by path; none for an unknown manifest.
        """
        found = self.repository.manifests.get(manifest_id)
        return tuple(sorted(found.instructions, key=lambda i: i.path)) if found else ()
