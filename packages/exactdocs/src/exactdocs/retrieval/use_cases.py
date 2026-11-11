import asyncio
import logging
import math
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import NoReturn

from exactdocs.retrieval.constants import (
    CHARS_PER_TOKEN,
    DEFAULT_EMBEDDING_BATCH,
    DEFAULT_QUERY_DOCS_TOKEN_BUDGET,
    FOOTER_CHARS,
    FREE_PROFILE_KINDS,
    MAX_RESOLVED,
    MAX_SEARCHED_LIBRARIES,
    NO_VECTOR_STORE,
    POINTER_TEXT,
    QUERY_DOCS_CANDIDATES,
    QUERY_HITS_CAP,
    RULE_FRAMING_CHARS,
    RULES_FRAMING_CHARS,
    RULES_SHARE,
    SECTION_FRAMING_CHARS,
    SPEND_INSTANCE_ID,
    SPEND_SCOPE_EMBEDDING,
    SPEND_SCOPE_INSTANCE,
    SPEND_SCOPE_LIBRARY,
    UNKNOWN_MANIFEST_GRACE,
)
from exactdocs.retrieval.dtos import (
    AiUsageOut,
    ArticleOutlineOut,
    ArticleOutlineQuery,
    BudgetOut,
    CheckProviderCommand,
    ChunkHeadingOut,
    ChunkOut,
    ChunkSetsOut,
    CollectChunksCommand,
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
    FinishedEmbeddingOut,
    FinishEmbeddingCommand,
    ForgetLibraryCommand,
    GetChunkSetsQuery,
    GetLibraryRetrievalQuery,
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
    SpentOut,
    UnembeddedVersionsOut,
    UnembeddedVersionsQuery,
    VectorStoreStateOut,
    VersionRefOut,
)
from exactdocs.retrieval.errors import (
    AiBudgetReachedError,
    ArticleNotFoundError,
    ChunkNotFoundError,
    InvalidProviderError,
    MovedSection,
    NothingToCheckError,
    ProviderExistsError,
    ProviderInUseError,
    ProviderReadOnlyError,
    ProviderUnsupportedError,
    RerankerError,
    RetiredEmbeddingSpaceError,
    SecretKeyRequiredError,
    StaleChunkError,
    UnknownEmbeddingSpaceError,
    UnknownLibraryError,
    UnknownProviderError,
    VectorStoreUnavailableError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    AiCaller,
    BudgetLimit,
    Budgets,
    Candidate,
    CatalogLibrary,
    Chunk,
    ChunkHeading,
    ChunkId,
    ChunkSet,
    ChunkSetKey,
    DocTarget,
    EmbeddingSkip,
    EmbeddingSpace,
    EmbeddingSpaceId,
    EmbeddingSpec,
    EmbeddingTarget,
    FallbackReason,
    IndexedManifest,
    InstanceRoles,
    KeySource,
    LibraryAi,
    ManifestChunk,
    ManifestPaths,
    ManifestStatus,
    ModeChoice,
    ModelCheck,
    ModelPrice,
    ModelRef,
    ModelRole,
    ModeRegistry,
    NameMatch,
    PendingChunks,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    ReachedBudget,
    RerankLimits,
    RetrievalMode,
    RoleBinding,
    SearchableVersion,
    SearchText,
    SectionRef,
    SpaceState,
    SpendEntry,
    SpendKey,
    SpendWindow,
    StoredChunk,
    TagFilter,
    TagMatch,
    VectorCoverage,
    article_chunk_rows,
    bind_role,
    current_space,
    embedding_spend,
    embedding_text,
    estimated_usd,
    language_first,
    name_match,
    outline,
    rank_matches,
    reorder,
    spend_entries,
)
from exactdocs.retrieval.ports.driven import (
    ActiveManifests,
    ArticleSuggestions,
    ArticleTitles,
    CallRates,
    ChunkRepository,
    DefaultVersions,
    EmbeddingModels,
    Embeddings,
    Libraries,
    LibraryModes,
    ModelFactory,
    ModelRoles,
    Prices,
    ProviderProfiles,
    RenamedPaths,
    Reranker,
    RetrievalPipeline,
    SearchableVersions,
    SearchIndex,
    SearchIndexMaintenance,
    SearchSpan,
    SearchTracer,
    SecretBox,
    SpendLedger,
    VectorIndex,
)
from exactdocs_kernel import NOTICE, Clock, SystemClock

logger = logging.getLogger(__name__)


