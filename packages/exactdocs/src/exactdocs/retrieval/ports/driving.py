"""Driving (primary) ports of retrieval."""

from typing import Protocol

from exactdocs.retrieval.dtos import (
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    DiscardPendingChunksCommand,
    GetChunkSetsQuery,
    IndexedManifestOut,
    IndexManifestCommand,
    ReadChunkQuery,
    RemovedChunks,
    SearchDocsQuery,
    SearchDocsResult,
)


class SearchDocs(Protocol):
    """Search within one library version (the default one without a ref).

    Raises ``VersionNotIndexedError`` for an unknown version; a known version without matches
    gives an empty ``results``. Never answers from another version.
    """

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
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
