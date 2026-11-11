from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Self

from exactdocs.retrieval.constants import (
    DEFAULT_EMBEDDING_BATCH,
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    HYDE_CACHE_TTL_DAYS,
    HYDE_TIMEOUT,
    QUERY_EMBEDDING_TIMEOUT,
)
from exactdocs.retrieval.models import (
    Budgets,
    InstanceRoles,
    ModelPrice,
    ProviderProfile,
    RerankLimits,
    RetrievalMode,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ArticleSuggestions,
    ArticleTitles,
    CallRates,
    ChunkRepository,
    DefaultVersions,
    EmbeddingModels,
    HypotheticalAnswerCache,
    HypotheticalAnswers,
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
    GetAiUsage,
    GetChunkSets,
    GetEmbeddingProgress,
    GetLibraryRetrieval,
    GetProvider,
    GetSearchIndexState,
    GetVectorStoreState,
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
    AiSpend,
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
    GetAiUsageUseCase,
    GetChunkSetsUseCase,
    GetEmbeddingProgressUseCase,
    GetLibraryRetrievalUseCase,
    GetProviderUseCase,
    GetSearchIndexStateUseCase,
    GetVectorStoreStateUseCase,
    HybridPipeline,
    HydePipeline,
    IndexManifestUseCase,
    ListProvidersUseCase,
    ListRolesUseCase,
    ListUnembeddedVersionsUseCase,
    NoHypothesisCache,
    NoModelFactory,
    NoSpendLedger,
    NoStoredProfiles,
    OpenEmbeddingSpaceUseCase,
    PlanEmbeddingUseCase,
    PriceBook,
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
    get_vector_store_state: GetVectorStoreState
    """Whether the vector store can search, once an embedding model is configured."""
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
    get_embedding_progress: GetEmbeddingProgress
    """How far each embedding space has got (``GET /api/v1/ai/embedding``)."""
    get_ai_usage: GetAiUsage
    """Spend and budget left per scope (``GET /api/v1/ai/usage``)."""

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
        price_overrides: Mapping[str, ModelPrice] | None = None,
        budgets: Budgets | None = None,
        call_rates: CallRates | None = None,
        embedding_dimensions: int | None = None,
        embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH,
        query_embedding_timeout: float = QUERY_EMBEDDING_TIMEOUT,
        hypotheses: HypotheticalAnswers | None = None,
        hypothesis_cache: HypotheticalAnswerCache | None = None,
        hyde_timeout: float = HYDE_TIMEOUT,
        hyde_cache_key: bytes | None = None,
        hyde_cache_ttl: timedelta = timedelta(days=HYDE_CACHE_TTL_DAYS),
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
        With a vector store, ``hybrid`` runs ``HybridPipeline`` (BM25 and vectors fused), whose
        query embedding waits at most ``query_embedding_timeout`` seconds; a ``hybrid`` entry
        of ``pipelines`` replaces it (tests). With a vector store and ``hypotheses`` (the HyDE
        writer), ``hybrid_hyde`` runs ``HydePipeline``: the ``llm`` role's hypothetical answer,
        cached in ``hypothesis_cache`` under ``hyde_cache_key`` (the HMAC key of its queries;
        without one nothing is cached), searches the vector half, and a search waits at most
        ``hyde_timeout`` seconds for it. The collection job prunes the cache: answers older than
        ``hyde_cache_ttl``, and those of an ``llm`` model no longer configured.
        Cost: ``price_overrides`` are the operator's prices by ``<profile>:<model>``, ``budgets``
        the spend limits and the LLM search rate limit, ``call_rates`` counts LLM searches per
        caller (without it they are not rate limited).
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
        ai_spend = AiSpend(
            ledger=spend or NoSpendLedger(),
            budgets=budgets or Budgets(),
            rates=call_rates,
            prices=PriceBook(listed=prices, overrides=dict(price_overrides or {})),
            clock=clock,
            library_modes=library_modes,
        )
        runs = EmbeddingRuns(
            providers=providers,
            vectors=vectors,
            chunks=chunks,
            manifests=manifests,
            models=embedding_models,
            titles=article_titles,
            spend=ai_spend,
            prices=ai_spend.prices,
            clock=clock,
            dimensions=embedding_dimensions,
            batch_size=embedding_batch_size,
        )
        hypotheses_cached = hypothesis_cache or NoHypothesisCache()
        built: dict[RetrievalMode, RetrievalPipeline] = {
            RetrievalMode.BM25: Bm25Pipeline(search=search)
        }
        if vectors is not None:
            hybrid = HybridPipeline(
                search=search,
                vectors=vectors,
                chunks=chunks,
                runs=runs,
                tracer=tracer,
                timeout=query_embedding_timeout,
            )
            built[RetrievalMode.HYBRID] = hybrid
            if hypotheses is not None:
                built[RetrievalMode.HYBRID_HYDE] = HydePipeline(
                    hybrid=hybrid,
                    providers=providers,
                    writer=hypotheses,
                    cache=hypotheses_cached if hyde_cache_key is not None else NoHypothesisCache(),
                    cache_key=hyde_cache_key or b"",
                    spend=ai_spend,
                    tracer=tracer,
                    timeout=hyde_timeout,
                )
        modes = RetrievalModes(
            pipelines={**built, **(pipelines or {})},
            roles=roles or ProfileModelRoles(providers=providers),
            library_modes=library_modes,
            instance_mode=instance_mode,
            vectors=vectors,
            reranking=Reranking(
                providers=providers, chunks=chunks, limits=rerank_limits or RerankLimits()
            ),
            embedded=runs,
            spend=ai_spend,
            providers=providers,
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
                manifests=manifests, chunks=chunks, clock=clock, hypotheses=hypotheses_cached
            ),
            collect_chunks=CollectChunksUseCase(
                manifests=manifests,
                chunks=chunks,
                clock=clock,
                hypotheses=hypotheses_cached,
                hyde_ttl=hyde_cache_ttl,
                providers=providers,
            ),
            remove_chunks=RemoveChunksUseCase(
                manifests=manifests, chunks=chunks, hypotheses=hypotheses_cached
            ),
            retag_articles=RetagArticlesUseCase(chunks=chunks),
            get_search_index_state=GetSearchIndexStateUseCase(maintenance=maintenance),
            get_vector_store_state=GetVectorStoreStateUseCase(modes=modes),
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
            get_embedding_progress=GetEmbeddingProgressUseCase(runs=runs),
            get_ai_usage=GetAiUsageUseCase(spend=ai_spend),
        )
