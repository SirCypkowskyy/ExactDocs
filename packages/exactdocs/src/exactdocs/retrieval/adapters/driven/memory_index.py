"""The reference external index backend: dictionaries in this process (``memory``).

What an external backend adapter looks like (#352): it implements ``SearchBackend`` and
``VectorBackend`` (and, optionally, ``NativeHybrid``) over its own client, and holds derived
data only. This one keeps nothing across a restart, so every start finds it empty and
``exactdocs index check`` reports every version missing until ``exactdocs index rebuild``: it is
for tests and for trying the extension point, never for production.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from exactdocs.retrieval.adapters.driven.memory import _cosine_distance
from exactdocs.retrieval.constants import MEMORY_BACKEND
from exactdocs.retrieval.errors import IndexBackendUnavailableError
from exactdocs.retrieval.models import (
    BackendHit,
    BackendNeighbour,
    ChunkId,
    EmbeddingSpace,
    EmbeddingSpaceId,
    HeldVersion,
    IndexedManifest,
    IndexEntry,
    TagFilter,
    TextQuery,
    as_float32,
    fuse_across_manifests,
    identifier_tokens,
)

type _Entries = dict[str, dict[ChunkId, IndexEntry]]


def _score(entry: IndexEntry, terms: Collection[str]) -> int:
    """Score an entry as the in-memory reference index does: heading matches count ten times.

    Args:
        entry: The entry.
        terms: The query's terms.

    Returns:
        The score; 0 when no term matches.
    """
    heading = Counter(identifier_tokens(" ".join(entry.heading_path)).split())
    body = Counter(identifier_tokens(entry.content).split())
    return sum(10 * heading[t] + body[t] for t in terms)


def _held(entries: _Entries, library: str | None) -> list[HeldVersion]:
    """List the versions held, with their entry counts.

    Args:
        entries: The entries, by manifest then chunk.
        library: Only this library's, if given.

    Returns:
        One per version held.
    """
    return [
        HeldVersion(manifest_id=m, library=next(iter(held.values())).library, entries=len(held))
        for m, held in sorted(entries.items())
        if held and (library is None or next(iter(held.values())).library == library)
    ]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- tests switch it off
class InMemorySearchBackend:
    """Implements ``ports.driven.SearchBackend`` with dictionaries; scores count terms."""

    name: str = MEMORY_BACKEND
    """The registered name."""
    entries: _Entries = field(default_factory=dict)
    """Every entry, by manifest then chunk ID."""
    unavailable: bool = False
    """Set it True to stand for a backend that does not answer."""

    async def open(self) -> None:
        """Check the backend answers (``IndexBackendUnavailableError`` when ``unavailable``)."""
        self._answer()

    async def close(self) -> None:
        """Nothing to release."""

    async def put(self, manifest: IndexedManifest, entries: Sequence[IndexEntry]) -> None:
        """Add or replace the entries.

        Args:
            manifest: The version.
            entries: Some of its entries.
        """
        self._answer()
        held = self.entries.setdefault(manifest.manifest_id, {})
        held.update({e.chunk_id: e for e in entries})

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries.

        Args:
            manifest_ids: The versions.
        """
        self._answer()
        for manifest_id in manifest_ids:
            self.entries.pop(manifest_id, None)

    async def held(self, library: str | None) -> Sequence[HeldVersion]:
        """List the versions held.

        Args:
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        self._answer()
        return _held(self.entries, library)

    async def search(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter, limit: int
    ) -> Sequence[BackendHit]:
        """Rank the versions' entries by term counts, headings ten times the body.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first; ties by chunk ID, then manifest ID.
        """
        return self._ranked(manifest_ids, query, tag_filter)[:limit]

    async def count(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Count the matching entries of each version.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many entries match, by manifest ID; zeros left out.
        """
        return Counter(h.manifest_id for h in self._ranked(manifest_ids, query, tag_filter))

    def _ranked(
        self, manifest_ids: Sequence[str], query: TextQuery, tag_filter: TagFilter
    ) -> list[BackendHit]:
        """Score every entry of the versions that passes the filter.

        Args:
            manifest_ids: The versions searched.
            query: The query and its terms.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            Every match, best first.
        """
        self._answer()
        hits = [
            BackendHit(manifest_id=m, chunk_id=e.chunk_id, score=float(score))
            for m in dict.fromkeys(manifest_ids)
            for e in self.entries.get(m, {}).values()
            if tag_filter.keeps(e.tags) and (score := _score(e, query.terms))
        ]
        hits.sort(key=lambda h: (-h.score, h.chunk_id, h.manifest_id))
        return hits

    def _answer(self) -> None:
        """Fail as an unreachable backend does.

        Raises:
            IndexBackendUnavailableError: ``unavailable`` is set.
        """
        if self.unavailable:
            raise IndexBackendUnavailableError(self.name, "switched off")


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- tests switch it off
class InMemoryVectorBackend:
    """Implements ``ports.driven.VectorBackend`` and ``NativeHybrid``: exact cosine in Python."""

    name: str = MEMORY_BACKEND
    """The registered name."""
    spaces: dict[EmbeddingSpaceId, _Entries] = field(default_factory=dict)
    """Every space's entries, by manifest then chunk ID."""
    unavailable: bool = False
    """Set it True to stand for a backend that does not answer."""

    async def open(self) -> None:
        """Check the backend answers (``IndexBackendUnavailableError`` when ``unavailable``)."""
        self._answer()

    async def close(self) -> None:
        """Nothing to release."""

    async def put(
        self, space: EmbeddingSpace, manifest: IndexedManifest, entries: Sequence[IndexEntry]
    ) -> None:
        """Add or replace the entries in the space (their vectors are the store's float32 ones).

        Args:
            space: The space.
            manifest: The version.
            entries: Some of its entries, each with a vector.
        """
        self._answer()
        held = self.spaces.setdefault(space.id, {}).setdefault(manifest.manifest_id, {})
        held.update({e.chunk_id: e for e in entries if e.vector is not None})

    async def remove(
        self, space_id: EmbeddingSpaceId, manifest_id: str, chunk_ids: Collection[ChunkId]
    ) -> None:
        """Delete some entries of a version in a space.

        Args:
            space_id: The space.
            manifest_id: The version.
            chunk_ids: The chunks.
        """
        self._answer()
        held = self.spaces.get(space_id, {}).get(manifest_id, {})
        for chunk_id in chunk_ids:
            held.pop(chunk_id, None)

    async def delete(self, manifest_ids: Collection[str]) -> None:
        """Delete the versions' entries in every space.

        Args:
            manifest_ids: The versions.
        """
        self._answer()
        for entries in self.spaces.values():
            for manifest_id in manifest_ids:
                entries.pop(manifest_id, None)

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Forget a space.

        Args:
            space_id: The space.
        """
        self._answer()
        self.spaces.pop(space_id, None)

    async def held(self, space_id: EmbeddingSpaceId, library: str | None) -> Sequence[HeldVersion]:
        """List the versions the space holds.

        Args:
            space_id: The space.
            library: Only this library's, if given.

        Returns:
            One per version held.
        """
        self._answer()
        return _held(self.spaces.get(space_id, {}), library)

    async def nearest(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendNeighbour]:
        """Compare the query with every vector of the versions.

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits at most.

        Returns:
            The nearest entries, nearest first; ties by chunk ID, then manifest ID.
        """
        self._answer()
        wanted = as_float32(query)
        entries = self.spaces.get(space.id, {})
        hits = [
            BackendNeighbour(
                manifest_id=m, chunk_id=e.chunk_id, distance=_cosine_distance(wanted, e.vector)
            )
            for m in dict.fromkeys(manifest_ids)
            for e in entries.get(m, {}).values()
            if e.vector is not None and tag_filter.keeps(e.tags)
        ]
        hits.sort(key=lambda h: (h.distance, h.chunk_id, h.manifest_id))
        return hits[:limit]

    async def hybrid(
        self,
        space: EmbeddingSpace,
        manifest_ids: Sequence[str],
        query: TextQuery,
        vector: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[BackendHit]:
        """Fuse a term-count ranking and the vector ranking of the versions' entries (RRF).

        Args:
            space: The space.
            manifest_ids: The versions searched.
            query: The query and its terms.
            vector: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: The most hits.

        Returns:
            The fused hits, best first.
        """
        entries = self.spaces.get(space.id, {})
        words = [
            (m, e.chunk_id, score)
            for m in dict.fromkeys(manifest_ids)
            for e in entries.get(m, {}).values()
            if tag_filter.keeps(e.tags) and (score := _score(e, query.terms))
        ]
        words.sort(key=lambda w: (-w[2], w[1], w[0]))
        near = await self.nearest(space, manifest_ids, vector, tag_filter, len(words) + limit)
        fused = fuse_across_manifests(
            [(m, c) for m, c, _ in words], [(h.manifest_id, h.chunk_id) for h in near]
        )
        return [
            BackendHit(manifest_id=f.manifest_id, chunk_id=f.chunk_id, score=f.score)
            for f in fused[:limit]
        ]

    def _answer(self) -> None:
        """Fail as an unreachable backend does.

        Raises:
            IndexBackendUnavailableError: ``unavailable`` is set.
        """
        if self.unavailable:
            raise IndexBackendUnavailableError(self.name, "switched off")


def search_backend(options: Mapping[str, object]) -> InMemorySearchBackend:
    """Build the search backend from its ``[index_backends.memory]`` options (it takes none).

    Args:
        options: The options; must be empty.

    Returns:
        A new, empty backend.

    Raises:
        ValueError: An option was given.
    """
    if options:
        message = f"the memory backend takes no options (got {', '.join(sorted(options))})"
        raise ValueError(message)
    return InMemorySearchBackend()


def vector_backend(options: Mapping[str, object]) -> InMemoryVectorBackend:
    """Build the vector backend from its ``[index_backends.memory]`` options (it takes none).

    Args:
        options: The options; must be empty.

    Returns:
        A new, empty backend.

    Raises:
        ValueError: An option was given.
    """
    if options:
        message = f"the memory backend takes no options (got {', '.join(sorted(options))})"
        raise ValueError(message)
    return InMemoryVectorBackend()
