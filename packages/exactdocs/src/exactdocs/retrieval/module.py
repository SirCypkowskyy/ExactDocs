from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Self

from exactdocs.retrieval.constants import (
    DEFAULT_AGENT_CACHE_TTL_DAYS,
    DEFAULT_EMBEDDING_BATCH,
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    HYDE_CACHE_TTL_DAYS,
    HYDE_TIMEOUT,
    QUERY_EMBEDDING_TIMEOUT,
)
from exactdocs.retrieval.models import (
    AgentBounds,
    Budgets,
    InstanceRoles,
    ModelPrice,
    ProviderProfile,
    RerankLimits,
    RerankWith,
    RetrievalMode,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    AgentAnswerCache,
    AgentReads,
    ArticleSuggestions,
    ArticleTitles,
    CallRates,
    CandidateJudge,
    ChunkRepository,
    DefaultVersions,
    EmbeddingModels,
    Explorer,
    HypotheticalAnswerCache,
    HypotheticalAnswers,
    InstructionFiles,
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
    VersionArticles,
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
    PruneHypotheses,
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
    AgentAnswerCaching,
    AgenticPipeline,
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
    NoAgentAnswerCache,
    NoHypothesisCache,
    NoModelFactory,
    NoSpendLedger,
    NoStoredProfiles,
    OpenEmbeddingSpaceUseCase,
    PlanEmbeddingUseCase,
    PriceBook,
    ProfileModelRoles,
    PruneHypothesesUseCase,
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
    UnrecordedAgentReads,
    UntracedSearches,
)
from exactdocs_kernel import Clock, SystemClock


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModule:
    """Retrieval's driving ports, ready to be exposed by driving adapters."""

    search_docs: SearchDocs
    """Searches one exact library version (``search_docs``)."""
    search_all_libraries: SearchAllLibraries
    """Searches the default version of every library (``search_all_docs``)."""
    index_manifest: IndexManifest
    """Stores the chunks of a manifest ingestion made."""
    get_chunk_sets: GetChunkSets
    """The stored chunk sets of blobs, so ingestion does not chunk them again."""
    read_chunk: ReadChunk
    """One chunk verbatim by its ID (``read_chunk``)."""
    article_outline: ArticleOutline
    """An article's heading tree with chunk IDs (MCP, REST, and the agentic mode)."""
    resolve_library_id: ResolveLibraryId
    """Libraries matching a name (``resolve-library-id``)."""
    query_docs: QueryDocs
    """Whole chunks of one version within a size budget (``query-docs``)."""
    discard_pending_chunks: DiscardPendingChunks
    """Deletes the chunk rows of manifests the catalog holds as pending."""
    collect_chunks: CollectChunks
    """Collects chunk rows of manifests the catalog no longer knows, and unused chunk sets."""
    remove_chunks: RemoveChunks
    """Deletes the chunk rows of manifests the catalog deleted."""
    retag_articles: RetagArticles
    """Copies articles' current tags onto their chunk rows."""
    get_search_index_state: GetSearchIndexState
    """The full-text index's format, and whether a rebuild would change it."""
    get_vector_store_state: GetVectorStoreState
    """Whether the vector store can search, once an embedding model is configured."""
    rebuild_search_index: RebuildSearchIndex
    """Rebuilds the full-text index in the current format."""
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
    prune_hypotheses: PruneHypotheses
    """Deletes HyDE's cached answers past their TTL or of models no longer configured."""

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
        rerank_with: RerankWith = RerankWith.CROSS_ENCODER,
        judge: CandidateJudge | None = None,
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
        explorer: Explorer | None = None,
        version_articles: VersionArticles | None = None,
        agent_bounds: AgentBounds | None = None,
        agent_reads: AgentReads | None = None,
        hypotheses: HypotheticalAnswers | None = None,
        hypothesis_cache: HypotheticalAnswerCache | None = None,
        hyde_timeout: float = HYDE_TIMEOUT,
        hyde_cache_key: bytes | None = None,
        hyde_cache_ttl: timedelta = timedelta(days=HYDE_CACHE_TTL_DAYS),
        agent_answer_cache: AgentAnswerCache | None = None,
        agent_cache_key: bytes | None = None,
        agent_cache_enabled: bool = False,
        agent_cache_threshold: float | None = None,
        agent_cache_scope: str = "library",
        agent_cache_ttl: timedelta = timedelta(days=DEFAULT_AGENT_CACHE_TTL_DAYS),
        instruction_files: InstructionFiles | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        A retrieval mode can run when it has a pipeline and its roles are configured, and, for
        the hybrid modes, when ``vectors`` (the vector store) can search. ``bm25`` is always
        there. Removing a manifest, or saving or forgetting a library's settings, forgets its
        cached agentic answers, whether the cache is on or off.

        Args:
            searchable: Resolves a library version to the manifest a search may run on.
            libraries: The catalog's libraries, for ``resolve-library-id``.
            defaults: Every library's default version, for searches across libraries.
            manifests: Which manifests the catalog holds as active or pending.
            chunks: Stores chunk sets and the chunk rows of each manifest.
            search: The full-text index.
            maintenance: Reads and rebuilds the full-text index's format.
            library_modes: Each library's retrieval mode and AI overrides.
            roles: Replaces the role resolution over the profiles and roles below (tests).
            configured_profiles: The provider profiles of the environment and the configuration
                file, read-only.
            stored_profiles: The provider profiles stored over the REST API; none without it.
            instance_roles: The instance's model roles.
            models: Builds callable models; nothing can be called without it.
            secret_box: Seals keys sent over the REST API; they are refused without it.
            instance_mode: The instance's retrieval mode; the best one configured without it.
            rerank_limits: The instance's reranker top N and timeouts; the defaults without it.
            rerank_with: What reranks libraries without their own choice when both are
                configured.
            judge: Rates candidates with the ``judge`` role; the LLM judge never reranks without
                it.
            pipelines: Retrieval modes beside ``bm25``; an entry replaces the built-in pipeline
                of its mode (tests).
            renames: Finds where a stale chunk's article went, for ``stale_chunk`` errors.
            suggestions: Finds close article paths, for an outline of a path that is missing.
            clock: The time; the system clock without it.
            query_docs_token_budget: Size budget of a ``query-docs`` answer, in estimated tokens.
            tracer: Observes every search and its stages; nothing is recorded without it.
            vectors: The vector store; no hybrid mode runs without it.
            embedding_models: Wraps the embedder the factory builds; nothing is embedded
                without it.
            article_titles: The titles embedded with each chunk.
            spend: Records the AI usage.
            prices: Prices the usage (the bundled price list).
            price_overrides: The operator's prices by ``<profile>:<model>``.
            budgets: The spend limits and the LLM search rate limit.
            call_rates: Counts LLM searches per caller; they are not rate limited without it.
            embedding_dimensions: The embedding role's vector size, if it sets one.
            embedding_batch_size: How many chunks one embedding call sends.
            query_embedding_timeout: Seconds ``hybrid`` waits for a query's embedding.
            explorer: The agent of ``agentic`` (``AgenticPipeline``); the mode cannot run
                without it.
            version_articles: Lists and reads a version's articles for the agent.
            agent_bounds: The agent's limits.
            agent_reads: Records each read of the agent (the runs' trace); none by default.
            hypotheses: HyDE's writer of hypothetical answers; ``hybrid_hyde`` cannot run
                without it.
            hypothesis_cache: Caches HyDE's answers.
            hyde_timeout: Seconds a search waits for HyDE's answer.
            hyde_cache_key: The HMAC key of HyDE's cached queries; nothing is cached without it.
            hyde_cache_ttl: How long a cached HyDE answer lives; the collection job prunes older
                ones and those of an ``llm`` model no longer configured.
            agent_answer_cache: Caches agentic answers (``AgentAnswerCaching``).
            agent_cache_key: The HMAC key of the cached questions; nothing is cached without it.
            agent_cache_enabled: Whether the agentic answer cache answers (it is opt-in).
            agent_cache_threshold: How similar a question must be to one answered before.
            agent_cache_scope: ``library`` (callers share answers) or ``caller``.
            agent_cache_ttl: How long a cached agentic answer lives; the nightly prune deletes
                older ones, and every answer while the cache is off.
            instruction_files: Reads a manifest's ``AGENTS.md`` / ``CLAUDE.md`` files for a
                library with repo guidance on (RET-08).

        Returns:
            The module, its driving ports wired.
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
        # The store is always wired, so its rows are forgotten and pruned even with the cache
        # off; only looking up and storing need it on and a key.
        answers: AgentAnswerCache = agent_answer_cache or NoAgentAnswerCache()
        caching = None
        if agent_answer_cache is not None and agent_cache_key is not None and agent_cache_enabled:
            caching = AgentAnswerCaching(
                cache=answers,
                key=agent_cache_key,
                clock=clock,
                runs=runs,
                threshold=agent_cache_threshold,
                audience=agent_cache_scope,
                timeout=query_embedding_timeout,
            )
        prune_hypotheses = PruneHypothesesUseCase(
            hypotheses=hypotheses_cached,
            providers=providers,
            clock=clock,
            ttl=hyde_cache_ttl,
            caching=caching,
            answers=answers,
            answers_ttl=agent_cache_ttl,
        )
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
        if explorer is not None:
            built[RetrievalMode.AGENTIC] = AgenticPipeline(
                providers=providers,
                chunks=chunks,
                search=search,
                spend=ai_spend,
                explorer=explorer,
                articles=version_articles,
                bounds=agent_bounds or AgentBounds(),
                tracer=tracer,
                instructions=instruction_files,
                reads=agent_reads or UnrecordedAgentReads(),
                cache=caching,
            )
        modes = RetrievalModes(
            pipelines={**built, **(pipelines or {})},
            roles=roles or ProfileModelRoles(providers=providers),
            library_modes=library_modes,
            instance_mode=instance_mode,
            vectors=vectors,
            reranking=Reranking(
                providers=providers,
                chunks=chunks,
                limits=rerank_limits or RerankLimits(),
                judge=judge,
                spend=ai_spend,
            ),
            rerank_with=rerank_with,
            embedded=runs,
            spend=ai_spend,
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
                manifests=manifests,
                chunks=chunks,
                clock=clock,
                hypotheses=hypotheses_cached,
                answers=answers,
            ),
            collect_chunks=CollectChunksUseCase(
                manifests=manifests,
                chunks=chunks,
                clock=clock,
                hypotheses=hypotheses_cached,
                answers=answers,
                prune=prune_hypotheses,
            ),
            prune_hypotheses=prune_hypotheses,
            remove_chunks=RemoveChunksUseCase(
                manifests=manifests, chunks=chunks, hypotheses=hypotheses_cached, answers=answers
            ),
            retag_articles=RetagArticlesUseCase(chunks=chunks),
            get_search_index_state=GetSearchIndexStateUseCase(maintenance=maintenance),
            get_vector_store_state=GetVectorStoreStateUseCase(modes=modes),
            rebuild_search_index=RebuildSearchIndexUseCase(maintenance=maintenance),
            get_library_retrieval=GetLibraryRetrievalUseCase(libraries=libraries, modes=modes),
            set_library_retrieval=SetLibraryRetrievalUseCase(
                libraries=libraries, modes=modes, providers=providers, answers=answers
            ),
            forget_library=ForgetLibraryUseCase(library_modes=library_modes, answers=answers),
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
