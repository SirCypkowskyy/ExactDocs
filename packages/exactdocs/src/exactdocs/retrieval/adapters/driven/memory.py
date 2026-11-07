import sys
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from exactdocs.retrieval.constants import MEMORY_FORMAT
from exactdocs.retrieval.errors import ChunkSetMismatchError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    IndexedManifest,
    LibraryAi,
    ManifestChunk,
    ManifestHit,
    ModelRole,
    ProviderProfile,
    RebuiltIndex,
    Removed,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    SearchIndexState,
    SectionRef,
    StoredChunk,
    TagFilter,
    VersionCounts,
    highlights,
    identifier_tokens,
    search_terms,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryChunkRepository:
    """Implements ``ports.driven.ChunkRepository`` with dictionaries."""

    chunk_sets: dict[ChunkSetKey, ChunkSet] = field(default_factory=dict)
    manifests: dict[str, IndexedManifest] = field(default_factory=dict)
    rows: dict[str, dict[ChunkId, ManifestChunk]] = field(default_factory=dict)

    async def add(
        self,
        manifest: IndexedManifest,
        chunk_sets: Mapping[ChunkSetKey, ChunkSet],
        rows: Sequence[ManifestChunk],
    ) -> int | None:
        """Store rows and the new chunk sets; ``None`` when the manifest is already indexed."""
        if manifest.manifest_id in self.manifests:
            return None
        for key, value in chunk_sets.items():
            if key in self.chunk_sets and self.chunk_sets[key].digest != value.digest:
                raise ChunkSetMismatchError(*key)
        new = {key: value for key, value in chunk_sets.items() if key not in self.chunk_sets}
        self.chunk_sets.update(new)
        self.manifests[manifest.manifest_id] = manifest
        self.rows[manifest.manifest_id] = {row.chunk_id: row for row in rows}
        return len(new)

    async def get_sets(self, keys: Sequence[ChunkSetKey]) -> Mapping[ChunkSetKey, ChunkSet]:
        """Return the stored chunk sets among ``keys``."""
        return {key: self.chunk_sets[key] for key in keys if key in self.chunk_sets}

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        row = self.rows.get(manifest_id, {}).get(chunk_id)
        if row is None:
            return None
        chunk = self.chunk_sets[row.chunk_set].chunks[row.position]
        version_id = self.manifests[manifest_id].version_id
        return StoredChunk(manifest_id=manifest_id, version_id=version_id, row=row, chunk=chunk)

    async def get_many(
        self, manifest_id: str, chunk_ids: Sequence[ChunkId]
    ) -> Mapping[ChunkId, StoredChunk]:
        """Return the chunks of the manifest that exist, by ID; missing IDs are left out."""
        found = {i: await self.get(manifest_id, i) for i in chunk_ids}
        return {i: c for i, c in found.items() if c is not None}

    async def get_across(
        self, wanted: Mapping[str, Collection[ChunkId]]
    ) -> Mapping[tuple[str, ChunkId], StoredChunk]:
        """Return the chunks that exist, by (manifest ID, chunk ID)."""
        found = {
            (m, i): await self.get(m, i) for m, ids in wanted.items() for i in dict.fromkeys(ids)
        }
        return {key: c for key, c in found.items() if c is not None}

    async def article(self, manifest_id: str, article_path: str) -> Sequence[SectionRef]:
        """Return the sections of one article of the manifest in order, without their text."""
        rows = sorted(
            (r for r in self.rows.get(manifest_id, {}).values() if r.article_path == article_path),
            key=lambda r: r.position,
        )
        found: list[SectionRef] = []
        for row in rows:
            chunk = self.chunk_sets[row.chunk_set].chunks[row.position]
            found.append(
                SectionRef(
                    chunk_id=row.chunk_id,
                    position=row.position,
                    heading_path=chunk.heading_path,
                    occurrence_index=chunk.occurrence_index,
                    content_hash=chunk.content_hash,
                    anchor=chunk.anchor,
                    headings=chunk.headings,
                )
            )
        return found

    async def counts(self, manifest_id: str) -> VersionCounts:
        """Count the manifest's articles and chunks."""
        rows = self.rows.get(manifest_id, {}).values()
        return VersionCounts(articles=len({r.article_path for r in rows}), chunks=len(rows))

    async def manifests_with_chunk(self, chunk_id: ChunkId) -> Sequence[IndexedManifest]:
        """Return every indexed manifest that has a row for this chunk ID (any status)."""
        return [self.manifests[i] for i, rows in self.rows.items() if chunk_id in rows]

    async def find_manifests(
        self, *, manifest_id: str | None, library: str | None, indexed_before: datetime | None
    ) -> Sequence[IndexedManifest]:
        """Return the indexed manifests that match every given filter."""
        return [
            m
            for m in self.manifests.values()
            if manifest_id in {None, m.manifest_id}
            and library in {None, m.library}
            and (indexed_before is None or m.indexed_at < indexed_before)
        ]

    async def remove(self, manifest_ids: Collection[str]) -> Removed:
        """Delete these manifests' rows, then every chunk set no row points at."""
        # O(all rows) per call: a test double, not a place to optimise.
        gone = [i for i in manifest_ids if self.manifests.pop(i, None) is not None]
        for manifest_id in gone:
            del self.rows[manifest_id]
        used = {row.chunk_set for rows in self.rows.values() for row in rows.values()}
        unused = [key for key in self.chunk_sets if key not in used]
        for key in unused:
            del self.chunk_sets[key]
        return Removed(manifests=len(gone), chunk_sets=len(unused))

    async def set_tags(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> int:
        """Replace the tags of the named articles' rows of the manifest."""
        rows = self.rows.get(manifest_id, {})
        changed = {
            chunk_id: replace(row, tags=tags[row.article_path])
            for chunk_id, row in rows.items()
            if row.article_path in tags and row.tags != tags[row.article_path]
        }
        rows.update(changed)
        return len(changed)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- index format
class InMemorySearchIndex:
    """Reference ``ports.driven.SearchIndex``: a term-count score, not BM25.

    It reads the chunk rows of the repository it is built on, so it forgets a chunk set when the
    repository does, as the SQLite index does. Headings weigh ten times the body.

    It scores the whole heading path alike; it does not model the SQLite index's own-heading versus
    ancestors weighting. The ranking suite (`docker`) is what every engine must satisfy.
    """

    chunks: InMemoryChunkRepository
    indexed: set[ChunkSetKey] = field(default_factory=set)
    stored_format: int = MEMORY_FORMAT
    """Set it lower to stand for an index from an older build."""

    async def index(self, chunk_set: ChunkSet) -> None:
        """Remember the set; the text itself is read from the repository."""
        self.indexed.add(chunk_set.key)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return this manifest's best matches, ties broken by chunk ID."""
        terms = search_terms(query)
        hits: list[SearchHit] = []
        for row in self.chunks.rows.get(manifest_id, {}).values():
            if row.chunk_set not in self.indexed or row.chunk_set not in self.chunks.chunk_sets:
                continue
            if not tag_filter.keeps(row.tags):
                continue
            chunk = self.chunks.chunk_sets[row.chunk_set].chunks[row.position]
            heading = Counter(identifier_tokens(" ".join(chunk.heading_path)).split())
            body = Counter(identifier_tokens(chunk.content).split())
            score = sum(10 * heading[t] + body[t] for t in terms)
            if score:
                hits.append(_hit(row.chunk_id, float(score), chunk.content, terms))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:limit]

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return the best matches of any of the manifests (scores are plain term counts)."""
        found = [
            ManifestHit(manifest_id=m, hit=h)
            for m in dict.fromkeys(manifest_ids)
            for h in await self.search(m, query, tag_filter, limit)
        ]
        found.sort(key=lambda f: (-f.hit.score, f.hit.chunk_id, f.manifest_id))
        return found[:limit]

    async def state(self) -> SearchIndexState:
        """Return the format the index was "built" in and the current one."""
        return SearchIndexState(stored_format=self.stored_format, current_format=MEMORY_FORMAT)

    async def rebuild(self) -> RebuiltIndex:
        """Index every stored chunk set again (one step: nothing can search in between)."""
        self.indexed.clear()
        self.indexed.update(self.chunks.chunk_sets)
        self.stored_format = MEMORY_FORMAT
        entries = sum(len(s.chunks) for s in self.chunks.chunk_sets.values())
        return RebuiltIndex(format=MEMORY_FORMAT, entries=entries)

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Return how many chunks of each manifest match (reference only: it scores every chunk)."""
        counts = {
            m: len(await self.search(m, query, tag_filter, sys.maxsize))
            for m in dict.fromkeys(manifest_ids)
        }
        return {m: n for m, n in counts.items() if n}


