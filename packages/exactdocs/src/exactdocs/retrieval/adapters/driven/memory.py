from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from exactdocs.retrieval.errors import ChunkSetMismatchError
from exactdocs.retrieval.models import (
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    Excerpt,
    IndexedManifest,
    ManifestChunk,
    Removed,
    SearchHit,
    SearchText,
    StoredChunk,
    highlights,
    identifier_tokens,
    search_terms,
)


@dataclass(slots=True)
class InMemoryExcerptIndex:
    """Implements ``ports.driven.ExcerptIndex`` with case-insensitive substring matching.

    Placeholder until the SQLite (FTS5 + sqlite-vec) and pgvector adapters land.
    """

    excerpts: list[Excerpt] = field(default_factory=list)

    @classmethod
    def of(cls, excerpts: Iterable[Excerpt]) -> Self:
        """Create an index pre-filled with ``excerpts``."""
        return cls(list(excerpts))

    async def search(self, target: DocTarget, text: SearchText, limit: int) -> Sequence[Excerpt]:
        """Return excerpts of ``target`` that contain ``text``."""
        needle = text.value.casefold()
        hits = (e for e in self.excerpts if e.target == target and needle in e.text.casefold())
        return [hit for _, hit in zip(range(limit), hits, strict=False)]


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

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        row = self.rows.get(manifest_id, {}).get(chunk_id)
        if row is None:
            return None
        chunk = self.chunk_sets[row.chunk_set].chunks[row.position]
        version_id = self.manifests[manifest_id].version_id
        return StoredChunk(manifest_id=manifest_id, version_id=version_id, row=row, chunk=chunk)

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


@dataclass(slots=True)
class InMemorySearchIndex:
    """Reference ``ports.driven.SearchIndex``: a term-count score, not BM25.

    It reads the chunk rows of the repository it is built on, so it forgets a chunk set when the
    repository does, as the SQLite index does. Headings weigh ten times the body.
    """

    chunks: InMemoryChunkRepository
    indexed: set[ChunkSetKey] = field(default_factory=set)

    async def index(self, chunk_set: ChunkSet) -> None:
        """Remember the set; the text itself is read from the repository."""
        self.indexed.add(chunk_set.key)

    async def search(
        self, manifest_id: str, query: str, tag_filter: Collection[str], limit: int
    ) -> Sequence[SearchHit]:
        """Return this manifest's best matches, ties broken by chunk ID."""
        terms = search_terms(query)
        hits: list[SearchHit] = []
        for row in self.chunks.rows.get(manifest_id, {}).values():
            if row.chunk_set not in self.indexed or row.chunk_set not in self.chunks.chunk_sets:
                continue
            if tag_filter and not set(tag_filter) & set(row.tags):
                continue
            chunk = self.chunks.chunk_sets[row.chunk_set].chunks[row.position]
            heading = Counter(identifier_tokens(" ".join(chunk.heading_path)).split())
            body = Counter(identifier_tokens(chunk.content).split())
            score = sum(10 * heading[t] + body[t] for t in terms)
            if score:
                hits.append(_hit(row.chunk_id, float(score), chunk.content, terms))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:limit]


def _hit(chunk_id: ChunkId, score: float, content: str, terms: list[str]) -> SearchHit:
    marks = highlights(content, terms)
    start = max(0, marks[0][0] - 40) if marks else 0
    snippet = content[start : start + 160]
    return SearchHit(
        chunk_id=chunk_id, score=score, snippet=snippet, highlights=highlights(snippet, terms)
    )
