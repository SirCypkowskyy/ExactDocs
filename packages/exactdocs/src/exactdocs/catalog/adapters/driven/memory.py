from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Self

from exactdocs.catalog.errors import (
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
)
from exactdocs.catalog.models import (
    GarbageCollected,
    Library,
    LibraryId,
    Manifest,
    ManifestId,
    ManifestState,
    StoredArticle,
    Version,
    VersionRef,
)


@dataclass(slots=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests."""

    libraries: dict[LibraryId, Library] = field(default_factory=dict)

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

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same ID."""
        self.libraries[library.id] = library


@dataclass(slots=True)
class InMemoryManifestRepository:
    """Implements ``ports.driven.ManifestRepository``. For tests; activation moves a version."""

    libraries: InMemoryLibraryRepository
    manifests: dict[ManifestId, Manifest] = field(default_factory=dict)
    contents: dict[str, str] = field(default_factory=dict)

    async def add(self, manifest: Manifest, contents: Mapping[str, str]) -> None:
        """Store a pending manifest and the contents it needs; stored contents stay as they are."""
        if manifest.library not in self.libraries.libraries:
            raise LibraryNotFoundError(str(manifest.library))
        for blob_sha, text in contents.items():
            self.contents.setdefault(blob_sha, text)
        self.manifests[manifest.id] = manifest

    async def get(self, manifest_id: ManifestId) -> Manifest | None:
        """Return the manifest, or ``None``."""
        return self.manifests.get(manifest_id)

    async def get_active(self, library_id: LibraryId, ref: VersionRef) -> Manifest | None:
        """Return the active manifest of this version, or ``None``."""
        return next(
            (
                m
                for m in self.manifests.values()
                if (m.library, m.ref, m.state) == (library_id, ref, ManifestState.ACTIVE)
            ),
            None,
        )

    async def get_article(
        self, library_id: LibraryId, ref: VersionRef, path: str
    ) -> StoredArticle | None:
        """Return one article of the version's active manifest, or ``None``."""
        manifest = await self.get_active(library_id, ref)
        entry = next((e for e in manifest.entries if e.path == path), None) if manifest else None
        if manifest is None or entry is None:
            return None
        return StoredArticle(
            manifest_id=manifest.id,
            commit_sha=manifest.commit_sha,
            entry=entry,
            content=self.contents[entry.blob_sha],
        )

    async def activate(self, manifest_id: ManifestId, *, at: datetime) -> Version:
        """Make a pending manifest the version's active one; all or nothing."""
        manifest = self.manifests.get(manifest_id)
        if manifest is None:
            raise ManifestNotFoundError(manifest_id)
        if manifest.state is not ManifestState.PENDING:
            raise ManifestNotPendingError(manifest_id, manifest.state)
        library = self.libraries.libraries.get(manifest.library)
        if library is None:
            raise LibraryNotFoundError(str(manifest.library))
        version = Version(
            ref=manifest.ref, kind=manifest.kind, commit_sha=manifest.commit_sha, imported_at=at
        )
        # Everything is computed first; the three assignments below cannot fail.
        changed = {
            m.id: replace(m, state=ManifestState.SUPERSEDED, superseded_at=at)
            for m in self.manifests.values()
            if (m.library, m.ref, m.state) == (manifest.library, manifest.ref, ManifestState.ACTIVE)
        }
        changed[manifest_id] = replace(manifest, state=ManifestState.ACTIVE)
        moved = replace(
            library,
            versions=frozenset({v for v in library.versions if v.ref != manifest.ref} | {version}),
        )
        self.manifests.update(changed)
        self.libraries.libraries[library.id] = moved
        return version

    async def discard_pending(self, manifest_id: ManifestId | None) -> int:
        """Delete one pending manifest, or every pending one for ``None``."""
        doomed = [
            m.id
            for m in self.manifests.values()
            if m.state is ManifestState.PENDING and manifest_id in {None, m.id}
        ]
        for doomed_id in doomed:
            del self.manifests[doomed_id]
        return len(doomed)

    async def collect_garbage(self, *, superseded_before: datetime) -> GarbageCollected:
        """Delete manifests superseded before the cutoff, then contents no manifest uses."""
        old = [
            m.id
            for m in self.manifests.values()
            if m.state is ManifestState.SUPERSEDED
            and m.superseded_at is not None
            and m.superseded_at < superseded_before
        ]
        for old_id in old:
            del self.manifests[old_id]
        used = {e.blob_sha for m in self.manifests.values() for e in m.entries}
        unused = [sha for sha in self.contents if sha not in used]
        for sha in unused:
            del self.contents[sha]
        return GarbageCollected(manifests=len(old), contents=len(unused))
