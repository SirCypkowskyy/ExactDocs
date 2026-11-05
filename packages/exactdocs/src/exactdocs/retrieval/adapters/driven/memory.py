import sys
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from exactdocs.retrieval.errors import ChunkSetMismatchError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    IndexedManifest,
    ManifestChunk,
    ManifestHit,
    RebuiltIndex,
    Removed,
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


@dataclass(slots=True)
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
        self.chunk_sets |= new
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


MEMORY_FORMAT = 1


@dataclass(slots=True)
class InMemorySearchIndex:
    """Reference ``ports.driven.SearchIndex``: a term-count score, not BM25.

    It reads the chunk rows of the repository it is built on, so it forgets a chunk set when the
    repository does, as the SQLite index does. Headings weigh ten times the body.

    It scores the whole heading path alike; it does not model the SQLite index's own-heading versus
    ancestors weighting. The ranking suite (`docker`) is what every engine must satisfy.
    """

    chunks: InMemoryChunkRepository
    indexed: set[ChunkSetKey] = field(default_factory=set)
    stored_format: int = MEMORY_FORMAT  # set it lower to stand for an index from an older build

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
        self.indexed = set(self.chunks.chunk_sets)
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


@dataclass(frozen=True, slots=True)
class InMemoryDefaultVersions:
    """Implements ``ports.driven.DefaultVersions`` with a fixed list."""

    versions: Sequence[SearchableVersion] = ()

    async def all(self) -> Sequence[SearchableVersion]:
        """Return the versions sorted by library."""
        return sorted(self.versions, key=lambda v: v.library)


@dataclass(frozen=True, slots=True)
class InMemoryLibraries:
    """Implements ``ports.driven.Libraries`` with a fixed list."""

    libraries: Sequence[CatalogLibrary] = ()

    async def all(self) -> Sequence[CatalogLibrary]:
        """Return the libraries that have a default version."""
        return [lib for lib in self.libraries if lib.default_version is not None]
