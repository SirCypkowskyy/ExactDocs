from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    Libraries,
    SearchableVersions,
    SearchIndex,
)
from exactdocs.retrieval.ports.driving import (
    CollectChunks,
    DiscardPendingChunks,
    GetChunkSets,
    IndexManifest,
    ReadChunk,
    RemoveChunks,
    ResolveLibraryId,
    SearchDocs,
)
from exactdocs.retrieval.use_cases import (
    CollectChunksUseCase,
    DiscardPendingChunksUseCase,
    GetChunkSetsUseCase,
    IndexManifestUseCase,
    ReadChunkUseCase,
    RemoveChunksUseCase,
    ResolveLibraryIdUseCase,
    SearchDocsUseCase,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModule:
    """Retrieval's driving ports, ready to be exposed by driving adapters."""

    search_docs: SearchDocs
    index_manifest: IndexManifest
    get_chunk_sets: GetChunkSets
    read_chunk: ReadChunk
    resolve_library_id: ResolveLibraryId
    discard_pending_chunks: DiscardPendingChunks
    collect_chunks: CollectChunks
    remove_chunks: RemoveChunks

    @classmethod
    def build(
        cls,
        *,
        searchable: SearchableVersions,
        libraries: Libraries,
        manifests: ActiveManifests,
        chunks: ChunkRepository,
        search: SearchIndex,
        clock: Clock | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters."""
        clock = clock or SystemClock()
        return cls(
            search_docs=SearchDocsUseCase(searchable, search, chunks),
            index_manifest=IndexManifestUseCase(chunks, search, clock),
            get_chunk_sets=GetChunkSetsUseCase(chunks),
            read_chunk=ReadChunkUseCase(searchable, manifests, chunks),
            resolve_library_id=ResolveLibraryIdUseCase(libraries, searchable, search, chunks),
            discard_pending_chunks=DiscardPendingChunksUseCase(manifests, chunks, clock),
            collect_chunks=CollectChunksUseCase(manifests, chunks, clock),
            remove_chunks=RemoveChunksUseCase(manifests, chunks),
        )
