from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.constants import DEFAULT_QUERY_DOCS_TOKEN_BUDGET
from exactdocs.retrieval.models import RetrievalMode
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ArticleSuggestions,
    ChunkRepository,
    DefaultVersions,
    Libraries,
    LibraryModes,
    ModelRoles,
    RenamedPaths,
    RetrievalPipeline,
    SearchableVersions,
    SearchIndex,
    SearchIndexMaintenance,
    SearchTracer,
)
from exactdocs.retrieval.ports.driving import (
    ArticleOutline,
    CollectChunks,
    DiscardPendingChunks,
    ForgetLibrary,
    GetChunkSets,
    GetLibraryRetrieval,
    GetSearchIndexState,
    IndexManifest,
    QueryDocs,
    ReadChunk,
    RebuildSearchIndex,
    RemoveChunks,
    ResolveLibraryId,
    RetagArticles,
    SearchAllLibraries,
    SearchDocs,
    SetLibraryRetrieval,
)
from exactdocs.retrieval.use_cases import (
    ArticleOutlineUseCase,
    Bm25Pipeline,
    CollectChunksUseCase,
    DiscardPendingChunksUseCase,
    ForgetLibraryUseCase,
    GetChunkSetsUseCase,
    GetLibraryRetrievalUseCase,
    GetSearchIndexStateUseCase,
    IndexManifestUseCase,
    NoModelRoles,
    QueryDocsUseCase,
    ReadChunkUseCase,
    RebuildSearchIndexUseCase,
    RemoveChunksUseCase,
    ResolveLibraryIdUseCase,
    RetagArticlesUseCase,
    RetrievalModes,
    SearchAllLibrariesUseCase,
    SearchDocsUseCase,
    SetLibraryRetrievalUseCase,
    UntracedSearches,
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
    article_outline: ArticleOutline
    """An article's heading tree with chunk IDs (MCP, REST, and the agentic mode)."""
    resolve_library_id: ResolveLibraryId
    query_docs: QueryDocs
    discard_pending_chunks: DiscardPendingChunks
    collect_chunks: CollectChunks
    remove_chunks: RemoveChunks
    retag_articles: RetagArticles
    get_search_index_state: GetSearchIndexState
    rebuild_search_index: RebuildSearchIndex
    get_library_retrieval: GetLibraryRetrieval
    """A library's retrieval mode and the one its searches use now."""
    set_library_retrieval: SetLibraryRetrieval
    """Sets or clears a library's retrieval mode."""
    forget_library: ForgetLibrary
    """Drops what retrieval keeps for a removed library."""

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
        library_modes: LibraryModes,
        roles: ModelRoles | None = None,
        instance_mode: RetrievalMode | None = None,
        pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
        renames: RenamedPaths | None = None,
        suggestions: ArticleSuggestions | None = None,
        clock: Clock | None = None,
        query_docs_token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
        tracer: SearchTracer | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``tracer`` observes every search and its stages; without it nothing is recorded.
        ``roles`` says which model roles are configured (none without it); ``pipelines`` adds
        retrieval modes beside ``bm25``, which is always there. A mode can run when it has a
        pipeline and its roles are configured.
        """
        clock = clock or SystemClock()
        tracer = tracer or UntracedSearches()
        modes = RetrievalModes(
            pipelines={RetrievalMode.BM25: Bm25Pipeline(search=search), **(pipelines or {})},
            roles=roles or NoModelRoles(),
            library_modes=library_modes,
            instance_mode=instance_mode,
        )
        return cls(
            search_docs=SearchDocsUseCase(
                versions=searchable, modes=modes, chunks=chunks, tracer=tracer
            ),
            search_all_libraries=SearchAllLibrariesUseCase(
                defaults=defaults, versions=searchable, search=search, chunks=chunks, tracer=tracer
            ),
            index_manifest=IndexManifestUseCase(chunks=chunks, search=search, clock=clock),
            get_chunk_sets=GetChunkSetsUseCase(chunks=chunks),
            read_chunk=ReadChunkUseCase(
                versions=searchable, manifests=manifests, chunks=chunks, renames=renames
            ),
            article_outline=ArticleOutlineUseCase(
                versions=searchable, chunks=chunks, suggestions=suggestions
            ),
            resolve_library_id=ResolveLibraryIdUseCase(
                libraries=libraries,
                versions=searchable,
                search=search,
                chunks=chunks,
                tracer=tracer,
            ),
            query_docs=QueryDocsUseCase(
                versions=searchable,
                modes=modes,
                chunks=chunks,
                token_budget=query_docs_token_budget,
                tracer=tracer,
            ),
            discard_pending_chunks=DiscardPendingChunksUseCase(
                manifests=manifests, chunks=chunks, clock=clock
            ),
            collect_chunks=CollectChunksUseCase(manifests=manifests, chunks=chunks, clock=clock),
            remove_chunks=RemoveChunksUseCase(manifests=manifests, chunks=chunks),
            retag_articles=RetagArticlesUseCase(chunks=chunks),
            get_search_index_state=GetSearchIndexStateUseCase(maintenance=maintenance),
            rebuild_search_index=RebuildSearchIndexUseCase(maintenance=maintenance),
            get_library_retrieval=GetLibraryRetrievalUseCase(libraries=libraries, modes=modes),
            set_library_retrieval=SetLibraryRetrievalUseCase(libraries=libraries, modes=modes),
            forget_library=ForgetLibraryUseCase(library_modes=library_modes),
        )
