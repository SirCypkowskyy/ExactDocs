"""Driven (secondary) ports of retrieval."""

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from exactdocs.retrieval.models import (
    CatalogLibrary,
    ChunkId,
    ChunkKey,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    IndexedManifest,
    ManifestChunk,
    ManifestHit,
    ManifestStatus,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    RebuiltIndex,
    Removed,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    SearchIndexState,
    SectionRef,
    StoredChunk,
    TagFilter,
    VectorCoverage,
    VectorHit,
    VersionCounts,
)


class SearchableVersions(Protocol):
    """Which version a search runs on, in retrieval's own terms (the catalog answers).

    Version is a hard filter: an unknown version is ``None``, never another version.
    """

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        """Return the exact ``ref`` (the default version when ``None``) and the manifest it serves.

        ``None`` when there is no such version or it has no active manifest.
        """
        ...


class DefaultVersions(Protocol):
    """Every library's default version that has an active manifest, in one call."""

    async def all(self) -> Sequence[SearchableVersion]:
        """Return them sorted by library ID; libraries with nothing readable are left out."""
        ...


class Libraries(Protocol):
    """The libraries the catalog lists, in retrieval's own terms."""

    async def all(self) -> Sequence[CatalogLibrary]:
        """Return every library that has a default version; the rest cannot be queried."""
        ...

    async def canonical_id(self, library: str) -> str | None:
        """Spell the library's ID as the catalog does (IDs match in any letter case).

        Args:
            library: The ID as asked.

        Returns:
            The catalog's spelling; ``None`` when there is no such library, whether or not it
            has a version yet.
        """
        ...


class ActiveManifests(Protocol):
    """What the catalog says about manifests. Retrieval holds manifest IDs by value only.

    The order is: the catalog stores the manifest (pending), retrieval indexes it, the catalog
    activates it. So a manifest the catalog does not know is one it already dropped, or one
    whose Store call has not been answered yet; only an old one is safe to remove.
    """

    async def active_id(self, target: DocTarget) -> str | None:
        """Return the ID of the version's active manifest, or ``None`` when it has none."""
        ...

    async def statuses(self, manifest_ids: Collection[str]) -> Mapping[str, ManifestStatus]:
        """Return the status of each ID the catalog knows; unknown IDs are left out.

        A status this domain has no name for is ``ManifestStatus.OTHER``.
        """
        ...


class RenamedPaths(Protocol):
    """Renames git saw, in retrieval's terms (the catalog answers)."""

    async def new_path(self, target: DocTarget, old_path: str) -> str | None:
        """Return where ``old_path`` of the version before is in the target version, or ``None``.

        ``None`` also when nothing is known (no map, no active manifest): never an error.
        """
        ...


class ArticleSuggestions(Protocol):
    """Paths of a version an agent may have meant by one it does not have (the catalog answers)."""

    async def close_to(self, target: DocTarget, path: str) -> Sequence[str]:
        """Return at most five paths of the target version close to ``path``, best first.

        Args:
            target: The exact library version.
            path: The path the version does not have.

        Returns:
            Close paths; empty when nothing is close or nothing is known (never an error).
        """
        ...