async def _confirmed_removals(
    manifests: ActiveManifests,
    candidates: Sequence[IndexedManifest],
    *,
    now: datetime,
    pending_too: bool,
) -> list[str]:
    """Import asyncioPick the manifests safe to remove, asking the catalog twice.

    Removable: pending in the catalog (when ``pending_too``), or unknown to it and older than
    the grace period. Everything else stays, including a status we cannot name. The second
    question comes right before the delete and narrows the window in which a manifest could
    be activated; it cannot close it, as that would take a transaction across both domains.
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
class PriceBook:
    """Prices models: the operator's price for a ``<profile>:<model>``, else the bundled list.

    In-process models (``local``) cost nothing; their tokens are still counted. Never fetched
    over the network.
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
            Its spend today and this month, and its budgets (a library's own applied).
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
        if kind == SPEND_SCOPE_LIBRARY:
            budgets = budgets.for_library(own.get(scope_id.casefold(), ()))
        return ScopeUsageOut(
            scope=kind,
            id=scope_id,
            day=SpentOut.from_model(spent[SpendWindow.DAY]),
            month=SpentOut.from_model(spent[SpendWindow.MONTH]),
            budgets=[
                BudgetOut.from_model(limit, spent[limit.window], now)
                for limit in budgets.limits
                if limit.scope_kind == kind
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
    providers: AiProviders | None = None
    """Resolves the reranker's profile: a ``local`` one costs nothing and is never skipped."""

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
        choice = replace(choice, library_ai=ai)
        if not choice.rerank:
            return choice
        if self.reranking is None:
            return replace(choice, rerank=False)
        return replace(choice, rerank_top_n=self.rerank_top_n(ai))

    async def run(
        self,
        choice: ModeChoice,
        version: SearchableVersion,
        query: str,
        tag_filter: TagFilter,
        limit: int,
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

        Returns:
            The pipeline's answer; the choice's fallback reason unless the pipeline gave one
            (``within_budget`` sets ``llm_budget_reached`` or ``llm_rate_limited`` on it when a
            limit skipped the LLM step or the rerank). A mode that searches vectors
            answers BM25 with ``embedding_in_progress`` while the configured model has not
            embedded every chunk of the version (never two models' vectors in one search).
        """
        depth = max(limit, choice.rerank_top_n) if choice.rerank else limit
        request = PipelineRequest(
            version=version,
            query=query,
            tag_filter=tag_filter,
            limit=depth,
            rerank=choice.rerank,
        )
        if choice.mode.needs_vectors and self.embedded is not None:
            found = await self.embedded.search_space(version.manifest_id)
            if not found.searchable:
                answer = await self.pipelines[RetrievalMode.BM25].run(request)
                return replace(answer, fallback_reason=FallbackReason.EMBEDDING_IN_PROGRESS)
            request = replace(request, space=found.space)
        answer = await self.pipelines[choice.mode].run(request)
        if answer.fallback_reason is None and choice.fallback_reason is not None:
            return replace(answer, fallback_reason=choice.fallback_reason)
        return answer

    async def within_budget(
        self, choice: ModeChoice, *, library: str, caller: str | None
    ) -> ModeChoice:
        """Skip the LLM step or the paid rerank a budget or the rate limit does not allow now.

        Called by the search use cases once the version resolved (a search of an unknown
        library or ref uses up nothing), before every later stage (the pipeline, a rerank),
        which all see the same choice.

        Args:
            choice: The mode picked by ``choose``.
            library: The library searched, any letter case.
            caller: The account searching; ``None`` for a stdio MCP process.

        Returns:
            The choice, or the cheaper one without the LLM step, or the same without reranking,
            with the reason.
        """
        choice = replace(choice, caller=caller)
        if self.spend is None:
            return choice
        who = AiCaller(library=library.casefold(), user=caller)
        own = None if choice.library_ai is None else choice.library_ai.budgets
        if choice.mode.needs_llm and (reason := await self.spend.llm_step(who, own)) is not None:
            choice = choice.without_llm(reason)
        if (
            choice.rerank
            # no limit: no need to read the reranker's profile
            and (self.spend.budgets.limits or own)
            and await self._paid_rerank(who.library, choice.library_ai)
            and (reason := await self.spend.paid_call(who, own)) is not None
        ):
            choice = replace(choice, rerank=False, fallback_reason=choice.fallback_reason or reason)
        return choice

    async def _paid_rerank(self, library: str, ai: LibraryAi | None) -> bool:
        """Say whether the library's reranker costs money (any but an in-process one).

        Args:
            library: The library searched.
            ai: Its overrides as read for this search.

        Returns:
            False only for a reranker whose profile is ``local``.
        """
        if self.providers is None:
            return True
        found = await self.providers.resolved(ModelRole.RERANKER, library, ai)
        return found is None or found[1] not in FREE_PROFILE_KINDS

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
        if not choice.rerank or self.reranking is None:
            return answer, {}
        reranked, read = await self.reranking.apply(version, query, answer, choice)
        if reranked.reranked:
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
        if self.spend is None or self.providers is None:
            return
        try:
            found = await self.providers.resolved(
                ModelRole.RERANKER, version.library, choice.library_ai
            )
            if found is None:
                return
            ref, kind = found
            sent = len(query) + sum(
                len(read[h.chunk_id].chunk.content)
                for h in reranked.hits[: reranked.reranked]
                if h.chunk_id in read
            )
            await self.spend.record(
                AiCaller(library=version.library, user=choice.caller).scopes(),
                ref=ref,
                profile_kind=kind,
                input_tokens=-(-sent // CHARS_PER_TOKEN),
            )
        except Exception:
            logger.exception("could not record the spend of a rerank of %s", version.library)


@dataclass(frozen=True, slots=True, kw_only=True)
class Reranking:
    """Reorders a search's best candidates with a cross-encoder (RET-02).

    The reranker is the one the library resolves to (its override, else the instance's
    ``reranker`` role), built from the profile as it is now. It receives the query text and the
    candidates' chunk text only, read before the clock starts. Building the reranker and its call
    must finish within ``limits.timeout``. A reranker that does not, that fails, answers something
    unusable or cannot be built (a profile that cannot rerank, a key that no longer opens) never
    fails the search: the candidates keep the mode's order, ``reranked`` stays 0, and the
    fallback reason says why (when no other reason was given already). Failures are logged
    without the query or any text.
    """

    providers: AiProviders
    """Resolves and builds the library's reranker."""
    chunks: ChunkRepository
    """Reads the candidates' text."""
    limits: RerankLimits = field(default_factory=RerankLimits)
    """The instance's top N and timeout."""

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
        try:
            async with asyncio.timeout(self.limits.timeout):
                reranker = await self._reranker(version.library, choice.library_ai)
                scores = await _called(reranker, query, texts)
        except TimeoutError:
            logger.warning(
                "the reranker of %s did not answer within %ss: the search keeps its order",
                version.library,
                self.limits.timeout,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_TIMEOUT), stored
        except RerankerError as error:
            logger.warning(
                "the reranker of %s failed: %s; the search keeps its order", version.library, error
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED), stored
        if len(scores) != len(kept) or not all(math.isfinite(score) for score in scores):
            logger.warning(
                "the reranker of %s did not answer one finite score per candidate; the search "
                "keeps its order",
                version.library,
            )
            return _fallen_back(answer, FallbackReason.RERANKER_FAILED), stored
        reranked = replace(
            answer, hits=(*reorder(kept, scores), *answer.hits[len(kept) :]), reranked=len(kept)
        )
        return reranked, stored

    async def _reranker(self, library: str, ai: LibraryAi | None) -> Reranker:
        """Build the library's reranker from the profile as it is now.

        Args:
            library: The library searched.
            ai: Its overrides, as read for this search; ``None`` reads them.

        Returns:
            The reranker.

        Raises:
            RerankerError: No reranker resolves for the library, or building it failed, for
                whatever reason (the profile cannot rerank here, its key does not open, its key
                file cannot be read, a partly installed SDK).
        """
        try:
            reranker = await self.providers.reranker_for(library, ai)
        except Exception as error:  # a reranker problem never fails a search; re-raised as ours
            # Never the error's text: only its kind, which holds no key, URL or path.
            reason = f"it could not be built ({_kind(error)})"
            raise RerankerError(reason) from error
        if reranker is None:
            reason = "no reranker resolves for the library"
            raise RerankerError(reason)
        return reranker


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


def _fallen_back(answer: PipelineAnswer, reason: FallbackReason) -> PipelineAnswer:
    """Keep the answer's order and say why it was not reranked, unless a reason is given already.

    Args:
        answer: The pipeline's answer.
        reason: Why reranking did not happen.

    Returns:
        The answer, not reranked, with the first fallback reason.
    """
    return replace(answer, reranked=0, fallback_reason=answer.fallback_reason or reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchDocsUseCase:
    """Implements ``ports.driving.SearchDocs``."""

    versions: SearchableVersions
    modes: RetrievalModes
    """Picks the mode and runs its pipeline."""
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

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
        # Built only to refuse a whitespace-only query (EmptySearchTextError).
        text = SearchText(value=query.query)
        choice = await self.modes.choose(asked=query.mode, library=query.library)
        with self.tracer.span(
            "search_docs",
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
        with self.tracer.span("search_docs.version", mode=mode):
            version = await self.versions.find(query.library, query.ref)
        if version is None:
            raise VersionNotIndexedError(query.library, query.ref or "(default version)")
        # Only a search that will run counts against the caller's limits; every stage after this
        # one sees the same choice.
        choice = await self.modes.within_budget(choice, library=version.library, caller=caller)
        mode = choice.mode.value
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        with self.tracer.span("search_docs.rank", mode=mode) as rank:
            answer = await self.modes.run(choice, version, text.value, tag_filter, query.limit)
            rank.answered_by(answer.mode.value)
        whole.answered_by(answer.mode.value)
        read: Mapping[ChunkId, StoredChunk] = {}
        if choice.rerank:  # a stage of its own; it records neither the query nor any text
            with self.tracer.span("search_docs.rerank", mode=answer.mode.value):
                answer, read = await self.modes.rerank(choice, version, text.value, answer)
        answer = answer.cut(query.limit)
        if answer.fallback_reason is not None:
            self.tracer.fallback(mode=answer.mode.value, reason=answer.fallback_reason.value)
        with self.tracer.span("search_docs.chunks", mode=answer.mode.value):
            stored = await _chunks_of(self.chunks, version, answer, read)
        # A chunk gone since the search (the manifest was collected) leaves no result, and is not
        # counted as a candidate either, so results and coverage stay consistent.
        results = [
            SearchResultOut.from_models(version, stored[hit.chunk_id], hit)
            for hit in answer.hits
            if hit.chunk_id in stored
        ]
        vanished = len(answer.hits) - len(results)
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
            results=results,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchAllLibrariesUseCase:
    """Implements ``ports.driving.SearchAllLibraries``."""

    defaults: DefaultVersions
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: SearchAllQuery) -> SearchAllResult:
        """Rank the chunks of all default versions together; count the matches per library.

        There is no ``mode`` (BM25 only until E11), unlike ``search_docs``. With ``library`` set
        every library is still resolved: the counts stay global, which a facet needs.
        """
        text = SearchText(value=query.query)
        mode = RetrievalMode.BM25.value
        with self.tracer.span(
            "search_all_libraries", mode=mode, query=text.value, library=query.library
        ):
            return await self._search(query, text, mode)

    async def _search(self, query: SearchAllQuery, text: SearchText, mode: str) -> SearchAllResult:
        """Resolve the default versions, rank and count, then load the shown chunks.

        Args:
            query: The search as asked.
            text: Its validated query text.
            mode: The retrieval mode it runs in.

        Returns:
            The results across the libraries, with a facet per library.
        """
        tag_filter = TagFilter(tags=tuple(query.tags), match=query.tags_match)
        with self.tracer.span("search_all_libraries.versions", mode=mode):
            every = await self.defaults.all()
        searched = {v.manifest_id: v for v in every[:MAX_SEARCHED_LIBRARIES]}
        omitted = len(every) - len(searched)
        scope = searched
        if query.library is not None:
            with self.tracer.span("search_all_libraries.versions", mode=mode):
                only = await self.versions.find(query.library, None)
            if only is None:
                raise VersionNotIndexedError(query.library, "(default version)")
            if only.manifest_id not in searched:  # beyond the cap: searched, so no longer omitted
                searched[only.manifest_id] = only
                omitted -= 1
            scope = {only.manifest_id: only}
        # One more than asked for tells whether the answer was cut short.
        with self.tracer.span("search_all_libraries.rank", mode=mode):
            found_hits, counts = await asyncio.gather(
                self.search.search_many(list(scope), text.value, tag_filter, query.limit + 1),
                self.search.count_many(list(searched), text.value, tag_filter),
            )
        shown = found_hits[: query.limit]
        wanted: dict[str, list[ChunkId]] = {}
        for found_hit in shown:
            wanted.setdefault(found_hit.manifest_id, []).append(found_hit.hit.chunk_id)
        with self.tracer.span("search_all_libraries.chunks", mode=mode):
            stored = await self.chunks.get_across(wanted)
        # A chunk gone since the search (the manifest was collected) leaves no result.
        results = [
            LibrarySearchResultOut.of(
                searched[found_hit.manifest_id],
                stored[found_hit.manifest_id, found_hit.hit.chunk_id],
                found_hit.hit,
            )
            for found_hit in shown
            if (found_hit.manifest_id, found_hit.hit.chunk_id) in stored
        ]
        vanished = len(shown) - len(results)
        facets = sorted(
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
        return SearchAllResult(
            retrieval_mode=RetrievalMode.BM25,
            reranked=False,
            coverage=CoverageOut(
                candidates=len(found_hits) - vanished,
                reranked=0,
                complete=len(found_hits) <= query.limit,
            ),
            libraries_searched=len(searched),
            libraries_omitted=omitted,
            libraries=facets,
            results=results,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexManifestUseCase:
    """Implements ``ports.driving.IndexManifest``."""

    chunks: ChunkRepository
    search: SearchIndex
    clock: Clock

    async def __call__(self, command: IndexManifestCommand) -> IndexedManifestOut:
        """Compute the chunk IDs, store the rows plus the new chunk sets, and make them searchable.

        Call it between the catalog's store (pending) and its activate, never after.
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
        """Make the chunk sets and rows: CPU-bound (chunk IDs are hashed), so run in a thread."""
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
    manifests: ActiveManifests
    chunks: ChunkRepository
    renames: RenamedPaths | None = None

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Serve the chunk from its version's active manifest, or say why it cannot be served."""
        chunk_id = ChunkId(query.chunk_id)
        holders = await self.chunks.manifests_with_chunk(chunk_id)
        # The ID is a hash of the version it was issued for, so all holders share one version_id.
        # Anything else is not a state we understand: refuse rather than guess from the first row.
        if len({m.version_id for m in holders}) != 1:
            raise ChunkNotFoundError(query.chunk_id)
        first = holders[0]
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
            raise StaleChunkError(query.chunk_id, first.library, ref, moved)
        raise ChunkNotFoundError(query.chunk_id)  # only pending manifests hold it: not served yet

    async def _moved(
        self, version: SearchableVersion | None, chunk_id: ChunkId, old_manifest: str
    ) -> MovedSection | None:
        """Find the stale chunk's section in the active manifest: two reads, one rename lookup.

        The article is the old path, or where the rename map put it. The rename map covers one hop
        (the active manifest against the version before it), so an ID several re-syncs old whose
        article moved earlier gets no location. The section is then picked by ``_pick``.
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
    chunks: ChunkRepository
    """The article's chunk rows in that version's active manifest."""
    suggestions: ArticleSuggestions | None = None
    """Close paths for a miss, as ``read_article`` lists them; none without it."""

    async def __call__(self, query: ArticleOutlineQuery) -> ArticleOutlineOut:
        """Build the outline from the article's chunk rows in the version's active manifest.

        Args:
            query: The library, the exact ref (or none for the default version) and the path.

        Returns:
            The heading tree with a chunk ID per heading and the version that answered.

        Raises:
            VersionNotIndexedError: The version is not imported or has no active manifest.
            ArticleNotFoundError: The version has no article at this path.
        """
        version = await self.versions.find(query.library, query.ref)
        if version is None:
            raise VersionNotIndexedError(query.library, query.ref or "(default version)")
        sections = await self.chunks.article(version.manifest_id, query.path)
        if not sections:
            target = DocTarget(library=version.library, version=version.version)
            close = await self.suggestions.close_to(target, query.path) if self.suggestions else ()
            raise ArticleNotFoundError(version.library, version.version, query.path, close)
        return ArticleOutlineOut.from_model(
            version, query.path, outline(sections), chunks=len(sections)
        )


def _nearest(sections: Sequence[SectionRef], position: int) -> SectionRef | None:
    """Return the section nearest to ``position``; ``None`` when two are equally near."""
    ranked = sorted(sections, key=lambda s: abs(s.position - position))
    if len(ranked) > 1 and abs(ranked[0].position - position) == abs(ranked[1].position - position):
        return None
    return ranked[0] if ranked else None


def _pick(current: Sequence[SectionRef], was: Chunk, position: int) -> SectionRef | None:
    """Pick the section of ``current`` that ``was`` became, or ``None`` if unsure.

    In order: same headings and same text; same headings and occurrence (text edited); same text
    anywhere. Several equal candidates go to the nearest position, and a tie names no section:
    an ambiguous answer is better than a wrong ID. The occurrence alone is not trusted with the
    text unchecked, since an inserted duplicate heading shifts it onto another section.

    Known limit: if a duplicate heading is inserted above *and* the old section's text is
    edited too, the occurrence step lands on the inserted section. The match is then marked
    ``text_changed``, so the agent is told to re-check it.
    """
    same_headings = [s for s in current if s.heading_path == was.heading_path]
    same_text = [s for s in current if s.content_hash == was.content_hash]
    if both := [s for s in same_headings if s in same_text]:
        return _nearest(both, position)
    if edited := [s for s in same_headings if s.occurrence_index == was.occurrence_index]:
        return edited[0]
    return _nearest(same_text, position)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetChunkSetsUseCase:
    """Implements ``ports.driving.GetChunkSets``."""

    chunks: ChunkRepository

    async def __call__(self, query: GetChunkSetsQuery) -> ChunkSetsOut:
        """Look the sets up by (blob, config); sets that were never stored are left out."""
        found = await self.chunks.get_sets(
            [(sha, query.config_hash) for sha in dict.fromkeys(query.blob_shas)]
        )
        return ChunkSetsOut(
            chunks={
                sha: [
                    SetChunkOut(
                        heading_path=list(c.heading_path),
                        occurrence_index=c.occurrence_index,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardPendingChunksUseCase:
    """Implements ``ports.driving.DiscardPendingChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: DiscardPendingChunksCommand) -> RemovedChunks:
        """Delete rows of matching manifests the catalog holds as pending, or dropped long ago."""
        now = self.clock.now()
        older = command.older_than_seconds
        candidates = await self.chunks.find_manifests(
            manifest_id=command.manifest_id,
            library=None if command.library is None else command.library.lower(),
            indexed_before=None if older is None else now - timedelta(seconds=older),
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=True)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectChunksUseCase:
    """Implements ``ports.driving.CollectChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository
    clock: Clock

    async def __call__(self, command: CollectChunksCommand) -> RemovedChunks:
        """Run after the catalog's collection: its superseded manifests are gone, so are ours."""
        now = self.clock.now()
        cutoff = now - timedelta(seconds=command.grace_seconds)
        candidates = await self.chunks.find_manifests(
            manifest_id=None, library=None, indexed_before=cutoff
        )
        doomed = await _confirmed_removals(self.manifests, candidates, now=now, pending_too=False)
        return RemovedChunks.from_model(await self.chunks.remove(doomed))


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveChunksUseCase:
    """Implements ``ports.driving.RemoveChunks``."""

    manifests: ActiveManifests
    chunks: ChunkRepository

    async def __call__(self, command: RemoveChunksCommand) -> RemovedChunks:
        """Remove what the catalog has forgotten; keep every manifest it still knows."""
        asked = list(dict.fromkeys(command.manifest_ids))
        known = await self.manifests.statuses(asked)
        return RemovedChunks.from_model(
            await self.chunks.remove([i for i in asked if i not in known])
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetagArticlesUseCase:
    """Implements ``ports.driving.RetagArticles``."""

    chunks: ChunkRepository

    async def __call__(self, command: RetagArticlesCommand) -> RetaggedChunks:
        """Overwrite the tag copies of the named articles' chunk rows."""
        tags = {a.path: tuple(dict.fromkeys(a.tags)) for a in command.articles}
        return RetaggedChunks(chunks=await self.chunks.set_tags(command.manifest_id, tags))


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSearchIndexStateUseCase:
    """Implements ``ports.driving.GetSearchIndexState``."""

    maintenance: SearchIndexMaintenance

    async def __call__(self) -> SearchIndexStateOut:
        """Report the stored format against the current one."""
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

    async def __call__(self) -> RebuiltIndexOut:
        """Build the new index beside the old one, then swap it in."""
        return RebuiltIndexOut.from_model(await self.maintenance.rebuild())


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveLibraryIdUseCase:
    """Implements ``ports.driving.ResolveLibraryId``."""

    libraries: Libraries
    versions: SearchableVersions
    search: SearchIndex
    chunks: ChunkRepository
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

    async def __call__(self, query: ResolveLibraryIdQuery) -> ResolveLibraryIdResult:
        """Match the name, then let the default versions' hits for ``query`` re-rank the matches."""
        # Both refuse blank text the same way (EmptySearchTextError).
        text, name = SearchText(value=query.query), SearchText(value=query.library_name)
        mode = RetrievalMode.BM25.value
        with self.tracer.span("resolve_library_id", mode=mode, query=text.value):
            return await self._resolve(text, name, mode)

    async def _resolve(
        self, text: SearchText, name: SearchText, mode: str
    ) -> ResolveLibraryIdResult:
        """Match the names, then rank them by their hits, one span per stage.

        Args:
            text: The validated query text.
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
        """
        found: list[tuple[CatalogLibrary, NameMatch, SearchableVersion]] = []
        for start in range(0, len(named), MAX_RESOLVED):
            batch = named[start : start + MAX_RESOLVED]
            versions = await asyncio.gather(*(self.versions.find(lib.id, None) for lib, _ in batch))
            found += [(lib, m, v) for (lib, m), v in zip(batch, versions, strict=True) if v]
            if len(found) >= MAX_RESOLVED:
                break
        return found[:MAX_RESOLVED]


def _cost(section: DocSectionOut) -> int:
    """Characters a section takes in the payload: its parts plus the fixed framing."""
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
    modes: RetrievalModes
    """Picks the mode (the library's, else the instance's) and runs its pipeline."""
    chunks: ChunkRepository
    token_budget: int = DEFAULT_QUERY_DOCS_TOKEN_BUDGET
    tracer: SearchTracer = field(default_factory=UntracedSearches)
    """Observes the search and its stages (traces); records nothing by default."""

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
        # context7's tool has no mode argument: the library's mode, else the instance's (C7-02).
        choice = await self.modes.choose(asked=None, library=library)
        with self.tracer.span(
            "query_docs", mode=choice.mode.value, query=text.value, library=library, ref=ref
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
        with self.tracer.span("query_docs.version", mode=mode):
            version = await self.versions.find(library, ref)
        if version is None:
            raise VersionNotIndexedError(library, ref or "(default version)")
        # Only a request that will run counts against the caller's limits.
        choice = await self.modes.within_budget(choice, library=version.library, caller=caller)
        mode = choice.mode.value
        with self.tracer.span("query_docs.rank", mode=mode) as rank:
            answer = await self.modes.run(
                choice,
                version,
                text.value,
                TagFilter(tags=(), match=TagMatch.ANY),
                QUERY_DOCS_CANDIDATES,
            )
            rank.answered_by(answer.mode.value)
        whole.answered_by(answer.mode.value)
        read: Mapping[ChunkId, StoredChunk] = {}
        if choice.rerank:  # a stage of its own; it records neither the query nor any text
            with self.tracer.span("query_docs.rerank", mode=answer.mode.value):
                answer, read = await self.modes.rerank(choice, version, text.value, answer)
        answer = answer.cut(QUERY_DOCS_CANDIDATES)
        if answer.fallback_reason is not None:
            self.tracer.fallback(mode=answer.mode.value, reason=answer.fallback_reason.value)
        with self.tracer.span("query_docs.chunks", mode=answer.mode.value):
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
        rerank_top_n=ai.rerank_top_n,
        effective_rerank_top_n=modes.rerank_top_n(ai),
        budgets=LibraryBudgets.from_limits(ai.budgets),
        budget_ceilings=LibraryBudgets.from_ceilings(
            budgets.ceiling(SpendWindow.DAY), budgets.ceiling(SpendWindow.MONTH)
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLibraryRetrievalUseCase:
    """Implements ``ports.driving.GetLibraryRetrieval``."""

    libraries: Libraries
    """Spells the library ID as the catalog does."""
    modes: RetrievalModes
    """The instance's modes and the libraries' settings."""

    async def __call__(self, query: GetLibraryRetrievalQuery) -> LibraryRetrievalOut:
        """Read the library's mode and the one its searches use now.

        Args:
            query: The library.

        Returns:
            Its setting, the effective mode and the modes available.
        """
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

    async def __call__(self, command: SetLibraryRetrievalCommand) -> LibraryRetrievalOut:
        """Validate the settings against what can run with them, then store them.

        Args:
            command: The library, its mode and its AI overrides.

        Returns:
            The stored settings, the effective mode and the modes available.

        Raises:
            UnknownLibraryError: There is no such library.
            UnknownProviderError: An override names a profile that does not exist.
            ProviderUnsupportedError: An override names a profile this installation cannot call.
        """
        library = await self.libraries.canonical_id(command.library)
        if library is None:
            raise UnknownLibraryError(command.library)
        ai = LibraryAi(
            enabled=command.ai_enabled,
            llm=_parse_ref(command.llm),
            judge=_parse_ref(command.judge),
            reranker=_parse_ref(command.reranker),
            rerank_top_n=command.rerank_top_n,
            budgets=command.budgets.limits(),
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
        mode = None
        if command.mode is not None:
            mode = (await self.modes.registry(library, ai)).check(command.mode)
        await self.modes.library_modes.save(library, mode, ai)
        return await _library_retrieval(self.modes, library, mode, ai)


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetLibraryUseCase:
    """Implements ``ports.driving.ForgetLibrary``."""

    library_modes: LibraryModes
    """Each library's own mode, dropped with the library."""

    async def __call__(self, command: ForgetLibraryCommand) -> None:
        """Drop what retrieval keeps per library, so a library re-added later starts clean.

        Args:
            command: The removed library.
        """
        await self.library_modes.forget(command.library)


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

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        """Refuse.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            Nothing: it raises ``ProviderUnsupportedError``.
        """
        return self._refuse(profile, model)

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

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        """Report that nothing can be called.

        Args:
            profile: The profile.
            model: The model.
            role: The role.

        Returns:
            A failed check.
        """
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
        if ai is None:
            ai = await self.library_modes.ai_of(library)
        binding = bind_role(role, self.roles, ai)
        if binding is None:
            return None
        profile = await self.profile(binding.ref.profile)
        return None if profile is None else (binding.ref, profile.kind.value)

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
        binding = bind_role(role, self.roles, await self.library_modes.ai_of(library))
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
                return await self.factory.chat_model(profile, binding.ref.model)

    async def reranker_for(self, library: str, ai: LibraryAi | None = None) -> Reranker | None:
        """Build the reranker a library's searches use, from the profile as it is now.

        Args:
            library: The library ID, any letter case.
            ai: The library's overrides, when the caller read them already; ``None`` reads them.

        Returns:
            The reranker, or ``None`` when the role does not resolve for the library (AI off,
            no role, a profile that no longer exists). The factory raises
            ``ProviderUnsupportedError`` for a profile that cannot rerank here.
        """
        if ai is None:
            ai = await self.library_modes.ai_of(library)
        binding = bind_role(ModelRole.RERANKER, self.roles, ai)
        if binding is None:
            return None
        profile = await self.profile(binding.ref.profile)
        if profile is None:
            return None
        return await self.factory.reranker(profile, binding.ref.model)

    async def check(self, binding_role: ModelRole | None, ref: ModelRef) -> ModelCheck:
        """Make one minimal call, or say why it cannot be made.

        Args:
            binding_role: The role being checked; ``None`` when not a configured role.
            ref: The profile and model.

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
        return await self.factory.check(profile, ref.model, role)


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
            bindings = [
                b for b in self.providers.instance_bindings() if b.ref.profile == command.name
            ]
            if not bindings:
                raise NothingToCheckError(command.name)
            checks = [await self.providers.check(b.role, b.ref) for b in bindings]
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
            await self.providers.check(b.role, b.ref) for b in self.providers.instance_bindings()
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
        bound = {b.role: b for b in self.providers.instance_bindings()}
        roles = []
        for role in ModelRole:
            binding = bound.get(role)
            exists = (
                binding is not None
                and await self.providers.profile(binding.ref.profile) is not None
            )
            roles.append(
                RoleOut(
                    role=role,
                    model=None if binding is None else str(binding.ref),
                    source=None if binding is None else binding.source,
                    profile_exists=exists,
                )
            )
        return RoleListOut(roles=roles)


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
        coverage = await self.runs.store().coverage(space.id, version.manifest_id)
        return EmbeddingPlanOut(
            space_id=space.id,
            manifest_id=version.manifest_id,
            missing=coverage.chunks - coverage.embedded,
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


def _done() -> EmbeddedBatchOut:
    """Say a batch embedded nothing and the job is done.

    Returns:
        The batch.
    """
    return EmbeddedBatchOut(embedded=0, input_tokens=0, finished=True)


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
        if runs.spend is not None:  # before the batch: a used-up budget stops the job here
            await runs.spend.embedding_batch(command.library)
        vectors = runs.store()
        keys = await vectors.missing(space.id, command.manifest_id, runs.batch_size)
        sources = await runs.chunks.embedding_sources(command.manifest_id, keys)
        if not sources:
            return _done()
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
                )
            )
        try:
            stored = await vectors.upsert(
                space.id, dict(zip(ordered, embedded.vectors, strict=True))
            )
        except RetiredEmbeddingSpaceError:
            return _done()
        return EmbeddedBatchOut(
            embedded=stored,
            input_tokens=embedded.input_tokens,
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
            none of a library while a budget its embedding counts to is used up.
        """
        configured = await self.runs.configured()
        if configured is None or self.runs.vectors is None:
            return UnembeddedVersionsOut(versions=[])
        space = await self.runs.space(configured.target)
        spent: dict[str, bool] = {}
        versions: list[VersionRefOut] = []
        for v in await self.runs.active_versions(query.library):
            if space is not None and await self.runs.covers(space, v.manifest_id):
                continue
            if v.library not in spent:
                spent[v.library] = await self._spent(v.library)
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
