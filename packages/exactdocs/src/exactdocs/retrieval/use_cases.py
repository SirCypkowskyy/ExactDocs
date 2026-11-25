import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext, suppress
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import NoReturn

from exactdocs.retrieval.constants import (
    AGENT_CHUNK_CHARS,
    AGENT_LIST_LIMIT,
    AGENT_READ_CHARS,
    AGENT_SEARCH_LIMIT,
    AGENT_STAGE,
    AGENT_STEP_ARGUMENT_CHARS,
    AGENTIC_ANSWER_CACHE,
    ANSWER_STAGE,
    BM25_SIMILARITY,
    CHARS_PER_TOKEN,
    DEFAULT_AGENT_CACHE_THRESHOLD,
    DEFAULT_AGENT_CACHE_TTL_DAYS,
    DEFAULT_BM25_CACHE_THRESHOLD,
    DEFAULT_EMBEDDING_BATCH,
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    EXTERNAL_HIT_MARGIN,
    EXTERNAL_PAGE,
    EXTERNAL_WRITE_ATTEMPTS,
    EXTERNAL_WRITE_RETRY_SECONDS,
    FOOTER_CHARS,
    FREE_PROFILE_KINDS,
    HYDE_ANSWER_CACHE,
    HYDE_CACHE_TTL_DAYS,
    HYDE_TIMEOUT,
    MAX_ANSWER_CHARS,
    MAX_ANSWER_LIBRARIES,
    MAX_EXPLORED_STEPS,
    MAX_JUSTIFICATION_CHARS,
    MAX_QUOTE_CHARS,
    MAX_RESOLVED,
    MAX_SEARCHED_LIBRARIES,
    NO_VECTOR_STORE,
    PATH_PREFIX_POOL,
    POINTER_TEXT,
    QUERY_DOCS,
    QUERY_DOCS_CANDIDATES,
    QUERY_EMBEDDING_TIMEOUT,
    QUERY_HITS_CAP,
    READ_BEFORE_STOP,
    RRF_DEPTH,
    RULE_FRAMING_CHARS,
    RULES_FRAMING_CHARS,
    RULES_SHARE,
    SEARCH_ALL,
    SEARCH_DOCS,
    SECTION_FRAMING_CHARS,
    SPEND_INSTANCE_ID,
    SPEND_SCOPE_EMBEDDING,
    SPEND_SCOPE_INSTANCE,
    SPEND_SCOPE_LIBRARY,
    SPEND_SCOPE_USER,
    TOKENS_PER_MILLION,
    UNKNOWN_MANIFEST_GRACE,
)
from exactdocs.retrieval.dtos import (
    AiUsageOut,
    AnswerAvailabilityOut,
    AnswerLibraryOut,
    AnswerQuery,
    AnswerResult,
    AnswerSourceOut,
    AnswerUsageOut,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    BudgetOut,
    CheckProviderCommand,
    ChunkHeadingOut,
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
    CountVersionChunksQuery,
    CoverageOut,
    DiscardPendingChunksCommand,
    DocSectionOut,
    EmbedBatchCommand,
    EmbeddedBatchOut,
    EmbeddingEstimateOut,
    EmbeddingPlanOut,
    EmbeddingProgressOut,
    EmbeddingSpaceOut,
    EmbeddingSpaceProgressOut,
    EmbedVersionCommand,
    ExternalIndexScope,
    FinishedEmbeddingOut,
    FinishEmbeddingCommand,
    ForgetLibraryCommand,
    GetChunkSetsQuery,
    GetLibraryRetrievalQuery,
    IndexDriftOut,
    IndexedManifestOut,
    IndexManifestCommand,
    LibraryBudgets,
    LibraryFacetOut,
    LibraryMatchOut,
    LibraryRetrievalOut,
    LibrarySearchResultOut,
    ModelCheckOut,
    ModelChecksOut,
    OpenEmbeddingSpaceCommand,
    ProviderListOut,
    ProviderNameQuery,
    ProviderOut,
    PrunedHypothesesOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    RebuiltIndexOut,
    RebuiltVersionsOut,
    RemoveChunksCommand,
    RemovedChunks,
    ResolvedLibraryOut,
    ResolveLibraryIdQuery,
    ResolveLibraryIdResult,
    ResolveLibraryNameQuery,
    RetagArticlesCommand,
    RetaggedChunks,
    RoleListOut,
    RoleOut,
    SaveProviderCommand,
    ScopeUsageOut,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
    SearchIndexStateOut,
    SearchResultOut,
    SetChunkOut,
    SetLibraryRetrievalCommand,
    SetRoleThinkingCommand,
    SpendHistoryEntryOut,
    SpendHistoryOut,
    SpendHistoryQuery,
    SpentOut,
    UnembeddedVersionsOut,
    UnembeddedVersionsQuery,
    VectorStoreStateOut,
    VersionChunkCounts,
    VersionChunksOut,
    VersionRefOut,
)
from exactdocs.retrieval.errors import (
    AgentCacheError,
    AgentStoppedError,
    AiBudgetReachedError,
    ArticleNotFoundError,
    ChunkNotFoundError,
    EmbeddingFailedError,
    HypothesisCacheError,
    IndexBackendUnavailableError,
    InvalidJudgmentError,
    InvalidProviderError,
    InvalidVectorError,
    LibraryAccessDeniedError,
    LlmBudgetReachedError,
    LlmFailedError,
    MovedSection,
    NothingToCheckError,
    ProviderExistsError,
    ProviderInUseError,
    ProviderReadOnlyError,
    ProviderUnsupportedError,
    RerankerError,
    RetiredEmbeddingSpaceError,
    RoleConfiguredError,
    RoleTakesNoThinkingError,
    SecretKeyRequiredError,
    StaleChunkError,
    ThinkingUnsupportedError,
    UnavailableModeError,
    UnknownEmbeddingSpaceError,
    UnknownIndexVersionError,
    UnknownLibraryError,
    UnknownProviderError,
    VectorDimensionError,
    VectorStoreUnavailableError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    Access,
    AgentBounds,
    AgentCacheLookup,
    AgentCacheScope,
    AgentPick,
    AgentRead,
    AgentRun,
    AiCaller,
    AnswerCitation,
    AnswerDraft,
    AnswerUsage,
    ArticleEntry,
    ArticleText,
    BudgetLimit,
    Budgets,
    CachedAgentAnswer,
    CachedPick,
    CachedQuestion,
    Candidate,
    CatalogLibrary,
    Chunk,
    ChunkHeading,
    ChunkId,
    ChunkKey,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    DriftKind,
    EmbeddedTexts,
    EmbeddingSkip,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    EmbeddingTarget,
    FallbackReason,
    GuidanceFiles,
    HeldVersion,
    HydeKey,
    IndexDrift,
    IndexedManifest,
    IndexKind,
    InstanceRoles,
    JudgedCandidate,
    KeySource,
    LibraryAi,
    LlmStep,
    ManifestChunk,
    ManifestHit,
    ManifestPaths,
    ManifestStatus,
    ModeChoice,
    ModelCheck,
    ModelPrice,
    ModelRef,
    ModelRole,
    ModeRegistry,
    NameMatch,
    NativeRanking,
    Outline,
    PendingChunks,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    ReachedBudget,
    RebuiltIndex,
    RebuiltVersions,
    RepoGuidance,
    RerankLimits,
    RerankWith,
    ResultGrouping,
    RetrievalMode,
    RoleBinding,
    SearchableVersion,
    SearchEngine,
    SearchHit,
    SearchIndexState,
    SearchText,
    SectionRef,
    SpaceState,
    SpendEntry,
    SpendHistorySpan,
    SpendKey,
    SpendWindow,
    StoredChunk,
    TagFilter,
    TagMatch,
    TextQuery,
    ThinkingLevel,
    VectorCoverage,
    VectorHit,
    VersionDrift,
    article_chunk_rows,
    article_groups,
    as_float32,
    bind_role,
    caller_audience,
    checked_vector,
    current_space,
    embedding_spend,
    embedding_text,
    estimated_usd,
    fuse_across_manifests,
    index_entry,
    judge_window,
    judged_scores,
    language_first,
    leading_hit,
    model_markdown,
    model_text,
    name_match,
    named_library,
    outline,
    pick_reranker,
    rank_matches,
    reciprocal_rank_fusion,
    reorder,
    search_terms,
    source_link,
    spend_entries,
)
from exactdocs.retrieval.ports.driven import (
    AccessPolicy,
    ActiveManifests,
    AgentAnswerCache,
    AgentReads,
    Answerer,
    AnswerProgress,
    ArticleSuggestions,
    ArticleTitles,
    CallRates,
    CandidateJudge,
    ChunkRepository,
    DefaultVersions,
    EmbeddingModels,
    Embeddings,
    Explorer,
    HypotheticalAnswerCache,
    HypotheticalAnswers,
    IndexBackend,
    InstructionFiles,
    Libraries,
    LibraryModes,
    ModelFactory,
    ModelRoles,
    NativeHybrid,
    NativeRerank,
    Prices,
    ProviderProfiles,
    RenamedPaths,
    Reranker,
    RetrievalPipeline,
    RoleThinkingLevels,
    SearchableVersions,
    SearchBackend,
    SearchIndex,
    SearchIndexMaintenance,
    SearchSpan,
    SearchTracer,
    SecretBox,
    SpendLedger,
    StoredVectors,
    VectorBackend,
    VectorIndex,
    VersionArticles,
    VersionRefs,
)
from exactdocs_kernel import NOTICE, Clock, SystemClock, inside, leading_v_twin

logger = logging.getLogger(__name__)


async def _confirmed_removals(
    manifests: ActiveManifests,
    candidates: Sequence[IndexedManifest],
    *,
    now: datetime,
    pending_too: bool,
) -> list[str]:
    """Pick the manifests safe to remove, asking the catalog twice.

    Removable: pending in the catalog (when ``pending_too``), or unknown to it and older than
    the grace period. Everything else stays, including a status we cannot name. The second
    question comes right before the delete and narrows the window in which a manifest could
    be activated; it cannot close it, as that would take a transaction across both domains.

    Args:
        manifests: What the catalog says about manifests.
        candidates: The indexed manifests that matched the caller's filters.
        now: The current time, for the grace period.
        pending_too: Whether manifests the catalog holds as pending may go too.

    Returns:
        The IDs of the manifests to remove.
    """
    unknown_before = now - UNKNOWN_MANIFEST_GRACE
    survivors = list(candidates)
    for _ in range(2):
        statuses = await manifests.statuses([m.manifest_id for m in survivors])
        survivors = [
            m
            for m in survivors
            if ((status := statuses.get(m.manifest_id)) is None and m.indexed_at < unknown_before)
            or (pending_too and status is ManifestStatus.PENDING)
        ]
        if not survivors:
            break
    return [m.manifest_id for m in survivors]