class ChunkRepository(Protocol):
    """Chunk sets (shared by content) and the per-manifest chunk rows that point at them."""

    async def add(
        self,
        manifest: IndexedManifest,
        chunk_sets: Mapping[ChunkSetKey, ChunkSet],
        rows: Sequence[ManifestChunk],
    ) -> int | None:
        """Store the manifest's rows and the chunk sets it needs, in one transaction.

        A chunk set whose key is already stored is left as it is, but its digest must match
        (``ChunkSetMismatchError`` otherwise, nothing is stored). Returns how many chunk sets
        were new, or ``None`` without changing anything when this manifest ID is already indexed.
        """
        ...

    async def get_sets(self, keys: Sequence[ChunkSetKey]) -> Mapping[ChunkSetKey, ChunkSet]:
        """Return the stored chunk sets among ``keys``, chunks in order; the rest is left out.

        Batched, so a caller may pass thousands of keys.
        """
        ...

    async def get(self, manifest_id: str, chunk_id: ChunkId) -> StoredChunk | None:
        """Return one chunk of the manifest with its content, or ``None``."""
        ...

    async def get_many(
        self, manifest_id: str, chunk_ids: Sequence[ChunkId]
    ) -> Mapping[ChunkId, StoredChunk]:
        """Return the chunks of the manifest that exist, by ID, in one query."""
        ...

    async def get_across(
        self, wanted: Mapping[str, Collection[ChunkId]]
    ) -> Mapping[tuple[str, ChunkId], StoredChunk]:
        """Return the chunks that exist, by (manifest ID, chunk ID), for several manifests at once.

        One query, whatever the number of manifests; missing pairs are left out.
        """
        ...

    async def article(self, manifest_id: str, article_path: str) -> Sequence[SectionRef]:
        """Return the sections of one article of the manifest in order, without their text.

        Empty if the manifest has no such article.
        """
        ...

    async def counts(self, manifest_id: str) -> VersionCounts:
        """Count the manifest's articles and chunks; zeros for an unknown manifest."""
        ...

    async def manifests_with_chunk(self, chunk_id: ChunkId) -> Sequence[IndexedManifest]:
        """Return every indexed manifest that has a row for this chunk ID (any status)."""
        ...

    async def find_manifests(
        self, *, manifest_id: str | None, library: str | None, indexed_before: datetime | None
    ) -> Sequence[IndexedManifest]:
        """Return the indexed manifests that match every given filter."""
        ...

    async def remove(self, manifest_ids: Collection[str]) -> Removed:
        """Delete these manifests' rows, then every chunk set no manifest points at."""
        ...

    async def set_tags(self, manifest_id: str, tags: Mapping[str, tuple[str, ...]]) -> int:
        """Replace the tags copied onto the chunk rows of these article paths of the manifest.

        Chunks and the search index stay as they are. Paths without rows are ignored; returns
        how many rows were changed.
        """
        ...


class SearchIndex(Protocol):
    """Full-text (BM25) search over stored chunk sets; SQLite FTS5 now, ParadeDB later.

    Every engine behaves the same: see ``tests/retrieval/test_search_index.py``. The index holds
    one entry per chunk of a chunk set, so a set shared by several manifests is indexed once.
    Which chunks a search may return is decided by the manifest's chunk rows, not by the index.
    Entries die with their chunk rows: when ``ChunkRepository.remove`` deletes a chunk set its
    index entries go in the same step, so discard and collect need no call here.
    """

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index a chunk set that ``ChunkRepository.add`` stored. Idempotent; indexes only gaps."""
        ...

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return at most ``limit`` chunks of this manifest, best first.

        ``query`` is plain text: quotes, ``NEAR``, ``*`` and ``(`` are ordinary characters, never
        syntax. Its words are alternatives (see ``identifier_tokens``). Snippets are verbatim text
        of the chunk with offsets from ``highlights``. ``tag_filter`` is applied
        before ranking: the best ``limit`` of the chunks that pass, not the passing part of the
        best ``limit``. An unknown manifest or a query without words gives no hits.
        """
        ...

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return at most ``limit`` chunks of any of these manifests, best first, in one search.

        Same rules as ``search``. Scores are comparable across manifests: the statistics are
        global over the stored chunks, never per manifest. A chunk set shared by two manifests
        is a hit for each (they are different library versions), with the same score.
        """
        ...

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Return how many chunks of each manifest match, uncapped; zero counts are left out."""
        ...


class SearchIndexMaintenance(Protocol):
    """Rebuilds the search index from the stored chunks, without stopping search.

    The new index is built beside the one that answers and replaces it in one step, so a search
    sees either the old index or the new one, never a half-built one. Chunks indexed or removed
    while it builds are in the new one too.
    """

    async def state(self) -> SearchIndexState:
        """Return the stored index's format and the one this build writes."""
        ...

    async def rebuild(self) -> RebuiltIndex:
        """Build a new index of every stored chunk in the current format, then swap it in."""
        ...


