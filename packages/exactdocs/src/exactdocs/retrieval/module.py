from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self

from exactdocs.retrieval.constants import DEFAULT_EMBEDDING_BATCH, DEFAULT_QUERY_DOCS_TOKEN_BUDGET
from exactdocs.retrieval.models import (
    InstanceRoles,
    ProviderProfile,
    RerankLimits,
    RetrievalMode,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ArticleSuggestions,
    ArticleTitles,
    ChunkRepository,
    DefaultVersions,
    EmbeddingModels,
    Libraries,
    LibraryModes,
    ModelFactory,
    ModelRoles,
    Prices,
    ProviderProfiles,
    RenamedPaths,
    RetrievalPipeline,
    SearchableVersions,
    SearchIndex,
    SearchIndexMaintenance,
    SearchTracer,
    SecretBox,
    SpendLedger,
    VectorIndex,
)
from exactdocs.retrieval.ports.driving import (
    ArticleOutline,
    CheckProvider,
    CheckRoles,
    CollectChunks,
    DeleteProvider,
    DiscardPendingChunks,
    EmbedBatch,
    EstimateEmbedding,
    FinishEmbedding,
    ForgetLibrary,
    GetChunkSets,
    GetLibraryRetrieval,
    GetProvider,
    GetSearchIndexState,
    IndexManifest,
    ListProviders,
    ListRoles,
    ListUnembeddedVersions,
    OpenEmbeddingSpace,
    PlanEmbedding,
    QueryDocs,
    ReadChunk,
    RebuildSearchIndex,
    RemoveChunks,
    ResolveLibraryId,
    RetagArticles,
    SaveProvider,
    SearchAllLibraries,
    SearchDocs,
    SetLibraryRetrieval,
)
from exactdocs.retrieval.use_cases import (
    AiProviders,
    ArticleOutlineUseCase,
    Bm25Pipeline,
    CheckProviderUseCase,
    CheckRolesUseCase,
    CollectChunksUseCase,
    DeleteProviderUseCase,
    DiscardPendingChunksUseCase,
    EmbedBatchUseCase,
    EmbeddingRuns,
    EstimateEmbeddingUseCase,
    FinishEmbeddingUseCase,
    ForgetLibraryUseCase,
    GetChunkSetsUseCase,
    GetLibraryRetrievalUseCase,
    GetProviderUseCase,
    GetSearchIndexStateUseCase,
    IndexManifestUseCase,
    ListProvidersUseCase,
    ListRolesUseCase,
    ListUnembeddedVersionsUseCase,
    NoModelFactory,
    NoStoredProfiles,
    OpenEmbeddingSpaceUseCase,
    PlanEmbeddingUseCase,
    ProfileModelRoles,
    QueryDocsUseCase,
    ReadChunkUseCase,
    RebuildSearchIndexUseCase,
    RemoveChunksUseCase,
    Reranking,
    ResolveLibraryIdUseCase,
    RetagArticlesUseCase,
    RetrievalModes,
    SaveProviderUseCase,
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
    list_providers: ListProviders
    """Every AI provider profile, without secrets."""
    get_provider: GetProvider
    """One AI provider profile."""
    save_provider: SaveProvider
    """Creates or replaces a profile over the REST API, its key sealed."""
    delete_provider: DeleteProvider
    """Deletes a stored profile."""
    check_provider: CheckProvider
    """One minimal call per role that uses a profile."""
    check_roles: CheckRoles
    """One minimal call per instance role (``exactdocs ai check``)."""
    list_roles: ListRoles
    """The instance's roles."""
    open_embedding_space: OpenEmbeddingSpace
    """Finds the embedding space of a model, or creates one when the model changed."""
    plan_embedding: PlanEmbedding
    """Starts an ``embed`` job of one version: its space and how much is missing."""
    embed_batch: EmbedBatch
    """Embeds the next batch of a version's chunks (one durable step of the job)."""
    finish_embedding: FinishEmbedding
    """Switches spaces once the configured model's covers every version."""
    list_unembedded_versions: ListUnembeddedVersions
    """The versions to queue ``embed`` jobs for."""
    estimate_embedding: EstimateEmbedding
    """Chunks, tokens and US dollars of embedding what is not embedded yet."""

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
        configured_profiles: Sequence[ProviderProfile] = (),
        stored_profiles: ProviderProfiles | None = None,
        instance_roles: InstanceRoles | None = None,
        models: ModelFactory | None = None,
        secret_box: SecretBox | None = None,
        instance_mode: RetrievalMode | None = None,
        rerank_limits: RerankLimits | None = None,
        pipelines: Mapping[RetrievalMode, RetrievalPipeline] | None = None,
        renames: RenamedPaths | None = None,
        suggestions: ArticleSuggestions | None = None,
        clock: Clock | None = None,
        query_docs_token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
        tracer: SearchTracer | None = None,
        vectors: VectorIndex | None = None,
        embedding_models: EmbeddingModels | None = None,
        article_titles: ArticleTitles | None = None,
        spend: SpendLedger | None = None,
        prices: Prices | None = None,
        embedding_dimensions: int | None = None,
        embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``tracer`` observes every search and its stages; without it nothing is recorded.
        The AI configuration: ``configured_profiles`` (the environment's and the file's,
        read-only), ``stored_profiles`` (the REST API's; none without it), ``instance_roles``,
        ``models`` (builds callable models; nothing can be called without it) and
        ``secret_box`` (seals keys sent over the REST API; they are refused without it).
        ``rerank_limits`` is the instance's reranker top N and timeout (the defaults without it).
        ``roles`` replaces the role resolution over them (tests). ``pipelines`` adds retrieval
        modes beside ``bm25``, which is always there. A mode can run when it has a pipeline and
        its roles are configured, and, for the hybrid modes, when ``vectors`` (the vector store)
        can search. The embedding jobs: ``embedding_models`` wraps the embedder the factory
        builds (nothing is embedded without it), ``article_titles`` gives the titles embedded
        with each chunk, ``spend`` records the usage and ``prices`` prices it;
        ``embedding_dimensions`` and ``embedding_batch_size`` are the embedding role's settings.
        """
        clock = clock or SystemClock()
        tracer = tracer or UntracedSearches()
        providers = AiProviders(
            configured=tuple(configured_profiles),
            stored=stored_profiles or NoStoredProfiles(),
            roles=instance_roles or InstanceRoles(),
            library_modes=library_modes,
            factory=models or NoModelFactory(),
            box=secret_box,
        )
        runs = EmbeddingRuns(
            providers=providers,
            vectors=vectors,
            chunks=chunks,
            manifests=manifests,
            models=embedding_models,
            titles=article_titles,
            spend=spend,
            prices=prices,
            clock=clock,
            dimensions=embedding_dimensions,
            batch_size=embedding_batch_size,
        )
        modes = RetrievalModes(
            pipelines={RetrievalMode.BM25: Bm25Pipeline(search=search), **(pipelines or {})},
            roles=roles or ProfileModelRoles(providers=providers),
            library_modes=library_modes,
            instance_mode=instance_mode,
            vectors=vectors,
            reranking=Reranking(
                providers=providers, chunks=chunks, limits=rerank_limits or RerankLimits()
            ),
            embedded=runs,
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
            set_library_retrieval=SetLibraryRetrievalUseCase(
                libraries=libraries, modes=modes, providers=providers
            ),
            forget_library=ForgetLibraryUseCase(library_modes=library_modes),
            list_providers=ListProvidersUseCase(providers=providers),
            get_provider=GetProviderUseCase(providers=providers),
            save_provider=SaveProviderUseCase(providers=providers),
            delete_provider=DeleteProviderUseCase(providers=providers),
            check_provider=CheckProviderUseCase(providers=providers),
            check_roles=CheckRolesUseCase(providers=providers),
            list_roles=ListRolesUseCase(providers=providers),
            open_embedding_space=OpenEmbeddingSpaceUseCase(vectors=vectors, clock=clock),
            plan_embedding=PlanEmbeddingUseCase(runs=runs, versions=searchable),
            embed_batch=EmbedBatchUseCase(runs=runs),
            finish_embedding=FinishEmbeddingUseCase(runs=runs),
            list_unembedded_versions=ListUnembeddedVersionsUseCase(runs=runs),
            estimate_embedding=EstimateEmbeddingUseCase(runs=runs),
        )
