"""Driving (primary) ports of retrieval."""

from typing import Protocol

from exactdocs.retrieval.dtos import (
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    GetChunkSetsQuery,
    GetLibraryRetrievalQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    LibraryRetrievalOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    RebuiltIndexOut,
    RemoveChunksCommand,
    RemovedChunks,
    ResolveLibraryIdQuery,
    ResolveLibraryIdResult,
    RetagArticlesCommand,
    RetaggedChunks,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SearchIndexStateOut,
    SetLibraryRetrievalCommand,
)


class SearchDocs(Protocol):
    """Search within one library version (the default one without a ref).

    Raises ``VersionNotIndexedError`` for an unknown version; a known version without matches
    gives an empty ``results``. Never answers from another version.
    """

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Run the use case."""
        ...


class SearchAllLibraries(Protocol):
    """Search the default version of every library at once (or of one, with ``library``).

    Each result names its library and version; ``libraries`` counts the matches per library
    over all of them, also when ``library`` narrows the results. A version other than a
    library's default never answers. Raises ``VersionNotIndexedError`` for a ``library`` that
    has no readable default version.
    """

    async def __call__(self, query: SearchAllQuery) -> SearchAllResult:
        """Run the use case."""
        ...


class IndexManifest(Protocol):
    """Store the chunks of a catalog manifest, invisible until the catalog activates it.

    Idempotent: a manifest ID that is already indexed changes nothing and returns the same IDs.
    Raises ``DuplicateChunkError`` when two chunks of an article would share an ID.
    """

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Run the use case."""
        ...


class GetChunkSets(Protocol):
    """Return the stored chunks of blobs chunked under one config; unknown blobs are left out.

    This is how an importer skips chunking a blob that an earlier import already chunked.
    """

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Run the use case."""
        ...


class ReadChunk(Protocol):
    """Read one chunk verbatim by its ID; the ID names its version, so nothing else is needed.

    Only the version's active manifest is served. Raises ``StaleChunkError`` for an ID of a
    superseded manifest of a version that still exists, and ``ChunkNotFoundError`` for an ID
    nobody serves (unknown, still pending, or collected).
    """

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Run the use case."""
        ...


class DiscardPendingChunks(Protocol):
    """Delete the chunk rows of manifests that never became active (never "all")."""

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Run the use case."""
        ...


class CollectChunks(Protocol):
    """Delete chunk rows of manifests the catalog collected, then unused chunk sets."""

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run the use case."""
        ...


class RemoveChunks(Protocol):
    """Delete the chunk rows and unused chunk sets of manifests the catalog no longer knows.

    A manifest the catalog still knows (in any state) is kept, whatever the caller says. Unlike
    ``CollectChunks`` it needs no grace period: the caller names IDs the catalog just deleted.
    """

    async def __call__(self, command: RemoveChunksCommand) -> RemovedChunks:
        """Run the use case."""
        ...


class ResolveLibraryId(Protocol):
    """Find libraries by name, like context7's ``resolve-library-id``.

    Matches the name against library IDs, titles and descriptions in memory, then ranks the best
    candidates by how many chunks of their default version match ``query``. Never searches a
    version other than the default one.
    """

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Run the use case."""
        ...


class QueryDocs(Protocol):
    """Return documentation for a context7-style library ID, within a size budget.

    `/owner/repo` is the default version, `/owner/repo/<ref>` exactly that ref; raises
    ``VersionNotIndexedError`` for a version that is not imported and never answers from another.
    Only whole chunks are returned, best first, within the configured budget; one too large to fit
    is listed as a pointer for ``read_chunk``. ``language`` only reorders the best matches (chunks
    with code in it first); it never filters, and a chunk ranked beyond the candidates is not seen.
    """

    async def __call__(self, query: QueryDocsQuery) -> QueryDocsResult:
        """Run the use case."""
        ...


class RetagArticles(Protocol):
    """Copy an article's current tags onto its chunk rows in one manifest (no re-chunking).

    Tags change outside an import (a user tags an article by hand); the chunk rows hold a copy
    so a search can filter by tag. Unknown manifests and paths change nothing.
    """

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Run the use case."""
        ...


class GetSearchIndexState(Protocol):
    """Say which format the search index is in and whether ``RebuildSearchIndex`` is needed."""

    async def __call__(self) -> SearchIndexStateOut:
        """Run the use case."""
        ...


class RebuildSearchIndex(Protocol):
    """Rebuild the search index from the stored chunks while the old one keeps answering.

    No import runs again: the chunks are already stored. Needed after a release whose notes say
    "requires reindex"; harmless otherwise.
    """

    async def __call__(self) -> RebuiltIndexOut:
        """Run the use case."""
        ...


class GetLibraryRetrieval(Protocol):
    """Read a library's retrieval mode and the mode its searches use now.

    Raises ``UnknownLibraryError`` when there is no such library.
    """

    async def __call__(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        """Run the use case.

        Args:
            query: The library.

        Returns:
            Its setting, the mode its searches use now, and the modes available.
        """
        ...


class SetLibraryRetrieval(Protocol):
    """Set or clear a library's retrieval mode; it must be a mode that can run now.

    Raises ``UnknownLibraryError`` when there is no such library, ``UnavailableModeError`` when
    the mode is unknown or a model role it needs is not configured.
    """

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Run the use case.

        Args:
            command: The library and its mode (none: clear it).

        Returns:
            The stored setting, the mode its searches use now, and the modes available.
        """
        ...
