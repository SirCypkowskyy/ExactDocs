import hashlib
import math
import struct
import sys
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import batched

from exactdocs.retrieval.constants import CHARS_PER_TOKEN, MEMORY_FORMAT
from exactdocs.retrieval.errors import (
    ChunkSetMismatchError,
    RetiredEmbeddingSpaceError,
    UnknownEmbeddingSpaceError,
    VectorStoreUnavailableError,
)
from exactdocs.retrieval.models import (
    CatalogLibrary,
    Chunk,
    ChunkId,
    ChunkKey,
    ChunkSet,
    ChunkSetKey,
    EmbeddedTexts,
    EmbeddingSource,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    LibraryAi,
    ManifestChunk,
    ManifestHit,
    ModelRole,
    PendingArticle,
    PendingChunks,
    ProviderProfile,
    RebuiltIndex,
    Removed,
    RetrievalMode,
    SearchableVersion,
    SearchEngine,
    SearchHit,
    SearchIndexState,
    SectionRef,
    SpaceState,
    SpendEntry,
    SpendWindow,
    StoredChunk,
    TagFilter,
    VectorCoverage,
    VectorHit,
    VersionCounts,
    checked_vector,
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

    async def embedding_sources(
        self, manifest_id: str, keys: Collection[ChunkKey]
    ) -> Mapping[ChunkKey, EmbeddingSource]:
        """Return what each of these chunks of the manifest is embedded from (first path wins).

        Args:
            manifest_id: The manifest.
            keys: The stored chunks.

        Returns:
            The sources found.
        """
        wanted = set(keys)
        found: dict[ChunkKey, EmbeddingSource] = {}
        for row in sorted(self.rows.get(manifest_id, {}).values(), key=lambda r: r.article_path):
            key: ChunkKey = (row.chunk_set[0], row.chunk_set[1], row.position)
            if key in wanted and key not in found:
                chunk = self.chunk_sets[row.chunk_set].chunks[row.position]
                found[key] = EmbeddingSource(
                    article_path=row.article_path,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                )
        return found


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
        return SearchIndexState(
            stored_format=self.stored_format,
            current_format=MEMORY_FORMAT,
            engine=SearchEngine.MEMORY,
        )

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


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryVectorIndex:
    """Reference ``ports.driven.VectorIndex``: exact cosine distance in pure Python.

    It reads the chunk rows of the repository it is built on, and each vector remembers the chunk
    set it was stored for, so a vector is forgotten when the repository drops that set (even if
    the same blob is stored again later), as SQLite's foreign key does. Vectors are rounded to
    32-bit floats, as the stores keep them.
    """

    chunks: InMemoryChunkRepository
    """The chunks the vectors belong to."""
    can_search: bool = True
    """Set it False to stand for a store that cannot be loaded."""
    spaces_by_id: dict[EmbeddingSpaceId, EmbeddingSpace] = field(default_factory=dict)
    """Every space, retired ones too."""
    vectors: dict[EmbeddingSpaceId, dict[ChunkKey, tuple[ChunkSet, tuple[float, ...]]]] = field(
        default_factory=dict
    )
    """The vectors of each space that is not retired, with the chunk set each was stored for."""

    def requirement(self) -> str:
        """Name what the store needs: nothing outside this process.

        Returns:
            ``memory``.
        """
        return "memory"

    async def available(self) -> bool:
        """Say whether searches can run.

        Returns:
            ``can_search``.
        """
        return self.can_search

    async def spaces(self) -> Sequence[EmbeddingSpace]:
        """List every space, oldest first.

        Returns:
            The spaces.
        """
        return [self.spaces_by_id[i] for i in sorted(self.spaces_by_id)]

    async def create_space(self, spec: EmbeddingSpec, at: datetime) -> EmbeddingSpace:
        """Create an empty ``building`` space with the next ID.

        Args:
            spec: The model and format of its vectors.
            at: When it is created.

        Returns:
            The new space.
        """
        space = EmbeddingSpace(
            id=EmbeddingSpaceId(max(self.spaces_by_id, default=0) + 1),
            spec=spec,
            state=SpaceState.BUILDING,
            created_at=at,
        )
        self.spaces_by_id[space.id] = space
        self.vectors[space.id] = {}
        return space

    async def activate_space(self, space_id: EmbeddingSpaceId, at: datetime) -> EmbeddingSpace:
        """Mark the space active.

        Args:
            space_id: The space.
            at: When; the first activation's time is kept.

        Returns:
            The space now.
        """
        space = self._live(space_id)
        active = replace(space, state=SpaceState.ACTIVE, activated_at=space.activated_at or at)
        self.spaces_by_id[space_id] = active
        return active

    async def retire_space(self, space_id: EmbeddingSpaceId) -> None:
        """Mark the space retired and drop its vectors.

        Args:
            space_id: The space.
        """
        space = self._space(space_id)
        self.spaces_by_id[space_id] = replace(space, state=SpaceState.RETIRED)
        self.vectors.pop(space_id, None)

    async def upsert(
        self, space_id: EmbeddingSpaceId, vectors: Mapping[ChunkKey, Sequence[float]]
    ) -> int:
        """Store the vectors of chunks that exist; all or nothing.

        Args:
            space_id: The space.
            vectors: The vector of each chunk.

        Returns:
            How many were stored.
        """
        space = self._live(space_id)
        checked = {
            k: _float32(checked_vector(v, space.spec.dimensions)) for k, v in vectors.items()
        }
        stored = self._stored(space_id)
        kept = {k: (owner, v) for k, v in checked.items() if (owner := self._owner(k)) is not None}
        stored.update(kept)
        return len(kept)

    async def delete(self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]) -> int:
        """Delete the vectors of these chunks.

        Args:
            space_id: The space.
            keys: The chunks.

        Returns:
            How many were deleted.
        """
        self._live(space_id)
        stored = self._stored(space_id)
        return sum(stored.pop(k, None) is not None for k in set(keys))

    async def nearest(
        self,
        space_id: EmbeddingSpaceId,
        manifest_id: str,
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[VectorHit]:
        """Compare the query with every vector of the manifest's chunks.

        Args:
            space_id: The space.
            manifest_id: The manifest.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest chunks, nearest first, ties by chunk ID.

        Raises:
            VectorStoreUnavailableError: ``can_search`` is False.
        """
        space = self._live(space_id)
        wanted = _float32(checked_vector(query, space.spec.dimensions))
        if not self.can_search:
            raise VectorStoreUnavailableError
        stored = self._stored(space_id)
        hits = [
            VectorHit(chunk_id=row.chunk_id, distance=_cosine_distance(wanted, vector))
            for row in self.chunks.rows.get(manifest_id, {}).values()
            if tag_filter.keeps(row.tags)
            and (entry := stored.get((*row.chunk_set, row.position))) is not None
            and (vector := entry[1])
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id))
        return hits[:limit]

    async def coverage(self, space_id: EmbeddingSpaceId, manifest_id: str) -> VectorCoverage:
        """Count the manifest's chunks and those with a vector.

        Args:
            space_id: The space.
            manifest_id: The manifest.

        Returns:
            The counts.
        """
        self._live(space_id)
        stored = self._stored(space_id)
        rows = self.chunks.rows.get(manifest_id, {}).values()
        embedded = sum((*r.chunk_set, r.position) in stored for r in rows)
        return VectorCoverage(chunks=len(rows), embedded=embedded)

    async def missing(
        self, space_id: EmbeddingSpaceId, manifest_id: str, limit: int
    ) -> Sequence[ChunkKey]:
        """Return chunk keys of the manifest without a vector, sorted.

        Args:
            space_id: The space.
            manifest_id: The manifest.
            limit: How many at most.

        Returns:
            The keys.
        """
        self._live(space_id)
        stored = self._stored(space_id)
        keys = {(*r.chunk_set, r.position) for r in self.chunks.rows.get(manifest_id, {}).values()}
        return sorted(k for k in keys if k not in stored)[:limit]

    async def pending(
        self, space_id: EmbeddingSpaceId | None, manifest_ids: Collection[str]
    ) -> PendingChunks:
        """Count the distinct chunks of these manifests without a vector in the space.

        Args:
            space_id: The space; ``None`` counts every chunk.
            manifest_ids: The manifests.

        Returns:
            The chunks and their characters.
        """
        stored: Mapping[ChunkKey, object] = {}
        if space_id is not None:
            self._live(space_id)
            stored = self._stored(space_id)
        first: dict[ChunkKey, tuple[str, str]] = {}
        for manifest_id in sorted(set(manifest_ids)):
            for row in self.chunks.rows.get(manifest_id, {}).values():
                key: ChunkKey = (row.chunk_set[0], row.chunk_set[1], row.position)
                where = (manifest_id, row.article_path)
                if key not in stored and (key not in first or where < first[key]):
                    first[key] = where
        characters = sum(
            _characters(self.chunks.chunk_sets[k[0], k[1]].chunks[k[2]]) for k in first
        )
        articles = Counter(first.values())
        return PendingChunks(
            chunks=len(first),
            characters=characters,
            articles=tuple(
                PendingArticle(manifest_id=m, article_path=p, chunks=n)
                for (m, p), n in sorted(articles.items())
            ),
        )

    def _space(self, space_id: EmbeddingSpaceId) -> EmbeddingSpace:
        """Find the space.

        Args:
            space_id: The space.

        Returns:
            It, in any state.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
        """
        space = self.spaces_by_id.get(space_id)
        if space is None:
            raise UnknownEmbeddingSpaceError(space_id)
        return space

    def _live(self, space_id: EmbeddingSpaceId) -> EmbeddingSpace:
        """Find a space that is not retired.

        Args:
            space_id: The space.

        Returns:
            It.

        Raises:
            RetiredEmbeddingSpaceError: It was retired.
        """
        space = self._space(space_id)
        if space.state is SpaceState.RETIRED:
            raise RetiredEmbeddingSpaceError(space_id)
        return space

    def _owner(self, key: ChunkKey) -> ChunkSet | None:
        """Find the stored chunk set that holds this chunk.

        Args:
            key: The chunk.

        Returns:
            The set, or ``None`` when it is not stored or has no such position.
        """
        chunk_set = self.chunks.chunk_sets.get((key[0], key[1]))
        if chunk_set is None or not 0 <= key[2] < len(chunk_set.chunks):
            return None
        return chunk_set

    def _stored(
        self, space_id: EmbeddingSpaceId
    ) -> dict[ChunkKey, tuple[ChunkSet, tuple[float, ...]]]:
        """Return the space's vectors, forgetting those whose chunk set was collected.

        Args:
            space_id: The space.

        Returns:
            The live vectors (the stored dictionary itself).
        """
        stored = self.vectors[space_id]
        for key in [k for k, (owner, _) in stored.items() if self._owner(k) is not owner]:
            del stored[key]
        return stored


