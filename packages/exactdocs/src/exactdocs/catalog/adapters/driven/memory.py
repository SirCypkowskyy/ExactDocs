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
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ContentKey,
    GarbageCollected,
    Library,
    LibraryId,
    LibrarySettings,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestRename,
    ManifestState,
    ManualTag,
    ManualTags,
    StoredArticle,
    StoredImage,
    TagSelection,
    Version,
    VersionRef,
)


@dataclass(slots=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests."""

    libraries: MutableMapping[LibraryId, Library] = field(default_factory=dict)
    manual_tags: dict[LibraryId, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    @classmethod
    def of(cls, libraries: Iterable[Library]) -> Self:
        """Create a repository pre-filled with ``libraries``."""
        return cls({lib.id: lib for lib in libraries})

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        return tuple(self.libraries.values())

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``."""
        return self.libraries.get(library_id)

    async def add(self, library: Library) -> None:
        """Store a new library; raises ``LibraryAlreadyExistsError`` if the ID is taken."""
        if library.id in self.libraries:
            raise LibraryAlreadyExistsError(library.id.value)
        # pinned and given rules only later
        self.libraries[library.id] = replace(library, pinned_version=None, rules=())

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library, if present."""
        self.libraries.pop(library_id, None)
        self.manual_tags.pop(library_id, None)

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        """Return the library's manual tags by path."""
        return dict(self.manual_tags.get(library_id, {}))

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        """Replace one path's manual tags; none forgets the path."""
        if library_id not in self.libraries:
            return
        by_path = self.manual_tags.setdefault(library_id, {})
        if tags.tags:
            by_path[tags.path] = tags.tags
        else:
            by_path.pop(tags.path, None)

    async def save(self, library: Library) -> None:
        """Store the library; versions it already has are kept as they are, new ones are added."""
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
        """Replace the library's settings."""
        if (stored := self.libraries.get(library_id)) is not None:
            self.libraries[library_id] = replace(stored, settings=settings)

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        """Set the given fields and mark them as edited."""
        if (stored := self.libraries.get(library_id)) is None:
            return
        changes: dict[str, str | bool] = {}
        if title is not None:
            changes |= {"title": title, "title_edited": True}
        if description is not None:
            changes |= {"description": description, "description_edited": True}
        self.libraries[library_id] = replace(stored, **changes)

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        """Pin ``ref`` if the library has that version; ``None`` unpins."""
        stored = self.libraries.get(library_id)
        if stored is None or (ref is not None and all(v.ref != ref for v in stored.versions)):
            return False
        self.libraries[library_id] = replace(stored, pinned_version=ref)
        return True

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        """Set the fields no user edited, and the rules."""
        if (stored := self.libraries.get(library_id)) is None:
            return
        self.libraries[library_id] = replace(
            stored,
            title=stored.title if stored.title_edited else title,
            description=stored.description if stored.description_edited else description,
            rules=tuple(rules),
        )


@dataclass(slots=True)
class InMemoryManifestRepository:
    """Implements ``ports.driven.ManifestRepository``. For tests; activation moves a version."""

    libraries: InMemoryLibraryRepository
    manifests: dict[ManifestId, Manifest] = field(default_factory=dict)
    contents: dict[ContentKey, str] = field(default_factory=dict)
    images: dict[str, StoredImage] = field(default_factory=dict)

    async def add(
        self,
        manifest: Manifest,
        contents: Mapping[ContentKey, str],
        *,
        images: Mapping[str, StoredImage] | None = None,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest, its texts and image blobs; stored ones stay as they are."""
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
        """Return the manifest without its entries, or ``None``."""
        found = self.manifests.get(manifest_id)
        return _light(found) if found else None

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out."""
        return {i: _light(self.manifests[i]) for i in manifest_ids if i in self.manifests}

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``."""
        found = self._active(library_id, ref)
        return _light(found) if found else None

    async def get_active_many(
        self, versions: Sequence[tuple[LibraryId, VersionRef]]
    ) -> Mapping[tuple[LibraryId, VersionRef], Manifest]:
        """Return the active manifests (without entries) of these versions, by (library, ref)."""
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
        """Return up to ``limit`` entries inside ``prefix`` sorted by path, after the path."""
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
        """Return the library's pending and active manifests, without entries."""
        live = {ManifestState.PENDING, ManifestState.ACTIVE}
        return tuple(
            _light(m)
            for m in self.manifests.values()
            if m.library == library_id and m.state in live
        )

    async def set_manual_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[ManualTag, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Set each entry's manual tags; report the entries that have or had some."""
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

    async def find_rename(self, manifest_id: ManifestId, old_path: str) -> ManifestRename | None:
        """Return the rename of ``old_path`` stored with the manifest, or ``None``."""
        found = self.manifests.get(manifest_id)
        return next((r for r in found.renames if r.old_path == old_path), None) if found else None

    async def find_rename_to(self, manifest_id: ManifestId, new_path: str) -> ManifestRename | None:
        """Return the rename that made ``new_path`` (the first by old path), or ``None``."""
        found = self.manifests.get(manifest_id)
        renames = sorted(found.renames, key=lambda r: r.old_path) if found else []
        return next((r for r in renames if r.new_path == new_path), None)

    async def list_renames(
        self, manifest_id: ManifestId, *, limit: int
    ) -> Sequence[ManifestRename]:
        """Return up to ``limit`` renames of the manifest, sorted by old path."""
        found = self.manifests.get(manifest_id)
        return tuple(sorted(found.renames, key=lambda r: r.old_path))[:limit] if found else ()

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted."""
        found = self.manifests.get(manifest_id)
        return tuple(sorted(e.path for e in found.entries))[:limit] if found else ()

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name."""
        found = self.manifests.get(manifest_id)
        counts = Counter(tag for e in found.entries for tag in e.all_tags) if found else Counter()
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))[:limit]

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``."""
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
        """Return the image at ``path`` of the version's active manifest, or ``None``."""
        manifest = self._active(library_id, ref)
        held = next((i for i in manifest.images if i.path == path), None) if manifest else None
        found = self.images.get(held.blob_sha) if held else None
        return found if found is None or with_data else replace(found, data=b"")

    async def activate(self, manifest_id: ManifestId, *, at: datetime) -> Version:
        """Make a pending manifest the version's active one; all or nothing."""
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
        version = Version(
            ref=manifest.ref, kind=manifest.kind, commit_sha=manifest.commit_sha, imported_at=at
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
        """Delete the pending manifests that match every given filter."""
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
        """Delete manifests superseded before the cutoff, then texts no manifest uses."""
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
        """Delete the version row and every manifest of the ref."""
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
        """Delete the library and all its manifests."""
        if library_id not in self.libraries.libraries:
            raise LibraryNotFoundError(str(library_id))
        doomed = [m.id for m in self.manifests.values() if m.library == library_id]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        del self.libraries.libraries[library_id]
        self.libraries.manual_tags.pop(library_id, None)
        return doomed

    def _active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        return next(
            (
                m
                for m in self.manifests.values()
                if (m.library, m.ref, m.state) == (library_id, ref, ManifestState.ACTIVE)
            ),
            None,
        )


def _light(manifest: Manifest) -> Manifest:
    """Return the manifest as ``get`` does: without entries, renames and images."""
    return replace(manifest, entries=(), renames=(), images=())


@dataclass(frozen=True, slots=True)
class InMemoryImportedTags:
    """Implements ``ports.driven.ImportedTagWriter`` on an ``InMemoryManifestRepository``."""

    repository: InMemoryManifestRepository

    async def set_imported_tags(
        self, manifest_id: ManifestId, tags: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        """Replace the imported tags of the named entries; report every one of them."""
        found = self.repository.manifests.get(manifest_id)
        if found is None:
            return {}
        entries = tuple(replace(e, tags=tags.get(e.path, e.tags)) for e in found.entries)
        self.repository.manifests[manifest_id] = replace(found, entries=entries)
        return {e.path: e.all_tags for e in entries if e.path in tags}
