from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    ExcerptIndex,
    IndexedVersions,
    SearchIndex,
)
from exactdocs.retrieval.ports.driving import (
    CollectChunks,
    DiscardPendingChunks,
    GetChunk,
    IndexManifest,
    SearchDocs,
)
from exactdocs.retrieval.use_cases import (
    CollectChunksUseCase,
    DiscardPendingChunksUseCase,
    GetChunkUseCase,
    IndexManifestUseCase,
    SearchDocsUseCase,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModule:
    """Retrieval's driving ports, ready to be exposed by driving adapters."""

    search_docs: SearchDocs
    index_manifest: IndexManifest
    get_chunk: GetChunk
    discard_pending_chunks: DiscardPendingChunks
    collect_chunks: CollectChunks

    @classmethod
    def build(
        cls,
        *,
        versions: IndexedVersions,
        index: ExcerptIndex,
        manifests: ActiveManifests,
        chunks: ChunkRepository,
        search: SearchIndex,
        clock: Clock | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters."""
        clock = clock or SystemClock()
        return cls(
            search_docs=SearchDocsUseCase(versions, index),
            index_manifest=IndexManifestUseCase(chunks, search, clock),
            get_chunk=GetChunkUseCase(versions, manifests, chunks),
            discard_pending_chunks=DiscardPendingChunksUseCase(manifests, chunks, clock),
            collect_chunks=CollectChunksUseCase(manifests, chunks, clock),
        )