def _characters(chunk: Chunk) -> int:
    """Count the characters of a chunk's text and heading path, as the estimate does.

    Args:
        chunk: The chunk.

    Returns:
        The characters.
    """
    return len(chunk.content) + sum(len(h) for h in chunk.heading_path)


def _float32(vector: tuple[float, ...]) -> tuple[float, ...]:
    """Round to 32-bit floats, as the stores keep vectors.

    Args:
        vector: The values.

    Returns:
        The values a store would read back.
    """
    return struct.unpack(f"<{len(vector)}f", struct.pack(f"<{len(vector)}f", *vector))


def _cosine_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Return 1 minus the cosine of the angle between two non-zero vectors.

    Args:
        a: One vector.
        b: The other, of the same length.

    Returns:
        The distance, from 0 (same direction) to 2 (opposite).
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return max(0.0, 1 - dot / norms)  # rounding can put a vector's own distance below 0


@dataclass(frozen=True, slots=True, kw_only=True)
class HashEmbeddings:
    """Implements ``ports.driven.Embeddings`` in process: a vector from each text's hash.

    The same text always gets the same vector, and different texts different ones, so tests can
    tell what was embedded without any provider. ``usage`` is one token per 4 characters.
    """

    name: str
    """``<profile>:<model>``."""
    size: int
    """The vectors' dimensions."""
    batch_size: int
    """Texts per call."""
    sent: list[str]
    """Every text embedded as a document, in order (shared with ``HashEmbeddingModels``)."""
    calls: list[str]
    """The model of every call, in order (shared with ``HashEmbeddingModels``)."""

    async def dimensions(self) -> int:
        """Say the vectors' size.

        Returns:
            ``size``.
        """
        return self.size

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        """Embed texts as documents, ``batch_size`` per call.

        Args:
            texts: The texts.

        Returns:
            Their vectors.
        """
        self.sent.extend(texts)
        return self._embed(texts)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        """Embed a query.

        Args:
            text: The query.

        Returns:
            Its vector.
        """
        return self._embed([text])

    def _embed(self, texts: Sequence[str]) -> EmbeddedTexts:
        """Hash each text into a vector, one call per batch.

        Args:
            texts: The texts.

        Returns:
            The vectors and the usage.
        """
        calls = list(batched(texts, self.batch_size, strict=False))
        self.calls.extend(self.name for _ in calls)
        return EmbeddedTexts(
            vectors=tuple(_hash_vector(t, self.size) for t in texts),
            input_tokens=sum(-(-len(t) // CHARS_PER_TOKEN) for t in texts),
            requests=len(calls),
        )


def _hash_vector(text: str, size: int) -> tuple[float, ...]:
    """Make a non-zero vector from a text's SHA-256.

    Args:
        text: The text.
        size: The dimensions.

    Returns:
        The vector.
    """
    digest = hashlib.sha256(text.encode()).digest()
    return tuple(1.0 + digest[i % len(digest)] / 255 for i in range(size))


@dataclass(frozen=True, slots=True, kw_only=True)
class HashEmbeddingModels:
    """Implements ``ports.driven.EmbeddingModels`` with ``HashEmbeddings`` (tests, no provider).

    The handle the factory built is ignored; what is sent and which model is called is kept.
    """

    size: int = 8
    """The dimensions a model answers when none are configured."""
    sent: list[str] = field(default_factory=list)
    """Every text embedded as a document, in order."""
    calls: list[str] = field(default_factory=list)
    """The model of every call, in order."""

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> HashEmbeddings:
        """Make a hash model.

        Args:
            handle: Ignored.
            name: ``<profile>:<model>``.
            dimensions: The configured dimensions, else ``size``.
            batch_size: Texts per call.

        Returns:
            The model.
        """
        del handle
        return HashEmbeddings(
            name=name,
            size=dimensions or self.size,
            batch_size=batch_size,
            sent=self.sent,
            calls=self.calls,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemorySpendLedger:
    """Implements ``ports.driven.SpendLedger`` with a dictionary of summed rows."""

    rows: dict[tuple[str, str, SpendWindow, str], SpendEntry] = field(default_factory=dict)
    """Each row by (scope kind, scope ID, window, window start)."""

    async def add(self, entries: Sequence[SpendEntry]) -> None:
        """Add each entry to its row.

        Args:
            entries: The usage.
        """
        for entry in entries:
            key = (entry.scope_kind, entry.scope_id, entry.window, entry.window_start.isoformat())
            row = self.rows.get(key)
            self.rows[key] = (
                entry
                if row is None
                else replace(
                    row,
                    input_tokens=row.input_tokens + entry.input_tokens,
                    output_tokens=row.output_tokens + entry.output_tokens,
                    requests=row.requests + entry.requests,
                    usd_micros=row.usd_micros + entry.usd_micros,
                    unpriced=row.unpriced + entry.unpriced,
                )
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticPrices:
    """Implements ``ports.driven.Prices`` from a fixed table (tests)."""

    input_prices: Mapping[tuple[str, str], float] = field(default_factory=dict)
    """US dollars per million input tokens, by (profile kind, model)."""

    def input_usd_per_million(self, profile_kind: str, model: str) -> float | None:
        """Look the model up.

        Args:
            profile_kind: The profile's kind.
            model: The model.

        Returns:
            Its price, or ``None``.
        """
        return self.input_prices.get((profile_kind, model))