class SearchSpan(Protocol):
    """An open search span: it can still learn which mode really answered."""

    def answered_by(self, mode: str) -> None:
        """Record the mode that answered, when a pipeline fell back to a cheaper one.

        Args:
            mode: The mode in the result (``retrieval_mode``).
        """
        ...


class SearchTracer(Protocol):
    """Marks a search and its stages for whoever observes them (traces and metrics, OPS-01).

    The use cases open a span per search and one per stage inside it. The query text is handed
    over separately: an adapter records it only when the operator explicitly opted in.
    """

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[SearchSpan]:
        """Open the span ``name`` (``search_docs``, ``search_docs.rank``...) until the block ends.

        Args:
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode the search was chosen to run in (``bm25``); the block may
                replace it with the mode that answered (``SearchSpan.answered_by``).
            query: The query text, recorded only when the adapter was told to.
            attributes: Further labels (library, ref); ``None`` ones are left out.

        Returns:
            A context manager: the span lasts as long as its block.
        """
        ...


class ModelRoles(Protocol):
    """Which model roles a library's searches may use: the availability view of role resolution.

    In the decision record's terms (docs/decisions/ai-retrieval.md, *Where the code lives*),
    retrieval resolves the profile and model of each role from ``ProviderProfiles`` (instance
    roles from the environment, the TOML file or the UI, #241) plus the library's overrides
    (AI on or off, its own ``llm``/``judge``/``reranker``, #102); ``ModelFactory`` then turns a
    resolved profile into something callable. This port only says which roles resolve for a
    library, so #241 implements it inside retrieval over ``ProviderProfiles``, not as a second
    source of truth in bootstrap. A library with AI off has no role at all: nothing of it is
    sent to a provider. Asked at every search, so a change counts at the next one.
    """

    async def configured(self, library: str) -> frozenset[ModelRole]:
        """Say which roles a search of ``library`` may use.

        Args:
            library: The library ID, any letter case.

        Returns:
            The roles; empty when nothing is configured or the library has AI off (BM25 only).
        """
        ...


class LibraryModes(Protocol):
    """Each library's own retrieval mode, which a search uses when the call names none.

    Library IDs match in any letter case.
    """

    async def mode_of(self, library: str) -> RetrievalMode | None:
        """Read the library's mode.

        Args:
            library: The library ID, any letter case.

        Returns:
            The mode, or ``None`` when it has none (the instance's applies).
        """
        ...

    async def forget(self, library: str) -> None:
        """Drop everything stored for a library that was removed (a no-op when nothing is).

        Args:
            library: The library ID, any letter case.
        """
        ...

    async def set_mode(self, library: str, mode: RetrievalMode | None) -> None:
        """Store the library's mode.

        Args:
            library: The library ID as the catalog spells it.
            mode: The mode; ``None`` removes it.
        """
        ...


