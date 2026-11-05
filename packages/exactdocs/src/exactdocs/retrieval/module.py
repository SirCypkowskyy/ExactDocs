from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ChunkRepository,
    DefaultVersions,
    Libraries,
    RenamedPaths,
    SearchableVersions,
    SearchIndex,
    SearchIndexMaintenance,
)
from exactdocs.retrieval.ports.driving import (
    CollectChunks,
    DiscardPendingChunks,
    GetChunkSets,
    GetSearchIndexState,
    IndexManifest,
    QueryDocs,
    ReadChunk,
    RebuildSearchIndex,
    RemoveChunks,
    ResolveLibraryId,
    SearchAllLibraries,
    SearchDocs,
)
from exactdocs.retrieval.use_cases import (
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    CollectChunksUseCase,
    DiscardPendingChunksUseCase,
    GetChunkSetsUseCase,
    GetSearchIndexStateUseCase,
    IndexManifestUseCase,
    QueryDocsUseCase,
    ReadChunkUseCase,
    RebuildSearchIndexUseCase,
    RemoveChunksUseCase,
    ResolveLibraryIdUseCase,
    SearchAllLibrariesUseCase,
    SearchDocsUseCase,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModule:
    """Retrieval's driving ports, ready to be exposed by driving adapters."""

    search_docs: SearchDocs
    search_all_libraries: SearchAllLibraries
    index_manifest: IndexManifest
    get_chunk_sets: GetChunkSets
    read_chunk: ReadChunk
    resolve_library_id: ResolveLibraryId
    query_docs: QueryDocs
    discard_pending_chunks: DiscardPendingChunks
    collect_chunks: CollectChunks
    remove_chunks: RemoveChunks
    get_search_index_state: GetSearchIndexState
    rebuild_search_index: RebuildSearchIndex

    @classmethod
    def build(
        cls,
        *,
        searchable: SearchableVersions,
        libraries: Libraries,
        defaults: DefaultVersions,
        manifests: ActiveManifests,
        chunks: ChunkRepository,
        search: SearchIndex,
        maintenance: SearchIndexMaintenance,
        renames: RenamedPaths | None = None,
        clock: Clock | None = None,
        query_docs_token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    ) -> Self:
        """Assemble the use cases around the given driven adapters."""
        clock = clock or SystemClock()
        return cls(
            search_docs=SearchDocsUseCase(searchable, search, chunks),
            search_all_libraries=SearchAllLibrariesUseCase(defaults, searchable, search, chunks),
            index_manifest=IndexManifestUseCase(chunks, search, clock),
            get_chunk_sets=GetChunkSetsUseCase(chunks),
            read_chunk=ReadChunkUseCase(searchable, manifests, chunks, renames),
            resolve_library_id=ResolveLibraryIdUseCase(libraries, searchable, search, chunks),
            query_docs=QueryDocsUseCase(searchable, search, chunks, query_docs_token_budget),
            discard_pending_chunks=DiscardPendingChunksUseCase(manifests, chunks, clock),
            collect_chunks=CollectChunksUseCase(manifests, chunks, clock),
            remove_chunks=RemoveChunksUseCase(manifests, chunks),
            get_search_index_state=GetSearchIndexStateUseCase(maintenance),
            rebuild_search_index=RebuildSearchIndexUseCase(maintenance),
        )