async def _require(access: AccessPolicy, library: str, needed: Access) -> None:
    """Refuse unless the caller holds the role ``needed`` on the library.

    Args:
        access: Library roles.
        library: The library ID, any case.
        needed: The role the action needs.

    Raises:
        UnknownLibraryError: The library is hidden from this caller.
        LibraryAccessDeniedError: The caller's role on the library is lower.
    """
    if not await access.allows(library, Access.READ):
        raise UnknownLibraryError(library)
    if needed is not Access.READ and not await access.allows(library, needed):
        raise LibraryAccessDeniedError(library, needed.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class _UntracedSpan:
    """Implements ``ports.driven.SearchSpan`` by recording nothing."""

    def answered_by(self, mode: str) -> None:
        """Record nothing.

        Args:
            mode: The mode that answered.
        """
        del mode


@dataclass(frozen=True, slots=True, kw_only=True)
class UnrecordedAgentReads:
    """Implements ``ports.driven.AgentReads`` by recording nothing (no trace is kept)."""

    def record(self, read: AgentRead) -> None:
        """Record nothing.

        Args:
            read: The read.
        """
        del read


@dataclass(frozen=True, slots=True, kw_only=True)
class UntracedSearches:
    """Implements ``ports.driven.SearchTracer`` by recording nothing (telemetry is off)."""

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[SearchSpan]:
        """Open nothing.

        Args:
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode the search runs in.
            query: The query text.
            attributes: Further labels.

        Returns:
            A context manager that does nothing.
        """
        del name, mode, query, attributes
        return nullcontext(_UntracedSpan())

    def fallback(self, *, mode: str, reason: str) -> None:
        """Count nothing.

        Args:
            mode: The mode that answered.
            reason: Why it did.
        """
        del mode, reason

    def cache_hit(self, *, cache: str, mode: str) -> None:
        """Count nothing.

        Args:
            cache: Which cache.
            mode: The mode that answered.
        """
        del cache, mode


@dataclass(frozen=True, slots=True, kw_only=True)
class NoModelRoles:
    """Implements ``ports.driven.ModelRoles`` for an instance with no model configured."""

    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        """Say that no role is set, for any library.

        Args:
            library: The library searched.
            ai: The library's overrides being checked.

        Returns:
            The empty set: BM25 is the only mode.
        """
        del library, ai
        return frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class Bm25Pipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``bm25``: the full-text index alone."""

    search: SearchIndex
    """The full-text index."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Rank the version's chunks with BM25.

        Args:
            request: What to search; reranking happens after it (``RetrievalModes.rerank``).

        Returns:
            The best hits, and whether more matched than the limit allowed.
        """
        # One more than asked for tells whether the answer was cut short.
        found = await self.search.search(
            request.version.manifest_id, request.query, request.tag_filter, request.limit + 1
        )
        return PipelineAnswer(
            mode=RetrievalMode.BM25,
            hits=tuple(found[: request.limit]),
            candidates=len(found),
            reranked=0,
            complete=len(found) <= request.limit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class NoSpendLedger:
    """Implements ``ports.driven.SpendLedger`` for a build that records nothing (tests)."""

    async def add(self, entries: Sequence[SpendEntry]) -> None:
        """Record nothing.

        Args:
            entries: The usage.
        """
        del entries

    async def get(self, keys: Sequence[SpendKey]) -> dict[SpendKey, SpendEntry]:
        """Read nothing.

        Args:
            keys: The rows.

        Returns:
            No rows: nothing was spent.
        """
        del keys
        return {}

    async def since(self, first: date) -> list[SpendEntry]:
        """Read nothing.

        Args:
            first: The earliest window start.

        Returns:
            No rows.
        """
        del first
        return []


@dataclass(frozen=True, slots=True, kw_only=True)
class NoHypothesisCache:
    """Implements ``ports.driven.HypotheticalAnswerCache`` for a build that keeps none."""

    async def get(self, key: HydeKey) -> str | None:
        """Find nothing.

        Args:
            key: The key.

        Returns:
            ``None``.
        """
        del key
        return None

    async def put(self, key: HydeKey, answer: str, at: datetime) -> None:
        """Keep nothing.

        Args:
            key: The key.
            answer: The answer.
            at: When it was written.
        """
        del key, answer, at

    async def forget(self, manifest_ids: Collection[str]) -> int:
        """Delete nothing.

        Args:
            manifest_ids: The manifests.

        Returns:
            0.
        """
        del manifest_ids
        return 0

    async def prune(self, written_before: datetime, keep_models: Collection[str]) -> int:
        """Delete nothing.

        Args:
            written_before: The cutoff.
            keep_models: The models kept.

        Returns:
            0.
        """
        del written_before, keep_models
        return 0


@dataclass(frozen=True, slots=True, kw_only=True)
class NoAgentAnswerCache:
    """Implements ``ports.driven.AgentAnswerCache`` for a build that keeps none."""

    async def scoped(self, scope: AgentCacheScope) -> Sequence[CachedAgentAnswer]:
        """Find nothing.

        Args:
            scope: The scope.

        Returns:
            Nothing.
        """
        del scope
        return ()

    async def put(self, answer: CachedAgentAnswer) -> None:
        """Keep nothing.

        Args:
            answer: The answer.
        """
        del answer

    async def forget(self, manifest_ids: Collection[str]) -> int:
        """Delete nothing.

        Args:
            manifest_ids: The manifests.

        Returns:
            0.
        """
        del manifest_ids
        return 0

    async def forget_library(self, library: str) -> int:
        """Delete nothing.

        Args:
            library: The library.

        Returns:
            0.
        """
        del library
        return 0

    async def prune(
        self, written_before: datetime, keep_models: Collection[str], keep_similarity: str
    ) -> int:
        """Delete nothing.

        Args:
            written_before: The cutoff.
            keep_models: The models kept.
            keep_similarity: The space kept.

        Returns:
            0.
        """
        del written_before, keep_models, keep_similarity
        return 0


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceBook:
    """Prices models: the operator's price for a ``<profile>:<model>``, else the bundled list.

    In-process models (``local``) cost nothing; their tokens are still recorded, but count toward
    no token budget (``SpendEntry.local_tokens``). Never fetched over the network.
    """

    listed: Prices | None = None
    """The bundled price list; without it only overrides and free kinds are priced."""
    overrides: Mapping[str, ModelPrice] = field(default_factory=dict)
    """The operator's prices (``[ai.prices."<profile>:<model>"]``)."""

    def price(self, ref: ModelRef, profile_kind: str) -> ModelPrice | None:
        """Find a model's price.

        Args:
            ref: The model, ``<profile>:<model>``.
            profile_kind: Its profile's kind.

        Returns:
            The price, or ``None`` when nobody knows it.
        """
        if (override := self.overrides.get(str(ref))) is not None:
            return override
        if profile_kind in FREE_PROFILE_KINDS:
            return ModelPrice(input_usd_per_million=0.0)
        if self.listed is None:
            return None
        listed_input = self.listed.input_usd_per_million(profile_kind, ref.model)
        if listed_input is None:
            return None
        listed_output = self.listed.output_usd_per_million(profile_kind, ref.model)
        return ModelPrice(
            input_usd_per_million=listed_input, output_usd_per_million=listed_output or 0.0
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AiSpend:
    """Records what AI calls spend and enforces the budgets and the LLM search rate limit.

    One ledger for everything (docs/decisions/ai-retrieval.md, *Cost and budgets*): LLM agents
    write to it through the harness ``SpendLimits`` (its ``BatchSpendStore`` adapter), the
    embedding job and rerank calls through ``record``. Every check runs before the call or batch,
    so a burst can overshoot by the calls already in flight. A limit never fails a search: it
    skips the step, and the result says why.
    """

    ledger: SpendLedger
    """The ``retrieval_ai_spend`` rows."""
    budgets: Budgets = field(default_factory=Budgets)
    """The limits; none by default."""
    rates: CallRates | None = None
    """Counts LLM searches per caller; without it they are not rate limited."""
    prices: PriceBook = field(default_factory=PriceBook)
    """Prices what is recorded."""
    clock: Clock = field(default_factory=SystemClock)
    """Decides the UTC windows."""
    library_modes: LibraryModes | None = None
    """Each library's own budgets; without it only the instance's limits apply."""

    async def own_budgets(self, library: str) -> tuple[BudgetLimit, ...]:
        """Read a library's own budgets.

        Args:
            library: The library ID, any letter case.

        Returns:
            Its budgets; none without ``library_modes``.
        """
        if self.library_modes is None:
            return ()
        return (await self.library_modes.ai_of(library)).budgets

    async def all_own_budgets(self) -> Mapping[str, tuple[BudgetLimit, ...]]:
        """Read every library's own budgets at once.

        Returns:
            Each library's budgets that has some, by case-folded ID; none without
            ``library_modes``.
        """
        return {} if self.library_modes is None else await self.library_modes.budgets()

    async def limits_for(
        self, scopes: Sequence[tuple[str, str]], own: Sequence[BudgetLimit] | None = None
    ) -> Budgets:
        """Find the limits a call that counts to these scopes is checked against.

        Args:
            scopes: (kind, ID) of each scope a call would count to.
            own: The library's own budgets as already read; ``None`` reads them.

        Returns:
            The instance's limits, with the library's own applied where they are tighter.
        """
        if own is None:
            library = next((i for kind, i in scopes if kind == SPEND_SCOPE_LIBRARY), None)
            own = () if library is None else await self.own_budgets(library)
        return self.budgets.for_library(own)

    async def reached(
        self, scopes: Sequence[tuple[str, str]], own: Sequence[BudgetLimit] | None = None
    ) -> ReachedBudget | None:
        """Find a limit one of these scopes has used up now.

        Args:
            scopes: (kind, ID) of each scope a call would count to.
            own: The library's own budgets as already read; ``None`` reads them.

        Returns:
            The limit, or ``None`` when the call may be made.
        """
        now = self.clock.now()
        budgets = await self.limits_for(scopes, own)
        keys = budgets.keys(scopes, now)
        if not keys:
            return None
        return budgets.reached(scopes, await self.ledger.get(keys), now)

    def budgets_for(self, ai: LibraryAi) -> Budgets:
        """Give the budgets an LLM step of a library runs within (``agent_limits``).

        The tighter of the library's own limits and the instance's apply, so the harness check
        inside the agent (HyDE's writer, the agentic explorer) sees the same limits as
        ``llm_step`` before it.

        Args:
            ai: The library's overrides, as read for the search.

        Returns:
            The instance's limits, with the library's own applied where they are tighter.
        """
        return self.budgets.for_library(ai.budgets)

    async def llm_step(
        self, caller: AiCaller, own: Sequence[BudgetLimit] | None = None
    ) -> FallbackReason | None:
        """Decide whether a search may run its LLM step now (and count it if so).

        Args:
            caller: The library and the account searching.
            own: The library's own budgets as already read; ``None`` reads them.

        Returns:
            ``llm_budget_reached`` or ``llm_rate_limited`` when the step must be skipped, else
            ``None``. A search refused for its budget is not counted against the rate limit.
        """
        if await self.reached(caller.scopes(), own) is not None:
            return FallbackReason.LLM_BUDGET_REACHED
        limit = self.budgets.llm_searches_per_minute
        if (
            limit is not None
            and self.rates is not None
            and not await self.rates.allow(caller.rate_key, limit, self.clock.now())
        ):
            return FallbackReason.LLM_RATE_LIMITED
        return None

    async def paid_call(
        self, caller: AiCaller, own: Sequence[BudgetLimit] | None = None
    ) -> FallbackReason | None:
        """Decide whether a paid call that is not an LLM search (a rerank) may be made now.

        Args:
            caller: The library and the account searching.
            own: The library's own budgets as already read; ``None`` reads them.

        Returns:
            ``llm_budget_reached`` when a limit is used up, else ``None``.
        """
        if await self.reached(caller.scopes(), own) is not None:
            return FallbackReason.LLM_BUDGET_REACHED
        return None

    async def embedding_batch(self, library: str) -> None:
        """Refuse the next embedding batch of a library if a budget it counts to is used up.

        Args:
            library: The library being embedded.

        Raises:
            AiBudgetReachedError: The embedding, instance or library budget is used up; the job
                stops and is queued again when the window resets.
        """
        reached = await self.reached(AiCaller(library=library).embedding_scopes())
        if reached is not None:
            limit = reached.limit
            period = "daily" if limit.window is SpendWindow.DAY else "monthly"
            what = f"the {period} {limit.scope_kind} budget"
            raise AiBudgetReachedError(what, reached.resets_at)

    async def record(
        self,
        scopes: Sequence[tuple[str, str]],
        *,
        ref: ModelRef,
        profile_kind: str,
        input_tokens: int,
        output_tokens: int = 0,
        requests: int = 1,
    ) -> None:
        """Record a call that ran outside an agent (a rerank, a query embedding).

        A ``local`` model's tokens are recorded as ``local_tokens``: shown in the usage, never
        counted toward a token budget.

        Args:
            scopes: (kind, ID) of each scope it counts to.
            ref: The model called.
            profile_kind: Its profile's kind.
            input_tokens: Tokens the provider reported sending.
            output_tokens: Tokens it reported receiving.
            requests: Calls made.
        """
        await self.ledger.add(
            spend_entries(
                self.clock.now(),
                scopes,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                requests=requests,
                price=self.prices.price(ref, profile_kind),
                local=profile_kind in FREE_PROFILE_KINDS,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetAiUsageUseCase:
    """Implements ``ports.driving.GetAiUsage``."""

    spend: AiSpend
    """The ledger and the budgets."""

    async def __call__(self) -> AiUsageOut:
        """Read this month's rows and set each scope's budgets against them.

        Returns:
            The instance and the embedding budget, then every library and user, by ID.
        """
        now = self.spend.clock.now()
        month = SpendWindow.MONTH.start(now)
        today = SpendWindow.DAY.start(now)
        rows = {row.key: row for row in await self.spend.ledger.since(month)}
        own = await self.spend.all_own_budgets()  # every library's, in one read
        spenders = {(k.scope_kind, k.scope_id) for k in rows}
        spent_libraries = {i.casefold() for kind, i in spenders if kind == SPEND_SCOPE_LIBRARY}
        # A library with budgets of its own is listed even before it spends anything.
        spenders |= {(SPEND_SCOPE_LIBRARY, i) for i in own if i not in spent_libraries}
        scopes: dict[tuple[str, str], None] = {
            (SPEND_SCOPE_INSTANCE, SPEND_INSTANCE_ID): None,
            (SPEND_SCOPE_EMBEDDING, SPEND_INSTANCE_ID): None,
        }
        for scope in sorted(spenders):
            scopes.setdefault(scope, None)
        return AiUsageOut(
            at=now,
            llm_searches_per_minute=self.spend.budgets.llm_searches_per_minute,
            scopes=[
                self._scope(kind, scope_id, rows, today, month, now, own)
                for kind, scope_id in scopes
            ],
        )

    def _scope(
        self,
        kind: str,
        scope_id: str,
        rows: Mapping[SpendKey, SpendEntry],
        today: date,
        month: date,
        now: datetime,
        own: Mapping[str, tuple[BudgetLimit, ...]],
    ) -> ScopeUsageOut:
        """Show one scope.

        Args:
            kind: The scope kind.
            scope_id: The scope ID.
            rows: This month's rows.
            today: Today's window start.
            month: This month's window start.
            now: When the rows were read.
            own: Every library's own budgets, by case-folded library ID.

        Returns:
            Its spend today and this month, and its budgets (a library's own applied, and shown
            where the instance's lower limit applies instead).
        """

        def row(window: SpendWindow, start: date) -> SpendEntry:
            """Find a window's row.

            Args:
                window: Day or month.
                start: The window's first day.

            Returns:
                Its totals; zero when it has none.
            """
            key = SpendKey(scope_kind=kind, scope_id=scope_id, window=window, window_start=start)
            return rows.get(key) or SpendEntry.empty(key)

        spent = {
            SpendWindow.DAY: row(SpendWindow.DAY, today),
            SpendWindow.MONTH: row(SpendWindow.MONTH, month),
        }
        budgets = self.spend.budgets
        mine: tuple[BudgetLimit, ...] = ()
        if kind == SPEND_SCOPE_LIBRARY:
            mine = own.get(scope_id.casefold(), ())
            budgets = budgets.for_library(mine)
        return ScopeUsageOut(
            scope=kind,
            id=scope_id,
            day=SpentOut.from_model(spent[SpendWindow.DAY]),
            month=SpentOut.from_model(spent[SpendWindow.MONTH]),
            budgets=[
                BudgetOut.from_model(
                    limit,
                    spent[limit.window],
                    now,
                    next((m for m in mine if m.window is limit.window), None),
                )
                for limit in budgets.limits
                if limit.scope_kind == kind
            ],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSpendHistoryUseCase:
    """Implements ``ports.driving.GetSpendHistory``."""

    spend: AiSpend
    """The ledger, and the clock that says which day today is."""

    async def __call__(self, query: SpendHistoryQuery) -> SpendHistoryOut:
        """Read the scope's rows of the range in one read and fill the windows without one.

        Args:
            query: The scope, the window and the range.

        Returns:
            One entry per window, oldest first.
        """
        span = SpendHistorySpan.of(
            scope_kind=query.scope,
            scope_id=query.id,
            window=query.window,
            first=query.first,
            last=query.last,
            today=SpendWindow.DAY.start(self.spend.clock.now()),
        )
        keys = span.keys()
        rows = await self.spend.ledger.get(keys)
        return SpendHistoryOut(
            scope=query.scope,
            id=span.scope_id,
            window=span.window,
            first=span.first,
            last=span.last,
            entries=[
                SpendHistoryEntryOut.from_model(rows.get(key) or SpendEntry.empty(key))
                for key in keys
            ],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalModes:
    """Picks the mode of a search and runs its pipeline (RET-06, MCP-05).

    The mode is the call's, else the library's, else the instance's, else the best one that can
    run: a mode can run when a pipeline is registered for it and the model roles it needs are
    configured. Roles and library settings are read at every search, so changes count at once.
    """

    pipelines: Mapping[RetrievalMode, RetrievalPipeline]
    """The pipeline of each mode this build can run; BM25 always."""
    roles: ModelRoles
    """Which model roles are configured, asked at every search."""
    library_modes: LibraryModes
    """Each library's own mode."""
    instance_mode: RetrievalMode | None = None
    """The operator's default for every library (``EXACTDOCS_AI__MODE``)."""
    vectors: VectorIndex | None = None
    """The vector store the hybrid modes search; asked whether it can load only once an
    embedding model is configured. Without one, nothing is checked (pipelines decide)."""
    reranking: Reranking | None = None
    """Reorders the best candidates when a reranker is configured; none: nothing is reranked."""
    rerank_with: RerankWith = RerankWith.CROSS_ENCODER
    """What reranks the searches of libraries without their own choice, when a library has both
    a cross-encoder and a judge (``EXACTDOCS_AI__RERANK_WITH``); the judge reranks only when
    chosen (``pick_reranker``)."""

    def reranker_of(self, roles: Collection[ModelRole], ai: LibraryAi) -> RerankWith | None:
        """Say what reranks a library's searches now.

        Args:
            roles: The roles configured for the library now.
            ai: The library's overrides.

        Returns:
            The cross-encoder, the judge, or ``None`` when nothing reranks (no reranking here, or
            neither is configured).
        """
        if self.reranking is None:
            return None
        return pick_reranker(roles, ai.rerank_with or self.rerank_with)

    def rerank_top_n(self, ai: LibraryAi) -> int:
        """Say how many candidates a library's searches rerank.

        Args:
            ai: The library's overrides.

        Returns:
            Its own number, else the instance's.
        """
        limits = self.reranking.limits if self.reranking is not None else RerankLimits()
        return ai.rerank_top_n or limits.top_n

    embedded: EmbeddingRuns | None = None
    """Which versions the configured embedding model has embedded: a mode that searches vectors
    answers BM25 (``embedding_in_progress``) for a version its space does not cover yet."""
    spend: AiSpend | None = None
    """The budgets and the LLM search rate limit; without it no step is ever skipped for them."""

    async def registry(self, library: str, ai: LibraryAi | None = None) -> ModeRegistry:
        """Say which modes can run now for a library's searches.

        Args:
            library: The library, any letter case: roles can differ per library.
            ai: The library's overrides as they are about to be stored; ``None``: the stored.

        Returns:
            The registry of the library's configured roles, the registered pipelines and
            whether the vector store can search.
        """
        roles = await self.roles.configured(library, ai)
        vector_store = True
        if ModelRole.EMBEDDING in roles and self.vectors is not None:
            vector_store = await self.vectors.available()
        return ModeRegistry(
            roles=roles, pipelines=frozenset(self.pipelines), vector_store=vector_store
        )

    async def choose(self, *, asked: str | None, library: str) -> ModeChoice:
        """Pick the mode of a search of ``library``.

        Args:
            asked: The mode the call names, if any.
            library: The library searched, any letter case.

        Returns:
            The mode, whether to rerank and how many candidates, and why a setting was
            skipped. A call that names a mode that cannot run now fails with
            ``UnavailableModeError``.
        """
        ai = await self.library_modes.ai_of(library)  # read once per search
        registry = await self.registry(library, ai)
        if asked is not None:  # checked first: the library's setting does not matter then
            choice = registry.choose(asked=asked, library=None, instance=None)
        else:
            choice = registry.choose(
                asked=None,
                library=await self.library_modes.mode_of(library),
                instance=self.instance_mode,
            )
        reranker = self.reranker_of(registry.roles, ai)
        choice = replace(choice, library_ai=ai, rerank=reranker is not None, reranker=reranker)
        if reranker is None:
            return choice
        return replace(choice, rerank_top_n=self.rerank_top_n(ai))

    async def run(
        self,
        choice: ModeChoice,
        version: SearchableVersion,
        query: str,
        tag_filter: TagFilter,
        limit: int,
        *,
        search: str = SEARCH_DOCS,
    ) -> PipelineAnswer:
        """Run the chosen mode's pipeline on one version.

        With reranking, the pipeline is asked for the reranker's top N when that is more than
        ``limit``: the caller reranks them (``rerank``), then keeps ``limit`` (``cut``).

        Args:
            choice: The mode picked by ``choose``.
            version: The exact version searched.
            query: The query text.
            tag_filter: Which chunks may be returned.
            limit: How many hits the caller shows at most.
            search: The search it runs in, which names the spans of the pipeline's stages.

        Returns:
            The pipeline's answer; the choice's fallback reason unless the pipeline gave one
            (``within_budget`` sets ``llm_budget_reached`` or ``llm_rate_limited`` on it when a
            limit skipped the LLM step or the rerank). A mode that searches vectors
            answers BM25 with ``embedding_in_progress`` while the configured model has not
            embedded every chunk of the version (never two models' vectors in one search). An
            agentic run that stops (``AgentStoppedError``) is answered by the best mode without an
            LLM step, with the agent's reason (``agent_limit_reached``, ``agent_failed``...).
        """
        depth = choice.depth(limit)
        request = PipelineRequest(
            version=version,
            query=query,
            tag_filter=tag_filter,
            limit=depth,
            rerank=choice.rerank,
            search=search,
            caller=choice.caller,
            library_ai=choice.library_ai,
            hypothesis=choice.hypothesis,
            agent_cache=choice.agent_cache,
        )
        if choice.mode.needs_vectors and self.embedded is not None:
            found = await self.embedded.search_space(version.manifest_id)
            if not found.searchable:
                answer = await self.pipelines[RetrievalMode.BM25].run(request)
                return replace(answer, fallback_reason=FallbackReason.EMBEDDING_IN_PROGRESS)
            request = replace(request, space=found.space)
        try:
            answer = await self.pipelines[choice.mode].run(request)
        except AgentStoppedError as stopped:
            # The agent ended without an answer: the best mode without an LLM step answers, with
            # the agent's reason first (it is why the asked mode did not answer).
            reason = FallbackReason(stopped.reason)
            cheaper = await self.run(
                choice.without_llm(reason), version, query, tag_filter, limit, search=search
            )
            return replace(cheaper, fallback_reason=reason)
        if answer.fallback_reason is None and choice.fallback_reason is not None:
            return replace(answer, fallback_reason=choice.fallback_reason)
        return answer

    async def within_budget(
        self,
        choice: ModeChoice,
        *,
        library: str,
        caller: str | None,
        version: SearchableVersion | None = None,
        query: str | None = None,
        tag_filter: TagFilter | None = None,
        limit: int | None = None,
    ) -> ModeChoice:
        """Skip the LLM step or the paid rerank a budget or the rate limit does not allow now.

        Called by the search use cases once the version resolved (a search of an unknown
        library or ref uses up nothing), before every later stage (the pipeline, a rerank),
        which all see the same choice. A HyDE search whose hypothetical answer is cached makes no
        LLM call: it is neither refused by a budget nor counted against the rate limit. Nor is
        an agentic search the agentic answer cache answers: it is looked up first, once.

        Args:
            choice: The mode picked by ``choose``.
            library: The library searched, any letter case.
            caller: The account searching; ``None`` for a stdio MCP process.
            version: The version searched, to look for a cached hypothetical or agentic answer.
            query: The query text, likewise.
            tag_filter: The search's tag filter, part of a cached agentic answer's scope.
            limit: How many hits the caller shows at most (a cached agentic answer must hold
                as many).

        Returns:
            The choice, or the cheaper one without the LLM step, or the same without reranking,
            with the reason.
        """
        choice = replace(choice, caller=caller)
        lookup = await self._cached_agentic(choice, version, query, tag_filter, limit)
        if lookup is not None:
            choice = replace(choice, agent_cache=lookup)
        if self.spend is None:
            return choice
        who = AiCaller(library=library.casefold(), user=caller)
        own = None if choice.library_ai is None else choice.library_ai.budgets
        counted: FallbackReason | bool = False  # the LLM step's check: refused, passed, none
        if (hypothesis := await self._cached_hypothesis(choice, version, query)) is not None:
            choice = replace(choice, hypothesis=hypothesis)  # no LLM call: no limit applies
        elif lookup is not None and lookup.hit is not None:
            pass  # answered from the agentic answer cache: no LLM call, no limit applies
        elif choice.mode.needs_llm:
            if (reason := await self.spend.llm_step(who, own)) is not None:
                choice = choice.without_llm(reason)
                counted = reason
            else:
                counted = True
        if choice.rerank and choice.reranker is RerankWith.JUDGE:
            return await _judge_within_budget(self.spend, choice, who, own, counted=counted)
        if choice.rerank and (self.spend.budgets.limits or own):  # no limit: no need for its kind
            choice = await self._with_reranker_profile(choice, who.library)
            if (
                choice.rerank
                and _paid_rerank(choice)
                and (reason := await self.spend.paid_call(who, own)) is not None
            ):
                choice = replace(
                    choice, rerank=False, fallback_reason=choice.fallback_reason or reason
                )
        return choice

    async def _cached_agentic(
        self,
        choice: ModeChoice,
        version: SearchableVersion | None,
        query: str | None,
        tag_filter: TagFilter | None,
        limit: int | None,
    ) -> AgentCacheLookup | None:
        """Look an agentic search up in the agentic answer cache (no LLM call).

        Args:
            choice: The mode picked.
            version: The version searched, if known.
            query: The query text, if known.
            tag_filter: The search's tag filter, if known.
            limit: How many hits the caller shows, if known.

        Returns:
            The lookup of an ``agentic`` search with a cache (a hit or a miss to store), else
            ``None``.
        """
        if (
            choice.mode is not RetrievalMode.AGENTIC
            or version is None
            or query is None
            or tag_filter is None
            or limit is None
        ):
            return None
        agentic = self.pipelines.get(RetrievalMode.AGENTIC)
        if not isinstance(agentic, AgenticPipeline):
            return None
        return await agentic.cached_answer(
            version,
            query,
            tag_filter,
            choice.depth(limit),
            caller=choice.caller,
            ai=choice.library_ai,
        )

    async def _cached_hypothesis(
        self, choice: ModeChoice, version: SearchableVersion | None, query: str | None
    ) -> str | None:
        """Read a HyDE search's cached hypothetical answer, if it has one (no LLM call then).

        Args:
            choice: The mode picked.
            version: The version searched, if known.
            query: The query text, if known.

        Returns:
            The answer of a ``hybrid_hyde`` search whose answer is cached, else ``None``.
        """
        if choice.mode is not RetrievalMode.HYBRID_HYDE or version is None or query is None:
            return None
        hyde = self.pipelines.get(RetrievalMode.HYBRID_HYDE)
        return await hyde.cached_answer(version, query) if isinstance(hyde, HydePipeline) else None

    async def _with_reranker_profile(self, choice: ModeChoice, library: str) -> ModeChoice:
        """Read the cross-encoder's profile once for this search, unless it was read already.

        Args:
            choice: The choice; the judge has no cross-encoder profile to read.
            library: The library searched.

        Returns:
            The choice carrying the profile read, or the same without reranking and the reason
            when it cannot be read (``Reranking.profile``): a reranker problem never fails a
            search.
        """
        if (
            self.reranking is None
            or choice.reranker is RerankWith.JUDGE
            or choice.reranker_profile is not None
        ):
            return choice
        found = await self.reranking.profile(library, choice.library_ai)
        if isinstance(found, FallbackReason):
            return replace(choice, rerank=False, fallback_reason=choice.fallback_reason or found)
        return replace(choice, reranker_profile=found)

    async def rerank(
        self, choice: ModeChoice, version: SearchableVersion, query: str, answer: PipelineAnswer
    ) -> tuple[PipelineAnswer, Mapping[ChunkId, StoredChunk]]:
        """Reorder the best candidates of ``answer`` with the library's reranker, if it reranks.

        Args:
            choice: The mode picked by ``choose``: whether to rerank, and how many.
            version: The version searched (its library resolves the reranker).
            query: The query text.
            answer: What ``run`` found.

        Returns:
            The reranked answer; on a timeout or a failure, the answer in its own order with a
            fallback reason. Never raises for the reranker. Also the chunks it read, by ID.
        """
        if not choice.rerank or self.reranking is None or answer.reranked:
            return answer, {}  # nothing reranks, or the vector backend's own ranker did (#473)
        if choice.reranker is not RerankWith.JUDGE and choice.reranker_profile is None:
            found = await self.reranking.profile(version.library, choice.library_ai)
            if isinstance(found, FallbackReason):
                return _fallen_back(answer, found), {}
            choice = replace(choice, reranker_profile=found)  # its spend is recorded from it too
        reranked, read = await self.reranking.apply(version, query, answer, choice)
        # The judge's spend is recorded by the harness inside its agent; a cross-encoder's here.
        if reranked.reranked and choice.reranker is not RerankWith.JUDGE:
            await self._record_rerank(choice, version, query, reranked, read)
        return reranked, read

    async def _record_rerank(
        self,
        choice: ModeChoice,
        version: SearchableVersion,
        query: str,
        reranked: PipelineAnswer,
        read: Mapping[ChunkId, StoredChunk],
    ) -> None:
        """Record one rerank call in the spend ledger, for the caller's scopes.

        The rerank dialects report no token usage, so its tokens are estimated from what was
        sent (the query and each candidate's text) at ``CHARS_PER_TOKEN``, and priced with the
        price book (the operator's ``[ai.prices]``, zero for ``local``; unpriced otherwise). A
        failure to record is logged and never fails the search.

        Args:
            choice: The search's choice: its caller and the library's overrides.
            version: The version searched.
            query: The query text.
            reranked: The reranked answer; its first ``reranked`` hits were sent.
            read: The candidates' chunks, by ID.
        """
        if self.spend is None or choice.reranker_profile is None:
            return
        try:
            ref, profile = choice.reranker_profile  # as the search read it: no read of its own
            sent = len(query) + sum(
                len(read[h.chunk_id].chunk.content)
                for h in reranked.hits[: reranked.reranked]
                if h.chunk_id in read
            )
            await self.spend.record(
                AiCaller(library=version.library, user=choice.caller).scopes(),
                ref=ref,
                profile_kind=profile.kind.value,
                input_tokens=-(-sent // CHARS_PER_TOKEN),
            )
        except Exception:
            logger.exception("could not record the spend of a rerank of %s", version.library)


def _paid_rerank(choice: ModeChoice) -> bool:
    """Say whether the search's cross-encoder costs money (any but an in-process one).

    Args:
        choice: The choice, carrying the reranker's profile when it was read.

    Returns:
        False only for a reranker whose profile is ``local``; True when it was not read (there is
        no ``Reranking`` to read it).
    """
    found = choice.reranker_profile
    return found is None or found[1].kind.value not in FREE_PROFILE_KINDS


async def _judge_within_budget(
    spend: AiSpend,
    choice: ModeChoice,
    who: AiCaller,
    own: Sequence[BudgetLimit] | None,
    *,
    counted: FallbackReason | bool,
) -> ModeChoice:
    """Skip the judge a budget or the LLM search rate limit does not allow now.

    The judge is an LLM step: a search whose own LLM step was refused skips it for the same
    reason, without asking again; one whose LLM step was allowed (and so counted against the
    rate limit) checks only the budgets; any other is checked and counted as an LLM search.

    Args:
        spend: The budgets and the LLM search rate limit.
        choice: The choice, after its own LLM step was checked.
        who: The library and the account searching.
        own: The library's own budgets as already read.
        counted: The reason the search's LLM step was refused, True when it was allowed,
            False when it has none (or answered from the cache).

    Returns:
        The choice, or the same without reranking, with the reason.
    """
    if isinstance(counted, FallbackReason):
        reason: FallbackReason | None = counted
    elif counted:
        reason = await spend.paid_call(who, own)
    else:
        reason = await spend.llm_step(who, own)
    if reason is None:
        return choice
    return replace(
        choice, rerank=False, reranker=None, fallback_reason=choice.fallback_reason or reason
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Reranking:
    """Reorders a search's best candidates with a cross-encoder or the LLM judge (RET-02).

    The reranker is the one the library resolves to (its override, else the instance's
    ``reranker`` role), built from its profile as read once for the search (``profile``: bounded
    by ``limits.longest`` and never failing the search either). It receives the query text and the
    candidates' chunk text only, read before the clock starts. Building the reranker and its call
    must finish within the timeout of the profile's kind (``limits.timeout_for``). A reranker
    that does not, that fails, answers something unusable or cannot be built (a profile that
    cannot rerank, a key that no longer opens) never fails the search: the candidates keep the
    mode's order, ``reranked`` stays 0, and the fallback reason says why (when no other reason
    was given already). Failures are logged without the query or any text.

    The judge (#96, ``choice.reranker`` is ``judge``) is the library's ``judge`` role (its
    override, else the instance's, else the ``llm`` role), called once for all the candidates
    within ``limits.judge_timeout`` and the budgets of every LLM step. Its ratings are checked
    again here (``judged_scores``): it can only reorder the candidates it was given, never add,
    drop or rewrite one. A budget used up meanwhile answers ``llm_budget_reached``; a timeout,
    an error or refused ratings ``reranker_timeout`` or ``reranker_failed``.
    """

    providers: AiProviders
    """Resolves and builds the library's reranker and judge."""
    chunks: ChunkRepository
    """Reads the candidates' text."""
    limits: RerankLimits = field(default_factory=RerankLimits)
    """The instance's top N and timeouts."""
    judge: CandidateJudge | None = None
    """Rates the candidates with the ``judge`` role (pydantic-ai); none: the judge never
    reranks (``reranker_failed``)."""
    spend: AiSpend | None = None
    """The budgets, the prices and the clock of the judge's step; none: no budget applies."""

    async def apply(
        self, version: SearchableVersion, query: str, answer: PipelineAnswer, choice: ModeChoice
    ) -> tuple[PipelineAnswer, Mapping[ChunkId, StoredChunk]]:
        """Rerank the first ``choice.rerank_top_n`` hits of ``answer``.

        Args:
            version: The version searched.
            query: The query text.
            answer: The pipeline's answer, best first.
            choice: How many hits to rerank, and the library's overrides read for this search.

        Returns:
            The answer with its first hits reordered by the reranker's score (each carrying it),
            the rest after them in the mode's order with the mode's scores; or the answer in its
            own order, with a fallback reason, when reranking failed. Candidates whose chunk is
            gone are dropped (and no longer counted). Also the chunks read, by ID, so the caller
            need not read them again.
        """
        top_n = choice.rerank_top_n
        head = answer.hits[:top_n]
        if not head:
            return answer, {}
        stored = await self.chunks.get_many(version.manifest_id, [h.chunk_id for h in head])
        # A chunk gone since the search (the manifest was collected) is not sent, nor shown, nor
        # counted, so results and coverage stay consistent.
        kept = tuple(h for h in head if h.chunk_id in stored)
        answer = replace(
            answer,
            hits=(*kept, *answer.hits[top_n:]),
            candidates=answer.candidates - (len(head) - len(kept)),
        )
        if not kept:
            return answer, stored
        texts = [stored[h.chunk_id].chunk.content for h in kept]
        if choice.reranker is RerankWith.JUDGE:
            return await self._judged(version, query, answer, choice, kept, texts), stored
        return await self._cross_encoded(version, query, answer, choice, kept, texts), stored

    async def _cross_encoded(
        self,
        version: SearchableVersion,
        query: str,
        answer: PipelineAnswer,
        choice: ModeChoice,
        kept: Sequence[SearchHit],
        texts: Sequence[str],
    ) -> PipelineAnswer:
        """Have the cross-encoder score the candidates, and reorder them by its scores.

        Args:
            version: The version searched.
            query: The query text.
            answer: The pipeline's answer, its first hits the candidates.
            choice: The search's choice: the library's overrides.
            kept: The candidates whose chunk exists, best first.
            texts: Their text, in the same order.

        Returns:
            The answer reordered, or in its own order with a fallback reason.
        """
        found = choice.reranker_profile
        if found is None:  # not read for this search yet (``RetrievalModes.rerank`` reads it)
            found = await self.profile(version.library, choice.library_ai)
            if isinstance(found, FallbackReason):
                return _fallen_back(answer, found)
        ref, profile = found
        timeout = self.limits.timeout_for(profile.kind.value)
        try:
            async with asyncio.timeout(timeout):
                reranker = await self._reranker(ref, profile)
                scores = await _called(reranker, query, texts)
        except TimeoutError:
            logger.warning(
                "the reranker of %s did not answer within %ss: the search keeps its order",
                version.library,
                timeout,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_TIMEOUT)
        except RerankerError as error:
            logger.warning(
                "the reranker of %s failed: %s; the search keeps its order", version.library, error
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED)
        if len(scores) != len(kept) or not all(math.isfinite(score) for score in scores):
            logger.warning(
                "the reranker of %s did not answer one finite score per candidate; the search "
                "keeps its order",
                version.library,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED)
        return replace(
            answer, hits=(*reorder(kept, scores), *answer.hits[len(kept) :]), reranked=len(kept)
        )

    async def _judged(
        self,
        version: SearchableVersion,
        query: str,
        answer: PipelineAnswer,
        choice: ModeChoice,
        kept: Sequence[SearchHit],
        texts: Sequence[str],
    ) -> PipelineAnswer:
        """Have the judge rate the candidates in one call, and reorder them by its ratings.

        Args:
            version: The version searched.
            query: The query text.
            answer: The pipeline's answer, its first hits the candidates.
            choice: The search's choice: its caller and the library's overrides.
            kept: The candidates whose chunk exists, best first.
            texts: Their text, in the same order.

        Returns:
            The answer reordered, or in its own order with a fallback reason.
        """
        offered = [
            JudgedCandidate(chunk_id=h.chunk_id, text=text)
            for h, text in zip(kept, texts, strict=True)
        ]
        # Only the best candidates that fit one bounded call are judged; the rest keep their
        # order after them (never a call the token limit would stop once it was paid for).
        window = judge_window(query, offered)
        if window == 0:
            logger.warning(
                "the judge of %s was not called: not one candidate fits a call; the search "
                "keeps its order",
                version.library,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED)
        candidates = offered[:window]
        judged = kept[:window]
        try:
            async with asyncio.timeout(self.limits.judge_timeout):
                scores = await self._judge_scores(version.library, query, candidates, choice)
        except TimeoutError:
            logger.warning(
                "the judge of %s did not answer within %ss: the search keeps its order",
                version.library,
                self.limits.judge_timeout,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_TIMEOUT)
        except LlmBudgetReachedError:
            logger.info(
                "a budget stopped the judge of %s: the search keeps its order", version.library
            )
            return _fallen_back(answer, FallbackReason.LLM_BUDGET_REACHED)
        except RerankerError as error:
            logger.warning(
                "the judge of %s failed: %s; the search keeps its order", version.library, error
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED)
        return replace(
            answer,
            hits=(*reorder(judged, scores), *kept[window:], *answer.hits[len(kept) :]),
            reranked=window,
        )

    async def _judge_scores(
        self,
        library: str,
        query: str,
        candidates: Sequence[JudgedCandidate],
        choice: ModeChoice,
    ) -> tuple[float, ...]:
        """Build the library's judge from the profile as it is now and have it rate.

        Args:
            library: The library searched.
            query: The query text.
            candidates: The candidates.
            choice: The search's choice: its caller and the library's overrides.

        Returns:
            One score per candidate, in their order.

        Raises:
            LlmBudgetReachedError: A budget refused the request.
            RerankerError: No judge resolves, it cannot be built or called, it failed, or its
                ratings are not exactly one bounded score per candidate; only the kind of
                failure is kept, never a message that may echo the prompt.
        """
        if self.judge is None:
            reason = "no judge can run here"
            raise RerankerError(reason)
        ai = choice.library_ai or await self.providers.library_modes.ai_of(library)
        found = await self.providers.profile_for(ModelRole.JUDGE, library, ai)
        if found is None:  # AI off, no role, or a profile that no longer exists
            reason = "no judge resolves for the library"
            raise RerankerError(reason)
        ref, profile = found
        spend = self.spend
        step = LlmStep(
            caller=AiCaller(library=library.casefold(), user=choice.caller),
            budgets=spend.budgets_for(ai) if spend is not None else Budgets(),
            price=spend.prices.price(ref, profile.kind.value) if spend is not None else None,
            clock=spend.clock.now if spend is not None else SystemClock().now,
        )
        try:
            thinking = await self.providers.thinking_of(ModelRole.JUDGE, ai)
            model = await self.providers.factory.chat_model(profile, ref.model, thinking=thinking)
            verdict = await self.judge.judge(model, query, candidates, step=step)
            return judged_scores(candidates, verdict.ratings)
        except LlmBudgetReachedError:
            raise
        except LlmFailedError as error:
            reason = f"it failed ({error.reason})"
            raise RerankerError(reason) from error
        except InvalidJudgmentError as error:
            reason = f"its ratings were refused ({error.fault})"
            raise RerankerError(reason) from error
        except Exception as error:  # a judge problem never fails a search; re-raised as ours
            reason = f"it failed ({_kind(error)})"
            raise RerankerError(reason) from error

    async def profile(
        self, library: str, ai: LibraryAi | None
    ) -> tuple[ModelRef, ProviderProfile] | FallbackReason:
        """Read the model and the profile the library's cross-encoder resolves to now.

        Read once per search, for its kind (a budget, the timeout), the reranker built and the
        spend recorded. A stored profile is a database read: it must finish within
        ``limits.longest`` (the kind, and so the timeout, is not known before it), and whatever
        it raises never fails the search (#284).

        Args:
            library: The library searched.
            ai: Its overrides, as read for this search.

        Returns:
            The model and the profile; or ``reranker_timeout`` or ``reranker_failed`` when the
            read did not finish in time, failed (logged by its kind only) or nothing resolves.
        """
        bound = self.limits.longest
        try:
            async with asyncio.timeout(bound):
                return await self._read_profile(library, ai)
        except TimeoutError:
            logger.warning(
                "the reranker profile of %s was not read within %ss: the search keeps its order",
                library,
                bound,
            )
            return FallbackReason.RERANKER_TIMEOUT
        except RerankerError as error:
            logger.warning(
                "the reranker of %s failed: %s; the search keeps its order", library, error
            )
            return FallbackReason.RERANKER_FAILED

    async def _read_profile(
        self, library: str, ai: LibraryAi | None
    ) -> tuple[ModelRef, ProviderProfile]:
        """Read the model and the profile the library's cross-encoder resolves to now.

        Args:
            library: The library searched.
            ai: Its overrides, as read for this search.

        Returns:
            The model and the profile.

        Raises:
            RerankerError: The read failed, however (its text names only the kind of failure),
                or no reranker resolves for the library.
        """
        try:
            found = await self.providers.profile_for(ModelRole.RERANKER, library, ai)
        except Exception as error:  # a reranker problem never fails a search; re-raised as ours
            # Never the error's text: only its kind, which holds no URL, key or path.
            reason = f"its profile could not be read ({_kind(error)})"
            raise RerankerError(reason) from error
        if found is None:
            reason = "no reranker resolves for the library"
            raise RerankerError(reason)
        return found

    async def _reranker(self, ref: ModelRef, profile: ProviderProfile) -> Reranker:
        """Build the reranker from the profile read for this search.

        Args:
            ref: The model.
            profile: Its profile, as read for this search.

        Returns:
            The reranker.

        Raises:
            RerankerError: Building it failed, for whatever reason (the profile cannot rerank
                here, its key does not open, its key file cannot be read, a partly installed SDK).
        """
        try:
            return await self.providers.factory.reranker(profile, ref.model)
        except Exception as error:  # a reranker problem never fails a search; re-raised as ours
            # Never the error's text: only its kind, which holds no key, URL or path.
            reason = f"it could not be built ({_kind(error)})"
            raise RerankerError(reason) from error


async def _called(reranker: Reranker, query: str, texts: Sequence[str]) -> Sequence[float]:
    """Call the reranker; whatever it raises becomes a ``RerankerError``.

    An adapter should raise only ``RerankerError``, but an HTTP client closed under a call (its
    profile was edited or deleted meanwhile) raises ``RuntimeError``, and a ``TaskGroup`` wraps
    errors in an ``ExceptionGroup``: none of it may fail the search. Cancellation (the timeout)
    is not an ``Exception`` and passes through.

    Args:
        reranker: The library's reranker.
        query: The query text.
        texts: The candidates' text.

    Returns:
        Its scores.

    Raises:
        RerankerError: The call failed, however; its text names only the kind of failure.
    """
    try:
        return await reranker.rerank(query, texts)
    except RerankerError:
        raise
    except Exception as error:  # a reranker problem never fails a search; re-raised as ours
        reason = f"it failed ({_kind(error)})"
        raise RerankerError(reason) from error


def _kind(error: Exception) -> str:
    """Name what went wrong without its text: the class, or the first one an exception group holds.

    Args:
        error: The error.

    Returns:
        Its class name (``RuntimeError``), never its message.
    """
    while isinstance(error, ExceptionGroup) and error.exceptions:
        first = error.exceptions[0]
        if not isinstance(first, Exception):
            break
        error = first
    return type(error).__name__


async def _chunks_of(
    chunks: ChunkRepository,
    version: SearchableVersion,
    answer: PipelineAnswer,
    read: Mapping[ChunkId, StoredChunk],
) -> Mapping[ChunkId, StoredChunk]:
    """Load the answer's chunks from the version, reusing those the reranker read already.

    Args:
        chunks: The chunk store.
        version: The version searched: chunks come from its manifest only.
        answer: The hits to show.
        read: Chunks of the same manifest read earlier in this search, by ID.

    Returns:
        The chunks that exist, by ID.
    """
    missing = [h.chunk_id for h in answer.hits if h.chunk_id not in read]
    loaded = await chunks.get_many(version.manifest_id, missing) if missing else {}
    wanted = {h.chunk_id for h in answer.hits}
    return {**{k: v for k, v in read.items() if k in wanted}, **loaded}


async def _inside_prefix(
    chunks: ChunkRepository, version: SearchableVersion, answer: PipelineAnswer, prefix: str
) -> tuple[PipelineAnswer, Mapping[ChunkId, StoredChunk]]:
    """Keep the hits of articles inside ``prefix`` (``path_prefix``, as ``list_articles`` reads it).

    Args:
        chunks: The chunk store.
        version: The version searched: chunks come from its manifest only.
        answer: The ranking, deeper than shown.
        prefix: The directory, cleaned (``clean_path_prefix``).

    Returns:
        The hits inside the directory, best first, still complete only when the ranking was (no
        match was left out of it); and the chunks read, by ID, for the later stages.
    """
    stored = await _chunks_of(chunks, version, answer, {})
    kept = tuple(
        hit
        for hit in answer.hits
        if hit.chunk_id in stored and inside(stored[hit.chunk_id].row.article_path, prefix)
    )
    return replace(answer, hits=kept, candidates=len(kept)), stored


def _fallen_back(answer: PipelineAnswer, reason: FallbackReason) -> PipelineAnswer:
    """Keep the answer's order and say why it was not reranked, unless a reason is given already.

    Args:
        answer: The pipeline's answer.
        reason: Why reranking did not happen.

    Returns:
        The answer, not reranked, with the first fallback reason.
    """
    return replace(answer, reranked=0, fallback_reason=answer.fallback_reason or reason)


async def _asked_version(
    versions: SearchableVersions, refs: VersionRefs | None, library: str, ref: str | None
) -> SearchableVersion:
    """Find the version a search or read asked for; never one of another version number.

    The exact ref (the default version without one) answers when it has an index. Else, when the
    library has not imported that ref as written, the one ref that is it with its version number's
    leading ``v`` dropped or added answers (#606): ``v1.10.0`` reads ``1.10.0``. The result names
    the version that answered.

    Args:
        versions: Resolves a ref to the version's active manifest.
        refs: The library's imported refs; without it only the exact ref answers.
        library: The library ID.
        ref: The ref as asked; ``None`` for the default version.

    Returns:
        The version that answers.

    Raises:
        VersionNotIndexedError: No version of that ref, or of its other spelling, has an index;
            it names the library's refs.
    """
    version = await versions.find(library, ref)
    if version is not None:
        return version
    known = [target.version for target in await refs.of(library)] if refs is not None else []
    twin = leading_v_twin(ref, known) if ref is not None else None
    if twin is not None and (version := await versions.find(library, twin)) is not None:
        return version
    raise VersionNotIndexedError(library, ref, known)


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: SearchableVersions
    """Resolves the asked version to the manifest the search reads."""
    refs: VersionRefs | None = None
    """The library's refs: a ref's other ``v`` spelling, and the refs a miss names."""
    modes: RetrievalModes
    """Picks the mode and runs its pipeline."""
    chunks: ChunkRepository
    """Reads the hits' chunks."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(
        self, query: SearchDocsQuery, *, caller: str | None = None
    ) -> SearchDocsResult:
        """Search the active manifest of one exact version; never fall back to another version.

        Args:
            query: The search.
            caller: The account searching; ``None`` for a stdio MCP process.

        Returns:
            The results of the one version searched.
        """
        await _require(self.access, query.library, Access.READ)
        # Built only to refuse a whitespace-only query (EmptySearchTextError).
        text = SearchText(value=query.query)
        choice = await self.modes.choose(asked=query.mode, library=query.library)
        with self.tracer.span(
            SEARCH_DOCS,
            mode=choice.mode.value,
            query=text.value,
            library=query.library,
            ref=query.ref,
        ) as whole:
            return await self._search(query, text, choice, whole, caller)

    async def _search(
        self,
        query: SearchDocsQuery,
        text: SearchText,
        choice: ModeChoice,
        whole: SearchSpan,
        caller: str | None,
    ) -> SearchDocsResult:
        """Resolve the version, rank its chunks and load the shown ones, one span per stage.

        Args:
            query: The search as asked.
            text: Its validated query text.
            choice: The retrieval mode it runs in.
            whole: The search's span, told which mode answered.
            caller: The account searching.

        Returns:
            The results of the one version searched.
        """
        mode = choice.mode.value
        with self.tracer.span(f"{SEARCH_DOCS}.version", mode=mode):
            version = await _asked_version(self.versions, self.refs, query.library, query.ref)
        # Only a search that will run counts against the caller's limits; every stage after this
        # one sees the same choice.
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        choice = await self.modes.within_budget(
            choice,
            library=version.library,
            caller=caller,
            version=version,
            query=text.value,
            tag_filter=tag_filter,
            limit=query.limit,
        )
        mode = choice.mode.value
        prefix = query.path_prefix
        # A prefix narrows a deeper ranking (the backends filter tags, not paths); the agentic
        # explorer is not asked for more picks than shown, only its picks are filtered.
        pool = query.limit
        if prefix and choice.mode is not RetrievalMode.AGENTIC:
            pool = max(query.limit, PATH_PREFIX_POOL)
        with self.tracer.span(f"{SEARCH_DOCS}.rank", mode=mode) as rank:
            answer = await self.modes.run(choice, version, text.value, tag_filter, pool)
            rank.answered_by(answer.mode.value)
        whole.answered_by(answer.mode.value)
        read: Mapping[ChunkId, StoredChunk] = {}
        if prefix:
            with self.tracer.span(f"{SEARCH_DOCS}.path_prefix", mode=answer.mode.value):
                answer, read = await _inside_prefix(self.chunks, version, answer, prefix)
        if choice.rerank:  # a stage of its own; it records neither the query nor any text
            stage = "judge" if choice.reranker is RerankWith.JUDGE else "rerank"
            with self.tracer.span(f"{SEARCH_DOCS}.{stage}", mode=answer.mode.value):
                answer, reread = await self.modes.rerank(choice, version, text.value, answer)
            read = {**read, **reread}
        answer = answer.cut(query.limit)
        if answer.fallback_reason is not None:
            self.tracer.fallback(mode=answer.mode.value, reason=answer.fallback_reason.value)
        with self.tracer.span(f"{SEARCH_DOCS}.chunks", mode=answer.mode.value):
            stored = await _chunks_of(self.chunks, version, answer, read)
        # A chunk gone since the search (the manifest was collected) leaves no result, and is not
        # counted as a candidate either, so results and coverage stay consistent.
        results = [
            SearchResultOut.from_models(version, stored[hit.chunk_id], hit)
            for hit in answer.hits
            if hit.chunk_id in stored
        ]
        vanished = len(answer.hits) - len(results)
        if query.group_by is ResultGrouping.ARTICLE:
            results = _grouped(results, lambda r: r.article_path)
        return SearchDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=answer.mode,
            reranked=answer.reranked > 0,
            coverage=CoverageOut(
                candidates=answer.candidates - vanished,
                reranked=answer.reranked,
                complete=answer.complete,
            ),
            fallback_reason=answer.fallback_reason,
            cache_hit=answer.cache_hit,
            results=results,
        )


def _grouped[R: SearchResultOut](results: Sequence[R], article: Callable[[R], str]) -> list[R]:
    """Order results by article group (``ResultGrouping.ARTICLE``), each told its group.

    Args:
        results: The results, best first.
        article: The article of a result (with its library when several are searched).

    Returns:
        The same results, each article's together, best first, with ``group`` set.
    """
    order = article_groups([article(r) for r in results])
    return [results[i].model_copy(update={"group": group}) for i, group in order]


def _shown_across(
    query: SearchAllQuery, results: Sequence[LibrarySearchResultOut]
) -> list[LibrarySearchResultOut]:
    """Keep the results of a search across libraries that are shown, grouped as asked.

    Args:
        query: The search (its path prefix, limit and grouping).
        results: The ranked results, best first.

    Returns:
        Those under the prefix, at most ``limit``, grouped by library and article when asked.
    """
    shown = [r for r in results if inside(r.article_path, query.path_prefix)][: query.limit]
    if query.group_by is ResultGrouping.ARTICLE:
        return _grouped(shown, lambda r: f"{r.library}\n{r.article_path}")
    return shown


def _cross_library_embedding_scopes(caller: str | None) -> tuple[tuple[str, str], ...]:
    """Name the ledger scopes the query embedding of a search across libraries counts to.

    It is made once for every library searched, so it counts to no one library: to the embedding
    budget, the instance and the caller.

    Args:
        caller: The account searching; ``None`` for a stdio MCP process.

    Returns:
        (kind, ID) of each scope.
    """
    scopes = [(SPEND_SCOPE_EMBEDDING, SPEND_INSTANCE_ID), (SPEND_SCOPE_INSTANCE, SPEND_INSTANCE_ID)]
    if caller is not None:
        scopes.append((SPEND_SCOPE_USER, caller))
    return tuple(scopes)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Ranked:
    """A chunk a search across libraries keeps, before its row is read."""

    manifest_id: str
    """The manifest (so the library version) it was found in."""
    chunk_id: ChunkId
    """The chunk."""
    score: float
    """Its score in the mode that answered."""
    bm25_rank: int | None = None
    """Its 1-based rank in the BM25 ranking, if it is there."""
    vector_rank: int | None = None
    """Its 1-based rank in the vector ranking, if it is there."""
    hit: SearchHit | None = None
    """BM25's hit, with its marked snippet; ``None`` when only the vectors found it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Nearest:
    """The vector ranking of a search across libraries, or why there is none."""

    hits: tuple[tuple[str, VectorHit], ...] = ()
    """``(manifest, hit)``, nearest first across the manifests searched."""
    reason: FallbackReason | None = None
    """Why the vectors could not be used; ``None`` when they were."""
    without: tuple[str, ...] = ()
    """Libraries left out of the vector ranking: AI is off for them, or their version is not
    embedded with the configured model yet."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchAllLibrariesUseCase:
    """Implements ``ports.driving.SearchAllLibraries`` (#428: ``bm25``, ``vector``, ``hybrid``).

    BM25 ranks the chunks of every searched default version together in one full-text query. The
    vector modes embed the query once with the instance's embedding model and rank the chunks of
    every searched version its space covers by their distance to it, nearest first across the
    versions (one space, so the distances compare); ``hybrid`` fuses both rankings with reciprocal
    rank fusion. A library with AI off, or whose version the model has not embedded yet, is left
    out of the vector ranking and named in ``libraries_without_vectors``. When the vectors cannot
    be used at all, BM25 answers with the reason, as in a search of one version.
    """

    defaults: DefaultVersions
    """Every library's default version."""
    versions: SearchableVersions
    """Resolves a ``library`` filter to its default version."""
    search: SearchIndex
    """The full-text index, searched over all manifests at once."""
    chunks: ChunkRepository
    """Reads the hits' chunks."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""
    modes: RetrievalModes | None = None
    """The vector store and the embedding model the vector modes search with; without them only
    ``bm25`` runs."""

    async def __call__(
        self, query: SearchAllQuery, *, caller: str | None = None
    ) -> SearchAllResult:
        """Rank the chunks of the chosen default versions together; count the matches per library.

        With libraries chosen, every library is still resolved: the counts stay global, which a
        facet needs.

        Args:
            query: The query, the mode, the libraries, the filters and the limit.
            caller: The account searching (a paid query embedding counts to it); ``None`` for a
                stdio MCP process.

        Returns:
            The results across libraries and the matches per library.
        """
        text = SearchText(value=query.query)
        mode = await self._mode(query.mode)
        libraries = ",".join(query.chosen) or None
        with self.tracer.span(
            SEARCH_ALL, mode=mode.value, query=text.value, library=libraries
        ) as whole:
            result = await self._search(query, text, mode, caller)
            whole.answered_by(result.retrieval_mode.value)
            return result

    def _hybrid(self) -> HybridPipeline | None:
        """Find the pipeline whose vector store and query embedding the vector modes use.

        Returns:
            The ``hybrid`` pipeline, or ``None`` when this build has none (no vector store).
        """
        found = None if self.modes is None else self.modes.pipelines.get(RetrievalMode.HYBRID)
        return found if isinstance(found, HybridPipeline) else None

    async def _mode(self, asked: str | None) -> RetrievalMode:
        """Check the mode a call asked for; ``bm25`` when it names none.

        Args:
            asked: The mode as the caller wrote it, if any.

        Returns:
            The mode.

        Raises:
            UnavailableModeError: The mode is unknown, cannot search across libraries
                (``hybrid_hyde``, ``agentic``), or cannot run now (no embedding model, or the
                vector store cannot load).
        """
        if asked is None:
            return RetrievalMode.BM25
        hybrid = self._hybrid()
        configured = None if hybrid is None else await hybrid.runs.configured()
        store = hybrid is not None and await hybrid.vectors.available()
        vectors = configured is not None and store
        across = [RetrievalMode.BM25, RetrievalMode.VECTOR, RetrievalMode.HYBRID]
        available = [m.value for m in across if vectors or not m.needs_vectors]
        try:
            mode = RetrievalMode(asked.strip().lower())
        except ValueError:
            raise UnavailableModeError(asked, available, []) from None
        if mode.value in available:
            return mode
        if mode in across:
            missing = [ModelRole.EMBEDDING.value] if configured is None else []
            raise UnavailableModeError(asked, available, missing, vector_store=store)
        raise UnavailableModeError(asked, available, [])

    async def _scope(
        self, query: SearchAllQuery, mode: RetrievalMode
    ) -> tuple[dict[str, SearchableVersion], dict[str, SearchableVersion], int]:
        """Resolve the default versions searched and counted.

        Args:
            query: The search as asked.
            mode: The mode it runs in.

        Returns:
            The versions ranked (the chosen libraries', or every readable one's), the versions
            counted (every readable one's, the chosen ones included), by manifest, and how many
            readable libraries were left out because there are too many.
        """
        with self.tracer.span(f"{SEARCH_ALL}.versions", mode=mode.value):
            return await _default_versions(
                self.defaults, self.versions, self.access, query.chosen, MAX_SEARCHED_LIBRARIES
            )

    async def _nearest(
        self,
        scope: Mapping[str, SearchableVersion],
        text: str,
        tag_filter: TagFilter,
        depth: int,
        *,
        mode: RetrievalMode,
        caller: str | None,
    ) -> _Nearest:
        """Embed the query once and rank the covered versions' chunks by their vectors.

        Args:
            scope: The versions searched, by manifest.
            text: The query.
            tag_filter: Which chunks may be returned.
            depth: How many chunks at most.
            mode: The mode searching, which labels the embedding's span.
            caller: The account searching.

        Returns:
            The nearest chunks across the versions, or why the vectors cannot be used, and the
            libraries left out.
        """
        hybrid = self._hybrid()
        if hybrid is None:
            return _Nearest(reason=FallbackReason.VECTOR_STORE_UNAVAILABLE)
        configured = await hybrid.runs.configured()
        if configured is None:
            return _Nearest(reason=FallbackReason.EMBEDDING_UNAVAILABLE)
        space = await hybrid.runs.space(configured.target)
        covered, left_out = await _covered(hybrid.runs, space, scope)
        if space is None or not covered:
            return _Nearest(reason=FallbackReason.EMBEDDING_IN_PROGRESS, without=left_out)
        scopes = _cross_library_embedding_scopes(caller)
        vector = await hybrid.query_vector(space, text, mode=mode, scopes=scopes, search=SEARCH_ALL)
        if isinstance(vector, FallbackReason):
            return _Nearest(reason=vector, without=left_out)
        found = await _nearest_in(hybrid.vectors, space.id, covered, vector, tag_filter, depth)
        if isinstance(found, FallbackReason):
            return _Nearest(reason=found, without=left_out)
        found.sort(key=lambda p: (p[1].distance, scope[p[0]].library, p[1].chunk_id))
        return _Nearest(hits=tuple(found[:depth]), without=left_out)

    async def _search(
        self, query: SearchAllQuery, text: SearchText, mode: RetrievalMode, caller: str | None
    ) -> SearchAllResult:
        """Resolve the default versions, rank and count, then load the shown chunks.

        Args:
            query: The search as asked.
            text: Its validated query text.
            mode: The mode asked for.
            caller: The account searching.

        Returns:
            The results across the libraries, with a facet per library.
        """
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        scope, searched, omitted = await self._scope(query, mode)
        # A prefix narrows a deeper ranking, as in a search of one version.
        limit = max(query.limit, PATH_PREFIX_POOL) if query.path_prefix else query.limit
        near = _Nearest()
        if mode.needs_vectors:
            depth = limit + 1 if mode is RetrievalMode.VECTOR else RRF_DEPTH
            with self.tracer.span(f"{SEARCH_ALL}.vectors", mode=mode.value):
                near = await self._nearest(
                    scope, text.value, tag_filter, depth, mode=mode, caller=caller
                )
        answered = RetrievalMode.BM25 if near.reason is not None else mode
        # One more than is kept tells whether the answer was cut short.
        bm25_depth = (max(RRF_DEPTH, limit) if answered is RetrievalMode.HYBRID else limit) + 1
        with self.tracer.span(f"{SEARCH_ALL}.rank", mode=answered.value):
            found_hits, counts = await asyncio.gather(
                self._bm25(answered, scope, text.value, tag_filter, bm25_depth),
                self.search.count_many(list(searched), text.value, tag_filter),
            )
        ranked, candidates, complete = _ranked_across(answered, found_hits, near, limit)
        results = await self._results(ranked, scope, text.value, answered)
        return SearchAllResult(
            retrieval_mode=answered,
            reranked=False,
            coverage=_coverage_across(
                query, results, candidates - (len(ranked) - len(results)), complete=complete
            ),
            fallback_reason=near.reason,
            libraries_searched=len(searched),
            libraries_omitted=omitted,
            libraries_without_vectors=list(near.without),
            libraries=_facets(counts, searched),
            results=_shown_across(query, results),
        )

    async def _bm25(
        self,
        mode: RetrievalMode,
        scope: Mapping[str, SearchableVersion],
        text: str,
        tag_filter: TagFilter,
        depth: int,
    ) -> Sequence[ManifestHit]:
        """Rank the scope's chunks with BM25, unless the mode answering has no BM25 ranking.

        Args:
            mode: The mode answering.
            scope: The versions searched, by manifest.
            text: The query.
            tag_filter: Which chunks may be returned.
            depth: How many hits at most.

        Returns:
            The hits, best first; none for ``vector``.
        """
        if mode is RetrievalMode.VECTOR:
            return ()
        return await self.search.search_many(list(scope), text, tag_filter, depth)

    async def _results(
        self,
        ranked: Sequence[_Ranked],
        scope: Mapping[str, SearchableVersion],
        text: str,
        mode: RetrievalMode,
    ) -> list[LibrarySearchResultOut]:
        """Read the kept chunks and build their results.

        Args:
            ranked: The chunks kept, best first.
            scope: The versions searched, by manifest.
            text: The query, whose terms mark the snippets of chunks only the vectors found.
            mode: The mode answering.

        Returns:
            The results; a chunk gone since the search (its manifest was collected) leaves none.
        """
        wanted: dict[str, list[ChunkId]] = {}
        for entry in ranked:
            wanted.setdefault(entry.manifest_id, []).append(entry.chunk_id)
        with self.tracer.span(f"{SEARCH_ALL}.chunks", mode=mode.value):
            stored = await self.chunks.get_across(wanted)
        terms = search_terms(text)
        results = []
        for entry in ranked:
            chunk = stored.get((entry.manifest_id, entry.chunk_id))
            if chunk is None:
                continue
            hit = entry.hit or leading_hit(entry.chunk_id, entry.score, chunk.chunk.content, terms)
            hit = replace(
                hit, score=entry.score, bm25_rank=entry.bm25_rank, vector_rank=entry.vector_rank
            )
            results.append(LibrarySearchResultOut.of(scope[entry.manifest_id], chunk, hit))
        return results


async def _default_versions(
    defaults: DefaultVersions,
    versions: SearchableVersions,
    access: AccessPolicy,
    chosen: Sequence[str],
    cap: int,
) -> tuple[dict[str, SearchableVersion], dict[str, SearchableVersion], int]:
    """Resolve the default versions a search or an answer across libraries reads.

    Args:
        defaults: Every library's default version.
        versions: Resolves a chosen library to its default version.
        access: What the caller may read (library roles and the API token's scope).
        chosen: The libraries chosen; none for every readable one.
        cap: The most readable libraries taken when none is chosen.

    Returns:
        The versions read (the chosen libraries', or the first ``cap`` readable ones), every
        readable version (the first ``cap``, and the chosen ones), by manifest, and how many
        readable libraries were left out of the latter.

    Raises:
        VersionNotIndexedError: A chosen library has no default version the caller may read.
    """
    every = await defaults.all()
    allowed = await access.readable([v.library for v in every])
    readable = [v for v in every if v.library.casefold() in allowed]
    searched = {v.manifest_id: v for v in readable[:cap]}
    omitted = len(readable) - len(searched)
    if not chosen:
        return searched, searched, omitted
    scope: dict[str, SearchableVersion] = {}
    for library in chosen:
        only = await versions.find(library, None)
        if only is None or only.library.casefold() not in allowed:
            raise VersionNotIndexedError(library, None)
        if only.manifest_id not in searched:  # beyond the cap: read, so no longer omitted
            searched[only.manifest_id] = only
            omitted -= 1
        scope[only.manifest_id] = only
    return scope, searched, omitted


def _facets(
    counts: Mapping[str, int], searched: Mapping[str, SearchableVersion]
) -> list[LibraryFacetOut]:
    """Count the matches of each searched library, most first.

    Args:
        counts: BM25 matches by manifest.
        searched: The versions counted, by manifest.

    Returns:
        A facet per library with at least one match.
    """
    return sorted(
        (
            LibraryFacetOut(
                library=searched[m].library,
                version=searched[m].version,
                commit_sha=searched[m].commit_sha,
                matches=n,
            )
            for m, n in counts.items()
            if m in searched and n > 0
        ),
        key=lambda f: (-f.matches, f.library),
    )


async def _nearest_in(
    vectors: VectorIndex,
    space: EmbeddingSpaceId,
    manifests: Sequence[str],
    vector: Sequence[float],
    tag_filter: TagFilter,
    depth: int,
) -> list[tuple[str, VectorHit]] | FallbackReason:
    """Find each manifest's chunks nearest to a query vector.

    Args:
        vectors: The vector store.
        space: The space searched.
        manifests: The manifests searched.
        vector: The query's vector.
        tag_filter: Which chunks may be returned.
        depth: How many chunks of each manifest at most.

    Returns:
        ``(manifest, hit)`` of every chunk found, in no particular order, or why the store could
        not search.
    """
    try:
        return [
            (manifest, hit)
            for manifest in manifests
            for hit in await vectors.nearest(space, manifest, vector, tag_filter, depth)
        ]
    except UnknownEmbeddingSpaceError, RetiredEmbeddingSpaceError:
        return FallbackReason.EMBEDDING_IN_PROGRESS  # retired by a switch of models meanwhile
    except VectorStoreUnavailableError:
        return FallbackReason.VECTOR_STORE_UNAVAILABLE
    except VectorDimensionError, InvalidVectorError:
        return FallbackReason.EMBEDDING_UNAVAILABLE


async def _covered(
    runs: EmbeddingRuns, space: EmbeddingSpace | None, scope: Mapping[str, SearchableVersion]
) -> tuple[list[str], tuple[str, ...]]:
    """Split the versions searched into those the vectors can rank and the libraries left out.

    Args:
        runs: The embedding model and which versions its space covers.
        space: The configured model's space, if it has one.
        scope: The versions searched, by manifest.

    Returns:
        The manifests with AI on that the space covers, and the libraries of the others, sorted.
    """
    covered: list[str] = []
    without: list[str] = []
    for manifest, version in scope.items():
        ai = await runs.providers.library_modes.ai_of(version.library)
        if ai.enabled and space is not None and await runs.covers(space, manifest):
            covered.append(manifest)
        else:
            without.append(version.library)
    return covered, tuple(sorted(without))


def _coverage_across(
    query: SearchAllQuery,
    results: Sequence[LibrarySearchResultOut],
    candidates: int,
    *,
    complete: bool,
) -> CoverageOut:
    """Say how much a search across libraries looked at, once its ``path_prefix`` is applied.

    Args:
        query: The search, with its limit and prefix.
        results: The chunks read from the ranking, best first, before the prefix.
        candidates: Matching chunks looked at (their chunks still there).
        complete: Whether the ranking held every match.

    Returns:
        The coverage; with a prefix, the matches inside it, complete only when the deeper ranking
        held every match and they all fit the limit.
    """
    if not query.path_prefix:
        return CoverageOut(candidates=candidates, reranked=0, complete=complete)
    kept = sum(1 for r in results if inside(r.article_path, query.path_prefix))
    return CoverageOut(candidates=kept, reranked=0, complete=complete and kept <= query.limit)


def _ranked_across(
    mode: RetrievalMode, found: Sequence[ManifestHit], near: _Nearest, limit: int
) -> tuple[list[_Ranked], int, bool]:
    """Keep the best ``limit`` chunks of a search across libraries, in the mode answering.

    Args:
        mode: The mode answering.
        found: BM25's hits, best first (none for ``vector``); one more than kept when cut short.
        near: The vector ranking (for ``vector`` and ``hybrid``).
        limit: How many to keep.

    Returns:
        The kept chunks, best first; how many candidates were looked at; and whether nothing
        more matched.
    """
    match mode:
        case RetrievalMode.VECTOR:
            kept = [
                _Ranked(
                    manifest_id=m, chunk_id=h.chunk_id, score=1.0 - h.distance, vector_rank=rank
                )
                for rank, (m, h) in enumerate(near.hits[:limit], start=1)
            ]
            return kept, len(near.hits), len(near.hits) <= limit
        case RetrievalMode.HYBRID:
            by_key = {(f.manifest_id, f.hit.chunk_id): f.hit for f in found}
            fused = fuse_across_manifests(
                [(f.manifest_id, f.hit.chunk_id) for f in found[:RRF_DEPTH]],
                [(m, h.chunk_id) for m, h in near.hits],
            )
            kept = [
                _Ranked(
                    manifest_id=f.manifest_id,
                    chunk_id=f.chunk_id,
                    score=f.score,
                    bm25_rank=f.bm25_rank,
                    vector_rank=f.vector_rank,
                    hit=by_key.get((f.manifest_id, f.chunk_id)),
                )
                for f in fused[:limit]
            ]
            cut = len(found) > RRF_DEPTH or len(near.hits) >= RRF_DEPTH
            return kept, len(fused), not cut and len(fused) <= limit
        case _:
            kept = [
                _Ranked(
                    manifest_id=f.manifest_id,
                    chunk_id=f.hit.chunk_id,
                    score=f.hit.score,
                    bm25_rank=rank,
                    hit=f.hit,
                )
                for rank, f in enumerate(found[:limit], start=1)
            ]
            return kept, len(found), len(found) <= limit


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexManifestUseCase:
    """Implements ``ports.driving.IndexManifest``."""

    chunks: ChunkRepository
    """Stores the rows and chunk sets."""
    search: SearchIndex
    """Indexes the new chunk sets."""
    clock: Clock
    """Stamps the manifest's indexing time."""
    external: ExternalIndexes | None = None
    """Writes the version to the external backends; ``None``: every index is the database's."""

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Compute the chunk IDs, store the rows plus the new chunk sets, and make them searchable.

        Call it between the catalog's store (pending) and its activate, never after. With
        external backends the version is written to them too (also when it was already indexed:
        a replay fills what a crash left out); a backend that does not take it fails the import,
        so the version is never published without its external copy.

        Args:
            command: The manifest and its articles' chunks.

        Returns:
            The chunk IDs by article and how many chunk sets were new.
        """
        library = command.library.lower()
        manifest = IndexedManifest(
            manifest_id=command.manifest_id,
            version_id=f"{library}/{command.ref}",
            library=library,
            indexed_at=self.clock.now(),
        )
        chunk_sets, rows = await asyncio.to_thread(self._build, command, manifest)
        stored = await self.chunks.add(manifest, chunk_sets, rows)
        # Also when the manifest was already indexed: a crash between the two calls above and
        # below leaves sets without index entries, and indexing only fills gaps.
        for chunk_set in chunk_sets.values():
            await self.search.index(chunk_set)
        if self.external is not None:
            await self.external.put_version(manifest)
        ids: dict[str, list[str]] = {a.path: [] for a in command.articles}
        for row in rows:
            ids[row.article_path].append(row.chunk_id)
        return IndexedManifestOut(
            manifest_id=command.manifest_id,
            chunk_ids=ids,
            chunk_sets_stored=stored or 0,
            already_indexed=stored is None,
        )

    @staticmethod
    def _build(
        command: IndexManifestCommand, manifest: IndexedManifest
    ) -> tuple[dict[ChunkSetKey, ChunkSet], list[ManifestChunk]]:
        """Make the chunk sets and rows: CPU-bound (chunk IDs are hashed), so run in a thread.

        Args:
            command: The manifest and its articles' chunks.
            manifest: The manifest being indexed.

        Returns:
            The chunk sets by key, and the manifest's rows.
        """
        chunk_sets: dict[ChunkSetKey, ChunkSet] = {}
        rows: list[ManifestChunk] = []
        for article in command.articles:
            chunk_set = chunk_sets.setdefault(
                (article.blob_sha, command.config_hash),
                ChunkSet(
                    blob_sha=article.blob_sha,
                    config_hash=command.config_hash,
                    chunks=tuple(
                        Chunk(
                            heading_path=tuple(c.heading_path),
                            occurrence_index=c.occurrence_index,
                            part=c.part,
                            content=c.content,
                            content_hash=c.content_hash,
                            anchor=c.anchor,
                            code_languages=tuple(c.code_languages),
                            headings=None
                            if c.headings is None
                            else tuple(
                                ChunkHeading(
                                    heading_path=tuple(h.heading_path),
                                    anchor=h.anchor,
                                    starts_chunk=h.starts_chunk,
                                )
                                for h in c.headings
                            ),
                        )
                        for c in article.chunks
                    ),
                ),
            )
            rows += article_chunk_rows(
                manifest.version_id, article.path, chunk_set, tuple(article.tags)
            )
        return chunk_sets, rows


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadChunkUseCase:
    """Implements ``ports.driving.ReadChunk``."""

    versions: SearchableVersions
    """Resolves the chunk's version to its active manifest."""
    manifests: ActiveManifests
    """What the catalog says about the manifests that hold the chunk."""
    chunks: ChunkRepository
    """Reads the chunk and the manifests that hold it."""
    renames: RenamedPaths | None = None
    """Where a stale chunk's article went; without it only the old path is tried."""
    suggestions: ArticleSuggestions | None = None
    """The version's paths closest to a stale chunk's article when that is gone; none without it."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Serve the chunk from its version's active manifest, or say why it cannot be served.

        Args:
            query: The chunk ID.

        Returns:
            The chunk.

        Raises:
            StaleChunkError: The ID is of a superseded manifest of a version that still exists.
            ChunkNotFoundError: No version serves the ID (unknown, still pending, or collected).
        """
        chunk_id = ChunkId(query.chunk_id)
        holders = await self.chunks.manifests_with_chunk(chunk_id)
        # The ID is a hash of the version it was issued for, so all holders share one version_id.
        # Anything else is not a state we understand: refuse rather than guess from the first row.
        if len({m.version_id for m in holders}) != 1:
            raise ChunkNotFoundError(query.chunk_id)
        first = holders[0]
        if not await self.access.allows(first.library, Access.READ):
            raise ChunkNotFoundError(query.chunk_id)
        ref = first.version_id.removeprefix(f"{first.library}/")
        version = await self.versions.find(first.library, ref)
        ids = {m.manifest_id for m in holders}
        if version is not None and version.manifest_id in ids:
            stored = await self.chunks.get(version.manifest_id, chunk_id)
            if (
                stored is not None
                and stored.version_id == f"{version.library.lower()}/{version.version}"
            ):
                return ChunkOut.from_stored(version, stored)
        # Note: manifests the catalog already collected (E9-03) are unknown to it, so after
        # collection an old ID reports not_found, not stale, until tombstones keep them (E9-03).
        # Those must keep the old path, headings, occurrence and content hash too, or the new
        # location (E7-09) is lost with the manifest.
        statuses = await self.manifests.statuses(ids)
        superseded = [i for i, s in statuses.items() if s is ManifestStatus.SUPERSEDED]
        if superseded:
            # Any superseded holder gives the same old chunk (the ID hashes its content); the
            # smallest ID keeps the choice deterministic.
            moved = await self._moved(version, ChunkId(query.chunk_id), min(superseded))
            close = (
                await self._closest(version, ChunkId(query.chunk_id), min(superseded))
                if moved is None
                else ()
            )
            raise StaleChunkError(query.chunk_id, first.library, ref, moved, close)
        raise ChunkNotFoundError(query.chunk_id)  # only pending manifests hold it: not served yet

    async def _closest(
        self, version: SearchableVersion | None, chunk_id: ChunkId, old_manifest: str
    ) -> Sequence[str]:
        """Name the version's paths closest to a stale chunk's article, which it no longer has.

        Args:
            version: The version now, with its active manifest; ``None`` when it has none.
            chunk_id: The stale chunk ID.
            old_manifest: The manifest that held the chunk.

        Returns:
            The closest paths, best first; none when nothing is known.
        """
        if version is None or self.suggestions is None:
            return ()
        old = await self.chunks.get(old_manifest, chunk_id)
        if old is None:
            return ()
        target = DocTarget(library=version.library, version=version.version)
        return await self.suggestions.close_to(target, old.row.article_path)

    async def _moved(
        self, version: SearchableVersion | None, chunk_id: ChunkId, old_manifest: str
    ) -> MovedSection | None:
        """Find the stale chunk's section in the active manifest: two reads, one rename lookup.

        The article is the old path, or where the rename map put it. The rename map covers one hop
        (the active manifest against the version before it), so an ID several re-syncs old whose
        article moved earlier gets no location. The section is then picked by ``_pick``.

        Args:
            version: The version now, with its active manifest; ``None`` when it has none.
            chunk_id: The stale chunk ID.
            old_manifest: The manifest that held the chunk.

        Returns:
            Where the section is now, or ``None`` when not even the article is found.
        """
        old = await self.chunks.get(old_manifest, chunk_id)
        if version is None or old is None:
            return None
        path = old.row.article_path
        current = await self.chunks.article(version.manifest_id, path)
        if not current and self.renames is not None:
            target = DocTarget(library=version.library, version=version.version)
            # No rename known: keep the old path. Its article is empty, so the result is no
            # location rather than a guess.
            path = await self.renames.new_path(target, path) or path
            current = await self.chunks.article(version.manifest_id, path)
        if not current:
            return None  # the article is gone
        match = _pick(current, old.chunk, old.row.position)
        if match is None:
            return MovedSection(article_path=path)
        return MovedSection(
            article_path=path,
            chunk_id=match.chunk_id,
            heading_path=match.heading_path,
            anchor=match.anchor,
            text_changed=match.content_hash != old.chunk.content_hash,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ArticleOutlineUseCase:
    """Implements ``ports.driving.ArticleOutline``."""

    versions: SearchableVersions
    """Which version answers: the exact ref, or the default one."""
    refs: VersionRefs | None = None
    """The library's refs: a ref's other ``v`` spelling, and the refs a miss names."""
    chunks: ChunkRepository
    """The article's chunk rows in that version's active manifest."""
    suggestions: ArticleSuggestions | None = None
    """Close paths for a miss, as ``read_article`` lists them; none without it."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ArticleOutlineQuery) -> ArticleOutlineOut:
        """Build the outline from the article's chunk rows in the version's active manifest.

        Args:
            query: The library, the exact ref (or none for the default version) and the path.

        Returns:
            The heading tree with a chunk ID per heading and the version that answered.

        Raises:
            ArticleNotFoundError: The version has no article at this path.
        """
        await _require(self.access, query.library, Access.READ)
        version = await _asked_version(self.versions, self.refs, query.library, query.ref)
        sections = await self.chunks.article(version.manifest_id, query.path)
        if not sections:
            target = DocTarget(library=version.library, version=version.version)
            close = await self.suggestions.close_to(target, query.path) if self.suggestions else ()
            raise ArticleNotFoundError(version.library, version.version, query.path, close)
        return ArticleOutlineOut.from_model(
            version, query.path, outline(sections), chunks=len(sections)
        )


def _nearest(sections: Sequence[SectionRef], position: int) -> SectionRef | None:
    """Return the section nearest to ``position``; ``None`` when two are equally near.

    Args:
        sections: The candidate sections.
        position: The old chunk's position.

    Returns:
        The nearest section, or ``None``.
    """
    ranked = sorted(sections, key=lambda s: abs(s.position - position))
    if len(ranked) > 1 and abs(ranked[0].position - position) == abs(ranked[1].position - position):
        return None
    return ranked[0] if ranked else None


def _pick(current: Sequence[SectionRef], was: Chunk, position: int) -> SectionRef | None:
    """Pick the section of ``current`` that ``was`` became, or ``None`` if unsure.

    In order: same headings and same text; same section (headings and occurrence: text edited);
    same text anywhere. Several equal candidates go to the nearest position, and a tie names no
    section: an ambiguous answer is better than a wrong ID. The occurrence alone is not trusted
    with the text unchecked, since an inserted duplicate heading shifts it onto another section.
    A section is ``(heading_path, occurrence_index)`` whether or not it is split into parts
    (#141): of the same section, the same part is picked, else its first part, which holds the
    heading. So a section that grows past the size bound and is split moves no other section.

    Known limit: if a duplicate heading is inserted above *and* the old section's text is
    edited too, the occurrence step lands on the inserted section. The match is then marked
    ``text_changed``, so the agent is told to re-check it.

    Args:
        current: The sections of the article in the active manifest.
        was: The stale chunk.
        position: Its position in the old article.

    Returns:
        The section, or ``None``.
    """
    same_headings = [s for s in current if s.heading_path == was.heading_path]
    same_text = [s for s in current if s.content_hash == was.content_hash]
    if both := [s for s in same_headings if s in same_text]:
        return _nearest(both, position)
    if section := [s for s in same_headings if s.occurrence_index == was.occurrence_index]:
        return next((s for s in section if s.part == was.part), section[0])
    return _nearest(same_text, position)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetChunkSetsUseCase:
    """Implements ``ports.driving.GetChunkSets``."""

    chunks: ChunkRepository
    """Reads the stored chunk sets."""

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Look the sets up by (blob, config); sets that were never stored are left out.

        Args:
            query: The chunking config and the blobs.

        Returns:
            The stored chunks of each blob that has them.
        """
        found = await self.chunks.get_sets(
            [(sha, query.config_hash) for sha in dict.fromkeys(query.blob_shas)]
        )
        return ChunkSetsOut(
            chunks={
                sha: [
                    SetChunkOut(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
                        part=c.part,
                        content=c.content,
                        content_hash=c.content_hash,
                        anchor=c.anchor,
                        code_languages=list(c.code_languages),
                        headings=None
                        if c.headings is None
                        else [
                            ChunkHeadingOut(
                                heading_path=list(h.heading_path),
                                anchor=h.anchor,
                                starts_chunk=h.starts_chunk,
                            )
                            for h in c.headings
                        ],
                    )
                    for c in chunk_set.chunks
                ]
                for (sha, _), chunk_set in found.items()
            }
        )


async def _removed(
    chunks: ChunkRepository,
    hypotheses: HypotheticalAnswerCache,
    doomed: Sequence[str],
    answers: AgentAnswerCache | None = None,
    external: ExternalIndexes | None = None,
) -> RemovedChunks:
    """Remove manifests' chunks, then the cached answers for them (a changed version invalidates).

    The external backends go first: if one does not answer, nothing is deleted and the job
    fails, so the next collection finds the manifests again and retries.

    Args:
        chunks: The chunk store.
        hypotheses: HyDE's cached answers.
        doomed: The manifests to remove.
        answers: The agentic answer cache, if any.
        external: The external backends, if any.

    Returns:
        What was removed.
    """
    if external is not None:
        await external.forget(doomed)
    removed = await chunks.remove(doomed)
    if doomed:
        await hypotheses.forget(doomed)
        if answers is not None:
            await answers.forget(doomed)
    return RemovedChunks.from_model(removed)


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardPendingChunksUseCase:
    """Implements ``ports.driving.DiscardPendingChunks``."""

    manifests: ActiveManifests
    """What the catalog says about the manifests."""
    chunks: ChunkRepository
    """Finds and deletes the chunk rows."""
    clock: Clock
    """The time, for the grace period and ``older_than_seconds``."""
    hypotheses: HypotheticalAnswerCache = field(default_factory=NoHypothesisCache)
    """HyDE's cached answers: those of a removed manifest go with its chunks."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answer cache: the answers of a removed manifest go with its chunks."""
    external: ExternalIndexes | None = None
    """The external backends: a removed manifest is deleted from them first."""

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Delete rows of matching manifests the catalog holds as pending, or dropped long ago.

        Args:
            command: Which manifests: by ID, by library or by age.

        Returns:
            What was deleted.
        """
        now = self.clock.now()
        older = command.older_than_seconds
        candidates = await self.chunks.find_manifests(
            manifest_id=command.manifest_id,
            library=None if command.library is None else command.library.lower(),
            indexed_before=None if older is None else now - timedelta(seconds=older),
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=True)
        return await _removed(self.chunks, self.hypotheses, doomed, self.answers, self.external)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectChunksUseCase:
    """Implements ``ports.driving.CollectChunks``.

    Also prunes HyDE's cache (``PruneHypothesesUseCase``), as the server does once a day.
    """

    manifests: ActiveManifests
    """What the catalog says about the manifests."""
    chunks: ChunkRepository
    """Finds and deletes the chunk rows and unused sets."""
    clock: Clock
    """The time, for the grace period."""
    hypotheses: HypotheticalAnswerCache = field(default_factory=NoHypothesisCache)
    """HyDE's cached answers: those of a removed manifest go with its chunks."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answer cache: the answers of a removed manifest go with its chunks."""
    external: ExternalIndexes | None = None
    """The external backends: a removed manifest is deleted from them first."""
    prune: PruneHypothesesUseCase | None = None
    """Prunes HyDE's cache by age and model; without it the cache is not pruned here."""

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run after the catalog's collection: its superseded manifests are gone, so are ours.

        Args:
            command: The grace period.

        Returns:
            What was deleted.
        """
        now = self.clock.now()
        cutoff = now - timedelta(seconds=command.grace_seconds)
        candidates = await self.chunks.find_manifests(
            manifest_id=None, library=None, indexed_before=cutoff
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=False)
        removed = await _removed(self.chunks, self.hypotheses, doomed, self.answers, self.external)
        if self.prune is not None:
            await self.prune()
        return removed


@dataclass(frozen=True, slots=True, kw_only=True)
class PruneHypothesesUseCase:
    """Implements ``ports.driving.PruneHypotheses``.

    Deletes HyDE's answers older than ``ttl``, and those of an ``llm`` model no longer
    configured (neither the instance's nor any library's override, or its profile is gone).
    Also the agentic answer cache's (``answers``): those older than ``answers_ttl``, of an
    ``llm`` model no longer configured, or compared in another space than the configured
    embedding model's (``caching.similarity_space``); every one while the cache is off
    (``caching`` is ``None``: ``enabled = false``, or no secret key).
    """

    hypotheses: HypotheticalAnswerCache
    """HyDE's cached answers."""
    providers: AiProviders
    """Names the ``llm`` models still configured."""
    clock: Clock
    """Decides the TTL's cutoff."""
    ttl: timedelta = timedelta(days=HYDE_CACHE_TTL_DAYS)
    """How long a cached hypothetical answer is kept (``[ai.hyde] cache_ttl``)."""
    caching: AgentAnswerCaching | None = None
    """Looks up and stores agentic answers; ``None``: the cache is off."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answers stored, pruned whether the cache is on or off."""
    answers_ttl: timedelta = timedelta(days=DEFAULT_AGENT_CACHE_TTL_DAYS)
    """How long a cached agentic answer is kept (``[ai.agentic_cache] ttl``)."""

    async def __call__(self) -> PrunedHypothesesOut:
        """Prune the caches.

        Returns:
            How many answers were deleted, of each cache.
        """
        kept = await _llm_models(self.providers)
        now = self.clock.now()
        deleted = await self.hypotheses.prune(now - self.ttl, kept)
        if deleted:
            logger.info("pruned %d cached hypothetical answers", deleted)
        if self.caching is None:  # off: none of its answers is kept
            answers = await self.answers.prune(now, (), "")
        else:
            space = await self.caching.similarity_space()
            answers = await self.answers.prune(now - self.answers_ttl, kept, space)
        if answers:
            logger.info("pruned %d cached agentic answers", answers)
        return PrunedHypothesesOut(deleted=deleted, agentic_answers=answers)


async def _llm_models(providers: AiProviders) -> set[str]:
    """Name the ``llm`` models a HyDE search may use now.

    Args:
        providers: The profiles, the instance's roles and the libraries' overrides.

    Returns:
        The instance's and every library override's ``<profile>:<model>`` whose profile exists.
    """
    refs = set(await providers.library_modes.llm_overrides())
    if (instance := providers.roles.explicit(ModelRole.LLM)) is not None:
        refs.add(str(instance))
    return {r for r in refs if await providers.profile(ModelRef.parse(r).profile) is not None}


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveChunksUseCase:
    """Implements ``ports.driving.RemoveChunks``."""

    manifests: ActiveManifests
    """What the catalog still knows: those manifests are kept."""
    chunks: ChunkRepository
    """Deletes the chunk rows and unused sets."""
    hypotheses: HypotheticalAnswerCache = field(default_factory=NoHypothesisCache)
    """HyDE's cached answers: those of a removed manifest go with its chunks."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answer cache: the answers of a removed manifest go with its chunks."""
    external: ExternalIndexes | None = None
    """The external backends: a removed manifest is deleted from them first."""

    async def __call__(self, command: RemoveChunksCommand) -> RemovedChunks:
        """Remove what the catalog has forgotten; keep every manifest it still knows.

        Args:
            command: The manifests the catalog deleted.

        Returns:
            What was deleted.
        """
        asked = list(dict.fromkeys(command.manifest_ids))
        known = await self.manifests.statuses(asked)
        gone = [i for i in asked if i not in known]
        return await _removed(self.chunks, self.hypotheses, gone, self.answers, self.external)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetagArticlesUseCase:
    """Implements ``ports.driving.RetagArticles``."""

    chunks: ChunkRepository
    """Holds the chunk rows' tag copies."""
    external: ExternalIndexes | None = None
    """The external backends, whose entries carry the tags too."""

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Overwrite the tag copies of the named articles' chunk rows (and their external entries).

        The external entries are written whether or not a row changed: a re-tag retried after a
        backend failed finds the rows already changed, and must still write the entries.

        Args:
            command: The manifest and each article's current tags.

        Returns:
            How many chunk rows got other tags.
        """
        tags = {a.path: tuple(dict.fromkeys(a.tags)) for a in command.articles}
        changed = await self.chunks.set_tags(command.manifest_id, tags)
        if self.external is not None and tags:
            await self.external.refresh(command.manifest_id, frozenset(tags))
        return RetaggedChunks(chunks=changed)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSearchIndexStateUseCase:
    """Implements ``ports.driving.GetSearchIndexState``."""

    maintenance: SearchIndexMaintenance
    """Reads the index's format."""

    async def __call__(self) -> SearchIndexStateOut:
        """Report the stored format against the current one.

        Returns:
            The stored and current formats, and the engine.
        """
        return SearchIndexStateOut.from_model(await self.maintenance.state())


@dataclass(frozen=True, slots=True, kw_only=True)
class GetVectorStoreStateUseCase:
    """Implements ``ports.driving.GetVectorStoreState``."""

    modes: RetrievalModes
    """The roles configured and the vector store the hybrid modes search."""

    async def __call__(self) -> VectorStoreStateOut:
        """Check the store only when the instance embeds (the embedding model is instance-wide).

        Returns:
            What the store needs, and whether it can search (``None``: not checked).
        """
        vectors = self.modes.vectors
        if vectors is None:
            return VectorStoreStateOut(requirement=None, available=None)
        # A library without overrides: the instance's roles (no library overrides the embedder).
        roles = await self.modes.roles.configured("", LibraryAi())
        if ModelRole.EMBEDDING not in roles:
            return VectorStoreStateOut(requirement=vectors.requirement(), available=None)
        return VectorStoreStateOut(
            requirement=vectors.requirement(), available=await vectors.available()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RebuildSearchIndexUseCase:
    """Implements ``ports.driving.RebuildSearchIndex``."""

    maintenance: SearchIndexMaintenance
    """Rebuilds the index."""

    async def __call__(self) -> RebuiltIndexOut:
        """Build the new index beside the old one, then swap it in.

        Returns:
            The format the index is now in and how many chunks it holds.
        """
        return RebuiltIndexOut.from_model(await self.maintenance.rebuild())


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveLibraryIdUseCase:
    """Implements ``ports.driving.ResolveLibraryId``."""

    libraries: Libraries
    """The catalog's libraries, matched by name."""
    versions: SearchableVersions
    """Resolves each match's default version."""
    search: SearchIndex
    """Counts each default version's chunks matching the query."""
    chunks: ChunkRepository
    """Counts each default version's articles and chunks."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Match the name, then let the default versions' hits for ``query`` re-rank the matches.

        Args:
            query: The library name and what the caller wants to look up.

        Returns:
            The matching libraries, best first.
        """
        # A blank name is refused (EmptySearchTextError); no query ranks by name alone, as
        # context7 does with an empty one (#573).
        name = SearchText(value=query.library_name)
        text = SearchText(value=query.query) if query.query else None
        mode = RetrievalMode.BM25.value
        with self.tracer.span(
            "resolve_library_id", mode=mode, query=text.value if text else name.value
        ):
            return await self._resolve(text, name, mode)

    async def _resolve(
        self, text: SearchText | None, name: SearchText, mode: str
    ) -> ResolveLibraryIdResult:
        """Match the names, then rank them by their hits, one span per stage.

        Args:
            text: The validated query text; ``None``: no hits are counted.
            name: The validated library name.
            mode: The retrieval mode the hits are found in.

        Returns:
            The matching libraries, best first.
        """
        with self.tracer.span("resolve_library_id.versions", mode=mode):
            named = [
                (lib, found)
                for lib in await self.libraries.all()
                if (found := name_match(name.value, lib)) is not None
            ]
            # Pre-order by name only, so the cut keeps the best names; hits re-rank within it.
            named.sort(key=lambda m: (m[1], m[0].id))
            allowed = await self.access.readable([lib.id for lib, _ in named])
            named = [(lib, found) for lib, found in named if lib.id.casefold() in allowed]
            readable = await self._readable(named)
        with self.tracer.span("resolve_library_id.rank", mode=mode):
            hits = await asyncio.gather(
                *(
                    self.search.search(
                        version.manifest_id,
                        text.value,
                        TagFilter(tags=(), match=TagMatch.ANY),
                        QUERY_HITS_CAP,
                    )
                    if text is not None
                    else _no_hits()
                    for _, _, version in readable
                )
            )
        ranked = rank_matches(
            [
                Candidate(library=lib, match=found, hits=len(h))
                for (lib, found, _), h in zip(readable, hits, strict=True)
            ]
        )
        manifests = {lib.id: version.manifest_id for lib, _, version in readable}
        with self.tracer.span("resolve_library_id.chunks", mode=mode):
            counts = await asyncio.gather(
                *(self.chunks.counts(manifests[c.library.id]) for c in ranked)
            )
        return ResolveLibraryIdResult(
            matches=[
                LibraryMatchOut.from_candidate(c, n.articles, n.chunks)
                for c, n in zip(ranked, counts, strict=True)
            ]
        )

    async def _readable(
        self, named: Sequence[tuple[CatalogLibrary, NameMatch]]
    ) -> list[tuple[CatalogLibrary, NameMatch, SearchableVersion]]:
        """Take the best names that have a readable default version, ``MAX_RESOLVED`` at most.

        Libraries with nothing imported are dropped before the cut, so they cost no slot.

        Args:
            named: The libraries whose name matched, best name first.

        Returns:
            Each kept library with its match and default version.
        """
        found: list[tuple[CatalogLibrary, NameMatch, SearchableVersion]] = []
        for start in range(0, len(named), MAX_RESOLVED):
            batch = named[start : start + MAX_RESOLVED]
            versions = await asyncio.gather(*(self.versions.find(lib.id, None) for lib, _ in batch))
            found += [(lib, m, v) for (lib, m), v in zip(batch, versions, strict=True) if v]
            if len(found) >= MAX_RESOLVED:
                break
        return found[:MAX_RESOLVED]


async def _no_hits() -> Sequence[SearchHit]:
    """Stand in for a search not made: a ``resolve-library-id`` without a query counts no hits.

    Returns:
        No hits.
    """
    return ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveLibraryNameUseCase:
    """Implements ``ports.driving.ResolveLibraryName``."""

    libraries: Libraries
    """The catalog's libraries, matched by name."""
    access: AccessPolicy
    """Decides what the caller may read: other libraries are never named or picked."""

    async def __call__(self, query: ResolveLibraryNameQuery) -> ResolvedLibraryOut:
        """Pick the one readable library the name means, as ``resolve-library-id`` matches names.

        Args:
            query: The name.

        Returns:
            The library's ID.
        """
        named = [
            Candidate(library=lib, match=found)
            for lib in await self.libraries.all()
            if (found := name_match(query.name, lib)) is not None
        ]
        allowed = await self.access.readable([c.library.id for c in named])
        readable = [c for c in named if c.library.id.casefold() in allowed]
        return ResolvedLibraryOut(name=query.name, id=named_library(query.name, readable).id)


def _cost(section: DocSectionOut) -> int:
    """Characters a section takes in the payload: its parts plus the fixed framing.

    Args:
        section: The section.

    Returns:
        Its size in characters.
    """
    pointer = len(POINTER_TEXT) if section.too_large else 0
    return (
        SECTION_FRAMING_CHARS
        + len(section.title)
        + len(section.source)
        + len(section.chunk_id)
        + len(section.content)
        + pointer
    )


def _pack(sections: Sequence[DocSectionOut], room: int) -> list[DocSectionOut]:
    """Take sections in order while they fit ``room``; a chunk that never could becomes a pointer.

    A chunk is never cut. One that merely finds the room used up is skipped, and a smaller one
    after it may still fit.

    Args:
        sections: The sections, best first.
        room: The characters left for them.

    Returns:
        The sections kept, in order, some of them pointers.
    """
    used, kept = 0, []
    for section in sections:
        shown = section if _cost(section) <= room else section.as_pointer()
        if used + _cost(shown) <= room:
            kept.append(shown)
            used += _cost(shown)
    return kept


def _fit_rules(rules: Sequence[str], room: int) -> list[str]:
    """Take the library's rules in order until one does not fit ``room``; they precede any chunk.

    The agent sees a prefix of what the authors wrote, never a later rule without an earlier one.

    Args:
        rules: The library's rules, in order.
        room: The characters the rules may take.

    Returns:
        The leading rules that fit.
    """
    used, kept = RULES_FRAMING_CHARS, []
    for rule in rules:
        if used + RULE_FRAMING_CHARS + len(rule) > room:
            break
        kept.append(rule)
        used += RULE_FRAMING_CHARS + len(rule)
    return kept


@dataclass(frozen=True, slots=True, kw_only=True)
class QueryDocsUseCase:
    """Implements ``ports.driving.QueryDocs``."""

    versions: SearchableVersions
    """Resolves the library ID to the version's active manifest."""
    refs: VersionRefs | None = None
    """The library's refs: a ref's other ``v`` spelling, and the refs a miss names."""
    modes: RetrievalModes
    """Picks the mode (the library's, else the instance's) and runs its pipeline."""
    chunks: ChunkRepository
    """Reads the hits' chunks."""
    token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET
    """Size budget of an answer, in estimated tokens."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(
        self, query: QueryDocsQuery, *, caller: str | None = None
    ) -> QueryDocsResult:
        """Answer from exactly one version, with whole chunks that fit the budget, best first.

        The budget covers the whole payload: the notice, the sections and the closing line. A
        chunk that could never fit is listed as a pointer (no text, ``too_large``) so the agent
        can fetch it; one that merely found no room left is counted in ``omitted``. The
        library's rules (from its ``context7.json``) come first and are counted too; they take
        at most a ``RULES_SHARE``-th of the room: whole rules, a prefix of the list.

        Args:
            query: The library ID and the question.
            caller: The account asking; ``None`` for a stdio MCP process.

        Returns:
            The packed sections of the one version.
        """
        text = SearchText(value=query.query)
        # `/owner/repo` or `/owner/repo/<ref>`; a ref may itself contain slashes.
        _, owner, repo, *rest = query.library_id.split("/", 3)
        ref = rest[0] if rest else None
        library = f"/{owner}/{repo}"
        await _require(self.access, library, Access.READ)
        # context7's tool has no mode argument: the library's mode, else the instance's (C7-02).
        choice = await self.modes.choose(asked=None, library=library)
        with self.tracer.span(
            QUERY_DOCS, mode=choice.mode.value, query=text.value, library=library, ref=ref
        ) as whole:
            return await self._answer(query, text, library, ref, choice, whole, caller)

    async def _answer(
        self,
        query: QueryDocsQuery,
        text: SearchText,
        library: str,
        ref: str | None,
        choice: ModeChoice,
        whole: SearchSpan,
        caller: str | None,
    ) -> QueryDocsResult:
        """Resolve the version, rank, load the chunks and pack them, one span per stage.

        Args:
            query: The request as asked.
            text: Its validated query text.
            library: The library ID it names.
            ref: The version it names; ``None`` for the default version.
            choice: The retrieval mode it runs in.
            whole: The search's span, told which mode answered.
            caller: The account asking.

        Returns:
            The packed sections of the one version searched.
        """
        mode = choice.mode.value
        with self.tracer.span(f"{QUERY_DOCS}.version", mode=mode):
            version = await _asked_version(self.versions, self.refs, library, ref)
        # Only a request that will run counts against the caller's limits.
        everything = TagFilter(tags=(), match=TagMatch.ANY)
        choice = await self.modes.within_budget(
            choice,
            library=version.library,
            caller=caller,
            version=version,
            query=text.value,
            tag_filter=everything,
            limit=QUERY_DOCS_CANDIDATES,
        )
        mode = choice.mode.value
        with self.tracer.span(f"{QUERY_DOCS}.rank", mode=mode) as rank:
            answer = await self.modes.run(
                choice, version, text.value, everything, QUERY_DOCS_CANDIDATES, search=QUERY_DOCS
            )
            rank.answered_by(answer.mode.value)
        whole.answered_by(answer.mode.value)
        read: Mapping[ChunkId, StoredChunk] = {}
        if choice.rerank:  # a stage of its own; it records neither the query nor any text
            stage = "judge" if choice.reranker is RerankWith.JUDGE else "rerank"
            with self.tracer.span(f"{QUERY_DOCS}.{stage}", mode=answer.mode.value):
                answer, read = await self.modes.rerank(choice, version, text.value, answer)
        answer = answer.cut(QUERY_DOCS_CANDIDATES)
        if answer.fallback_reason is not None:
            self.tracer.fallback(mode=answer.mode.value, reason=answer.fallback_reason.value)
        with self.tracer.span(f"{QUERY_DOCS}.chunks", mode=answer.mode.value):
            stored = await _chunks_of(self.chunks, version, answer, read)
        sections = [
            DocSectionOut.from_stored(version, stored[hit.chunk_id])
            for hit in answer.hits
            if hit.chunk_id in stored
        ]
        if query.language:
            sections = language_first(sections, lambda s: s.code_languages, query.language)
        budget = self.token_budget * CHARS_PER_TOKEN
        room = budget - len(NOTICE) - FOOTER_CHARS
        rules = _fit_rules(version.rules, room // RULES_SHARE)
        if rules:
            room -= RULES_FRAMING_CHARS + sum(RULE_FRAMING_CHARS + len(r) for r in rules)
        kept = _pack(sections, room)
        return QueryDocsResult(
            library=version.library,
            version=version.version,
            commit_sha=version.commit_sha,
            retrieval_mode=answer.mode,
            reranked=answer.reranked > 0,
            fallback_reason=answer.fallback_reason,
            cache_hit=answer.cache_hit,
            sections=kept,
            omitted=len(sections) - len(kept),
            budget_chars=budget,
            rules=rules,
        )


async def _library_retrieval(
    modes: RetrievalModes, library: str, mode: RetrievalMode | None, ai: LibraryAi
) -> LibraryRetrievalOut:
    """Describe a library's setting and what a search without ``mode`` would run in now.

    Args:
        modes: The instance's modes.
        library: The library's ID as the catalog spells it.
        mode: The library's setting.
        ai: The library's AI overrides.

    Returns:
        The setting, the effective mode and the modes on offer.
    """
    registry = await modes.registry(library, ai)
    choice = registry.choose(asked=None, library=mode, instance=modes.instance_mode)
    budgets = modes.spend.budgets if modes.spend is not None else Budgets()
    return LibraryRetrievalOut(
        library=library,
        mode=mode,
        instance_mode=modes.instance_mode,
        effective_mode=choice.mode,
        fallback_reason=choice.fallback_reason,
        available_modes=list(registry.available()),
        configured_roles=[r for r in ModelRole if r in registry.roles],
        ai_enabled=ai.enabled,
        llm=_ref_text(ai.llm),
        judge=_ref_text(ai.judge),
        reranker=_ref_text(ai.reranker),
        llm_thinking=ai.llm_thinking,
        judge_thinking=ai.judge_thinking,
        rerank_top_n=ai.rerank_top_n,
        effective_rerank_top_n=modes.rerank_top_n(ai),
        rerank_with=ai.rerank_with,
        instance_rerank_with=modes.rerank_with,
        effective_reranker=modes.reranker_of(registry.roles, ai),
        budgets=LibraryBudgets.from_limits(ai.budgets),
        budget_ceilings=LibraryBudgets.from_ceilings(
            budgets.ceiling(SpendWindow.DAY), budgets.ceiling(SpendWindow.MONTH)
        ),
        repo_guidance=ai.repo_guidance,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLibraryRetrievalUseCase:
    """Implements ``ports.driving.GetLibraryRetrieval``."""

    libraries: Libraries
    """Spells the library ID as the catalog does."""
    modes: RetrievalModes
    """The instance's modes and the libraries' settings."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        """Read the library's mode and the one its searches use now.

        Args:
            query: The library.

        Returns:
            Its setting, the effective mode and the modes available.

        Raises:
            UnknownLibraryError: There is no such library.
        """
        await _require(self.access, query.library, Access.READ)
        library = await self.libraries.canonical_id(query.library)
        if library is None:
            raise UnknownLibraryError(query.library)
        mode = await self.modes.library_modes.mode_of(library)
        ai = await self.modes.library_modes.ai_of(library)
        return await _library_retrieval(self.modes, library, mode, ai)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetLibraryRetrievalUseCase:
    """Implements ``ports.driving.SetLibraryRetrieval``."""

    libraries: Libraries
    """Spells the library ID as the catalog does."""
    modes: RetrievalModes
    """The instance's modes and the libraries' settings."""
    providers: AiProviders
    """The profiles an override may name."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answer cache: a library's answers go when its settings are saved."""
    access: AccessPolicy
    """Decides what the caller may do with the library."""

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Validate the settings against what can run with them, then store them.

        A thinking level of the library's own that its model cannot take is refused too
        (``ThinkingUnsupportedError``, from ``AiProviders.refuse_unsupported_thinking``).

        Args:
            command: The library, its mode and its AI overrides.

        Returns:
            The stored settings, the effective mode and the modes available.

        Raises:
            UnknownLibraryError: There is no such library.
            UnknownProviderError: An override names a profile that does not exist.
            ProviderUnsupportedError: An override names a profile this installation cannot call.
        """
        await _require(self.access, command.library, Access.ADMINISTER)
        library = await self.libraries.canonical_id(command.library)
        if library is None:
            raise UnknownLibraryError(command.library)
        ai = LibraryAi(
            enabled=command.ai_enabled,
            llm=_parse_ref(command.llm),
            judge=_parse_ref(command.judge),
            reranker=_parse_ref(command.reranker),
            llm_thinking=command.llm_thinking,
            judge_thinking=command.judge_thinking,
            rerank_top_n=command.rerank_top_n,
            rerank_with=command.rerank_with,
            budgets=command.budgets.limits(),
            repo_guidance=command.repo_guidance,
        )
        if self.modes.spend is not None:
            stored = await self.modes.library_modes.ai_of(library)
            self.modes.spend.budgets.check_library(ai.budgets, stored.budgets)
        for name in sorted(ai.profiles()):
            profile = await self.providers.profile(name)
            if profile is None:
                raise UnknownProviderError(name)
            if (reason := self.providers.factory.unsupported(profile)) is not None:
                raise ProviderUnsupportedError(name, reason)
        # Only the library's own levels are refused here: the instance's were checked when set.
        await self.providers.refuse_unsupported_thinking(
            _without_thinking(self.providers.roles), ai
        )
        mode = None
        if command.mode is not None:
            mode = (await self.modes.registry(library, ai)).check(command.mode)
        await self.modes.library_modes.save(library, mode, ai)
        await self.answers.forget_library(library)  # its settings may change what the agent finds
        return await _library_retrieval(self.modes, library, mode, ai)


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetLibraryUseCase:
    """Implements ``ports.driving.ForgetLibrary``."""

    library_modes: LibraryModes
    """Each library's own mode, dropped with the library."""
    answers: AgentAnswerCache = field(default_factory=NoAgentAnswerCache)
    """The agentic answer cache: the library's answers are dropped too."""

    async def __call__(self, command: ForgetLibraryCommand) -> None:
        """Drop what retrieval keeps per library, so a library re-added later starts clean.

        Args:
            command: The removed library.
        """
        await self.library_modes.forget(command.library)
        await self.answers.forget_library(command.library)


def _ref_text(ref: ModelRef | None) -> str | None:
    """Write a model reference back as text.

    Args:
        ref: The reference.

    Returns:
        ``<profile>:<model>``, or ``None``.
    """
    return None if ref is None else str(ref)


def _parse_ref(text: str | None) -> ModelRef | None:
    """Read an optional ``<profile>:<model>``.

    Args:
        text: The text, or ``None``.

    Returns:
        The reference, or ``None``.
    """
    return None if text is None else ModelRef.parse(text)


@dataclass(frozen=True, slots=True, kw_only=True)
class NoStoredThinking:
    """Implements ``ports.driven.RoleThinkingLevels`` for a process that stores none."""

    async def levels(self) -> Mapping[ModelRole, ThinkingLevel]:
        """Read nothing.

        Returns:
            No level.
        """
        return {}

    async def save(self, role: ModelRole, level: ThinkingLevel | None) -> None:
        """Store nothing: such a process serves no REST API.

        Args:
            role: The role.
            level: The level.
        """
        del role, level


@dataclass(frozen=True, slots=True, kw_only=True)
class NoStoredProfiles:
    """Implements ``ports.driven.ProviderProfiles`` for a process that stores none (read-only)."""

    async def all(self) -> Sequence[ProviderProfile]:
        """List nothing.

        Returns:
            No profile.
        """
        return ()

    async def get(self, name: str) -> ProviderProfile | None:
        """Find nothing.

        Args:
            name: The name asked for.

        Returns:
            ``None``.
        """
        del name
        return None

    async def save(self, profile: ProviderProfile) -> None:
        """Refuse to store.

        Args:
            profile: The profile.

        Raises:
            SecretKeyRequiredError: Always; this process cannot store profiles.
        """
        del profile
        raise SecretKeyRequiredError

    async def delete(self, name: str) -> bool:
        """Delete nothing.

        Args:
            name: The name asked for.

        Returns:
            False.
        """
        del name
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class NoModelFactory:
    """Implements ``ports.driven.ModelFactory`` for a build that calls no model."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say that nothing can be called.

        Args:
            profile: The profile.

        Returns:
            A fixed text.
        """
        del profile
        return "this process calls no AI model"

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        """Refuse.

        Args:
            profile: The profile.
            model: The model.
            thinking: The level (unused).

        Returns:
            Nothing: it raises ``ProviderUnsupportedError``.
        """
        del thinking
        return self._refuse(profile, model)

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        """Know nothing about any model.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            ``None``: that cannot be known here.
        """
        del profile, model
        return None

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Refuse.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            Nothing: it raises ``ProviderUnsupportedError``.
        """
        return self._refuse(profile, model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        """Refuse.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            Nothing: it raises ``ProviderUnsupportedError``.
        """
        return self._refuse(profile, model)

    async def release(self, name: str) -> None:
        """Hold nothing, so release nothing.

        Args:
            name: The profile's name.
        """
        del name

    def _refuse(self, profile: ProviderProfile, model: str) -> NoReturn:
        """Refuse to build a model.

        Args:
            profile: The profile.
            model: The model.

        Raises:
            ProviderUnsupportedError: Always.
        """
        del model
        raise ProviderUnsupportedError(profile.name, "this process calls no AI model")

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        """Report that nothing can be called.

        Args:
            profile: The profile.
            model: The model.
            role: The role.
            thinking: The level (unused).

        Returns:
            A failed check.
        """
        del thinking
        return ModelCheck(
            role=role,
            profile=profile.name,
            model=model,
            ok=False,
            error=self.unsupported(profile),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AiProviders:
    """The instance's AI configuration: profiles (configured and stored), roles and overrides.

    Configured profiles (the environment, the TOML file) are read-only and shadow a stored one of
    the same name. Everything is read at each call, so a profile edited over the REST API counts
    at the next one without a restart.
    """

    configured: Sequence[ProviderProfile] = ()
    """The environment's and the file's profiles."""
    stored: ProviderProfiles = field(default_factory=NoStoredProfiles)
    """The profiles managed over the REST API."""
    roles: InstanceRoles = field(default_factory=InstanceRoles)
    """The instance's roles."""
    library_modes: LibraryModes
    """Each library's overrides."""
    factory: ModelFactory = field(default_factory=NoModelFactory)
    """Turns a profile into a callable model."""
    box: SecretBox | None = None
    """Seals keys sent over the REST API; ``None``: they cannot be stored."""
    thinking_levels: RoleThinkingLevels = field(default_factory=NoStoredThinking)
    """The roles' thinking levels set over the REST API (#421); a configured level wins."""

    async def instance_roles(self) -> InstanceRoles:
        """The instance's roles with the thinking levels stored over the REST API.

        A level set in the environment or the configuration file wins over a stored one.

        Returns:
            The roles.
        """
        stored = await self.thinking_levels.levels()
        return replace(
            self.roles,
            llm_thinking=self.roles.llm_thinking or stored.get(ModelRole.LLM),
            judge_thinking=self.roles.judge_thinking or stored.get(ModelRole.JUDGE),
        )

    async def bindings(self) -> list[RoleBinding]:
        """Resolve the instance's roles outside any library, with their thinking levels.

        Returns:
            One binding per role that is set (the judge may default to the LLM).
        """
        roles, defaults = await self.instance_roles(), LibraryAi()
        return [b for r in ModelRole if (b := bind_role(r, roles, defaults)) is not None]

    async def thinking_of(self, role: ModelRole, ai: LibraryAi) -> ThinkingLevel | None:
        """Resolve the thinking level a role's calls send for a library.

        Args:
            role: The role.
            ai: The library's overrides (the defaults outside any library).

        Returns:
            The level, or ``None`` for the provider's default.
        """
        binding = bind_role(role, await self.instance_roles(), ai)
        return None if binding is None else binding.thinking

    async def thinking_problem(self, binding: RoleBinding) -> str | None:
        """Say why a binding's model cannot take its thinking level, when that is known.

        Args:
            binding: The role, its model and its level.

        Returns:
            Why not, or ``None`` when it can, has no level, or that cannot be known.
        """
        if binding.thinking is None:
            return None
        profile = await self.profile(binding.ref.profile)
        if profile is None or self.factory.unsupported(profile) is not None:
            return None
        return await self.factory.thinking_unsupported(profile, binding.ref.model)

    async def refuse_unsupported_thinking(self, roles: InstanceRoles, ai: LibraryAi) -> None:
        """Refuse thinking levels the models they apply to cannot take.

        Args:
            roles: The instance's roles, with only the levels being saved.
            ai: The library's overrides, as they are about to be.

        Raises:
            ThinkingUnsupportedError: A role's model cannot take its level.
        """
        for role in (ModelRole.LLM, ModelRole.JUDGE):
            binding = bind_role(role, roles, ai)
            if binding is None or binding.thinking is None:
                continue
            if (reason := await self.thinking_problem(binding)) is not None:
                raise ThinkingUnsupportedError(role.value, str(binding.ref), reason)

    def configured_profile(self, name: str) -> ProviderProfile | None:
        """Find a configured profile.

        Args:
            name: Its name.

        Returns:
            The profile, or ``None``.
        """
        return next((p for p in self.configured if p.name == name), None)

    async def profile(self, name: str) -> ProviderProfile | None:
        """Find a profile: a configured one first, then a stored one.

        Args:
            name: Its name.

        Returns:
            The profile, or ``None``.
        """
        return self.configured_profile(name) or await self.stored.get(name)

    async def profiles(self) -> list[ProviderProfile]:
        """List every profile: the configured ones, then the stored ones they do not shadow.

        Returns:
            The profiles.
        """
        names = {p.name for p in self.configured}
        stored = [p for p in await self.stored.all() if p.name not in names]
        return [*sorted(self.configured, key=lambda p: p.name), *stored]

    def instance_bindings(self) -> list[RoleBinding]:
        """Resolve the instance's roles, outside any library.

        Returns:
            One binding per role that is set (the judge may default to the LLM).
        """
        defaults = LibraryAi()
        return [b for r in ModelRole if (b := bind_role(r, self.roles, defaults)) is not None]

    def roles_using(self, name: str) -> list[ModelRole]:
        """Name the instance roles set to one of a profile's models.

        Args:
            name: The profile's name.

        Returns:
            The roles.
        """
        return [b.role for b in self.instance_bindings() if b.ref.profile == name]

    async def configured_roles(self, ai: LibraryAi) -> frozenset[ModelRole]:
        """Say which roles resolve to an existing profile under some overrides.

        Args:
            ai: The library's overrides (the defaults outside any library).

        Returns:
            The roles; empty with AI off.
        """
        found: set[ModelRole] = set()
        for role in ModelRole:
            binding = bind_role(role, self.roles, ai)
            if binding is not None and await self.profile(binding.ref.profile) is not None:
                found.add(role)
        return frozenset(found)

    async def resolved(
        self, role: ModelRole, library: str, ai: LibraryAi | None = None
    ) -> tuple[ModelRef, str] | None:
        """Find the model a role uses for a library, and its profile's kind.

        Args:
            role: The role.
            library: The library ID, any letter case.
            ai: The library's overrides, when the caller read them already; ``None`` reads them.

        Returns:
            The model and the kind, or ``None`` when the role does not resolve.
        """
        found = await self.profile_for(role, library, ai)
        return None if found is None else (found[0], found[1].kind.value)

    async def profile_for(
        self, role: ModelRole, library: str, ai: LibraryAi | None = None
    ) -> tuple[ModelRef, ProviderProfile] | None:
        """Find the model a role uses for a library, and its profile as it is now.

        Args:
            role: The role.
            library: The library ID, any letter case.
            ai: The library's overrides, when the caller read them already; ``None`` reads them.

        Returns:
            The model and the profile, or ``None`` when the role does not resolve.
        """
        if ai is None:
            ai = await self.library_modes.ai_of(library)
        binding = bind_role(role, self.roles, ai)
        if binding is None:
            return None
        profile = await self.profile(binding.ref.profile)
        return None if profile is None else (binding.ref, profile)

    async def model_for(self, role: ModelRole, library: str) -> object | None:
        """Build the model a role uses for a library, from the profile as it is now.

        The path every AI pipeline takes (#91 onwards): resolve the role (the library's override,
        else the instance's), read the profile (so an edit over the REST API counts at once), and
        let the factory build it. A library with AI off gets nothing, and nothing is sent.

        Args:
            role: The role.
            library: The library ID, any letter case.

        Returns:
            An opaque handle, or ``None`` when the role does not resolve for the library.
        """
        roles = await self.instance_roles()
        binding = bind_role(role, roles, await self.library_modes.ai_of(library))
        if binding is None:
            return None
        profile = await self.profile(binding.ref.profile)
        if profile is None:
            return None
        match role:
            case ModelRole.EMBEDDING:
                return await self.factory.embedder(profile, binding.ref.model)
            case ModelRole.RERANKER:
                return await self.factory.reranker(profile, binding.ref.model)
            case ModelRole.LLM | ModelRole.JUDGE:
                return await self.factory.chat_model(
                    profile, binding.ref.model, thinking=binding.thinking
                )

    async def check(
        self, binding_role: ModelRole | None, ref: ModelRef, thinking: ThinkingLevel | None = None
    ) -> ModelCheck:
        """Make one minimal call, or say why it cannot be made.

        Args:
            binding_role: The role being checked; ``None`` when not a configured role.
            ref: The profile and model.
            thinking: A chat role's thinking level, as its calls send it.

        Returns:
            The outcome.
        """
        role = binding_role or ModelRole.LLM
        profile = await self.profile(ref.profile)
        if profile is None:
            return ModelCheck(
                role=binding_role,
                profile=ref.profile,
                model=ref.model,
                ok=False,
                error=f"no AI provider {ref.profile!r}",
            )
        if (reason := self.factory.unsupported(profile)) is not None:
            return ModelCheck(
                role=binding_role, profile=ref.profile, model=ref.model, ok=False, error=reason
            )
        return await self.factory.check(profile, ref.model, role, thinking=thinking)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileModelRoles:
    """Implements ``ports.driven.ModelRoles`` over the instance's profiles, roles and overrides.

    A role counts when it resolves (the library's override, else the instance's; the judge else
    the LLM) to a profile that exists. A library with AI off has none.
    """

    providers: AiProviders
    """The profiles, the roles and the overrides."""

    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        """Resolve every role for the library.

        Args:
            library: The library ID, any letter case.
            ai: Overrides about to be stored; ``None`` reads the stored ones.

        Returns:
            The roles its searches may use.
        """
        if ai is None:
            ai = await self.providers.library_modes.ai_of(library)
        return await self.providers.configured_roles(ai)


def _profile_from(
    command: SaveProviderCommand, key: KeySource, sealed_key: str | None
) -> ProviderProfile:
    """Build a stored profile from a REST command.

    Args:
        command: The command.
        key: Where its key comes from (``none`` or ``sealed``).
        sealed_key: The sealed key, if any.

    Returns:
        The profile (``InvalidProviderError`` when it is not valid for its kind).
    """
    return ProviderProfile(
        name=command.name,
        kind=ProviderKind.parse(command.name, command.kind),
        origin=ProfileOrigin.API,
        base_url=command.base_url,
        key=key,
        sealed_key=sealed_key,
        headers=tuple(command.headers.items()),
        proxy=command.proxy,
        request_timeout=command.request_timeout,
        max_retries=command.max_retries,
        api_version=command.api_version,
        project=command.project,
        location=command.location,
        credentials_file=command.credentials_file,
        adc=command.credentials == "adc",
        platform=command.platform,
        auth=command.auth,
        resource=command.resource,
    )


def _provider_out(providers: AiProviders, profile: ProviderProfile) -> ProviderOut:
    """Describe a profile with the roles that use it.

    Args:
        providers: The instance's AI configuration.
        profile: The profile.

    Returns:
        Its description, without secrets.
    """
    return ProviderOut.from_model(
        profile, providers.roles_using(profile.name), providers.factory.unsupported(profile)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListProvidersUseCase:
    """Implements ``ports.driving.ListProviders``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self) -> ProviderListOut:
        """List every profile.

        Returns:
            The profiles, without keys or header values.
        """
        profiles = await self.providers.profiles()
        return ProviderListOut(providers=[_provider_out(self.providers, p) for p in profiles])


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProviderUseCase:
    """Implements ``ports.driving.GetProvider``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self, query: ProviderNameQuery) -> ProviderOut:
        """Read one profile.

        Args:
            query: Its name.

        Returns:
            The profile.

        Raises:
            UnknownProviderError: There is none of that name.
        """
        profile = await self.providers.profile(query.name)
        if profile is None:
            raise UnknownProviderError(query.name)
        return _provider_out(self.providers, profile)


@dataclass(frozen=True, slots=True, kw_only=True)
class SaveProviderUseCase:
    """Implements ``ports.driving.SaveProvider``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self, command: SaveProviderCommand) -> ProviderOut:
        """Validate the profile, seal its key, store it.

        Args:
            command: The profile.

        Returns:
            The stored profile, without its key.

        Raises:
            ProviderReadOnlyError: A configured profile has the name.
            ProviderExistsError: ``create`` and a stored profile has the name.
            SecretKeyRequiredError: A key was sent and nothing can seal it.
            InvalidProviderError: The profile is not valid for its kind.
            ProviderUnsupportedError: This installation cannot call it.
        """
        providers = self.providers
        if providers.configured_profile(command.name) is not None:
            raise ProviderReadOnlyError(command.name)
        existing = await providers.stored.get(command.name)
        if command.create and existing is not None:
            raise ProviderExistsError(command.name)
        key, sealed = KeySource.NONE, None
        if command.api_key is not None:
            plaintext = command.api_key.get_secret_value().strip()
            if not plaintext:
                raise InvalidProviderError(command.name, "the key is empty")
            if providers.box is None:
                raise SecretKeyRequiredError
            key, sealed = KeySource.SEALED, providers.box.seal(plaintext)
        elif command.keep_key and existing is not None and existing.key is KeySource.SEALED:
            key, sealed = KeySource.SEALED, existing.sealed_key
        profile = _profile_from(command, key, sealed)
        kept = command.api_key is None and key is KeySource.SEALED
        if kept and existing is not None and not existing.same_endpoint(profile):
            # The stored key never follows a profile to another endpoint.
            reason = "its endpoint changed: send api_key again (or keep_key false)"
            raise InvalidProviderError(command.name, reason)
        if (reason := providers.factory.unsupported(profile)) is not None:
            raise ProviderUnsupportedError(profile.name, reason)
        await providers.stored.save(profile)
        return _provider_out(providers, profile)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteProviderUseCase:
    """Implements ``ports.driving.DeleteProvider``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self, command: ProviderNameQuery) -> None:
        """Delete a stored profile no instance role uses.

        A library override naming it stops resolving (that role is then not configured for the
        library) until the profile exists again.

        Args:
            command: Its name.

        Raises:
            ProviderReadOnlyError: It is configured in the environment or the file.
            ProviderInUseError: An instance role uses it.
            UnknownProviderError: There is none of that name.
        """
        if self.providers.configured_profile(command.name) is not None:
            raise ProviderReadOnlyError(command.name)
        if roles := self.providers.roles_using(command.name):
            raise ProviderInUseError(command.name, [r.value for r in roles])
        if not await self.providers.stored.delete(command.name):
            raise UnknownProviderError(command.name)
        await self.providers.factory.release(command.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckProviderUseCase:
    """Implements ``ports.driving.CheckProvider``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self, command: CheckProviderCommand) -> ModelChecksOut:
        """Call the profile once per role that uses it, or once for the model named.

        Args:
            command: The profile, and optionally a role and a model.

        Returns:
            One check per call.

        Raises:
            UnknownProviderError: There is no such profile.
            NothingToCheckError: No model was named and no role uses it.
        """
        if await self.providers.profile(command.name) is None:
            raise UnknownProviderError(command.name)
        if command.role is not None and command.model is not None:
            ref = ModelRef(profile=command.name, model=command.model)
            checks = [await self.providers.check(command.role, ref)]
        else:
            bindings = [b for b in await self.providers.bindings() if b.ref.profile == command.name]
            if not bindings:
                raise NothingToCheckError(command.name)
            checks = [await self.providers.check(b.role, b.ref, b.thinking) for b in bindings]
        return ModelChecksOut(checks=[ModelCheckOut.from_model(c) for c in checks])


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckRolesUseCase:
    """Implements ``ports.driving.CheckRoles``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self) -> ModelChecksOut:
        """Call every configured instance role once.

        Returns:
            One check per role that is set.
        """
        checks = [
            await self.providers.check(b.role, b.ref, b.thinking)
            for b in await self.providers.bindings()
        ]
        return ModelChecksOut(checks=[ModelCheckOut.from_model(c) for c in checks])


@dataclass(frozen=True, slots=True, kw_only=True)
class ListRolesUseCase:
    """Implements ``ports.driving.ListRoles``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self) -> RoleListOut:
        """Show each instance role.

        Returns:
            One entry per role, set or not.
        """
        roles = await self.providers.instance_roles()
        return RoleListOut(
            roles=[await _role_out(self.providers, roles, role) for role in ModelRole]
        )


async def _role_out(providers: AiProviders, roles: InstanceRoles, role: ModelRole) -> RoleOut:
    """Describe one instance role: its model, its thinking level and whether it can take it.

    Args:
        providers: The instance's AI configuration.
        roles: The instance's roles with their stored thinking levels.
        role: The role.

    Returns:
        The role.
    """
    binding = bind_role(role, roles, LibraryAi())
    exists = binding is not None and await providers.profile(binding.ref.profile) is not None
    thinking = roles.thinking(role) if binding is None else binding.thinking
    return RoleOut(
        role=role,
        model=None if binding is None else str(binding.ref),
        source=None if binding is None else binding.source,
        profile_exists=exists,
        thinking=thinking,
        own_thinking=roles.thinking(role),
        thinking_configured=providers.roles.thinking(role) is not None,
        thinking_unsupported=(
            await providers.thinking_problem(binding) if binding is not None and exists else None
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SetRoleThinkingUseCase:
    """Implements ``ports.driving.SetRoleThinking``."""

    providers: AiProviders
    """The instance's AI configuration."""

    async def __call__(self, command: SetRoleThinkingCommand) -> RoleOut:
        """Check the level against the role's model, then store it.

        Args:
            command: The role and its level.

        Returns:
            The role as it is now.

        Raises:
            RoleTakesNoThinkingError: The role is not ``llm`` or ``judge``.
            RoleConfiguredError: Its level is set in the environment or the configuration file.
        """
        role = command.role
        if not role.thinks:
            raise RoleTakesNoThinkingError(role.value)
        if self.providers.roles.thinking(role) is not None:
            raise RoleConfiguredError(role.value)
        field_name = f"{role.value}_thinking"
        roles = replace(await self.providers.instance_roles(), **{field_name: command.thinking})
        if command.thinking is not None:  # only the level being set is checked
            only = replace(_without_thinking(roles), **{field_name: command.thinking})
            await self.providers.refuse_unsupported_thinking(only, LibraryAi())
        await self.providers.thinking_levels.save(role, command.thinking)
        return await _role_out(self.providers, roles, role)


def _without_thinking(roles: InstanceRoles) -> InstanceRoles:
    """Drop the instance's thinking levels, keeping its models.

    Args:
        roles: The roles.

    Returns:
        The same models with no level.
    """
    return replace(roles, llm_thinking=None, judge_thinking=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenEmbeddingSpaceUseCase:
    """Implements ``ports.driving.OpenEmbeddingSpace``."""

    vectors: VectorIndex | None
    """The vector store; ``None`` when this instance has none."""
    clock: Clock
    """Stamps a new space."""

    async def __call__(self, command: OpenEmbeddingSpaceCommand) -> EmbeddingSpaceOut:
        """Return the newest space of exactly this spec that is not retired, or create one.

        Changing only the endpoint of a model keeps its space; changing the model, its
        dimensions or the input format makes a new one.

        Args:
            command: The model the instance embeds with now.

        Returns:
            The space, and whether this call created it.

        Raises:
            VectorStoreUnavailableError: The instance has no vector store.
        """
        if self.vectors is None:
            raise VectorStoreUnavailableError
        spec = EmbeddingSpec(
            profile_kind=command.profile_kind,
            model=command.model,
            dimensions=command.dimensions,
            input_format=command.input_format,
        )
        for space in reversed(await self.vectors.spaces()):
            if space.spec == spec and space.state is not SpaceState.RETIRED:
                return EmbeddingSpaceOut.from_model(space, created=False)
        space = await self.vectors.create_space(spec, self.clock.now())
        return EmbeddingSpaceOut.from_model(space, created=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class _ActiveVersion:
    """A version with an active manifest, of a library with AI on."""

    library: str
    """The library ID."""
    ref: str
    """The version."""
    manifest_id: str
    """Its active manifest."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _SearchSpace:
    """Whether a version can be searched with vectors now, and in which space."""

    searchable: bool
    """False while the configured model has not embedded the whole version."""
    space: EmbeddingSpace | None
    """The configured model's space, which covers the version; ``None`` without a model."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Configured:
    """The embedding role as it resolves now."""

    target: EmbeddingTarget
    """The model and the format its vectors are made with."""
    ref: ModelRef
    """The role's ``<profile>:<model>``."""
    profile: ProviderProfile
    """Its profile, as it is now."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingRuns:
    """The instance's embedding model, its spaces and which versions they cover (RET-01).

    The embedding role is instance-wide: a library can only opt out (AI off), and then nothing
    of it is ever sent. Everything is read at each call, so a changed role or profile counts at
    once: the space of the configured model is the newest one it made that is not retired.
    """

    providers: AiProviders
    """The profiles, the roles and each library's overrides."""
    vectors: VectorIndex | None
    """The vector store; without one nothing is embedded."""
    chunks: ChunkRepository
    """The indexed manifests and their chunks."""
    manifests: ActiveManifests
    """Which manifests are active (the catalog answers)."""
    models: EmbeddingModels | None = None
    """Wraps the embedder the factory builds; without it nothing can be embedded."""
    titles: ArticleTitles | None = None
    """Article titles, part of what is embedded; without it they are left out."""
    spend: AiSpend | None = None
    """Where usage is recorded and the embedding budget checked; without it neither is."""
    prices: PriceBook = field(default_factory=PriceBook)
    """Prices the embedding model; without a list only overrides and free kinds are priced."""
    clock: Clock = field(default_factory=SystemClock)
    """Stamps spaces and usage."""
    dimensions: int | None = None
    """The configured dimensions of the embedding role, if any."""
    batch_size: int = DEFAULT_EMBEDDING_BATCH
    """Chunks per call and per batch of a job."""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    """One plan or finish at a time: two jobs never create two spaces for one model."""

    async def configured(self) -> _Configured | None:
        """Resolve the embedding role to its profile, as they are now.

        Returns:
            The role, or ``None`` when no model is configured or its profile is missing.
        """
        ref = self.providers.roles.embedding
        if ref is None:
            return None
        profile = await self.providers.profile(ref.profile)
        if profile is None:
            return None
        target = EmbeddingTarget(
            profile_kind=profile.kind.value, model=ref.model, dimensions=self.dimensions
        )
        return _Configured(target=target, ref=ref, profile=profile)

    async def space(self, target: EmbeddingTarget) -> EmbeddingSpace | None:
        """Find the configured model's space.

        Args:
            target: The configured model.

        Returns:
            Its newest space that is not retired, or ``None``.
        """
        vectors = self.store()
        return current_space(target, await vectors.spaces())

    async def model(self, configured: _Configured) -> Embeddings:
        """Build the configured model, from its profile as it is now.

        Args:
            configured: The role.

        Returns:
            The model, ready to call.

        Raises:
            ProviderUnsupportedError: This process cannot call it.
        """
        if self.models is None:
            raise ProviderUnsupportedError(configured.ref.profile, "this process embeds nothing")
        handle = await self.providers.factory.embedder(configured.profile, configured.ref.model)
        return self.models.bind(
            handle,
            name=str(configured.ref),
            dimensions=self.dimensions,
            batch_size=self.batch_size,
        )

    async def active_versions(self, library: str | None = None) -> list[_ActiveVersion]:
        """List the versions with an active manifest, of libraries with AI on.

        Args:
            library: Only this library's (any letter case); every library's when ``None``.

        Returns:
            The versions, by library and version.
        """
        indexed = await self.chunks.find_manifests(
            manifest_id=None, library=None, indexed_before=None
        )
        if library is not None:
            indexed = [m for m in indexed if m.library.lower() == library.lower()]
        statuses = await self.manifests.statuses([m.manifest_id for m in indexed])
        enabled: dict[str, bool] = {}
        found: list[_ActiveVersion] = []
        for manifest in indexed:
            if statuses.get(manifest.manifest_id) is not ManifestStatus.ACTIVE:
                continue
            if manifest.library not in enabled:
                ai = await self.providers.library_modes.ai_of(manifest.library)
                enabled[manifest.library] = ai.enabled
            if enabled[manifest.library]:
                found.append(
                    _ActiveVersion(
                        library=manifest.library,
                        ref=manifest.version_id.removeprefix(f"{manifest.library}/"),
                        manifest_id=manifest.manifest_id,
                    )
                )
        return sorted(found, key=lambda v: (v.library, v.ref))

    async def covers(self, space: EmbeddingSpace, manifest_id: str) -> bool:
        """Say whether every chunk of a manifest has a vector in the space.

        Args:
            space: The space.
            manifest_id: The manifest.

        Returns:
            True when nothing of it is left to embed.
        """
        return (await self.store().coverage(space.id, manifest_id)).complete

    async def search_space(self, manifest_id: str) -> _SearchSpace:
        """Find the space a version's vector search must use, if it covers the version.

        Args:
            manifest_id: The version's active manifest.

        Returns:
            Not searchable while the configured model's space does not cover the version yet
            (or does not exist); searchable in that space when it does; searchable with no
            space when no embedding model or no vector store is configured (the pipeline
            decides).
        """
        configured = await self.configured()
        if configured is None or self.vectors is None:
            return _SearchSpace(searchable=True, space=None)
        space = await self.space(configured.target)
        if space is None or not await self.covers(space, manifest_id):
            return _SearchSpace(searchable=False, space=None)
        return _SearchSpace(searchable=True, space=space)

    def price(self, configured: _Configured) -> float | None:
        """Look up the configured model's input price.

        Args:
            configured: The role.

        Returns:
            US dollars per million input tokens, or ``None`` when unknown.
        """
        price = self.prices.price(configured.ref, configured.target.profile_kind)
        return None if price is None else price.input_usd_per_million

    def store(self) -> VectorIndex:
        """Return the vector store.

        Returns:
            It.

        Raises:
            VectorStoreUnavailableError: The instance has none.
        """
        if self.vectors is None:
            raise VectorStoreUnavailableError(NO_VECTOR_STORE)
        return self.vectors


def _query_embedding_scopes(request: PipelineRequest) -> tuple[tuple[str, str], ...]:
    """Name the ledger scopes a search's query embedding counts to.

    An embedding (the embedding budget's scope) made for a search (the instance's, the library's
    and the caller's scopes, as a rerank's), so every budget it may exhaust is checked.

    Args:
        request: The search.

    Returns:
        (kind, ID) of each scope, each once.
    """
    caller = AiCaller(library=request.version.library.casefold(), user=request.caller)
    return tuple(dict.fromkeys([*caller.embedding_scopes(), *caller.scopes()]))


def _bm25_answer(
    found: Sequence[SearchHit], limit: int, reason: FallbackReason | None
) -> PipelineAnswer:
    """Answer with the BM25 half alone.

    Args:
        found: BM25's hits, best first (more than ``limit`` tells the answer was cut short).
        limit: How many hits to return at most.
        reason: Why the vectors were not used.

    Returns:
        A ``bm25`` answer.
    """
    return PipelineAnswer(
        mode=RetrievalMode.BM25,
        hits=tuple(found[:limit]),
        candidates=len(found),
        reranked=0,
        complete=len(found) <= limit,
        fallback_reason=reason,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HybridPipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``hybrid`` (RET-01): BM25 and vectors.

    The best ``RRF_DEPTH`` chunks of each half, both scoped to the version's manifest, are fused
    with reciprocal rank fusion (``k`` = ``RRF_K``), so exact identifiers BM25 finds stay first
    and paraphrases only the vectors find come in. The vector half always runs, also when BM25
    matches nothing (a synonym the docs never use): there is no similarity floor, so a hybrid
    answer holds the nearest chunks of the version that pass the tag filter. The vectors are
    those of ``request.space``,
    the space the gate checked covers the version, and the query is embedded by the configured
    model, which must be the one that made that space. When the vectors cannot be used the
    search still answers, with BM25 and a ``fallback_reason``: ``embedding_in_progress`` while
    the space does not match the configured model (a switch of models), ``embedding_unavailable``
    when the model failed, timed out or could not be built (an unopenable key), and
    ``vector_store_unavailable`` when the store cannot search. Cancellation still propagates.
    Nothing of a library with AI off is sent.
    """

    search: SearchIndex
    """The full-text half."""
    vectors: VectorIndex
    """The vector half."""
    chunks: ChunkRepository
    """Gives the text of chunks only the vectors found, for their snippets."""
    runs: EmbeddingRuns
    """The configured embedding model, which embeds the query."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Times the query's embedding (``<search>.embed_query``), without the query text."""
    timeout: float = QUERY_EMBEDDING_TIMEOUT
    """Seconds to wait for the query's embedding before answering with BM25."""
    native: NativeHybrid | None = None
    """An external vector backend that fuses keyword and vector search itself (#352); it then
    ranks instead of reciprocal rank fusion. ``None``: the two halves are fused here."""
    reranks: NativeRerank | None = None
    """The same backend when it also reranks with a ranker of its own (#473, Azure AI Search's
    semantic ranker): a search that asks for reranking (``request.rerank``) is then reranked by
    it, and ExactDocs' reranker leaves the answer as it is. ``None``: ExactDocs reranks, if
    anything does."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Fuse the BM25 and vector rankings of the version's chunks.

        Args:
            request: What to search; ``space`` is the space to search; with ``rerank``, a
                backend that reranks natively (``reranks``) reranks its hybrid answer.

        Returns:
            The best fused hits, or BM25's with the reason the vectors were not used.
        """
        return await self.fuse(request, embed=request.query, mode=RetrievalMode.HYBRID)

    async def fuse(
        self, request: PipelineRequest, *, embed: str, mode: RetrievalMode
    ) -> PipelineAnswer:
        """Fuse BM25 on the query with the vectors nearest to ``embed``'s embedding.

        HyDE (``HydePipeline``) embeds its hypothetical answer instead of the query; BM25 always
        searches the query itself, so exact identifiers keep their weight.

        Args:
            request: What to search; ``space`` is the space to search.
            embed: The text whose embedding the vector half searches by.
            mode: The mode a fused answer is reported as (``hybrid``, ``hybrid_hyde``).

        Returns:
            The best fused hits, or BM25's with the reason the vectors were not used.
        """
        if self.native is not None:
            return await self._natively(self.native, request, embed, mode)
        manifest = request.version.manifest_id
        # One more than is fused tells whether the BM25 half was cut short.
        depth = max(RRF_DEPTH, request.limit) + 1
        found = await self.search.search(manifest, request.query, request.tag_filter, depth)
        near = await self._nearest(request, embed, mode)
        if isinstance(near, FallbackReason):
            return _bm25_answer(found, request.limit, near)
        return await self._fused(request, found, near, mode)

    async def _natively(
        self, native: NativeHybrid, request: PipelineRequest, embed: str, mode: RetrievalMode
    ) -> PipelineAnswer:
        """Let the backend rank the query's words and its vector together.

        When the search asks for reranking and the backend reranks natively (``reranks``), it
        also reranks the answer with its own ranker; the answer then says how many hits it
        reordered (``reranked``), and ExactDocs' reranker does not rerank them again. The same
        fallbacks as ``fuse``: BM25 answers, with the reason, when there is no vector (or the
        backend does not answer, ``vector_store_unavailable``).

        Args:
            native: The backend.
            request: What to search; ``space`` is the space to search.
            embed: The text whose embedding is searched by.
            mode: The mode the answer is reported as.

        Returns:
            The backend's hits, or BM25's with the reason the backend was not used.
        """
        manifest = request.version.manifest_id
        space = request.space
        reason: FallbackReason = FallbackReason.EMBEDDING_UNAVAILABLE
        if space is not None:
            vector = await self._query_vector(request, space, embed, mode)
            if not isinstance(vector, FallbackReason):
                terms = tuple(search_terms(request.query))
                query = TextQuery(text=request.query, terms=terms)
                try:
                    ranking = await self._ranked(native, request, space, query, vector)
                except IndexBackendUnavailableError:
                    reason = FallbackReason.VECTOR_STORE_UNAVAILABLE
                else:
                    by_ranker = {h.chunk_id for h in ranking.hits[: ranking.reranked]}
                    ranked = [h for h in ranking.hits if h.manifest_id == manifest]
                    stored = await self.chunks.get_many(manifest, [h.chunk_id for h in ranked])
                    hits = [
                        leading_hit(h.chunk_id, h.score, stored[h.chunk_id].chunk.content, terms)
                        for h in ranked
                        if h.chunk_id in stored
                    ]
                    kept = hits[: request.limit]
                    return PipelineAnswer(
                        mode=mode,
                        hits=tuple(kept),
                        candidates=len(hits),
                        reranked=sum(1 for h in kept if h.chunk_id in by_ranker),
                        complete=len(hits) <= request.limit,
                    )
            else:
                reason = vector
        depth = request.limit + 1
        found = await self.search.search(manifest, request.query, request.tag_filter, depth)
        return _bm25_answer(found, request.limit, reason)

    async def _ranked(
        self,
        native: NativeHybrid,
        request: PipelineRequest,
        space: EmbeddingSpace,
        query: TextQuery,
        vector: Sequence[float],
    ) -> NativeRanking:
        """Ask the backend for its hybrid answer, reranked by it when the search asks for that.

        Args:
            native: The backend.
            request: The search: its version, tag filter, limit and rerank flag.
            space: The space searched.
            query: The query and its terms.
            vector: The query's vector.

        Returns:
            The backend's hits; ``reranked`` 0 unless its own ranker reordered some.
        """
        manifests = [request.version.manifest_id]
        depth = request.limit + 1  # one more tells whether the answer was cut short
        if request.rerank and self.reranks is not None:
            return await self.reranks.hybrid_reranked(
                space, manifests, query, vector, request.tag_filter, depth
            )
        hits = await native.hybrid(space, manifests, query, vector, request.tag_filter, depth)
        return NativeRanking(hits=tuple(hits), reranked=0)

    async def nearest_only(self, request: PipelineRequest) -> PipelineAnswer:
        """Rank the version's chunks by their vectors alone (``vector``): no BM25 half.

        The score is the cosine similarity (1 minus the distance). When the vectors cannot be
        used, BM25 answers with the reason, as ``fuse`` does.

        Args:
            request: What to search; ``space`` is the space to search.

        Returns:
            The nearest chunks, each with its vector rank, or BM25's with the reason.
        """
        near = await self._nearest_hits(
            request, request.query, RetrievalMode.VECTOR, request.limit + 1
        )
        if isinstance(near, FallbackReason):
            depth = request.limit + 1  # one more tells whether the answer was cut short
            found = await self.search.search(
                request.version.manifest_id, request.query, request.tag_filter, depth
            )
            return _bm25_answer(found, request.limit, near)
        kept = near[: request.limit]
        stored = await self.chunks.get_many(request.version.manifest_id, [h.chunk_id for h in kept])
        terms = search_terms(request.query)
        hits = [
            replace(
                leading_hit(h.chunk_id, 1.0 - h.distance, stored[h.chunk_id].chunk.content, terms),
                vector_rank=rank,
            )
            for rank, h in enumerate(kept, start=1)
            if h.chunk_id in stored
        ]
        return PipelineAnswer(
            mode=RetrievalMode.VECTOR,
            hits=tuple(hits),
            candidates=len(near),
            reranked=0,
            complete=len(near) <= request.limit,
        )

    async def _nearest(
        self, request: PipelineRequest, embed: str, mode: RetrievalMode
    ) -> list[ChunkId] | FallbackReason:
        """Embed ``embed`` and rank the version's chunks by their vectors' distance to it.

        Args:
            request: The search; its ``space`` is the one searched.
            embed: The text embedded: the query, or HyDE's hypothetical answer.
            mode: The mode searching, which labels the embedding's span.

        Returns:
            The best ``RRF_DEPTH`` chunks, nearest first, or why the vectors cannot be used.
        """
        near = await self._nearest_hits(request, embed, mode, RRF_DEPTH)
        return near if isinstance(near, FallbackReason) else [h.chunk_id for h in near]

    async def _nearest_hits(
        self, request: PipelineRequest, embed: str, mode: RetrievalMode, depth: int
    ) -> Sequence[VectorHit] | FallbackReason:
        """Embed ``embed`` and find the version's chunks whose vectors are nearest to it.

        Args:
            request: The search; its ``space`` is the one searched.
            embed: The text embedded: the query, or HyDE's hypothetical answer.
            mode: The mode searching, which labels the embedding's span.
            depth: How many chunks at most.

        Returns:
            The nearest chunks with their distances, nearest first, or why the vectors cannot be
            used.
        """
        space = request.space
        if space is None:  # no embedding model resolved when the gate looked
            return FallbackReason.EMBEDDING_UNAVAILABLE
        vector = await self._query_vector(request, space, embed, mode)
        if isinstance(vector, FallbackReason):
            return vector
        try:
            near = await self.vectors.nearest(
                space.id, request.version.manifest_id, vector, request.tag_filter, depth
            )
        except UnknownEmbeddingSpaceError, RetiredEmbeddingSpaceError:
            return FallbackReason.EMBEDDING_IN_PROGRESS  # retired by a switch of models meanwhile
        except VectorStoreUnavailableError:
            return FallbackReason.VECTOR_STORE_UNAVAILABLE
        except VectorDimensionError, InvalidVectorError:
            return FallbackReason.EMBEDDING_UNAVAILABLE  # the model answered an unusable vector
        return near

    async def _query_vector(
        self, request: PipelineRequest, space: EmbeddingSpace, embed: str, mode: RetrievalMode
    ) -> tuple[float, ...] | FallbackReason:
        """Embed the query (or HyDE's answer) with the model that made ``space``.

        Args:
            request: The search.
            space: The space searched.
            embed: The text embedded.
            mode: The mode searching.

        Returns:
            The query's vector, or why there is none.
        """
        if not (await self.runs.providers.library_modes.ai_of(request.version.library)).enabled:
            return FallbackReason.MODE_UNAVAILABLE  # AI off: the query is never sent
        return await self.query_vector(
            space, embed, mode=mode, scopes=_query_embedding_scopes(request), search=request.search
        )

    async def query_vector(
        self,
        space: EmbeddingSpace,
        embed: str,
        *,
        mode: RetrievalMode,
        scopes: Sequence[tuple[str, str]],
        search: str,
    ) -> tuple[float, ...] | FallbackReason:
        """Embed a text with the configured model, which must be the one that made ``space``.

        Checked against the budgets of ``scopes`` first (a paid model only), and recorded to them.

        Args:
            space: The space the vector will search.
            embed: The text embedded: the query, or HyDE's hypothetical answer.
            mode: The mode searching, which labels the embedding's span.
            scopes: (kind, ID) of each ledger scope the embedding counts to.
            search: The search it runs in, which names the span.

        Returns:
            The vector, or why there is none.
        """
        configured = await self.runs.configured()
        if configured is None:
            return FallbackReason.EMBEDDING_UNAVAILABLE
        if not configured.target.matches(space.spec):
            return FallbackReason.EMBEDDING_IN_PROGRESS  # the model changed since the gate
        spend = self.runs.spend
        paid = configured.target.profile_kind not in FREE_PROFILE_KINDS
        if spend is not None and paid and await spend.reached(scopes) is not None:
            return FallbackReason.LLM_BUDGET_REACHED  # as a paid rerank over budget (#95)
        try:
            embedded = await self._embedded(search, configured, embed, mode)
        except EmbeddingFailedError, ProviderUnsupportedError, TimeoutError:
            return FallbackReason.EMBEDDING_UNAVAILABLE
        if spend is not None:  # the one record of this call: the use case records no embedding
            await spend.record(
                scopes,
                ref=configured.ref,
                profile_kind=configured.target.profile_kind,
                input_tokens=embedded.input_tokens,
                requests=embedded.requests,
            )
        return (
            embedded.vectors[0]
            if len(embedded.vectors) == 1
            else FallbackReason.EMBEDDING_UNAVAILABLE
        )

    async def _embedded(
        self, search: str, configured: _Configured, embed: str, mode: RetrievalMode
    ) -> EmbeddedTexts:
        """Embed the query, in its span; ``TimeoutError`` after ``timeout`` seconds.

        Args:
            search: The search it runs in, which names the span.
            configured: The embedding role, which made the space searched.
            embed: The text embedded: the query, or HyDE's hypothetical answer.
            mode: The mode searching, which labels the span.

        Returns:
            The query's vector and usage.

        Raises:
            EmbeddingFailedError: The model failed, or anything else went wrong building or
                calling it (a key the secret box cannot open, an adapter bug); only the error's
                type is kept, never its message, which may echo a request. ``CancelledError`` is
                no ``Exception``, so cancelling a search still propagates.
            ProviderUnsupportedError: This process cannot call the model.
        """
        stage = f"{search}.embed_query"
        with self.tracer.span(stage, mode=mode.value):
            async with asyncio.timeout(self.timeout):
                try:
                    model = await self.runs.model(configured)
                    return await model.embed_query(embed)
                except EmbeddingFailedError, ProviderUnsupportedError:
                    raise
                except Exception as error:  # never a failed search (RET-01)
                    # The class only: the message may echo a request, a key or the query.
                    logger.warning(
                        "%s search answers BM25: the query embedding raised %s",
                        mode.value,
                        type(error).__name__,
                    )
                    raise EmbeddingFailedError(str(configured.ref), type(error).__name__) from error

    async def _fused(
        self,
        request: PipelineRequest,
        found: Sequence[SearchHit],
        near: Sequence[ChunkId],
        mode: RetrievalMode,
    ) -> PipelineAnswer:
        """Fuse the top ``RRF_DEPTH`` of both halves and give each kept chunk its snippet.

        Args:
            request: The search.
            found: The BM25 half, best first; one more than ``RRF_DEPTH`` when it was cut short.
            near: The vector half, nearest first.
            mode: The mode the answer is reported as.

        Returns:
            The fused answer; ``candidates`` counts the chunks of both halves, once each.
        """
        fused = reciprocal_rank_fusion([h.chunk_id for h in found[:RRF_DEPTH]], near)
        by_id = {h.chunk_id: h for h in found}
        kept = fused[: request.limit]
        only_vectors = [f.chunk_id for f in kept if f.chunk_id not in by_id]
        stored = (
            await self.chunks.get_many(request.version.manifest_id, only_vectors)
            if only_vectors
            else {}
        )
        terms = search_terms(request.query)
        hits = []
        for rank in kept:
            if (bm25 := by_id.get(rank.chunk_id)) is not None:
                hit = replace(bm25, score=rank.score)
            elif (chunk := stored.get(rank.chunk_id)) is not None:
                hit = leading_hit(rank.chunk_id, rank.score, chunk.chunk.content, terms)
            else:
                continue
            hits.append(replace(hit, bm25_rank=rank.bm25_rank, vector_rank=rank.vector_rank))
        cut = len(found) > RRF_DEPTH or len(near) >= RRF_DEPTH
        return PipelineAnswer(
            mode=mode,
            hits=tuple(hits),
            candidates=len(fused),
            reranked=0,
            complete=not cut and len(fused) <= request.limit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VectorPipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``vector`` (#428): the vectors alone.

    The version's chunks nearest to the query's embedding, in the space the gate checked covers
    the version, with no BM25 half: a way to see what the embedding model finds on its own. It
    is never a default. When the vectors cannot be used, BM25 answers with the reason, exactly as
    ``hybrid`` does (it shares its query embedding and its fallbacks).
    """

    hybrid: HybridPipeline
    """Embeds the query and searches the vector store."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Rank the version's chunks by their vectors.

        Args:
            request: What to search; ``space`` is the space to search.

        Returns:
            The nearest chunks, or BM25's with the reason the vectors were not used.
        """
        return await self.hybrid.nearest_only(request)


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionBrowser:
    """Implements ``ports.driven.DocsBrowser``: the explorer's read tools within the caller's scope.

    The scope is what the caller may see: the pinned version (``version.manifest_id``) and the
    search's tag filter. Every read goes to that manifest (chunks, outlines, BM25) or to the
    catalog's articles, of which an answer served from another manifest is dropped, so nothing of
    another version reaches the agent; an article or chunk the tag filter excludes reads as not
    found. The browser is the agent's ``deps``: no tool argument can name a library, a version
    or a tag. ``admit`` is the output guardrail's check, by the same rules.

    A library-level access check (ACL-02/04) does not belong here: the browser is already bound to
    one version, so it goes where ``SearchDocs`` resolves the library and ref, before any pipeline
    runs. Only per-article visibility would be added here, to the reads and to ``admit``.

    Each call is recorded as a step of the explored path (its argument is model-written text:
    control characters are dropped and it is cut at ``AGENT_STEP_ARGUMENT_CHARS``), and the first
    step that reached each article is remembered, so each result can say how the agent got to it.
    Each is also a read of the run's trace (``reads``): the version and manifest it was bound to
    and those of what it served, never its argument or the text.
    """

    version: SearchableVersion
    """The exact version searched."""
    chunks: ChunkRepository
    """Its chunks and outlines."""
    search: SearchIndex
    """Its BM25 index."""
    articles: VersionArticles | None = None
    """Its articles' list and Markdown; without it the agent lists and reads none."""
    tag_filter: TagFilter = field(default_factory=TagFilter)
    """The search's tag filter."""
    reads: AgentReads = field(default_factory=UnrecordedAgentReads)
    """The run's trace."""
    searched_by: str = SEARCH_DOCS
    """The search the agent runs for, as its trace names it."""
    steps: list[str] = field(default_factory=list)
    """Every call made, in order (``read_chunk(<id>)``)."""
    reached: dict[str, int] = field(default_factory=dict)
    """The index in ``steps`` of the first call that reached each article path."""
    seen: set[ChunkId] = field(default_factory=set)
    """Every chunk a call returned or named."""

    @property
    def _pinned(self) -> str:
        """Name the version searched as a chunk names its own.

        Returns:
            ``<library>/<ref>``.
        """
        return f"{self.version.library}/{self.version.version}"

    def _step(self, tool: str, argument: str, paths: Sequence[str] = ()) -> None:
        """Record a call and the articles it reached.

        Args:
            tool: The read function, e.g. ``article_outline``.
            argument: Its argument as the model wrote it.
            paths: The article paths it returned or read.
        """
        self.steps.append(f"{tool}({model_text(argument, AGENT_STEP_ARGUMENT_CHARS)})")
        for path in paths:
            self.reached.setdefault(path, len(self.steps) - 1)

    def _trace(self, tool: str, served: Sequence[tuple[str, str]]) -> None:
        """Record a read in the run's trace.

        Args:
            tool: The read function.
            served: ``(<library>/<ref>, manifest)`` of each thing it returned to the agent.
        """
        self.reads.record(
            AgentRead(
                search=self.searched_by,
                tool=tool,
                pinned_version=self._pinned,
                pinned_manifest=self.version.manifest_id,
                served_versions=tuple(dict.fromkeys(v for v, _ in served)),
                served_manifests=tuple(dict.fromkeys(m for _, m in served)),
            )
        )

    def path_to(self, article_path: str) -> tuple[str, ...]:
        """Say how the agent reached an article: the calls up to the first that reached it.

        Args:
            article_path: The article of a picked chunk.

        Returns:
            The calls, in order, at most the last ``MAX_EXPLORED_STEPS`` up to the one that
            reached it; every call made (as many) when none reached it.
        """
        end = self.reached.get(article_path, len(self.steps) - 1) + 1
        return tuple(self.steps[max(0, end - MAX_EXPLORED_STEPS) : end])

    async def _kept(self, path: str) -> bool:
        """Say whether the search's tag filter keeps an article of the version.

        Args:
            path: The article's path.

        Returns:
            True when there is no filter, or the article's tags pass it.
        """
        if not self.tag_filter.tags:
            return True
        sections = await self.chunks.article(self.version.manifest_id, path)
        if not sections:
            return False
        first = await self.chunks.get(self.version.manifest_id, sections[0].chunk_id)
        return first is not None and self.tag_filter.keeps(first.row.tags)

    async def list_articles(self, prefix: str = "") -> Sequence[ArticleEntry]:
        """List the version's articles under a folder.

        Args:
            prefix: A folder; empty for every article.

        Returns:
            At most ``AGENT_LIST_LIMIT`` articles; none when the catalog answered from another
            manifest.
        """
        self._step("list_articles", prefix)
        page = None
        if self.articles is not None:
            page = await self.articles.list(self.version, prefix, AGENT_LIST_LIMIT, self.tag_filter)
        if page is None or page.manifest_id != self.version.manifest_id:
            self._trace("list_articles", ())
            return ()
        listed = page.articles[:AGENT_LIST_LIMIT]
        self._trace("list_articles", [(self._pinned, page.manifest_id)] if listed else ())
        return listed

    async def article_outline(self, path: str) -> Outline | None:
        """Read an article's heading tree from the version's chunk rows.

        Args:
            path: The article's path.

        Returns:
            The outline, or ``None`` when the version has no such article.
        """
        sections = await self.chunks.article(self.version.manifest_id, path)
        if sections and not await self._kept(path):
            sections = []
        self._step("article_outline", path, [path] if sections else [])
        served = [(self._pinned, self.version.manifest_id)] if sections else []
        self._trace("article_outline", served)  # rows of this manifest's chunk store only
        if not sections:
            return None
        self.seen.update(s.chunk_id for s in sections)
        return outline(sections)

    async def read_article(self, path: str) -> ArticleText | None:
        """Read an article's Markdown, cut at ``AGENT_READ_CHARS``.

        Args:
            path: The article's path.

        Returns:
            Its text, or ``None`` when the version has no such article (or the catalog answered
            from another manifest).
        """
        served = None
        if self.articles is not None and await self._kept(path):
            served = await self.articles.read(self.version, path)
        if served is not None and served.manifest_id != self.version.manifest_id:
            served = None  # a re-sync activated another manifest meanwhile
        self._step("read_article", path, [] if served is None else [path])
        self._trace("read_article", [] if served is None else [(self._pinned, served.manifest_id)])
        if served is None:
            return None
        return ArticleText(
            path=path,
            content=served.content[:AGENT_READ_CHARS],
            truncated=len(served.content) > AGENT_READ_CHARS,
        )

    async def read_chunk(self, chunk_id: str) -> StoredChunk | None:
        """Read one chunk of the version, cut at ``AGENT_CHUNK_CHARS``.

        Args:
            chunk_id: Its ID.

        Returns:
            The chunk, or ``None`` when the version has no such chunk.
        """
        stored = await self.chunks.get(self.version.manifest_id, ChunkId(chunk_id))
        if stored is not None and not self.tag_filter.keeps(stored.row.tags):
            stored = None
        self._step("read_chunk", chunk_id, [] if stored is None else [stored.row.article_path])
        self._trace(
            "read_chunk", [] if stored is None else [(stored.version_id, stored.manifest_id)]
        )
        if stored is None:
            return None
        self.seen.add(stored.row.chunk_id)
        content = stored.chunk.content[:AGENT_CHUNK_CHARS]
        return replace(stored, chunk=replace(stored.chunk, content=content))

    async def search_docs(self, query: str, limit: int) -> Sequence[tuple[SearchHit, StoredChunk]]:
        """Search the version with BM25, within the search's tag filter.

        Args:
            query: The words to look for.
            limit: How many hits at most (1 to ``AGENT_SEARCH_LIMIT``).

        Returns:
            The best hits with their chunks, best first; nothing for a blank query.
        """
        if not query.strip():
            self._step("search_docs", query)
            self._trace("search_docs", ())
            return ()
        wanted = min(max(limit, 1), AGENT_SEARCH_LIMIT)
        manifest = self.version.manifest_id
        found = await self.search.search(manifest, query, self.tag_filter, wanted)
        stored = await self.chunks.get_many(manifest, [h.chunk_id for h in found])
        pairs = [(h, stored[h.chunk_id]) for h in found if h.chunk_id in stored]
        self._step("search_docs", query, [c.row.article_path for _, c in pairs])
        self._trace("search_docs", [(c.version_id, c.manifest_id) for _, c in pairs])
        self.seen.update(h.chunk_id for h, _ in pairs)
        return pairs

    def searched(self, query: str, found: Sequence[StoredChunk]) -> None:
        """Record a BM25 search made over several versions, this one included (an answer's).

        Args:
            query: The words searched for.
            found: The chunks of this version it returned.
        """
        self._step("search_docs", query, [c.row.article_path for c in found])
        self._trace("search_docs", [(c.version_id, c.manifest_id) for c in found])
        self.seen.update(c.row.chunk_id for c in found)

    async def admit(self, chunk_ids: Sequence[str]) -> Sequence[str]:
        """Keep the chunk IDs the pinned version holds and the tag filter keeps.

        Args:
            chunk_ids: The agent's picks, as the model wrote them.

        Returns:
            The admitted IDs, in order, once each.
        """
        wanted = list(dict.fromkeys(ChunkId(c) for c in chunk_ids))
        stored = await self.chunks.get_many(self.version.manifest_id, wanted) if wanted else {}
        return [c for c in wanted if c in stored and self.tag_filter.keeps(stored[c].row.tags)]


@dataclass(frozen=True, slots=True, kw_only=True)
class LibrariesScope:
    """Implements ``ports.driven.LibrariesBrowser``: the answering agent's reads (#428).

    One ``VersionBrowser`` per library of the question's scope, each pinned to that library's
    default version and the call's tag filter, so every read keeps the rules of an agentic search
    of one version (and records the same trace). A library is named by the model, so it is looked
    up in the scope (any letter case); one outside it reads as not found. ``read`` remembers the
    chunks the agent read, in order: the sources of an answer whose run stopped.
    """

    browsers: Mapping[str, VersionBrowser]
    """A browser per library of the scope, by case-folded library ID, in the order chosen."""
    search: SearchIndex
    """The BM25 index, searched over every library of the scope at once."""
    chunks: ChunkRepository
    """The chunks of the scope's versions."""
    tag_filter: TagFilter = field(default_factory=TagFilter)
    """The call's tag filter."""
    read: list[tuple[str, ChunkId]] = field(default_factory=list)
    """``(library, chunk)`` of every chunk the agent read, in order."""

    def _browser(self, library: str) -> VersionBrowser | None:
        """Find the browser of a library the model named.

        Args:
            library: The library ID as the model wrote it.

        Returns:
            Its browser, or ``None`` when the library is not in the scope.
        """
        return self.browsers.get(library.strip().casefold())

    def spelled(self, library: str) -> str | None:
        """Spell a library the model named as the scope does.

        Args:
            library: The library ID as the model wrote it.

        Returns:
            The scope's spelling, or ``None`` when the library is not in the scope.
        """
        browser = self._browser(library)
        return None if browser is None else browser.version.library

    def libraries(self) -> Sequence[tuple[str, str]]:
        """Name the libraries of the scope.

        Returns:
            ``(library, version)`` of each, in the order chosen.
        """
        return [(b.version.library, b.version.version) for b in self.browsers.values()]

    async def search_docs(
        self, query: str, library: str | None, limit: int
    ) -> Sequence[tuple[str, SearchHit, StoredChunk]]:
        """Search the scope (or one library of it) with BM25, within the tag filter.

        Args:
            query: The words to look for.
            library: One library of the scope; ``None`` for all of them in one ranking.
            limit: How many hits at most (1 to ``AGENT_SEARCH_LIMIT``).

        Returns:
            ``(library, hit, chunk)`` of the best hits, best first; nothing for a blank query or
            a library outside the scope.
        """
        wanted = min(max(limit, 1), AGENT_SEARCH_LIMIT)
        if library is not None:
            browser = self._browser(library)
            if browser is None:
                return ()
            found = await browser.search_docs(query, wanted)
            return [(browser.version.library, hit, chunk) for hit, chunk in found]
        if not query.strip():
            return ()
        by_manifest = {b.version.manifest_id: b for b in self.browsers.values()}
        hits = await self.search.search_many(list(by_manifest), query, self.tag_filter, wanted)
        wanted_chunks: dict[str, list[ChunkId]] = {}
        for found_hit in hits:
            wanted_chunks.setdefault(found_hit.manifest_id, []).append(found_hit.hit.chunk_id)
        stored = await self.chunks.get_across(wanted_chunks)
        found_all = [
            (by_manifest[f.manifest_id], f.hit, stored[f.manifest_id, f.hit.chunk_id])
            for f in hits
            if (f.manifest_id, f.hit.chunk_id) in stored
        ]
        for browser in by_manifest.values():  # each library's explored path and trace
            mine = [c for b, _, c in found_all if b is browser]
            browser.searched(query, mine)
        return [(b.version.library, hit, chunk) for b, hit, chunk in found_all]

    async def list_articles(self, library: str, prefix: str = "") -> Sequence[ArticleEntry]:
        """List a library's articles under a folder.

        Args:
            library: A library of the scope.
            prefix: A folder; empty for every article.

        Returns:
            The articles; none for a library outside the scope.
        """
        browser = self._browser(library)
        return () if browser is None else await browser.list_articles(prefix)

    async def article_outline(self, library: str, path: str) -> Outline | None:
        """Read an article's heading tree.

        Args:
            library: A library of the scope.
            path: The article's path.

        Returns:
            The outline, or ``None`` when the library is outside the scope or has no such article.
        """
        browser = self._browser(library)
        return None if browser is None else await browser.article_outline(path)

    async def read_chunk(self, library: str, chunk_id: str) -> StoredChunk | None:
        """Read one chunk, cut at ``AGENT_CHUNK_CHARS``.

        Args:
            library: A library of the scope.
            chunk_id: Its ID.

        Returns:
            The chunk, or ``None`` when it is not in the scope.
        """
        browser = self._browser(library)
        if browser is None:
            return None
        stored = await browser.read_chunk(chunk_id)
        if stored is not None:
            self.read.append((browser.version.library, stored.row.chunk_id))
        return stored

    async def admit(self, cited: Sequence[tuple[str, str]]) -> Sequence[tuple[str, str]]:
        """Keep the ``(library, chunk ID)`` pairs the scope holds and the tag filter keeps.

        Args:
            cited: The agent's citations, as the model wrote them.

        Returns:
            The admitted pairs, in order, once each, each library as the scope spells it.
        """
        by_library: dict[str, list[str]] = {}
        for library, chunk_id in cited:
            if (browser := self._browser(library)) is not None:
                by_library.setdefault(browser.version.library, []).append(chunk_id)
        admitted: set[tuple[str, str]] = set()
        for library, chunk_ids in by_library.items():
            browser = self.browsers[library.casefold()]
            admitted.update((library, c) for c in await browser.admit(chunk_ids))
        kept: dict[tuple[str, str], None] = {}
        for library, chunk_id in cited:
            if (name := self.spelled(library)) is not None and (name, chunk_id) in admitted:
                kept.setdefault((name, chunk_id))
        return list(kept)


def _tightest(owns: Sequence[Sequence[BudgetLimit]]) -> tuple[BudgetLimit, ...]:
    """Merge several libraries' own budgets into the tightest of each window.

    An answer over several libraries counts to each of them (``AiCaller.also``); the harness
    checks one ``library`` ceiling for all of them, so it gets the tightest.

    Args:
        owns: Each library's own budgets.

    Returns:
        Per window, the lowest US dollar and token ceilings any of them sets.
    """
    merged: list[BudgetLimit] = []
    for window in SpendWindow:
        limits = [limit for own in owns for limit in own if limit.window is window]
        if not limits:
            continue
        usd = [limit.usd_micros for limit in limits if limit.usd_micros is not None]
        tokens = [limit.tokens for limit in limits if limit.tokens is not None]
        merged.append(
            replace(
                limits[0],
                usd_micros=min(usd) if usd else None,
                tokens=min(tokens) if tokens else None,
            )
        )
    return tuple(merged)


def _quoted(quote: str | None, content: str) -> str | None:
    """Keep a quote only when the chunk holds it verbatim.

    Args:
        quote: What the model says it quoted.
        content: The chunk's text.

    Returns:
        The quote, made safe to show and cut at ``MAX_QUOTE_CHARS``; ``None`` when it is blank or
        not in the chunk.
    """
    if quote is None or not (wanted := quote.strip()) or wanted not in content:
        return None
    return model_text(wanted, MAX_QUOTE_CHARS)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetAnswerAvailabilityUseCase:
    """Implements ``ports.driving.GetAnswerAvailability``."""

    providers: AiProviders
    """The instance's roles and profiles."""
    answerer: Answerer | None = None
    """Runs the agent; without it no answer can run."""
    bounds: AgentBounds = field(default_factory=AgentBounds)
    """The run's limits."""

    async def __call__(self) -> AnswerAvailabilityOut:
        """Say whether the instance's ``llm`` role resolves to a profile.

        Returns:
            Whether answers can run, why not, and the tool-call limit.
        """
        reason = None
        if self.answerer is None:
            reason = "this build cannot run the agent"
        elif await self.providers.profile_for(ModelRole.LLM, "", LibraryAi()) is None:
            reason = "no llm role is configured"
        return AnswerAvailabilityOut(
            available=reason is None, reason=reason, max_tool_calls=self.bounds.max_tool_calls
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AnswerQuestionUseCase:
    """Implements ``ports.driving.AnswerQuestion`` (#428): an agent answers from chosen libraries.

    The agent runs on the instance's ``llm`` role (a library's own ``llm`` applies to its own
    searches only) in Code Mode, with the read tools of a ``LibrariesScope``: the default versions
    of the libraries the caller chose and may read, with AI on, under the call's tag filter. It is
    bounded as an agentic search: ``[ai.agentic]`` (tool calls, requests, tokens, the sandbox,
    ``timeout``), the LLM search rate limit (once per answer), and the budgets of the instance, the
    caller and every library read (each is charged the run; the tightest of their own budgets
    applies). Every citation is checked again against its library's version and the tag filter,
    and a quote is kept only when the chunk holds it verbatim. A run that stops returns no answer,
    the reason, and the chunks the agent had read as sources.
    """

    defaults: DefaultVersions
    """Every library's default version."""
    versions: SearchableVersions
    """Resolves a chosen library to its default version."""
    access: AccessPolicy
    """What the caller may read."""
    providers: AiProviders
    """Resolves and builds the ``llm`` role, and each library's AI settings."""
    chunks: ChunkRepository
    """The versions' chunks."""
    search: SearchIndex
    """The BM25 index, the agent's ``search_docs``."""
    spend: AiSpend
    """The ledger, the budgets, the rate limit and the price book."""
    answerer: Answerer | None = None
    """Runs the agent; without it no answer can run."""
    articles: VersionArticles | None = None
    """The versions' articles (``list_articles``)."""
    bounds: AgentBounds = field(default_factory=AgentBounds)
    """The run's limits."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Times the run, without the question."""
    reads: AgentReads = field(default_factory=UnrecordedAgentReads)
    """The runs' trace: every read the agent made."""

    async def __call__(
        self,
        query: AnswerQuery,
        *,
        caller: str | None = None,
        progress: AnswerProgress | None = None,
    ) -> AnswerResult:
        """Answer the question from the chosen libraries.

        Args:
            query: The question, the libraries and the filters.
            caller: The account asking.
            progress: Hears each tool call.

        Returns:
            The answer and its sources, or why there is none, with what the run used.

        Raises:
            UnavailableModeError: No ``llm`` role resolves, or this build cannot run the agent.
        """
        text = SearchText(value=query.question)
        found = await self.providers.profile_for(ModelRole.LLM, "", LibraryAi())
        if self.answerer is None or found is None:
            agentic = RetrievalMode.AGENTIC.value
            raise UnavailableModeError(agentic, [], [ModelRole.LLM.value])
        libraries = ",".join(query.chosen) or None
        with self.tracer.span(
            ANSWER_STAGE, mode=RetrievalMode.AGENTIC.value, query=text.value, library=libraries
        ):
            return await self._answer(query, text.value, found, caller, progress)

    async def _answer(
        self,
        query: AnswerQuery,
        question: str,
        found: tuple[ModelRef, ProviderProfile],
        caller: str | None,
        progress: AnswerProgress | None,
    ) -> AnswerResult:
        """Resolve the scope, check the limits, run the agent and check its sources.

        Args:
            query: The question as asked.
            question: Its validated text.
            found: The ``llm`` role's model and profile.
            caller: The account asking.
            progress: Hears each tool call.

        Returns:
            The result.
        """
        scope, _, omitted = await _default_versions(
            self.defaults, self.versions, self.access, query.chosen, MAX_ANSWER_LIBRARIES
        )
        enabled, without_ai, own = await self._with_ai(scope.values())
        result = AnswerResult(
            answer="",
            sources=[],
            libraries=[AnswerLibraryOut(library=v.library, version=v.version) for v in enabled],
            libraries_without_ai=without_ai,
            libraries_omitted=omitted,
            usage=self._usage(AnswerUsage(), found),
        )
        if not enabled:  # nothing of a library with AI off is ever sent
            return result.model_copy(update={"fallback_reason": FallbackReason.MODE_UNAVAILABLE})
        keys = [v.library.casefold() for v in enabled]
        who = AiCaller(library=keys[0], user=caller, also=tuple(keys[1:]))
        if (reason := await self.spend.llm_step(who, own)) is not None:
            return result.model_copy(update={"fallback_reason": reason})
        browser = self._browser(enabled, TagFilter(tags=tuple(query.tags), match=query.tags_match))
        ref, profile = found
        run = AgentRun(
            question=question,
            limit=query.max_sources,
            bounds=self.bounds,
            budgets=self.spend.budgets.for_library(own),
            # The harness keeps one budget per scope kind and window, so the run itself counts to
            # the first library; the others are charged the same usage once it ends.
            caller=replace(who, also=()),
            price=self.spend.prices.price(ref, profile.kind.value),
        )
        draft = await self._run(found, browser, run, progress)
        if who.also and (draft.usage.requests or draft.usage.input_tokens):
            await self.spend.record(
                [(SPEND_SCOPE_LIBRARY, library) for library in who.also],
                ref=ref,
                profile_kind=profile.kind.value,
                input_tokens=draft.usage.input_tokens,
                output_tokens=draft.usage.output_tokens,
                requests=draft.usage.requests,
            )
        return result.model_copy(
            update={
                "answer": "" if draft.stopped else model_markdown(draft.answer, MAX_ANSWER_CHARS),
                "sources": await self._sources(draft, browser, enabled, query.max_sources),
                "fallback_reason": draft.stopped,
                "usage": self._usage(draft.usage, found),
            }
        )

    async def _with_ai(
        self, versions: Collection[SearchableVersion]
    ) -> tuple[list[SearchableVersion], list[str], tuple[BudgetLimit, ...]]:
        """Keep the versions of libraries with AI on: nothing of the others is ever sent.

        Args:
            versions: The scope's versions.

        Returns:
            The versions kept, the libraries left out, and the tightest of the kept libraries'
            own budgets.
        """
        enabled: list[SearchableVersion] = []
        without_ai: list[str] = []
        owns: list[tuple[BudgetLimit, ...]] = []
        for version in versions:
            ai = await self.providers.library_modes.ai_of(version.library)
            if ai.enabled:
                enabled.append(version)
                owns.append(ai.budgets)
            else:
                without_ai.append(version.library)
        return enabled, without_ai, _tightest(owns)

    def _browser(
        self, versions: Sequence[SearchableVersion], tag_filter: TagFilter
    ) -> LibrariesScope:
        """Build the agent's read tools over the scope.

        Args:
            versions: The versions it may read.
            tag_filter: The call's tag filter.

        Returns:
            The browser.
        """
        return LibrariesScope(
            browsers={
                v.library.casefold(): VersionBrowser(
                    version=v,
                    chunks=self.chunks,
                    search=self.search,
                    articles=self.articles,
                    tag_filter=tag_filter,
                    reads=self.reads,
                    searched_by=ANSWER_STAGE,
                )
                for v in versions
            },
            search=self.search,
            chunks=self.chunks,
            tag_filter=tag_filter,
        )

    async def _run(
        self,
        found: tuple[ModelRef, ProviderProfile],
        browser: LibrariesScope,
        run: AgentRun,
        progress: AnswerProgress | None,
    ) -> AnswerDraft:
        """Build the model and run the agent within ``bounds.timeout``; never raise for it.

        Args:
            found: The ``llm`` role's model and profile.
            browser: The read tools on the scope.
            run: The question, the limits and who pays.
            progress: Hears each tool call.

        Returns:
            The agent's draft; one with ``stopped`` set when it timed out or failed.
        """
        answerer = self.answerer
        if answerer is None:  # checked by the caller; kept for the type checker
            return AnswerDraft(stopped=FallbackReason.MODE_UNAVAILABLE)
        try:
            draft = await self._bounded(answerer, found, browser, run, progress)
        except AgentStoppedError as stopped:
            return AnswerDraft(stopped=FallbackReason(stopped.reason))
        if draft.stopped is not None:
            logger.warning("an agentic answer stopped: %s", draft.stopped.value)
        if draft.rejected:  # the count only: a chunk ID or a library is not logged
            logger.warning("the output guardrail rejected %d citation(s)", draft.rejected)
        return draft

    async def _bounded(
        self,
        answerer: Answerer,
        found: tuple[ModelRef, ProviderProfile],
        browser: LibrariesScope,
        run: AgentRun,
        progress: AnswerProgress | None,
    ) -> AnswerDraft:
        """Build the model and run the agent within ``bounds.timeout``.

        Args:
            answerer: Runs the agent.
            found: The ``llm`` role's model and profile.
            browser: The read tools on the scope.
            run: The question, the limits and who pays.
            progress: Hears each tool call.

        Returns:
            The agent's draft.

        Raises:
            AgentStoppedError: It timed out (``agent_limit_reached``) or failed
                (``agent_failed``); only the error's class is logged.
        """
        ref, profile = found
        try:
            with self.tracer.span(
                f"{ANSWER_STAGE}.{AGENT_STAGE}", mode=RetrievalMode.AGENTIC.value
            ):
                async with asyncio.timeout(self.bounds.timeout):
                    model = await self.providers.factory.chat_model(profile, ref.model)
                    return await answerer.answer(
                        model,
                        browser,
                        run,
                        ledger=self.spend.ledger,
                        clock=self.spend.clock,
                        progress=progress,
                    )
        except TimeoutError as error:
            logger.warning("an agentic answer ran past its time limit")
            reason = FallbackReason.AGENT_LIMIT_REACHED.value
            raise AgentStoppedError(reason, "timeout") from error
        except Exception as error:  # an answer never fails for its agent
            # The class only: the message may echo a request, a key or the question.
            kind_of = type(error).__name__
            logger.warning("an agentic answer failed: %s", kind_of)
            raise AgentStoppedError(FallbackReason.AGENT_FAILED.value, kind_of) from error

    async def _sources(
        self,
        draft: AnswerDraft,
        browser: LibrariesScope,
        versions: Sequence[SearchableVersion],
        limit: int,
    ) -> list[AnswerSourceOut]:
        """Check the citations against the scope again and build the sources.

        Args:
            draft: The agent's draft.
            browser: The read tools, which know the scope and what the agent read.
            versions: The versions of the scope.
            limit: The most sources.

        Returns:
            The cited chunks the scope holds (or, when the run stopped, those it read), in order,
            once each, at most ``limit``.
        """
        cited = (
            [
                AnswerCitation(library=lib, chunk_id=c, quote=None, reason=READ_BEFORE_STOP)
                for lib, c in browser.read
            ]
            if draft.stopped is not None
            else list(draft.citations)
        )
        admitted = await browser.admit([(c.library, c.chunk_id) for c in cited])
        first: dict[tuple[str, str], AnswerCitation] = {}
        for citation in cited:
            if (library := browser.spelled(citation.library)) is not None:
                first.setdefault((library, citation.chunk_id), citation)
        by_library = {v.library: v for v in versions}
        wanted: dict[str, list[ChunkId]] = {}
        for library, chunk_id in admitted[:limit]:
            wanted.setdefault(by_library[library].manifest_id, []).append(ChunkId(chunk_id))
        stored = await self.chunks.get_across(wanted)
        sources = []
        for library, chunk_id in admitted[:limit]:
            version = by_library[library]
            chunk = stored.get((version.manifest_id, ChunkId(chunk_id)))
            if chunk is None:
                continue
            citation = first[library, chunk_id]
            sources.append(
                AnswerSourceOut(
                    library=version.library,
                    version=version.version,
                    commit_sha=version.commit_sha,
                    chunk_id=chunk_id,
                    article_path=chunk.row.article_path,
                    heading_path=list(chunk.chunk.heading_path),
                    anchor=chunk.chunk.anchor,
                    source_url=source_link(version, chunk.row.article_path, chunk.chunk.anchor),
                    quote=_quoted(citation.quote, chunk.chunk.content),
                    reason=model_text(citation.reason, MAX_JUSTIFICATION_CHARS),
                )
            )
        return sources

    def _usage(self, usage: AnswerUsage, found: tuple[ModelRef, ProviderProfile]) -> AnswerUsageOut:
        """Show what a run used, with its cost at the model's price.

        Args:
            usage: What it used.
            found: The ``llm`` role's model and profile.

        Returns:
            The usage, priced when the model has a known price.
        """
        ref, profile = found
        price = self.spend.prices.price(ref, profile.kind.value)
        cost = None
        if price is not None:
            cost = (
                usage.input_tokens * price.input_usd_per_million
                + usage.output_tokens * price.output_usd_per_million
            ) / TOKENS_PER_MILLION
        return AnswerUsageOut(
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_calls=usage.tool_calls,
            max_tool_calls=self.bounds.max_tool_calls,
            cost_usd=cost,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentAnswerCaching:
    """Answers an agentic search from an earlier answer to a similar question (RET-05, #100).

    Answers are kept per scope (``AgentCacheScope``): the pinned version's manifest, the ``llm``
    model, and a fingerprint of the tag filter, the agent's limits, the cache format and the
    space questions are compared in. A re-sync (a new manifest), another model, filter or
    setting is another scope, so it never reuses an answer; the use cases also forget a removed
    manifest's answers and a library's when its settings change, and the nightly upkeep prunes
    them by age. Only a question asked again hits (``CachedQuestion.similarity``): the same
    guards (numbers, versions, negations) and the same content terms in the same order, any
    inflection; with an embedding model, the cosine of the two questions' embeddings must also
    clear ``threshold``, as a confirmation, never as a bridge across different terms. The most
    similar at or above ``threshold`` whose picks the version still holds is the hit; its
    picks are checked again against the manifest and the filter before they are shown.

    A cache that fails is a miss (logged by class only); a question embedding that fails or
    that a budget refuses leaves the lexical similarity alone. The question is stored as
    HMACs under ``key`` and, with an embedding model, its embedding; never its text.
    """

    cache: AgentAnswerCache
    """The stored answers."""
    key: bytes
    """The instance's key for the HMACs of the questions (from its secret key)."""
    clock: Clock
    """Stamps the answers; the TTL counts from it."""
    runs: EmbeddingRuns | None = None
    """The instance's embedding model, which embeds the question; ``None``: lexical only."""
    threshold: float | None = None
    """How similar (0 to 1) a question must be to a cached one to reuse its answer; ``None``:
    ``DEFAULT_AGENT_CACHE_THRESHOLD`` with an embedding model, else
    ``DEFAULT_BM25_CACHE_THRESHOLD``."""
    audience: str = "library"
    """Who shares answers: ``library`` (every caller of the version) or ``caller``."""
    timeout: float = QUERY_EMBEDDING_TIMEOUT
    """Seconds to wait for the question's embedding before comparing words only."""

    async def similarity_space(self) -> str:
        """Name the space questions are compared in now.

        Returns:
            The embedding model's identity, or ``bm25`` without one.
        """
        configured = await self._configured()
        return BM25_SIMILARITY if configured is None else configured.target.identity

    async def _configured(self) -> _Configured | None:
        """Resolve the embedding role, if questions are compared with it.

        Returns:
            The role, or ``None``.
        """
        return None if self.runs is None else await self.runs.configured()

    async def lookup(
        self,
        version: SearchableVersion,
        query: str,
        tag_filter: TagFilter,
        limit: int,
        *,
        model: ModelRef,
        bounds: AgentBounds,
        caller: str | None,
        own: Sequence[BudgetLimit] = (),
        repo_guidance: str = "off",
        held: Callable[[Sequence[CachedPick]], Awaitable[Sequence[ChunkId]]],
    ) -> AgentCacheLookup:
        """Find the most similar cached question of the search's scope, if similar enough.

        The scope is read first, then its answers are compared by words: only the same question
        re-asked (the same guards and content terms) can hit. With no such answer nothing is
        embedded (``store`` embeds the question if the agent answers). With one and an embedding
        model, the question is embedded to confirm it: its cosine with the cached question must
        clear the threshold too. The embedding is made after the budgets it counts to are
        checked (the instance's, the library's and the caller's, the same ones the LLM step is
        checked against); when it fails or a budget refuses it, the words decide.

        Args:
            version: The version searched.
            query: The query text.
            tag_filter: The search's tag filter.
            limit: How many chunks the pipeline is asked for: an answer asked for fewer is
                not reused.
            model: The ``llm`` role's model.
            bounds: The agent's limits.
            caller: The account searching (a paid question embedding counts to it).
            own: The library's own budgets, as the search read them.
            repo_guidance: The library's repo guidance (part of the scope).
            held: Says which of an answer's picks the pinned version holds under the filter.

        Returns:
            The lookup: the hit, if any, and what a miss is stored under.
        """
        configured = await self._configured()
        threshold = self._threshold(configured)
        scope = AgentCacheScope.of(
            version=version,
            model=model,
            tag_filter=tag_filter,
            bounds=bounds,
            similarity=BM25_SIMILARITY if configured is None else configured.target.identity,
            audience=self._audience(caller),
            repo_guidance=repo_guidance,
        )
        question = CachedQuestion.of(query, key=self.key)
        miss = AgentCacheLookup(
            scope=scope, question=question, query=query, caller=caller, own=tuple(own)
        )
        try:
            entries = await self._cache_call(self.cache.scoped(scope))
        except AgentCacheError:  # never a failed search: the agent answers
            return miss
        # Only the same question re-asked can hit (``CachedQuestion.similarity``): words find
        # the candidates, and an embedding, when there is one, only confirms them.
        candidates = [
            e for e in entries if e.limit >= limit and question.similarity(e.question) >= threshold
        ]
        if not candidates:
            return miss  # nothing could serve: nothing is embedded
        if configured is not None:
            vector = await self._embedded(version, query, configured, caller, own)
            miss = replace(miss, embedded=True)
            if vector is not None:  # else the words decide (a failure or a budget)
                question = replace(question, vector=vector)
                miss = replace(miss, question=question)
        found = await self._best(question, candidates, threshold, held)
        if found is None:
            return miss
        return replace(miss, hit=found[1], similarity=found[0])

    def _threshold(self, configured: _Configured | None) -> float:
        """Say how similar a question must be in this space.

        Args:
            configured: The embedding role, if any.

        Returns:
            The operator's threshold, else the default of the space.
        """
        if self.threshold is not None:
            return self.threshold
        if configured is None:
            return DEFAULT_BM25_CACHE_THRESHOLD
        return DEFAULT_AGENT_CACHE_THRESHOLD

    def _audience(self, caller: str | None) -> str:
        """Name who shares the answers of a search: everyone, or the caller alone.

        Args:
            caller: The account searching; ``None`` for a stdio MCP process.

        Returns:
            Empty with ``scope = "library"``; with ``"caller"``, an HMAC of the caller (never
            the account name itself).
        """
        return caller_audience(caller, key=self.key) if self.audience == "caller" else ""

    @staticmethod
    async def _best(
        question: CachedQuestion,
        entries: Sequence[CachedAgentAnswer],
        threshold: float,
        held: Callable[[Sequence[CachedPick]], Awaitable[Sequence[ChunkId]]],
    ) -> tuple[float, CachedAgentAnswer] | None:
        """Find the most similar answer at or above the threshold whose picks are still there.

        Args:
            question: The search's question.
            entries: The answers that could serve.
            threshold: How similar it must be.
            held: Says which of an answer's picks the pinned version holds under the filter.

        Returns:
            Its similarity and the answer, or ``None``.
        """
        ranked = sorted(
            ((question.similarity(e.question), e) for e in entries),
            key=lambda pair: -pair[0],  # stable: the newest of equally similar ones first
        )
        for score, entry in ranked:
            if score < threshold:
                break
            if await held(entry.picks):
                return score, entry
        return None

    async def _embedded(
        self,
        version: SearchableVersion,
        query: str,
        configured: _Configured,
        caller: str | None,
        own: Sequence[BudgetLimit] = (),
    ) -> tuple[float, ...] | None:
        """Embed the question with the instance's embedding model, as a query.

        A paid model is checked against the budgets first (the embedding budget, and the
        instance's, the library's and the caller's, as the LLM step is) and its use recorded,
        as a hybrid search's query embedding is.

        Args:
            version: The version searched (its library's budgets apply).
            query: The query text.
            configured: The embedding role.
            caller: The account searching.
            own: The library's own budgets.

        Returns:
            The embedding, or ``None`` when a budget refuses it, the model fails or it does not
            answer within ``timeout`` (only the error's class is logged).
        """
        if self.runs is None:
            return None
        who = AiCaller(library=version.library.casefold(), user=caller)
        scopes = tuple(dict.fromkeys([*who.embedding_scopes(), *who.scopes()]))
        spend = self.runs.spend
        paid = configured.target.profile_kind not in FREE_PROFILE_KINDS
        if spend is not None and paid and await spend.reached(scopes, own) is not None:
            return None
        try:
            async with asyncio.timeout(self.timeout):
                embedded = await self._embed(query, configured)
        except EmbeddingFailedError, ProviderUnsupportedError, TimeoutError:
            return None  # never a failed search: words only
        if spend is not None:
            await spend.record(
                scopes,
                ref=configured.ref,
                profile_kind=configured.target.profile_kind,
                input_tokens=embedded.input_tokens,
                requests=embedded.requests,
            )
        return embedded.vectors[0] if len(embedded.vectors) == 1 else None

    async def store(
        self,
        version: SearchableVersion,
        lookup: AgentCacheLookup,
        picks: Sequence[CachedPick],
        *,
        limit: int,
        candidates: int,
        complete: bool,
    ) -> None:
        """Keep an agent's answer for similar questions; a cache that fails keeps nothing.

        A question the lookup did not embed (its scope held nothing to compare with) is
        embedded now, so later questions can be compared with it by meaning.

        Args:
            version: The version searched (its library's budgets apply to the embedding).
            lookup: The search's lookup (its scope and question).
            picks: The picks the pinned version held, best first.
            limit: How many chunks the agent was asked for.
            candidates: How many chunks it looked at.
            complete: False when it picked more than ``limit``.
        """
        question = lookup.question
        configured = await self._configured()
        if (
            not lookup.embedded
            and configured is not None
            and configured.target.identity == lookup.scope.similarity
        ):
            vector = await self._embedded(
                version, lookup.query, configured, lookup.caller, lookup.own
            )
            question = replace(question, vector=vector)
        answer = CachedAgentAnswer(
            scope=lookup.scope,
            question=question,
            picks=tuple(picks),
            limit=limit,
            candidates=candidates,
            complete=complete,
            created_at=self.clock.now(),
        )
        with suppress(AgentCacheError):  # costs an agent run next time only
            await self._cache_call(self.cache.put(answer))

    async def _cache_call[T](self, call: Awaitable[T]) -> T:
        """Await a call to the cache, turning any failure into ``AgentCacheError``.

        Args:
            call: The call.

        Returns:
            Its result.

        Raises:
            AgentCacheError: The call failed; only the error's class is logged, never its
                message, which may hold stored text.
        """
        try:
            return await call
        except Exception as error:
            logger.warning("the agentic answer cache failed: %s", type(error).__name__)
            raise AgentCacheError(type(error).__name__) from error

    async def _embed(self, query: str, configured: _Configured) -> EmbeddedTexts:
        """Build the embedding model and embed the question.

        Args:
            query: The query text.
            configured: The embedding role.

        Returns:
            The question's vector and usage.

        Raises:
            EmbeddingFailedError: The model failed, or anything else went wrong building or
                calling it; only the error's type is logged, never its message, which may echo
                a request, a key or the query. ``CancelledError`` is no ``Exception``, so
                cancelling a search still propagates.
            ProviderUnsupportedError: This process cannot call the model.
        """
        if self.runs is None:
            raise ProviderUnsupportedError(configured.ref.profile, "this process embeds nothing")
        try:
            model = await self.runs.model(configured)
            return await model.embed_query(query)
        except EmbeddingFailedError, ProviderUnsupportedError:
            raise
        except Exception as error:
            logger.warning(
                "the agentic answer cache compares words only: the question embedding raised %s",
                type(error).__name__,
            )
            raise EmbeddingFailedError(str(configured.ref), type(error).__name__) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class AgenticPipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``agentic`` (RET-04).

    An LLM (the library's ``llm`` role) browses the version in Code Mode with the read tools of
    a ``VersionBrowser``, bound to what the caller may see (the pinned version and the search's
    tag filter) and handed to the agent as its ``deps``, and answers with chunk IDs and a
    justification each. The explorer's output guardrail drops any pick ``admit`` refuses; every
    pick is then looked up again in the pinned manifest, under the tag filter: an ID of another
    version, or one the model made up, is dropped, so every result belongs to the version
    searched whatever the model or the adapter do. A run that passes a limit (``bounds``: tool
    calls, requests, tokens, the sandbox, its time), repeats a call as a loop does, passes a
    spend budget, or fails, raises ``AgentStoppedError``: ``RetrievalModes.run`` then answers
    with the best mode without an LLM step and the reason. Failures are logged by class only.
    Each read is recorded in ``reads``, the run's trace.
    """

    providers: AiProviders
    """Resolves and builds the library's ``llm`` model, and prices it."""
    chunks: ChunkRepository
    """The version's chunks."""
    search: SearchIndex
    """The version's BM25 index, the agent's ``search_docs``."""
    spend: AiSpend
    """The ledger, the budgets and the price book the run's ``SpendLimits`` use."""
    explorer: Explorer
    """Runs the agent."""
    articles: VersionArticles | None = None
    """The version's articles (``list_articles``, ``read_article``)."""
    bounds: AgentBounds = field(default_factory=AgentBounds)
    """The run's limits."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Times the run (``<search>.agent``), without the query text."""
    reads: AgentReads = field(default_factory=UnrecordedAgentReads)
    """The runs' trace: every read the agent made."""
    instructions: InstructionFiles | None = None
    """The instruction files kept with each manifest (repo guidance, RET-08); without it none."""
    cache: AgentAnswerCaching | None = None
    """Answers similar questions from earlier answers (#100); ``None``: every search runs the
    agent."""

    async def cached_answer(
        self,
        version: SearchableVersion,
        query: str,
        tag_filter: TagFilter,
        limit: int,
        *,
        caller: str | None,
        ai: LibraryAi | None = None,
    ) -> AgentCacheLookup | None:
        """Look a search up in the agentic answer cache (no LLM call).

        A hit is the most similar cached question of the search's scope at or above the
        threshold whose answer holds at least ``limit`` picks' worth (it was asked for as many)
        and of whose picks the pinned version, under the tag filter, still holds one.

        Args:
            version: The version searched.
            query: The query text.
            tag_filter: The search's tag filter.
            limit: How many chunks the pipeline is asked for.
            caller: The account searching (a paid question embedding counts to it).
            ai: The library's overrides as the search read them; ``None``: read them.

        Returns:
            The lookup (a hit, or a miss to store the agent's answer under); ``None`` without a
            cache, with AI off for the library or without an ``llm`` role.
        """
        if self.cache is None:
            return None
        ai = ai or await self.providers.library_modes.ai_of(version.library)
        if not ai.enabled:
            return None  # nothing of the library is sent, its question embedding included
        found = await self.providers.resolved(ModelRole.LLM, version.library, ai)
        if found is None:
            return None
        return await self.cache.lookup(
            version,
            query,
            tag_filter,
            limit,
            model=found[0],
            bounds=self.bounds,
            caller=caller,
            own=ai.budgets,
            repo_guidance=ai.repo_guidance.value,
            held=lambda picks: self._held(version, tag_filter, picks),
        )

    async def _held(
        self, version: SearchableVersion, tag_filter: TagFilter, picks: Sequence[CachedPick]
    ) -> list[ChunkId]:
        """Say which picks the pinned version holds and the tag filter keeps.

        Args:
            version: The version searched.
            tag_filter: The search's tag filter.
            picks: A cached answer's picks.

        Returns:
            Their chunk IDs that are still there, in order.
        """
        wanted = list(dict.fromkeys(p.chunk_id for p in picks))
        stored = await self.chunks.get_many(version.manifest_id, wanted) if wanted else {}
        return [c for c in wanted if c in stored and tag_filter.keeps(stored[c].row.tags)]

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Let the agent explore the version, then keep its picks that belong to it.

        A search the agentic answer cache answers (``request.agent_cache.hit``) runs no agent:
        its cached picks are looked up again in the pinned manifest, under the tag filter, as
        the agent's own are. A fresh answer is stored for similar questions.

        Args:
            request: What to search; ``limit`` is how many chunks the agent may pick.

        Returns:
            The ``agentic`` answer: the picks found in the version, in the agent's order. A run
            that ends without an answer raises ``AgentStoppedError`` (from ``_explore``).
        """
        lookup = request.agent_cache
        if lookup is not None and lookup.hit is not None:
            answer = await self._answer(
                request, lookup.hit.picks, candidates=lookup.hit.candidates, cache_hit=True
            )
            if answer.hits:
                self.tracer.cache_hit(cache=AGENTIC_ANSWER_CACHE, mode=RetrievalMode.AGENTIC.value)
                return answer
            # Every pick went since the lookup (a re-sync or a retag): the agent answers. Its
            # spend budgets still apply inside the run (SpendLimits); only the LLM search rate
            # limit did not count it.
        library = request.version.library
        browser = VersionBrowser(
            version=request.version,
            chunks=self.chunks,
            search=self.search,
            articles=self.articles,
            tag_filter=request.tag_filter,
            reads=self.reads,
            searched_by=request.search,
        )
        with self.tracer.span(f"{request.search}.{AGENT_STAGE}", mode=RetrievalMode.AGENTIC.value):
            picks = await self._explore(request, browser, library)
        explained = await self._explained(request, browser, picks)
        answer = await self._answer(request, explained, candidates=len(browser.seen))
        if lookup is not None and self.cache is not None and answer.hits:
            kept = {h.chunk_id for h in answer.hits}
            await self.cache.store(
                request.version,
                lookup,
                [p for p in explained if p.chunk_id in kept],
                limit=request.limit,
                candidates=answer.candidates,
                complete=answer.complete,
            )
        return answer

    async def _explore(
        self, request: PipelineRequest, browser: VersionBrowser, library: str
    ) -> Sequence[AgentPick]:
        """Build the model and run the agent within ``bounds.timeout``.

        Args:
            request: The search.
            browser: The read tools on the version.
            library: The library searched.

        Returns:
            The agent's picks.

        Raises:
            AgentStoppedError: The run ended without an answer.
        """
        ai = request.library_ai or await self.providers.library_modes.ai_of(library)
        found = await self.providers.resolved(ModelRole.LLM, library, ai)
        if found is None:
            raise AgentStoppedError(FallbackReason.MODE_UNAVAILABLE.value, "no llm role")
        ref, kind = found
        run = AgentRun(
            question=request.query,
            limit=request.limit,
            bounds=self.bounds,
            budgets=self.spend.budgets_for(ai),
            caller=AiCaller(library=library.casefold(), user=request.caller),
            price=self.spend.prices.price(ref, kind),
        )
        try:
            async with asyncio.timeout(self.bounds.timeout):
                run = replace(run, guidance=await self._guidance(request.version, ai))
                model = await self._model(library)
                return await self.explorer.explore(
                    model, browser, run, ledger=self.spend.ledger, clock=self.spend.clock
                )
        except AgentStoppedError as stopped:
            logger.warning(
                "the agentic search of %s stopped: %s (%s)", library, stopped.reason, stopped.detail
            )
            raise
        except TimeoutError as error:
            logger.warning("the agentic search of %s ran past its time limit", library)
            reason = FallbackReason.AGENT_LIMIT_REACHED.value
            raise AgentStoppedError(reason, "timeout") from error
        except Exception as error:  # an agentic search never fails a search (RET-04)
            # The class only: the message may echo a request, a key or the query.
            kind_of = type(error).__name__
            logger.warning("the agentic search of %s failed: %s", library, kind_of)
            raise AgentStoppedError(FallbackReason.AGENT_FAILED.value, kind_of) from error

    async def _guidance(self, version: SearchableVersion, ai: LibraryAi) -> GuidanceFiles | None:
        """Read the searched version's instruction files, when the library's repo guidance is on.

        Only the files kept with the version's own manifest, framed and bounded
        (``GuidanceFiles.of``). A read that fails ends the run like any other failure
        (``agent_failed``, logged by class only); their text is never logged.

        Args:
            version: The exact version searched.
            ai: The library's AI settings.

        Returns:
            The files for the run, or ``None``.
        """
        if ai.repo_guidance is RepoGuidance.OFF or self.instructions is None:
            return None
        files = await self.instructions.of(version.manifest_id)
        return GuidanceFiles.of(files, trusted=ai.repo_guidance is RepoGuidance.TRUSTED)

    async def _model(self, library: str) -> object:
        """Build the library's ``llm`` model from the profile as it is now.

        Args:
            library: The library searched.

        Returns:
            The model handle.

        Raises:
            AgentStoppedError: The role or its profile went away since the mode was chosen.
        """
        model = await self.providers.model_for(ModelRole.LLM, library)
        if model is None:
            raise AgentStoppedError(FallbackReason.MODE_UNAVAILABLE.value, "no llm role")
        return model

    async def _explained(
        self, request: PipelineRequest, browser: VersionBrowser, picks: Sequence[AgentPick]
    ) -> list[CachedPick]:
        """Give each picked chunk its justification and how the agent reached it.

        Args:
            request: The search.
            browser: The read tools, which recorded the explored path.
            picks: The agent's picks, best first.

        Returns:
            One pick per chunk, in order: its first justification, made safe to show, and the
            calls up to the first that reached its article (every call for a chunk the pinned
            version does not hold, which is dropped later).
        """
        first: dict[ChunkId, str] = {}
        for pick in picks:
            first.setdefault(ChunkId(pick.chunk_id), pick.justification)
        rows = await self.chunks.get_many(request.version.manifest_id, list(first)) if first else {}
        return [
            CachedPick(
                chunk_id=chunk_id,
                justification=model_text(why, MAX_JUSTIFICATION_CHARS),
                explored_path=browser.path_to(rows[chunk_id].row.article_path)
                if chunk_id in rows
                else (),
            )
            for chunk_id, why in first.items()
        ]

    async def _answer(
        self,
        request: PipelineRequest,
        picks: Sequence[CachedPick],
        *,
        candidates: int,
        cache_hit: bool = False,
    ) -> PipelineAnswer:
        """Keep the picks the pinned version holds and the tag filter allows, as hits.

        Args:
            request: The search.
            picks: The agent's picks (or a cached answer's), best first, once each.
            candidates: How many chunks the agent looked at.
            cache_hit: The picks come from the agentic answer cache.

        Returns:
            The ``agentic`` answer; each hit carries its justification and explored path.
        """
        wanted = [p.chunk_id for p in picks]
        why = {p.chunk_id: p for p in picks}
        stored = await self.chunks.get_many(request.version.manifest_id, wanted)
        kept = [
            stored[c]
            for c in wanted
            if c in stored and request.tag_filter.keeps(stored[c].row.tags)
        ]
        terms = search_terms(request.query)
        hits = []
        for rank, chunk in enumerate(kept[: request.limit]):
            hit = leading_hit(chunk.row.chunk_id, 1.0 / (rank + 1), chunk.chunk.content, terms)
            pick = why[chunk.row.chunk_id]
            hits.append(
                replace(hit, justification=pick.justification, explored_path=pick.explored_path)
            )
        return PipelineAnswer(
            mode=RetrievalMode.AGENTIC,
            hits=tuple(hits),
            candidates=max(candidates, len(kept)),
            reranked=0,
            complete=len(kept) <= request.limit,
            cache_hit=cache_hit,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HydePipeline:
    """Implements ``ports.driven.RetrievalPipeline`` for ``hybrid_hyde`` (RET-03).

    The ``llm`` role writes a short hypothetical answer to the query (HyDE, Gao et al. 2022); its
    embedding, closer to the docs' wording than the question's, searches the vector half, while
    BM25 keeps the query itself (``HybridPipeline.fuse``). The answer is cached per normalized
    query (an HMAC under ``cache_key``), manifest and model, so a repeated query of the same
    version calls no LLM; a cache hit is no LLM call, so ``RetrievalModes.within_budget`` lets it
    through even with a budget used up or the rate limit reached, and does not count it. A cache
    that cannot be read is a miss, one that cannot be written costs a call next time only.

    A call runs within the budgets of #95: ``within_budget`` checked them and the rate limit
    before, and the harness ``SpendLimits`` checks them at the request itself. Whatever stops the
    step never fails the search: a budget answers hybrid with ``llm_budget_reached``, an LLM
    error, an unusable answer or no answer within ``timeout`` with ``llm_unavailable``. When the
    hybrid answer itself falls back too (its query embedding failed), the reason given is
    hybrid's, as it names the mode that really answered (BM25). A timeout that strikes after the
    provider answered may cancel ``SpendLimits`` while it records the spend, which is then lost:
    as rare as the in-flight overshoot the decision record already accepts. Cache hits are not
    counted in ``exactdocs.ai.cache_hits`` (cache ``hyde_answer``).
    Nothing of a library with AI off is sent. Spans and logs never hold the query or the answer.
    """

    hybrid: HybridPipeline
    """Fuses BM25 on the query with the vectors nearest to the hypothetical answer."""
    providers: AiProviders
    """Resolves and builds the library's ``llm`` role, from the profile as it is now."""
    writer: HypotheticalAnswers
    """Writes the hypothetical answer (pydantic-ai)."""
    cache: HypotheticalAnswerCache
    """Hypothetical answers already written."""
    cache_key: bytes
    """The instance's key for the HMAC of the queries in ``cache`` (from its secret key)."""
    spend: AiSpend
    """The budgets, the prices and the clock of the step."""
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Times the step (``<search>.hyde``), without the query text."""
    timeout: float = HYDE_TIMEOUT
    """Seconds to wait for the hypothetical answer before answering with hybrid alone."""

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        """Search by the query's hypothetical answer, or by the query when there is none.

        Args:
            request: What to search; ``space`` is the space to search.

        Returns:
            The ``hybrid_hyde`` answer; or hybrid's (BM25's when the vectors cannot be used),
            with the reason the hypothetical answer was not used (hybrid's own when it has one).
        """
        hypothesis = request.hypothesis or await self._hypothesis(request)
        if request.hypothesis is not None:
            self.tracer.cache_hit(cache=HYDE_ANSWER_CACHE, mode=RetrievalMode.HYBRID_HYDE.value)
        if isinstance(hypothesis, FallbackReason):
            answer = await self.hybrid.run(request)
            return answer if answer.fallback_reason else replace(answer, fallback_reason=hypothesis)
        return await self.hybrid.fuse(request, embed=hypothesis, mode=RetrievalMode.HYBRID_HYDE)

    async def cached_answer(self, version: SearchableVersion, query: str) -> str | None:
        """Read the query's cached hypothetical answer for the version (no LLM call).

        Args:
            version: The version searched.
            query: The query text.

        Returns:
            The answer, or ``None`` when there is none (or AI is off for the library).
        """
        ai = await self.providers.library_modes.ai_of(version.library)
        if not ai.enabled:
            return None
        found = await self.providers.profile_for(ModelRole.LLM, version.library, ai)
        if found is None:
            return None
        return await self._cached(
            HydeKey.of(version.manifest_id, found[0], query, key=self.cache_key)
        )

    async def _cached(self, key: HydeKey) -> str | None:
        """Read a cached answer; a cache that cannot be read is a miss.

        Args:
            key: The answer's key.

        Returns:
            The answer, or ``None``.
        """
        try:
            return await self._cache_call(self.cache.get(key))
        except HypothesisCacheError:  # never a failed search: the LLM is asked instead
            return None

    async def _cache_call[T](self, call: Awaitable[T]) -> T:
        """Await a call to the cache, turning any failure into ``HypothesisCacheError``.

        Args:
            call: The call.

        Returns:
            Its result.

        Raises:
            HypothesisCacheError: The call failed; only the error's class is logged, never its
                message, which may hold the stored answer.
        """
        try:
            return await call
        except Exception as error:
            logger.warning("the HyDE cache failed: %s", type(error).__name__)
            raise HypothesisCacheError(type(error).__name__) from error

    async def _hypothesis(self, request: PipelineRequest) -> str | FallbackReason:
        """Read the cached hypothetical answer, or have the ``llm`` role write it.

        Args:
            request: The search.

        Returns:
            The answer, or why there is none.
        """
        library = request.version.library
        ai = await self.providers.library_modes.ai_of(library)
        if not ai.enabled:
            return FallbackReason.MODE_UNAVAILABLE  # AI off: the query is never sent
        found = await self.providers.profile_for(ModelRole.LLM, library, ai)
        if found is None:  # the role went away since the mode was chosen
            return FallbackReason.MODE_UNAVAILABLE
        ref, profile = found
        key = HydeKey.of(request.version.manifest_id, ref, request.query, key=self.cache_key)
        if (cached := await self._cached(key)) is not None:
            self.tracer.cache_hit(cache=HYDE_ANSWER_CACHE, mode=RetrievalMode.HYBRID_HYDE.value)
            return cached
        step = LlmStep(
            caller=AiCaller(library=library.casefold(), user=request.caller),
            budgets=self.spend.budgets_for(ai),
            price=self.spend.prices.price(ref, profile.kind.value),
            clock=self.spend.clock.now,
        )
        try:
            thinking = await self.providers.thinking_of(ModelRole.LLM, ai)
            with self.tracer.span(f"{request.search}.hyde", mode=RetrievalMode.HYBRID_HYDE.value):
                async with asyncio.timeout(self.timeout):
                    text = await self._written(request.query, ref, profile, step, thinking)
        except LlmBudgetReachedError:
            return FallbackReason.LLM_BUDGET_REACHED
        except LlmFailedError, ProviderUnsupportedError, TimeoutError:
            return FallbackReason.LLM_UNAVAILABLE
        # A cache that cannot be written costs a call next time only.
        with suppress(HypothesisCacheError):
            await self._cache_call(self.cache.put(key, text, self.spend.clock.now()))
        return text

    async def _written(
        self,
        query: str,
        ref: ModelRef,
        profile: ProviderProfile,
        step: LlmStep,
        thinking: ThinkingLevel | None,
    ) -> str:
        """Build the ``llm`` role's model and have it write the hypothetical answer.

        Args:
            query: The query text.
            ref: The role's model.
            profile: Its profile, as it is now.
            step: Who it counts to and the budgets it runs within.
            thinking: The role's thinking level for the library.

        Returns:
            The answer, stripped.

        Raises:
            LlmBudgetReachedError: A budget refused the request.
            LlmFailedError: The model failed, answered nothing, or anything else went wrong
                building or calling it; only the error's type is kept, never its message,
                which may echo a request, a key or the query. ``CancelledError`` is no
                ``Exception``, so cancelling a search still propagates.
            ProviderUnsupportedError: This process cannot call the model.
        """
        try:
            model = await self.providers.factory.chat_model(profile, ref.model, thinking=thinking)
            written = await self.writer.write(model, query, step=step)
        except LlmBudgetReachedError, LlmFailedError, ProviderUnsupportedError:
            raise
        except Exception as error:  # never a failed search (RET-03)
            logger.warning(
                "hybrid_hyde search answers hybrid: the hypothetical answer raised %s",
                type(error).__name__,
            )
            raise LlmFailedError(str(ref), type(error).__name__) from error
        text = written.text.strip()
        if not text:
            raise LlmFailedError(str(ref), "an empty answer")
        return text


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanEmbeddingUseCase:
    """Implements ``ports.driving.PlanEmbedding``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""
    versions: SearchableVersions
    """Finds the version's active manifest."""

    async def __call__(self, command: EmbedVersionCommand) -> EmbeddingPlanOut:
        """Pick the version's space (creating it for a new model) and count what is missing.

        Args:
            command: The version.

        Returns:
            The plan; ``skipped`` when nothing of the version is to be sent.
        """
        configured = await self.runs.configured()
        if configured is None:
            return _skipped(EmbeddingSkip.NO_MODEL)
        if not (await self.runs.providers.library_modes.ai_of(command.library)).enabled:
            return _skipped(EmbeddingSkip.AI_OFF)
        if self.runs.vectors is None or not await self.runs.vectors.available():
            # No store, or its extension cannot be loaded (pgvector's `vector` not in the
            # PostgreSQL database): nothing could be stored, so nothing is sent.
            return _skipped(EmbeddingSkip.VECTOR_STORE_UNAVAILABLE)
        version = await self.versions.find(command.library, command.ref)
        if version is None:
            return _skipped(EmbeddingSkip.NO_VERSION)
        async with self.runs.lock:
            space = await self.runs.space(configured.target)
            created = space is None
            if space is None:
                dimensions = configured.target.dimensions
                if dimensions is None:
                    dimensions = await (await self.runs.model(configured)).dimensions()
                spec = configured.target.spec(dimensions)
                space = await self.runs.store().create_space(spec, self.runs.clock.now())
        # Each chunk once, as the batches embed it: not the manifest's rows, one per path (#431).
        missing = await self.runs.store().count_missing(space.id, version.manifest_id)
        return EmbeddingPlanOut(
            space_id=space.id,
            manifest_id=version.manifest_id,
            missing=missing,
            created=created,
            skipped=None,
        )


def _skipped(reason: EmbeddingSkip) -> EmbeddingPlanOut:
    """Plan to send nothing.

    Args:
        reason: Why.

    Returns:
        The plan.
    """
    return EmbeddingPlanOut(
        space_id=None, manifest_id=None, missing=0, created=False, skipped=reason
    )


def _done(left: int | None = None) -> EmbeddedBatchOut:
    """Say a batch embedded nothing and the job is done.

    Args:
        left: The chunks still without a vector; ``None`` when the job stops without counting.

    Returns:
        The batch.
    """
    return EmbeddedBatchOut(embedded=0, input_tokens=0, left=left, finished=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbedBatchUseCase:
    """Implements ``ports.driving.EmbedBatch``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""

    async def __call__(self, command: EmbedBatchCommand) -> EmbeddedBatchOut:
        """Embed the next chunks of the manifest without a vector, and record the usage.

        Args:
            command: The plan's version, manifest and space.

        Returns:
            What was stored; ``finished`` when nothing is left, or nothing may be sent any more.
        """
        runs = self.runs
        configured = await runs.configured()
        if configured is None or runs.vectors is None:
            return _done()
        if not (await runs.providers.library_modes.ai_of(command.library)).enabled:
            return _done()  # switched off meanwhile: nothing more of it is sent
        space = await runs.space(configured.target)
        if space is None or space.id != command.space_id:
            return _done()  # the model changed: its own jobs embed the version
        local = configured.target.profile_kind in FREE_PROFILE_KINDS
        if runs.spend is not None and not local:  # before the batch: a used-up budget stops it
            await runs.spend.embedding_batch(command.library)  # a local model costs nothing (#284)
        vectors = runs.store()
        keys = await vectors.missing(space.id, command.manifest_id, runs.batch_size)
        sources = await runs.chunks.embedding_sources(command.manifest_id, keys)
        if not sources:  # nothing left, or found embedded by a job sharing chunks with this one
            return _done(await vectors.count_missing(space.id, command.manifest_id))
        ordered = sorted(sources)
        titles: Mapping[str, str] = {}
        if runs.titles is not None:  # the plan's manifest: the job's library runs one job at a time
            paths = tuple(sorted({sources[k].article_path for k in ordered}))
            titles = await runs.titles.titles(
                ManifestPaths(manifest_id=command.manifest_id, paths=paths)
            )
        texts = [
            embedding_text(titles.get(sources[k].article_path, ""), sources[k]) for k in ordered
        ]
        embedded = await (await runs.model(configured)).embed_documents(texts)
        if runs.spend is not None:
            await runs.spend.ledger.add(
                embedding_spend(
                    runs.clock.now(),
                    input_tokens=embedded.input_tokens,
                    requests=embedded.requests,
                    library=command.library,
                    usd_per_million=runs.price(configured),
                    local=local,
                )
            )
        try:
            stored = await vectors.upsert(
                space.id, dict(zip(ordered, embedded.vectors, strict=True))
            )
            # Counted again rather than worked out: other jobs embed chunks shared with this one.
            left = await vectors.count_missing(space.id, command.manifest_id)
        except RetiredEmbeddingSpaceError:
            return _done()
        return EmbeddedBatchOut(
            embedded=stored,
            input_tokens=embedded.input_tokens,
            left=left,
            finished=len(keys) < runs.batch_size or stored == 0,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FinishEmbeddingUseCase:
    """Implements ``ports.driving.FinishEmbedding``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""

    async def __call__(self, command: FinishEmbeddingCommand) -> FinishedEmbeddingOut:
        """Activate the configured model's space once it covers every version; retire older ones.

        Until then the older spaces stay (a search of a version the new space does not cover
        answers BM25 meanwhile); afterwards their vectors are dropped.

        Args:
            command: The space a job embedded into.

        Returns:
            Its state, and the spaces retired now.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
        """
        runs = self.runs
        vectors = runs.store()
        async with runs.lock:
            spaces = await vectors.spaces()
            space = next((s for s in spaces if s.id == command.space_id), None)
            if space is None:
                raise UnknownEmbeddingSpaceError(command.space_id)
            configured = await runs.configured()
            current = None if configured is None else current_space(configured.target, spaces)
            if current is None or current.id != space.id:
                return _finished(space, [])  # another model is configured now: not this one's
            if space.state is SpaceState.BUILDING:
                for version in await runs.active_versions():
                    if not await runs.covers(space, version.manifest_id):
                        return _finished(space, [])
                space = await vectors.activate_space(space.id, runs.clock.now())
            # Every other space, newer ones too: a model switched to and then away from (A, B,
            # back to A) leaves a half-filled space that no configured model will finish.
            retired = [
                s.id for s in spaces if s.id != space.id and s.state is not SpaceState.RETIRED
            ]
            for space_id in retired:
                await vectors.retire_space(space_id)
        return _finished(space, retired)


def _finished(space: EmbeddingSpace, retired: Sequence[EmbeddingSpaceId]) -> FinishedEmbeddingOut:
    """Describe a space after ``FinishEmbedding``.

    Args:
        space: The space.
        retired: The spaces retired now.

    Returns:
        The DTO.
    """
    return FinishedEmbeddingOut(space_id=space.id, state=space.state, retired=list(retired))


@dataclass(frozen=True, slots=True, kw_only=True)
class ListUnembeddedVersionsUseCase:
    """Implements ``ports.driving.ListUnembeddedVersions``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""

    async def __call__(self, query: UnembeddedVersionsQuery) -> UnembeddedVersionsOut:
        """List the versions the configured model's space does not cover (all without a space).

        Args:
            query: Every library, or one.

        Returns:
            The versions; none when no embedding model or no vector store is configured, and
            none of a library while a budget its embedding counts to is used up, unless the
            model is a ``local`` one, which no budget stops (#284).
        """
        configured = await self.runs.configured()
        if configured is None or self.runs.vectors is None:
            return UnembeddedVersionsOut(versions=[])
        space = await self.runs.space(configured.target)
        local = configured.target.profile_kind in FREE_PROFILE_KINDS
        spent: dict[str, bool] = {}
        versions: list[VersionRefOut] = []
        for v in await self.runs.active_versions(query.library):
            if space is not None and await self.runs.covers(space, v.manifest_id):
                continue
            if v.library not in spent:
                spent[v.library] = not local and await self._spent(v.library)
            if not spent[v.library]:
                versions.append(VersionRefOut(library=v.library, ref=v.ref))
        return UnembeddedVersionsOut(versions=versions)

    async def _spent(self, library: str) -> bool:
        """Say whether a budget keeps the library from being embedded now.

        Its versions are queued again when the window resets, not now: a job would only stop
        before its first batch.

        Args:
            library: The library.

        Returns:
            True when a budget its embedding counts to is used up.
        """
        if self.runs.spend is None:
            return False
        scopes = AiCaller(library=library).embedding_scopes()
        return await self.runs.spend.reached(scopes) is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class EstimateEmbeddingUseCase:
    """Implements ``ports.driving.EstimateEmbedding``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""

    async def __call__(self) -> EmbeddingEstimateOut:
        """Count what the configured model has not embedded, and price it.

        Returns:
            The estimate; zeros and no model when no embedding model is configured. Fails with
            ``VectorStoreUnavailableError`` when the instance has no vector store.
        """
        configured = await self.runs.configured()
        if configured is None:
            return EmbeddingEstimateOut(
                model=None,
                space_id=None,
                versions=0,
                chunks=0,
                characters=0,
                estimated_tokens=0,
                usd_per_million_tokens=None,
                estimated_usd=None,
            )
        space = await self.runs.space(configured.target)
        versions = await self.runs.active_versions()
        pending = await self.runs.store().pending(
            None if space is None else space.id, [v.manifest_id for v in versions]
        )
        pending = pending.with_titles(await self._titles(pending))
        price = self.runs.price(configured)
        return EmbeddingEstimateOut(
            model=str(configured.ref),
            space_id=None if space is None else space.id,
            versions=len(versions),
            chunks=pending.chunks,
            characters=pending.characters,
            estimated_tokens=pending.estimated_tokens,
            usd_per_million_tokens=price,
            estimated_usd=estimated_usd(pending.estimated_tokens, price),
        )

    async def _titles(self, pending: PendingChunks) -> dict[tuple[str, str], str]:
        """Read the titles the pending chunks are embedded with: one lookup per manifest.

        Args:
            pending: The chunks, per article.

        Returns:
            The title of each (manifest ID, article path).
        """
        if self.runs.titles is None:
            return {}
        by_manifest: dict[str, set[str]] = {}
        for article in pending.articles:
            by_manifest.setdefault(article.manifest_id, set()).add(article.article_path)
        found: dict[tuple[str, str], str] = {}
        for manifest_id, paths in sorted(by_manifest.items()):
            titles = await self.runs.titles.titles(
                ManifestPaths(manifest_id=manifest_id, paths=tuple(sorted(paths)))
            )
            found |= {(manifest_id, path): title for path, title in titles.items()}
        return found


@dataclass(frozen=True, slots=True, kw_only=True)
class GetEmbeddingProgressUseCase:
    """Implements ``ports.driving.GetEmbeddingProgress``."""

    runs: EmbeddingRuns
    """The embedding model and its spaces."""

    async def __call__(self) -> EmbeddingProgressOut:
        """Count, per space that is not retired, the versions and chunks it has vectors for.

        Returns:
            The configured model and the spaces, oldest first; no space without a vector store.
        """
        configured = await self.runs.configured()
        model = None if configured is None else str(configured.ref)
        if self.runs.vectors is None:
            return EmbeddingProgressOut(model=model, spaces=[])
        store = self.runs.store()
        spaces = [s for s in await store.spaces() if s.state is not SpaceState.RETIRED]
        current = None if configured is None else await self.runs.space(configured.target)
        versions = await self.runs.active_versions() if spaces else []
        progress: list[EmbeddingSpaceProgressOut] = []
        manifests = [v.manifest_id for v in versions]
        empty = VectorCoverage(chunks=0, embedded=0)
        for space in spaces:
            per_manifest = await store.coverage_many(space.id, manifests)  # one query per space
            covered = [per_manifest.get(m, empty) for m in manifests]
            progress.append(
                EmbeddingSpaceProgressOut(
                    id=space.id,
                    profile_kind=space.spec.profile_kind,
                    model=space.spec.model,
                    dimensions=space.spec.dimensions,
                    state=space.state,
                    current=current is not None and current.id == space.id,
                    created_at=space.created_at,
                    activated_at=space.activated_at,
                    versions=len(versions),
                    versions_embedded=sum(c.complete for c in covered),
                    chunks=sum(c.chunks for c in covered),
                    chunks_embedded=sum(min(c.embedded, c.chunks) for c in covered),
                )
            )
        return EmbeddingProgressOut(model=model, spaces=progress)


@dataclass(frozen=True, slots=True, kw_only=True)
class CountVersionChunksUseCase:
    """Implements ``ports.driving.CountVersionChunks`` (#513).

    A fixed number of queries, whatever the number of versions: no query per version.
    """

    runs: EmbeddingRuns
    """The indexed manifests, which are active, and the configured model's space."""
    access: AccessPolicy
    """Library roles: what the caller may do with the library."""

    async def __call__(self, query: CountVersionChunksQuery) -> VersionChunkCounts:
        """Count the chunks of the versions' active manifests and those embedded.

        Args:
            query: The library and the refs.

        Returns:
            The counts by ref; 0 and 0 for a ref with no indexed active manifest. A library
            hidden from the caller raises ``UnknownLibraryError``.
        """
        await _require(self.access, query.library, Access.READ)
        library = query.library.lower()
        wanted = {f"{library}/{ref}": ref for ref in query.refs}
        indexed = [
            m
            for m in await self.runs.chunks.find_manifests(
                manifest_id=None, library=library, indexed_before=None
            )
            if m.version_id in wanted
        ]
        statuses = (
            await self.runs.manifests.statuses([m.manifest_id for m in indexed]) if indexed else {}
        )
        active = {
            m.manifest_id: wanted[m.version_id]
            for m in indexed
            if statuses.get(m.manifest_id) is ManifestStatus.ACTIVE
        }
        counts = await self.runs.chunks.counts_many(active) if active else {}
        embedded = await self._embedded(list(active)) if active else {}
        found = {ref: VersionChunksOut(chunks=0, embedded_chunks=0) for ref in query.refs}
        for manifest_id, ref in active.items():
            chunks = counts[manifest_id].chunks if manifest_id in counts else 0
            found[ref] = VersionChunksOut(
                chunks=chunks, embedded_chunks=min(embedded.get(manifest_id, 0), chunks)
            )
        return VersionChunkCounts(versions=found)

    async def _embedded(self, manifest_ids: list[str]) -> dict[str, int]:
        """Count the chunks of these manifests with a vector in the configured model's space.

        Args:
            manifest_ids: The active manifests.

        Returns:
            The embedded chunks per manifest; none without a model, a vector store or a space.
        """
        configured = await self.runs.configured()
        if configured is None or self.runs.vectors is None:
            return {}
        space = await self.runs.space(configured.target)
        if space is None:
            return {}
        coverage = await self.runs.store().coverage_many(space.id, manifest_ids)
        return {m: c.embedded for m, c in coverage.items()}


# ---------------------------------------------------------------- external indexes (#352)


def _key(stored: StoredChunk) -> ChunkKey:
    """Name the stored chunk a manifest row points at (what a vector is keyed by).

    Args:
        stored: The chunk with its row.

    Returns:
        (blob SHA, config hash, position).
    """
    return (stored.row.chunk_set[0], stored.row.chunk_set[1], stored.row.position)


def _drifted(
    kind: IndexKind,
    manifests: Sequence[IndexedManifest],
    expected: Mapping[str, int],
    held: Sequence[HeldVersion],
    *,
    orphans: bool,
    space_id: EmbeddingSpaceId | None = None,
) -> list[VersionDrift]:
    """Compare what a backend holds with what the stored chunks give.

    Args:
        kind: The index compared.
        manifests: The versions in scope, as the database has them.
        expected: Entries each version should have (a version without any is left out).
        held: What the backend holds, in the same scope.
        orphans: Also report versions only the backend holds (the scope is not one version).
        space_id: The embedding space, for the vector index.

    Returns:
        Every version that drifted.
    """
    by_id = {h.manifest_id: h for h in held}
    found: list[VersionDrift] = []
    for manifest in manifests:
        want = expected.get(manifest.manifest_id, 0)
        have = by_id[manifest.manifest_id].entries if manifest.manifest_id in by_id else 0
        if have >= want:
            continue
        found.append(
            VersionDrift(
                kind=kind,
                drift=DriftKind.INCOMPLETE if have else DriftKind.MISSING,
                manifest_id=manifest.manifest_id,
                library=manifest.library,
                version_id=manifest.version_id,
                expected=want,
                held=have,
                space_id=space_id,
            )
        )
    if orphans:
        known = {m.manifest_id for m in manifests}
        found += [
            VersionDrift(
                kind=kind,
                drift=DriftKind.ORPHANED,
                manifest_id=h.manifest_id,
                library=h.library,
                version_id=None,
                expected=0,
                held=h.entries,
                space_id=space_id,
            )
            for h in held
            if h.manifest_id not in known
        ]
    return found


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalIndexes:
    """Keeps the external search and vector backends in step with the stored chunks (#352).

    The database is the source of truth: a backend holds a derived copy, one entry per chunk row
    of each version (version isolation), written from the database and rebuilt from it. A write
    the backend does not take is tried ``attempts`` times with doubling waits, inside the job
    step that made it; then ``IndexBackendUnavailableError`` fails that job (an import, an
    embedding batch, a removal or collection, a re-tag), whose retry writes it again, and the
    drift check names whatever is still missing. Writes come before the database's own change
    where losing them would go unnoticed: a removal deletes from the backends first, a vector
    reaches the backend before the store takes it (else the embed job would find it done).
    """

    chunks: ChunkRepository
    """The stored chunks: what every entry is made from."""
    search: SearchBackend | None = None
    """The external search backend; ``None``: search lives in the database."""
    vectors: VectorBackend | None = None
    """The external vector backend; ``None``: vectors live in the database alone."""
    store: VectorIndex | None = None
    """The database's vector store: its spaces and coverage (needed with ``vectors``)."""
    stored: StoredVectors | None = None
    """Reads the store's vectors back, for a version's copy (needed with ``vectors``)."""
    attempts: int = EXTERNAL_WRITE_ATTEMPTS
    """Tries of one write while the backend does not answer."""
    retry_seconds: float = EXTERNAL_WRITE_RETRY_SECONDS
    """The first wait between tries; it doubles each time."""
    page_size: int = EXTERNAL_PAGE
    """Chunks read and written per call."""
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    """Waits between tries (tests: no wait)."""

    @property
    def kinds(self) -> tuple[IndexKind, ...]:
        """The external indexes configured, search first."""
        configured = ((IndexKind.SEARCH, self.search), (IndexKind.VECTORS, self.vectors))
        return tuple(kind for kind, backend in configured if backend is not None)

    async def write(self, backend: IndexBackend, call: Callable[[], Awaitable[None]]) -> None:
        """Make one write, trying again with a growing wait while the backend does not answer.

        The last try's ``IndexBackendUnavailableError`` is the caller's: it fails the job.

        Args:
            backend: The backend written to (named in the log).
            call: Makes the write.
        """
        for attempt in range(self.attempts - 1):
            try:
                await call()
            except IndexBackendUnavailableError as error:
                logger.warning(
                    "the index backend %r did not take a write (try %d of %d): %s",
                    backend.name,
                    attempt + 1,
                    self.attempts,
                    error.reason,
                )
                await self.sleep(self.retry_seconds * 2**attempt)
            else:
                return
        await call()

    async def live_spaces(self) -> list[EmbeddingSpace]:
        """List the embedding spaces whose vectors the vector backend holds a copy of.

        Returns:
            Every space that is not retired; none without an external vector backend.
        """
        if self.vectors is None or self.store is None:
            return []
        return [s for s in await self.store.spaces() if s.state is not SpaceState.RETIRED]

    async def put_version(
        self, manifest: IndexedManifest, paths: Collection[str] | None = None
    ) -> tuple[int, int]:
        """Write a version's chunks, and their stored vectors in every space in use, page by page.

        Adds or replaces entries, so it is safe to repeat (a replayed import, a rebuild).

        Args:
            manifest: The version.
            paths: Only the chunks of these articles; every chunk when ``None``.

        Returns:
            The entries written to the search backend and to the vector backend.
        """
        if not self.kinds:
            return (0, 0)
        spaces = await self.live_spaces()
        search, vectors = 0, 0
        after: ChunkId | None = None
        while read := await self.chunks.page(manifest.manifest_id, after, self.page_size):
            after = read[-1].row.chunk_id
            page = read if paths is None else [c for c in read if c.row.article_path in paths]
            if page and self.search is not None:
                backend = self.search
                entries = [index_entry(manifest, c) for c in page]
                await self.write(backend, partial(backend.put, manifest, entries))
                search += len(entries)
            for space in spaces if page else ():
                vectors += await self._put_vectors(space, manifest, page)
            if len(read) < self.page_size:
                break
        return (search, vectors)

    async def _put_vectors(
        self,
        space: EmbeddingSpace,
        manifest: IndexedManifest,
        page: Sequence[StoredChunk],
        vectors: Mapping[ChunkKey, tuple[float, ...]] | None = None,
    ) -> int:
        """Write the entries of these chunks that have a vector in the space.

        Args:
            space: The space.
            manifest: The version.
            page: Some of its chunks.
            vectors: Their vectors; read from the store when not given.

        Returns:
            The entries written.
        """
        backend, store = self.vectors, self.stored
        if backend is None or store is None:
            return 0
        if vectors is None:
            try:
                vectors = await store.stored(space.id, {_key(c) for c in page})
            except UnknownEmbeddingSpaceError, RetiredEmbeddingSpaceError:
                return 0  # retired meanwhile: its copy is dropped with it
        entries = [index_entry(manifest, c, vectors[_key(c)]) for c in page if _key(c) in vectors]
        if entries:
            await self.write(backend, partial(backend.put, space, manifest, entries))
        return len(entries)

    async def copy_vectors(
        self, space: EmbeddingSpace, vectors: Mapping[ChunkKey, tuple[float, ...]]
    ) -> None:
        """Copy vectors of stored chunks to every version that holds those chunks.

        Args:
            space: The space they belong to.
            vectors: The checked, float32 vectors, by chunk.
        """
        if self.vectors is None or not vectors:
            return
        for manifest, rows in await self._by_manifest(await self.chunks.holding(list(vectors))):
            await self._put_vectors(space, manifest, rows, vectors)

    async def remove_vectors(self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]) -> None:
        """Delete the copies of these chunks' vectors from every version that holds them.

        Args:
            space_id: The space.
            keys: The chunks.
        """
        backend = self.vectors
        if backend is None or not keys:
            return
        grouped: dict[str, list[ChunkId]] = {}
        for stored in await self.chunks.holding(list(keys)):
            grouped.setdefault(stored.manifest_id, []).append(stored.row.chunk_id)
        for manifest_id, chunk_ids in grouped.items():
            await self.write(backend, partial(backend.remove, space_id, manifest_id, chunk_ids))

    async def _by_manifest(
        self, rows: Sequence[StoredChunk]
    ) -> list[tuple[IndexedManifest, list[StoredChunk]]]:
        """Group chunk rows by their manifest.

        Args:
            rows: Rows of any manifests.

        Returns:
            Each manifest still indexed, with its rows.
        """
        grouped: dict[str, list[StoredChunk]] = {}
        for stored in rows:
            grouped.setdefault(stored.manifest_id, []).append(stored)
        found: list[tuple[IndexedManifest, list[StoredChunk]]] = []
        for manifest_id, held in grouped.items():
            manifests = await self.chunks.find_manifests(
                manifest_id=manifest_id, library=None, indexed_before=None
            )
            found += [(m, held) for m in manifests]
        return found

    async def forget(self, manifest_ids: Collection[str]) -> None:
        """Delete these versions from every backend (before the database deletes their chunks).

        Args:
            manifest_ids: The versions.
        """
        doomed = list(dict.fromkeys(manifest_ids))
        if not doomed:
            return
        if (search := self.search) is not None:
            await self.write(search, partial(search.delete, doomed))
        if (vectors := self.vectors) is not None:
            await self.write(vectors, partial(vectors.delete, doomed))

    async def drop_space(self, space_id: EmbeddingSpaceId) -> None:
        """Drop a retired space's copy.

        Args:
            space_id: The space.
        """
        if (vectors := self.vectors) is not None:
            await self.write(vectors, partial(vectors.drop_space, space_id))

    async def refresh(self, manifest_id: str, paths: Collection[str]) -> None:
        """Write some articles of a version again, whose tags changed.

        Args:
            manifest_id: The version.
            paths: The articles.
        """
        if not self.kinds:
            return
        for manifest in await self.chunks.find_manifests(
            manifest_id=manifest_id, library=None, indexed_before=None
        ):
            await self.put_version(manifest, paths)

    async def scoped(self, library: str | None, ref: str | None) -> list[IndexedManifest]:
        """List the indexed versions in scope, in a stable order.

        Args:
            library: Only this library's (any letter case).
            ref: Only this version.

        Returns:
            The versions, by version ID then manifest ID.
        """
        manifests = await self.chunks.find_manifests(
            manifest_id=None,
            library=None if library is None else library.lower(),
            indexed_before=None,
        )
        if ref is not None:
            manifests = [m for m in manifests if m.version_id == f"{m.library}/{ref}"]
        return sorted(manifests, key=lambda m: (m.version_id, m.manifest_id))

    async def drift(self, library: str | None, ref: str | None) -> IndexDrift:
        """Compare every backend with the stored chunks of the versions in scope.

        Args:
            library: Only this library's (any letter case).
            ref: Only this version (no orphans are reported then).

        Returns:
            Every version that drifted.
        """
        found: list[VersionDrift] = []
        checked = 0
        lib = None if library is None else library.lower()
        if self.search is not None:
            held = await self.search.held(lib)  # first: a version imported meanwhile is known
            manifests = await self.scoped(library, ref)
            counts = {
                m.manifest_id: (await self.chunks.counts(m.manifest_id)).chunks for m in manifests
            }
            found += _drifted(IndexKind.SEARCH, manifests, counts, held, orphans=ref is None)
            checked += len(manifests)
        vectors, store = self.vectors, self.store
        if vectors is not None and store is not None:
            for space in await self.live_spaces():
                held = await vectors.held(space.id, lib)
                manifests = await self.scoped(library, ref)
                coverage = await store.coverage_many(space.id, [m.manifest_id for m in manifests])
                embedded = {m: c.embedded for m, c in coverage.items()}
                found += _drifted(
                    IndexKind.VECTORS,
                    manifests,
                    embedded,
                    held,
                    orphans=ref is None,
                    space_id=space.id,
                )
                checked += len(manifests)
        return IndexDrift(versions=tuple(found), checked=checked, kinds=self.kinds)

    async def rebuild(self, library: str | None, ref: str | None) -> RebuiltVersions:
        """Write the versions in scope again, then delete what only the backends still hold.

        Args:
            library: Only this library's (any letter case).
            ref: Only this version (nothing is deleted then).

        Returns:
            What was written and deleted.

        Raises:
            UnknownIndexVersionError: ``ref`` names no indexed version in scope.
        """
        manifests = await self.scoped(library, ref)
        if ref is not None and not manifests:
            raise UnknownIndexVersionError(library, ref)
        if not self.kinds:
            return RebuiltVersions(versions=0, search_entries=0, vector_entries=0, orphans=0)
        search, vectors = 0, 0
        for manifest in manifests:
            written = await self.put_version(manifest)
            search, vectors = search + written[0], vectors + written[1]
        orphans = 0 if ref is not None else await self._delete_orphans(library)
        return RebuiltVersions(
            versions=len(manifests), search_entries=search, vector_entries=vectors, orphans=orphans
        )

    async def _delete_orphans(self, library: str | None) -> int:
        """Delete the versions only the backends hold, and the spaces the store retired.

        What the backends hold is read before the database's versions, so a version imported
        meanwhile (database first, then the backends) is never taken for an orphan.

        Args:
            library: Only this library's (any letter case).

        Returns:
            How many versions were deleted.
        """
        lib = None if library is None else library.lower()
        held: set[str] = set()
        if self.search is not None:
            held |= {h.manifest_id for h in await self.search.held(lib)}
        vectors, store = self.vectors, self.store
        if vectors is not None:
            for space in await self.live_spaces():
                held |= {h.manifest_id for h in await vectors.held(space.id, lib)}
        known = {m.manifest_id for m in await self.scoped(library, None)}
        orphans = held - known
        await self.forget(sorted(orphans))
        if vectors is not None and store is not None and library is None:
            for space in await store.spaces():
                if space.state is SpaceState.RETIRED:
                    await self.drop_space(space.id)
        return len(orphans)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalSearchIndex:
    """Implements ``ports.driven.SearchIndex`` and ``SearchIndexMaintenance`` on a backend.

    The backend ranks; the snippets are cut from the stored chunks (``leading_hit``), and a hit
    the database no longer has (a removal the backend has not caught up with) is dropped. The
    database's own index is still written, so switching back needs no reindex, and its format is
    what ``exactdocs reindex`` keeps current; a rebuild also writes the backend again.
    """

    backend: SearchBackend
    """The external search backend."""
    chunks: ChunkRepository
    """The stored chunks: snippets come from them."""
    local: SearchIndex
    """The database's own full-text index, still written."""
    maintenance: SearchIndexMaintenance
    """Reads and rebuilds the database's index."""
    mirror: ExternalIndexes
    """Writes the backend again on a rebuild."""

    async def index(self, chunk_set: ChunkSet) -> None:
        """Index a stored chunk set in the database's index (the import writes the backend).

        Args:
            chunk_set: The stored chunk set.
        """
        await self.local.index(chunk_set)

    async def search(
        self, manifest_id: str, query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[SearchHit]:
        """Return at most ``limit`` chunks of this manifest, best first.

        Args:
            manifest_id: The manifest searched.
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first.
        """
        return [f.hit for f in await self.search_many([manifest_id], query, tag_filter, limit)]

    async def search_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter, limit: int
    ) -> Sequence[ManifestHit]:
        """Return at most ``limit`` chunks of any of these manifests, best first.

        Args:
            manifest_ids: The manifests searched.
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.
            limit: The most hits.

        Returns:
            The hits, best first, each naming its manifest.
        """
        terms = tuple(search_terms(query))
        wanted = list(dict.fromkeys(manifest_ids))
        if not terms or not wanted or limit < 1:
            return []
        hits = await self.backend.search(
            wanted, TextQuery(text=query, terms=terms), tag_filter, limit + EXTERNAL_HIT_MARGIN
        )
        allowed = set(wanted)
        hits = [h for h in hits if h.manifest_id in allowed]  # version isolation, whatever it did
        asked: dict[str, list[ChunkId]] = {}
        for hit in hits:
            asked.setdefault(hit.manifest_id, []).append(hit.chunk_id)
        stored = await self.chunks.get_across(asked)
        return [
            ManifestHit(
                manifest_id=h.manifest_id,
                hit=leading_hit(h.chunk_id, h.score, chunk.chunk.content, terms),
            )
            for h in hits
            if (chunk := stored.get((h.manifest_id, h.chunk_id))) is not None
        ][:limit]

    async def count_many(
        self, manifest_ids: Sequence[str], query: str, tag_filter: TagFilter
    ) -> Mapping[str, int]:
        """Return how many chunks of each manifest match, uncapped; zero counts are left out.

        Args:
            manifest_ids: The manifests searched.
            query: The query text.
            tag_filter: Which tags a chunk's article must carry.

        Returns:
            How many chunks match, by manifest ID.
        """
        terms = tuple(search_terms(query))
        wanted = list(dict.fromkeys(manifest_ids))
        if not terms or not wanted:
            return {}
        counts = await self.backend.count(wanted, TextQuery(text=query, terms=terms), tag_filter)
        return {m: n for m, n in counts.items() if n and m in set(wanted)}

    async def state(self) -> SearchIndexState:
        """Report the database index's format, with the external engine as the one answering.

        Returns:
            The stored and current formats, and ``external``.
        """
        return replace(await self.maintenance.state(), engine=SearchEngine.EXTERNAL)

    async def rebuild(self) -> RebuiltIndex:
        """Rebuild the database's index, then write every version to the backend again.

        Returns:
            The database index's new format and how many chunks it holds.
        """
        rebuilt = await self.maintenance.rebuild()
        await self.mirror.rebuild(None, None)
        return rebuilt


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalVectorIndex:
    """Implements ``ports.driven.VectorIndex``: the database keeps the vectors, a backend searches.

    Spaces, coverage and what is left to embed are the database store's; every vector it takes
    is copied first to each version holding its chunk, and ``nearest`` asks the backend, keeping
    only chunks the database still has. A backend that does not answer a search is
    ``VectorStoreUnavailableError``: hybrid then answers with BM25 and says why.
    """

    store: VectorIndex
    """The database's vector store: the source of every copy."""
    backend: VectorBackend
    """The external vector backend."""
    chunks: ChunkRepository
    """Tells which chunks of a version still exist."""
    mirror: ExternalIndexes
    """Copies the vectors to the backend."""

    def requirement(self) -> str:
        """Name what the database's store needs to keep vectors.

        Returns:
            The store's requirement.
        """
        return self.store.requirement()

    async def available(self) -> bool:
        """Say whether the database's store can keep the vectors the backend is copied from.

        Returns:
            The store's answer.
        """
        return await self.store.available()

    async def spaces(self) -> Sequence[EmbeddingSpace]:
        """List every space, retired ones too, oldest first.

        Returns:
            The store's spaces.
        """
        return await self.store.spaces()

    async def create_space(self, spec: EmbeddingSpec, at: datetime) -> EmbeddingSpace:
        """Create a space in the store (the backend makes its own on the first copy).

        Args:
            spec: The model and format its vectors will be made with.
            at: When it is created.

        Returns:
            The new space.
        """
        return await self.store.create_space(spec, at)

    async def activate_space(self, space_id: EmbeddingSpaceId, at: datetime) -> EmbeddingSpace:
        """Mark the space active in the store.

        Args:
            space_id: The space.
            at: When it became active.

        Returns:
            The space as it is now.
        """
        return await self.store.activate_space(space_id, at)

    async def retire_space(self, space_id: EmbeddingSpaceId) -> None:
        """Retire the space in the store, then drop the backend's copy.

        Args:
            space_id: The space.
        """
        await self.store.retire_space(space_id)
        await self.mirror.drop_space(space_id)

    async def upsert(
        self, space_id: EmbeddingSpaceId, vectors: Mapping[ChunkKey, Sequence[float]]
    ) -> int:
        """Copy the vectors to every version holding their chunks, then store them.

        Args:
            space_id: The space.
            vectors: The vector of each chunk.

        Returns:
            How many vectors the store took.
        """
        space = await self._live(space_id)
        checked = {
            k: as_float32(checked_vector(v, space.spec.dimensions)) for k, v in vectors.items()
        }
        await self.mirror.copy_vectors(space, checked)
        return await self.store.upsert(space_id, checked)

    async def delete(self, space_id: EmbeddingSpaceId, keys: Collection[ChunkKey]) -> int:
        """Delete the backend's copies of these chunks' vectors, then the stored vectors.

        Args:
            space_id: The space.
            keys: The chunks.

        Returns:
            How many stored vectors were deleted.
        """
        await self._live(space_id)
        await self.mirror.remove_vectors(space_id, keys)
        return await self.store.delete(space_id, keys)

    async def nearest(
        self,
        space_id: EmbeddingSpaceId,
        manifest_id: str,
        query: Sequence[float],
        tag_filter: TagFilter,
        limit: int,
    ) -> Sequence[VectorHit]:
        """Ask the backend for the manifest's nearest chunks, keeping those the database has.

        Args:
            space_id: The space.
            manifest_id: The version's manifest.
            query: The query's vector.
            tag_filter: Which chunks may be returned.
            limit: How many hits to return at most.

        Returns:
            The nearest chunks, nearest first.

        Raises:
            VectorStoreUnavailableError: The backend did not answer.
        """
        space = await self._live(space_id)
        vector = checked_vector(query, space.spec.dimensions)
        try:
            near = await self.backend.nearest(
                space, [manifest_id], vector, tag_filter, limit + EXTERNAL_HIT_MARGIN
            )
        except IndexBackendUnavailableError as error:
            raise VectorStoreUnavailableError(str(error)) from error
        near = [h for h in near if h.manifest_id == manifest_id]
        stored = await self.chunks.get_many(manifest_id, [h.chunk_id for h in near])
        return [
            VectorHit(chunk_id=h.chunk_id, distance=h.distance)
            for h in near
            if h.chunk_id in stored
        ][:limit]

    async def coverage(self, space_id: EmbeddingSpaceId, manifest_id: str) -> VectorCoverage:
        """Count the manifest's chunks and those with a stored vector.

        Args:
            space_id: The space.
            manifest_id: The version's manifest.

        Returns:
            The store's counts.
        """
        return await self.store.coverage(space_id, manifest_id)

    async def coverage_many(
        self, space_id: EmbeddingSpaceId, manifest_ids: Collection[str]
    ) -> Mapping[str, VectorCoverage]:
        """Count, for each manifest, its chunks and those with a stored vector.

        Args:
            space_id: The space.
            manifest_ids: The versions' manifests.

        Returns:
            The store's counts per manifest.
        """
        return await self.store.coverage_many(space_id, manifest_ids)

    async def missing(
        self, space_id: EmbeddingSpaceId, manifest_id: str, limit: int
    ) -> Sequence[ChunkKey]:
        """Return chunks of the manifest the store has no vector for yet.

        Args:
            space_id: The space.
            manifest_id: The version's manifest.
            limit: How many keys at most.

        Returns:
            The store's answer.
        """
        return await self.store.missing(space_id, manifest_id, limit)

    async def count_missing(self, space_id: EmbeddingSpaceId, manifest_id: str) -> int:
        """Count the chunks ``missing`` would return without a limit.

        Args:
            space_id: The space.
            manifest_id: The version's manifest.

        Returns:
            The store's count.
        """
        return await self.store.count_missing(space_id, manifest_id)

    async def pending(
        self, space_id: EmbeddingSpaceId | None, manifest_ids: Collection[str]
    ) -> PendingChunks:
        """Count the stored chunks of these manifests without a vector in the space.

        Args:
            space_id: The space; ``None`` counts every chunk.
            manifest_ids: The manifests.

        Returns:
            The store's counts.
        """
        return await self.store.pending(space_id, manifest_ids)

    async def _live(self, space_id: EmbeddingSpaceId) -> EmbeddingSpace:
        """Read a space that is not retired.

        Args:
            space_id: The space.

        Returns:
            It.

        Raises:
            UnknownEmbeddingSpaceError: No space has this ID.
            RetiredEmbeddingSpaceError: It was retired.
        """
        for space in await self.store.spaces():
            if space.id == space_id:
                if space.state is SpaceState.RETIRED:
                    raise RetiredEmbeddingSpaceError(space_id)
                return space
        raise UnknownEmbeddingSpaceError(space_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckExternalIndexesUseCase:
    """Implements ``ports.driving.CheckExternalIndexes``."""

    external: ExternalIndexes
    """Compares the backends with the stored chunks."""

    async def __call__(self, scope: ExternalIndexScope) -> IndexDriftOut:
        """Compare every external backend with the stored chunks of the versions in scope.

        Args:
            scope: Which versions.

        Returns:
            What drifted.
        """
        return IndexDriftOut.from_model(await self.external.drift(scope.library, scope.version))


@dataclass(frozen=True, slots=True, kw_only=True)
class RebuildExternalIndexesUseCase:
    """Implements ``ports.driving.RebuildExternalIndexes``."""

    external: ExternalIndexes
    """Writes the backends from the stored chunks."""

    async def __call__(self, scope: ExternalIndexScope) -> RebuiltVersionsOut:
        """Write the versions in scope to every external backend again.

        Args:
            scope: Which versions.

        Returns:
            What was written.
        """
        rebuilt = await self.external.rebuild(scope.library, scope.version)
        return RebuiltVersionsOut.from_model(rebuilt, self.external.kinds)