def _hit(chunk_id: ChunkId, score: float, content: str, terms: list[str]) -> SearchHit:
    marks = highlights(content, terms)
    start = max(0, marks[0][0] - 40) if marks else 0
    snippet = content[start : start + 160]
    return SearchHit(
        chunk_id=chunk_id, score=score, snippet=snippet, highlights=highlights(snippet, terms)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryDefaultVersions:
    """Implements ``ports.driven.DefaultVersions`` with a fixed list."""

    versions: Sequence[SearchableVersion] = ()

    async def all(self) -> Sequence[SearchableVersion]:
        """Return the versions sorted by library."""
        return sorted(self.versions, key=lambda v: v.library)


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraries:
    """Implements ``ports.driven.Libraries`` with a fixed list."""

    libraries: Sequence[CatalogLibrary] = ()

    async def all(self) -> Sequence[CatalogLibrary]:
        """Return the libraries that have a default version."""
        return [lib for lib in self.libraries if lib.default_version is not None]

    async def canonical_id(self, library: str) -> str | None:
        """Find the listed library that matches in any letter case.

        Args:
            library: The ID asked for.

        Returns:
            Its ID as listed, or ``None``.
        """
        wanted = library.casefold()
        return next((lib.id for lib in self.libraries if lib.id.casefold() == wanted), None)


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticModelRoles:
    """Implements ``ports.driven.ModelRoles`` with a fixed set (tests)."""

    roles: frozenset[ModelRole] = frozenset()
    """The roles that count as configured."""

    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        """Say which roles are set; the same for every library that has AI on.

        Args:
            library: The library searched.
            ai: The library's overrides, when they are about to change.

        Returns:
            The fixed set; empty when ``ai`` turns AI off.
        """
        del library
        return self.roles if ai is None or ai.enabled else frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraryModes:
    """Implements ``ports.driven.LibraryModes`` in dicts keyed by the case-folded library ID."""

    modes: dict[str, RetrievalMode] = field(default_factory=dict)
    """Mode by case-folded library ID."""
    overrides: dict[str, LibraryAi] = field(default_factory=dict)
    """AI overrides by case-folded library ID."""

    async def mode_of(self, library: str) -> RetrievalMode | None:
        """Read the library's mode.

        Args:
            library: The library ID, any letter case.

        Returns:
            Its mode, or ``None`` when it has none.
        """
        return self.modes.get(library.casefold())

    async def ai_of(self, library: str) -> LibraryAi:
        """Read the library's AI overrides.

        Args:
            library: The library ID, any letter case.

        Returns:
            Its overrides, or the defaults.
        """
        return self.overrides.get(library.casefold(), LibraryAi())

    async def forget(self, library: str) -> None:
        """Drop the library's settings.

        Args:
            library: The library ID, any letter case.
        """
        self.modes.pop(library.casefold(), None)
        self.overrides.pop(library.casefold(), None)

    async def save(self, library: str, mode: RetrievalMode | None, ai: LibraryAi) -> None:
        """Replace the library's settings.

        Args:
            library: The library ID, any letter case.
            mode: The mode; ``None`` removes it.
            ai: The AI overrides; the defaults remove them.
        """
        key = library.casefold()
        if mode is None:
            self.modes.pop(key, None)
        else:
            self.modes[key] = mode
        if ai.is_default:
            self.overrides.pop(key, None)
        else:
            self.overrides[key] = ai


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryProviderProfiles:
    """Implements ``ports.driven.ProviderProfiles`` in a dict keyed by name."""

    profiles: dict[str, ProviderProfile] = field(default_factory=dict)
    """Profile by name."""

    async def all(self) -> Sequence[ProviderProfile]:
        """List the profiles.

        Returns:
            Them, by name.
        """
        return [self.profiles[name] for name in sorted(self.profiles)]

    async def get(self, name: str) -> ProviderProfile | None:
        """Read one profile.

        Args:
            name: Its name.

        Returns:
            The profile, or ``None``.
        """
        return self.profiles.get(name)

    async def save(self, profile: ProviderProfile) -> None:
        """Create or replace a profile.

        Args:
            profile: The profile.
        """
        self.profiles[profile.name] = profile

    async def delete(self, name: str) -> bool:
        """Delete a profile.

        Args:
            name: Its name.

        Returns:
            Whether there was one.
        """
        return self.profiles.pop(name, None) is not None
