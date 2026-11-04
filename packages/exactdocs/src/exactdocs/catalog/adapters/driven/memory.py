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
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestState,
    StoredArticle,
    TagSelection,
    Version,
    VersionRef,
)


@dataclass(slots=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests."""

    libraries: MutableMapping[LibraryId, Library] = field(default_factory=dict)

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
        self.libraries[library.id] = library

    async def delete(self, library_id: LibraryId) -> None:
        """Remove the library, if present."""
        self.libraries.pop(library_id, None)

    async def save(self, library: Library) -> None:
        """Store the library; versions it already has are kept as they are, new ones are added."""
        stored = self.libraries.get(library.id)
        known = {v.ref: v for v in stored.versions} if stored else {}
        merged = known | {v.ref: v for v in library.versions if v.ref not in known}
        self.libraries[library.id] = replace(library, versions=frozenset(merged.values()))

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

    async def follow_readme(self, library_id: LibraryId, *, title: str, description: str) -> None:
        """Set the fields no user edited."""
        if (stored := self.libraries.get(library_id)) is None:
            return
        self.libraries[library_id] = replace(
            stored,
            title=stored.title if stored.title_edited else title,
            description=stored.description if stored.description_edited else description,
        )


@dataclass(slots=True)
class InMemoryManifestRepository:
    """Implements ``ports.driven.ManifestRepository``. For tests; activation moves a version."""

    libraries: InMemoryLibraryRepository
    manifests: dict[ManifestId, Manifest] = field(default_factory=dict)
    contents: dict[ContentKey, str] = field(default_factory=dict)

    async def add(
        self,
        manifest: Manifest,
        contents: Mapping[ContentKey, str],
        *,
        version_must_exist: bool = False,
    ) -> None:
        """Store a pending manifest and the texts it needs; stored texts stay as they are."""
        library = self.libraries.libraries.get(manifest.library)
        if library is None:
            raise LibraryNotFoundError(str(manifest.library))
        if version_must_exist and all(v.ref != manifest.ref for v in library.versions):
            raise VersionNotFoundError(str(manifest.library), str(manifest.ref))
        for key, text in contents.items():
            self.contents.setdefault(key, text)
        self.manifests[manifest.id] = manifest

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest without its entries, or ``None``."""
        found = self.manifests.get(manifest_id)
        return replace(found, entries=()) if found else None

    async def get_many(self, manifest_ids: Collection[ManifestId]) -> Mapping[ManifestId, Manifest]:
        """Return the manifests (without entries) that exist, by ID; unknown IDs are left out."""
        return {
            i: replace(self.manifests[i], entries=()) for i in manifest_ids if i in self.manifests
        }

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the version's active manifest without its entries, or ``None``."""
        found = self._active(library_id, ref)
        return replace(found, entries=()) if found else None

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
            and tags.keeps(e.tags)
        )
        later = sorted((e for e in inside if after is None or e.path > after), key=lambda e: e.path)
        return tuple(later[:limit])

    async def list_paths(self, manifest_id: ManifestId, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` article paths of the manifest, sorted."""
        found = self.manifests.get(manifest_id)
        return tuple(sorted(e.path for e in found.entries))[:limit] if found else ()

    async def count_tags(self, manifest_id: ManifestId, *, limit: int) -> Sequence[tuple[str, int]]:
        """Return up to ``limit`` ``(tag, article count)`` pairs, most used first, then by name."""
        found = self.manifests.get(manifest_id)
        counts = Counter(tag for e in found.entries for tag in set(e.tags)) if found else Counter()
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
        return GarbageCollected(manifests=len(old), contents=len(unused))

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
        self.libraries.libraries[library_id] = replace(library, versions=kept)
        return doomed

    async def remove_library(self, library_id: LibraryId) -> Sequence[ManifestId]:
        """Delete the library and all its manifests."""
        if library_id not in self.libraries.libraries:
            raise LibraryNotFoundError(str(library_id))
        doomed = [m.id for m in self.manifests.values() if m.library == library_id]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        del self.libraries.libraries[library_id]
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