class RetrievalPipeline(Protocol):
    """One way of finding the chunks of one version that answer a query (a retrieval mode).

    The use cases pick the mode (call, then library, then instance, then the best available, see
    ``ModeRegistry``) and run the pipeline registered for it. Version is a hard filter: every
    hit must come from ``request.version``. A pipeline that cannot do its part (a version not
    embedded yet, a budget reached) answers with a cheaper mode and says why in the answer; it
    raises only for what would fail any mode.
    """

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Search the version.

        Args:
            request: The version, the query, the tag filter, the limit and the rerank flag.

        Returns:
            At most ``request.limit`` hits, best first, with the mode that really answered.
        """
        ...


class VectorIndex(Protocol):
    """Chunk vectors, one store per embedding space; sqlite-vec on SQLite, pgvector later.

    Every engine behaves the same: see ``tests/retrieval/test_vector_index.py``. A space holds
    the vectors of one ``EmbeddingSpec``; a query runs in one space, so vectors of two models are
    never compared. A vector belongs to one stored chunk (``ChunkKey``), which every manifest
    holding the same blob with the same chunking shares, so a blob is embedded once. Vectors die
    with their chunks: when ``ChunkRepository.remove`` deletes a chunk set, its vectors go in the
    same step, in every space. Search is exact and scoped to one manifest (no ANN index).
    """

    async def available(self) -> bool:
        """Say whether ``nearest`` can run here (SQLite: whether sqlite-vec can be loaded).

        Asked only once an embedding model is configured: the answer may load the store.
        Storing vectors needs nothing loaded, so the other methods work either way.

        Returns:
            True when the store can search.
        """
        ...

    async def spaces(self) -> Sequence[EmbeddingSpace]:
        """List every space, retired ones too, oldest first.

        Returns:
            The spaces.
        """
        ...

    async def create_space(self, spec: EmbeddingSpec, at: datetime) -> EmbeddingSpace:
        """Create an empty space for ``spec``, in state ``building``, with a new ID.

        Args:
            spec: The model and format its vectors will be made with.
            at: When it is created.

        Returns:
            The new space.
        """
        ...

    async def activate_space(self, space_id: EmbeddingSpaceId, at: datetime) -> EmbeddingSpace:
        """Mark the space ``active`` (the caller retires the one it replaces).

        Args:
            space_id: The space.
            at: When it became active; kept from the first activation.

        Returns:
            The space as it is now.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
        """
        ...

    async def retire_space(self, space_id: EmbeddingSpaceId) -> None:
        """Mark the space ``retired`` and drop its vectors; a no-op for a retired space.

        Args:
            space_id: The space.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
        """
        ...

    async def upsert(
        self, space_id: EmbeddingSpaceId, vectors: Mapping[ChunkKey, Sequence[float]]
    ) -> int:
        """Store or replace the vectors of these chunks in the space, in one transaction.

        A key with no stored chunk (collected meanwhile) is skipped. Nothing is stored when one
        vector is invalid.

        Args:
            space_id: The space.
            vectors: The vector of each chunk.

        Returns:
            How many vectors were stored.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
            VectorDimensionError: A vector does not have the space's dimensions.
            InvalidVectorError: A vector is all zeros or holds a value that is not finite.
        """
        ...

    async def delete(self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]) -> int:
        """Delete the vectors of these chunks from the space.

        Args:
            space_id: The space.
            keys: The chunks; those without a vector are ignored.

        Returns:
            How many vectors were deleted.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
        """
        ...

    async def nearest(
        self,
        space_id: EmbeddingSpaceId,
        manifest_id: str,
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[VectorHit]:
        """Return the manifest's chunks nearest to ``query``, nearest first, ties by chunk ID.

        Version is a hard filter: only chunks of this manifest are looked at, whatever else the
        space holds. ``tag_filter`` is applied before ranking. Chunks without a vector are left
        out; an unknown manifest gives no hits.

        Args:
            space_id: The space; ``query`` must come from its model.
            manifest_id: The version's manifest.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits to return at most.

        Returns:
            At most ``limit`` hits with their distances.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
            VectorDimensionError: ``query`` does not have the space's dimensions.
            InvalidVectorError: ``query`` is all zeros or holds a value that is not finite.
            VectorStoreUnavailableError: The store cannot search here (``available`` is False).
        """
        ...

    async def coverage(self, space_id: EmbeddingSpaceId, manifest_id: str) -> VectorCoverage:
        """Count the manifest's chunks and those with a vector in the space.

        Args:
            space_id: The space.
            manifest_id: The version's manifest; an unknown one has no chunks.

        Returns:
            The counts.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
        """
        ...

    async def missing(
        self, space_id: EmbeddingSpaceId, manifest_id: str, limit: int
    ) -> Sequence[ChunkKey]:
        """Return chunks of the manifest that have no vector in the space yet, in a stable order.

        Args:
            space_id: The space.
            manifest_id: The version's manifest.
            limit: How many keys to return at most (a batch to embed).

        Returns:
            At most ``limit`` keys, each once; empty when the coverage is complete.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: The space was retired.
        """
        ...
