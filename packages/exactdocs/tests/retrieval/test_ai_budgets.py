"""RET-07: AI spend is limited by budgets and rate limits, and a limit degrades search.

Budgets per instance, library and user (UTC day and month, tokens and US dollars) are read from
the same ledger rows every AI call adds to; the LLM search rate limit is per caller. A limit
skips the LLM step or the paid rerank (the search answers in the cheaper mode and says why), and
stops an embedding job before its next batch.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from exactdocs.retrieval.adapters.driven.memory import (
    HashEmbeddingModels,
    InMemoryCallRates,
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
    InMemoryVectorIndex,
    ReadOnlySpendLedger,
    StaticPrices,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbedVersionCommand,
    GetLibraryRetrievalQuery,
    IndexManifestCommand,
    LibraryBudgets,
    QueryDocsQuery,
    SearchDocsQuery,
    SetLibraryRetrievalCommand,
    UnembeddedVersionsQuery,
)
from exactdocs.retrieval.errors import (
    AiBudgetReachedError,
    InvalidBudgetError,
    LibraryBudgetAboveInstanceError,
    UnknownSpendKeyError,
    VersionNotIndexedError,
)
from exactdocs.retrieval.models import (
    AiCaller,
    BudgetLimit,
    Budgets,
    CatalogLibrary,
    DocTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModeChoice,
    ModelCheck,
    ModelPrice,
    ModelRef,
    ModelRole,
    PipelineAnswer,
    PipelineRequest,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpendEntry,
    SpendKey,
    SpendWindow,
    spend_entries,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import Reranker, RetrievalPipeline, SearchTracer
from exactdocs.retrieval.use_cases import (
    AiSpend,
    Bm25Pipeline,
    PriceBook,
    RetrievalModes,
    UntracedSearches,
)

LIB = "/acme/payments"
OTHER = "/acme/other"
ADA, BOB = "account-ada", "account-bob"
T0 = datetime(2026, 11, 30, 23, 0, tzinfo=UTC)
DAY, MONTH = SpendWindow.DAY, SpendWindow.MONTH
BM25, HYBRID, HYDE, AGENTIC = (
    RetrievalMode.BM25,
    RetrievalMode.HYBRID,
    RetrievalMode.HYBRID_HYDE,
    RetrievalMode.AGENTIC,
)
USD = 1_000_000


@dataclass(slots=True)
class Clock:
    at: datetime = T0

    def now(self) -> datetime:
        return self.at


def _version(library: str, ref: str, manifest: str) -> SearchableVersion:
    return SearchableVersion(
        library=library,
        version=ref,
        manifest_id=manifest,
        commit_sha=manifest[-1] * 40,
        repository_url="https://github.com/acme/x",
        host=SourceHost.GITHUB,
    )


@dataclass(slots=True)
class Versions:
    by_key: dict[tuple[str, str], SearchableVersion]

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return self.by_key.get((library.lower(), ref or "v2"))

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        active = {v.manifest_id for v in self.by_key.values()}
        return {m: ManifestStatus.ACTIVE for m in manifest_ids if m in active}

    async def titles(self, articles: object) -> dict[str, str]:
        del articles
        return {}


@dataclass(slots=True)
class FakePipeline:
    """Answers as ``mode`` with the BM25 hits of the requested version (reranking is a stage of
    its own, through the ``Reranking`` and the factory's reranker)."""

    mode: RetrievalMode
    bm25: RetrievalPipeline
    requests: list[PipelineRequest] = field(default_factory=list)

    async def run(self, request: PipelineRequest) -> PipelineAnswer:
        self.requests.append(request)
        found = await self.bm25.run(request)
        return PipelineAnswer(
            mode=self.mode,
            hits=found.hits,
            candidates=found.candidates,
            reranked=0,
            complete=found.complete,
        )


@dataclass(slots=True)
class Roles:
    roles: frozenset[ModelRole]

    async def configured(self, library: str, ai: LibraryAi | None = None) -> frozenset[ModelRole]:
        del library, ai
        return self.roles


@dataclass(slots=True)
class World:
    module: RetrievalModule
    ledger: InMemorySpendLedger
    clock: Clock
    pipelines: dict[RetrievalMode, FakePipeline]
    models: HashEmbeddingModels
    reranker: CountingReranker


def _chunk(heading: str, content: str) -> ChunkIn:
    return ChunkIn(
        heading_path=[heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}-{content}",
        anchor=heading.lower(),
    )


async def _build(
    *roles: ModelRole,
    budgets: Budgets | None = None,
    rates: bool = True,
    reranker_kind: ProviderKind = ProviderKind.OPENAI_COMPATIBLE,
    embedding: bool = False,
    tracer: SearchTracer | None = None,
    price_overrides: dict[str, ModelPrice] | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    bm25 = Bm25Pipeline(search=index)
    factory = EmbedderFactory()
    fakes = {m: FakePipeline(mode=m, bm25=bm25) for m in RetrievalMode}
    versions = Versions(
        {
            (LIB, "v1"): _version(LIB, "v1", "m1"),
            (LIB, "v2"): _version(LIB, "v2", "m2"),
            (OTHER, "v2"): _version(OTHER, "v2", "m3"),
        }
    )
    ledger = InMemorySpendLedger()
    clock = Clock()
    models = HashEmbeddingModels(size=4)
    profile = ProviderProfile(
        name="corp",
        kind=reranker_kind,
        origin=ProfileOrigin.CONFIGURATION,
        base_url=None if reranker_kind is ProviderKind.LOCAL else "https://llm.example.com/v1",
    )
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(),
        libraries=InMemoryLibraries(
            libraries=[
                CatalogLibrary(
                    id=lib,
                    title=lib,
                    description="",
                    source_url="https://github.com/acme/x",
                    default_version="v2",
                    versions=("v2",),
                    version_count=1,
                )
                for lib in (LIB, OTHER)
            ]
        ),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        roles=None if embedding else Roles(frozenset(roles)),
        configured_profiles=[profile],
        instance_roles=InstanceRoles(
            reranker=ModelRef(profile="corp", model="rerank"),
            embedding=ModelRef(profile="corp", model="a") if embedding else None,
        ),
        models=factory,
        pipelines=fakes,
        vectors=InMemoryVectorIndex(chunks=chunks) if embedding else None,
        embedding_models=models if embedding else None,
        spend=ledger,
        prices=StaticPrices(input_prices={("openai-compatible", "a"): 0.02}),
        price_overrides=price_overrides,
        budgets=budgets,
        call_rates=InMemoryCallRates() if rates else None,
        clock=clock,
        embedding_batch_size=1,
        tracer=tracer,
    )
    for library, manifest, ref, text in [
        (LIB, "m1", "v1", "retry_policy is old"),
        (LIB, "m2", "v2", "Use a token. retry_policy"),
        (OTHER, "m3", "v2", "Other token docs."),
    ]:
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=library,
                ref=ref,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path="docs/guide.md",
                        blob_sha=f"b-{manifest}",
                        chunks=[_chunk("Guide", text), _chunk("More", f"{text} more")],
                    )
                ],
            )
        )
    return World(
        module=module,
        ledger=ledger,
        clock=clock,
        pipelines=fakes,
        models=models,
        reranker=factory.counting,
    )


@dataclass(slots=True)
class CountingReranker:
    """A reranker that scores the documents in reverse and records what it was sent."""

    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        return [float(i) for i in range(len(documents))]


@dataclass(slots=True)
class EmbedderFactory:
    """``ModelFactory`` whose embedder is a marker (the hash models ignore it)."""

    counting: CountingReranker = field(default_factory=CountingReranker)

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        del profile, model
        return self.counting

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        raise AssertionError((profile, model, role))

    async def release(self, name: str) -> None:
        del name


async def _spend(world: World, kind: str, scope_id: str, window: SpendWindow, usd: int) -> None:
    await world.ledger.add(
        [
            SpendEntry(
                scope_kind=kind,
                scope_id=scope_id,
                window=window,
                window_start=window.start(world.clock.at),
                input_tokens=500,
                output_tokens=500,
                requests=1,
                usd_micros=usd,
            )
        ]
    )


async def _search(
    world: World, mode: str | None = None, caller: str | None = ADA, library: str = LIB
) -> tuple[RetrievalMode, FallbackReason | None, bool, bool]:
    result = await world.module.search_docs(
        SearchDocsQuery(library=library, query="token", mode=mode), caller=caller
    )
    return result.retrieval_mode, result.fallback_reason, result.reranked, bool(result.results)


def _limit(kind: str, window: SpendWindow = DAY, usd: float | None = 1, tokens: int | None = None):
    return BudgetLimit(
        scope_kind=kind,
        window=window,
        usd_micros=None if usd is None else round(usd * USD),
        tokens=tokens,
    )


# ---------------------------------------------------------------- the model


def test_windows_are_utc_days_and_months_and_reset_at_the_next_one() -> None:
    late = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)
    in_warsaw = datetime(2026, 12, 1, 0, 30, tzinfo=UTC).astimezone(timezone(timedelta(hours=1)))

    assert DAY.start(late) == date(2026, 12, 31)
    assert MONTH.start(late) == date(2026, 12, 1)
    assert DAY.resets_at(late) == datetime(2027, 1, 1, tzinfo=UTC)
    assert MONTH.resets_at(late) == datetime(2027, 1, 1, tzinfo=UTC)
    assert MONTH.resets_at(T0) == datetime(2026, 12, 1, tzinfo=UTC)
    assert DAY.start(in_warsaw) == date(2026, 12, 1)


@pytest.mark.parametrize(("usd", "tokens"), [(None, None), (0, None), (None, 0), (-1, None)])
def test_a_budget_limits_something(usd: int | None, tokens: int | None) -> None:
    with pytest.raises(InvalidBudgetError):
        BudgetLimit(scope_kind="instance", window=DAY, usd_micros=usd, tokens=tokens)


def test_budgets_refuse_unknown_scopes_and_rates_below_one() -> None:
    with pytest.raises(UnknownSpendKeyError):
        BudgetLimit(scope_kind="team", window=DAY, tokens=10)
    with pytest.raises(InvalidBudgetError):
        Budgets(llm_searches_per_minute=0)


def test_a_limit_is_reached_at_either_ceiling() -> None:
    key = SpendKey(scope_kind="user", scope_id=ADA, window=DAY, window_start=date(2026, 11, 30))
    limit = BudgetLimit(scope_kind="user", window=DAY, usd_micros=USD, tokens=1000)
    row = SpendEntry.empty(key)

    assert not limit.reached(row)
    assert limit.reached(SpendEntry.empty(key).plus(_entry(key, usd=USD)))
    assert limit.reached(SpendEntry.empty(key).plus(_entry(key, tokens=600, output=400)))
    assert not limit.reached(SpendEntry.empty(key).plus(_entry(key, tokens=999)))


def _entry(key: SpendKey, *, usd: int = 0, tokens: int = 0, output: int = 0) -> SpendEntry:
    return SpendEntry(
        scope_kind=key.scope_kind,
        scope_id=key.scope_id,
        window=key.window,
        window_start=key.window_start,
        input_tokens=tokens,
        output_tokens=output,
        usd_micros=usd,
        requests=1,
    )


def test_each_scope_of_a_kind_has_its_own_ceiling() -> None:
    budgets = Budgets(limits=(_limit("library"), _limit("user", MONTH, usd=None, tokens=10)))
    ada = AiCaller(library=LIB, user=ADA)
    keys = budgets.keys(ada.scopes(), T0)
    spent = {
        SpendKey(scope_kind="library", scope_id=OTHER, window=DAY, window_start=T0.date()): (
            SpendEntry.empty(
                SpendKey(scope_kind="library", scope_id=OTHER, window=DAY, window_start=T0.date())
            ).plus(
                _entry(
                    SpendKey(
                        scope_kind="library", scope_id=OTHER, window=DAY, window_start=T0.date()
                    ),
                    usd=5 * USD,
                )
            )
        )
    }

    assert {(k.scope_kind, k.scope_id, k.window) for k in keys} == {
        ("library", LIB, DAY),
        ("user", ADA, MONTH),
    }
    assert budgets.reached(ada.scopes(), spent, T0) is None  # another library's spend
    # A stdio process has no account: per-user limits never apply to it.
    assert {k.scope_kind for k in budgets.keys(AiCaller(library=LIB).scopes(), T0)} == {"library"}


def test_one_call_is_written_to_every_scope_and_window_at_its_price() -> None:
    price = ModelPrice(input_usd_per_million=2.0, output_usd_per_million=8.0)

    entries = spend_entries(
        T0,
        AiCaller(library=LIB, user=ADA).scopes(),
        input_tokens=1000,
        output_tokens=500,
        requests=1,
        price=price,
    )

    assert {(e.scope_kind, e.window) for e in entries} == {
        (kind, window) for kind in ("instance", "library", "user") for window in SpendWindow
    }
    assert {(e.usd_micros, e.unpriced) for e in entries} == {(6000, 0)}  # $0.002 + $0.004


def test_prices_come_from_the_operator_then_free_kinds_then_the_bundled_list() -> None:
    listed = StaticPrices(
        input_prices={("openai", "gpt"): 1.0}, output_prices={("openai", "gpt"): 4.0}
    )
    book = PriceBook(
        listed=listed,
        overrides={"corp:gpt": ModelPrice(input_usd_per_million=0.4, output_usd_per_million=1.6)},
    )

    assert book.price(ModelRef(profile="corp", model="gpt"), "openai") == ModelPrice(
        input_usd_per_million=0.4, output_usd_per_million=1.6
    )
    assert book.price(ModelRef(profile="oa", model="gpt"), "openai") == ModelPrice(
        input_usd_per_million=1.0, output_usd_per_million=4.0
    )
    assert book.price(ModelRef(profile="mine", model="x"), "local") == ModelPrice(
        input_usd_per_million=0.0
    )
    assert book.price(ModelRef(profile="oa", model="unknown"), "openai") is None


async def test_the_rate_limit_is_a_sliding_minute_per_caller() -> None:
    rates = InMemoryCallRates()

    assert [await rates.allow("ada", 2, T0) for _ in range(3)] == [True, True, False]
    assert await rates.allow("bob", 2, T0)  # another caller counts on its own
    assert not await rates.allow("ada", 2, T0 + timedelta(seconds=59))
    assert await rates.allow("ada", 2, T0 + timedelta(seconds=61))


# ---------------------------------------------------------------- searches


async def test_a_used_up_instance_budget_skips_the_llm_step_and_answers_in_the_cheaper_mode() -> (
    None
):
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("instance"),)))
    assert await _search(world, "agentic") == (AGENTIC, None, False, True)

    await _spend(world, "instance", "", DAY, USD)

    assert await _search(world, "agentic") == (BM25, FallbackReason.LLM_BUDGET_REACHED, False, True)
    assert len(world.pipelines[AGENTIC].requests) == 1  # never asked again


async def test_hyde_falls_back_to_hybrid_not_bm25() -> None:
    world = await _build(
        ModelRole.LLM, ModelRole.EMBEDDING, budgets=Budgets(limits=(_limit("instance"),))
    )
    await _spend(world, "instance", "", DAY, USD)

    assert await _search(world, "hybrid_hyde") == (
        HYBRID,
        FallbackReason.LLM_BUDGET_REACHED,
        False,
        True,
    )


@pytest.mark.parametrize(
    ("kind", "scope_id", "window"),
    [("library", LIB, DAY), ("user", ADA, MONTH), ("instance", "", MONTH)],
)
async def test_library_user_and_monthly_budgets_count_too(
    kind: str, scope_id: str, window: SpendWindow
) -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit(kind, window),)))
    await _spend(world, kind, scope_id, window, 2 * USD)

    assert (await _search(world, "agentic"))[:2] == (BM25, FallbackReason.LLM_BUDGET_REACHED)
    if kind == "library":
        assert (await _search(world, "agentic", library=OTHER))[0] is AGENTIC
    if kind == "user":
        assert (await _search(world, "agentic", caller=BOB))[0] is AGENTIC
        assert (await _search(world, "agentic", caller=None))[0] is AGENTIC  # stdio


async def test_a_token_budget_counts_input_and_output_tokens() -> None:
    world = await _build(
        ModelRole.LLM, budgets=Budgets(limits=(_limit("instance", usd=None, tokens=1000),))
    )
    await _spend(world, "instance", "", DAY, 0)  # 500 in, 500 out

    assert (await _search(world, "agentic"))[:2] == (BM25, FallbackReason.LLM_BUDGET_REACHED)


async def test_the_budget_resets_with_its_window() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("instance"),)))
    await _spend(world, "instance", "", DAY, USD)

    world.clock.at = T0 + timedelta(hours=1, seconds=1)  # the next UTC day

    assert (await _search(world, "agentic"))[:2] == (AGENTIC, None)


async def test_the_eleventh_llm_search_in_a_minute_degrades() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(llm_searches_per_minute=10))

    first = [await _search(world, "agentic") for _ in range(10)]
    eleventh = await _search(world, "agentic")

    assert {r[:2] for r in first} == {(AGENTIC, None)}
    assert eleventh[:2] == (BM25, FallbackReason.LLM_RATE_LIMITED)
    assert (await _search(world, "agentic", caller=BOB))[:2] == (AGENTIC, None)
    assert (await _search(world))[:2] == (BM25, None)  # BM25 is never rate limited
    world.clock.at = T0 + timedelta(minutes=1, seconds=1)
    assert (await _search(world, "agentic"))[:2] == (AGENTIC, None)


async def test_query_docs_degrades_the_same_way() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(llm_searches_per_minute=1))
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, mode="agentic")
    )
    first = await world.module.query_docs(QueryDocsQuery(library_id=LIB, query="token"), caller=ADA)
    second = await world.module.query_docs(
        QueryDocsQuery(library_id=LIB, query="token"), caller=ADA
    )

    assert (first.retrieval_mode, first.fallback_reason) == (AGENTIC, None)
    assert (second.retrieval_mode, second.fallback_reason) == (
        BM25,
        FallbackReason.LLM_RATE_LIMITED,
    )


async def test_without_a_rate_counter_nothing_is_rate_limited() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(llm_searches_per_minute=1), rates=False)

    assert {(await _search(world, "agentic"))[0] for _ in range(3)} == {AGENTIC}


async def test_a_paid_rerank_over_budget_is_skipped_and_the_results_say_so() -> None:
    world = await _build(ModelRole.RERANKER, budgets=Budgets(limits=(_limit("library"),)))
    assert await _search(world) == (BM25, None, True, True)

    await _spend(world, "library", LIB, DAY, USD)

    assert await _search(world) == (BM25, FallbackReason.LLM_BUDGET_REACHED, False, True)
    assert len(world.reranker.calls) == 1  # the second search never called the reranker


async def test_a_rerank_call_counts_in_the_callers_rows_at_its_price() -> None:
    world = await _build(
        ModelRole.RERANKER,
        price_overrides={"corp:rerank": ModelPrice(input_usd_per_million=1_000_000.0)},
    )

    assert (await _search(world))[2] is True

    ((query, documents),) = world.reranker.calls
    tokens = -(-(len(query) + sum(len(d) for d in documents)) // 4)  # estimated: no usage
    rows = {(k.scope_kind, k.scope_id, k.window): r for k, r in world.ledger.rows.items()}
    assert set(rows) == {
        (kind, scope_id, window)
        for kind, scope_id in (("instance", ""), ("library", LIB), ("user", ADA))
        for window in SpendWindow
    }
    for row in rows.values():
        assert (row.input_tokens, row.requests, row.unpriced) == (tokens, 1, 0)
        assert row.usd_micros == tokens * 1_000_000  # $1 per token


async def test_an_unpriced_rerank_counts_its_tokens_and_is_marked_unpriced() -> None:
    world = await _build(ModelRole.RERANKER)

    await _search(world, caller=None)

    assert {k.scope_kind for k in world.ledger.rows} == {"instance", "library"}  # stdio: no user
    assert {(r.requests, r.unpriced, r.usd_micros) for r in world.ledger.rows.values()} == {
        (1, 1, 0)
    }


async def test_a_local_reranker_costs_nothing_and_is_never_skipped() -> None:
    world = await _build(
        ModelRole.RERANKER,
        budgets=Budgets(limits=(_limit("library"),)),
        reranker_kind=ProviderKind.LOCAL,
    )
    await _spend(world, "library", LIB, DAY, USD)

    assert await _search(world) == (BM25, None, True, True)
    assert {r.usd_micros for k, r in world.ledger.rows.items() if k.scope_kind == "user"} == {0}


async def test_a_fallback_never_answers_from_another_version() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("instance"),)))
    await _spend(world, "instance", "", DAY, USD)

    result = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v1", query="retry_policy", mode="agentic"), caller=ADA
    )

    assert (result.retrieval_mode, result.version) == (BM25, "v1")
    assert result.results
    assert {r.commit_sha for r in result.results} == {"1" * 40}  # v1's commit only
    with pytest.raises(VersionNotIndexedError):
        await world.module.search_docs(
            SearchDocsQuery(library=LIB, ref="v9", query="token", mode="agentic"), caller=ADA
        )


# ---------------------------------------------------------------- embedding


async def _plan(world: World, library: str = LIB, ref: str = "v2") -> EmbedBatchCommand:
    plan = await world.module.plan_embedding(EmbedVersionCommand(library=library, ref=ref))
    assert plan.space_id is not None
    assert plan.manifest_id is not None
    return EmbedBatchCommand(
        library=library, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
    )


async def test_a_used_up_embedding_budget_stops_the_job_before_its_next_batch() -> None:
    world = await _build(
        embedding=True, budgets=Budgets(limits=(_limit("embedding", MONTH, usd=None, tokens=5),))
    )
    command = await _plan(world)

    first = await world.module.embed_batch(command)  # under budget: one chunk sent
    sent = len(world.models.sent)
    with pytest.raises(AiBudgetReachedError) as raised:
        await world.module.embed_batch(command)

    assert (first.embedded, first.finished) == (1, False)
    assert len(world.models.sent) == sent  # nothing more was sent
    assert raised.value.code == "ai_budget_reached"
    assert raised.value.resets_at == datetime(2026, 12, 1, tzinfo=UTC)
    # Nothing is queued while it lasts; everything is once the window resets.
    assert (await world.module.list_unembedded_versions(UnembeddedVersionsQuery())).versions == []
    world.clock.at = datetime(2026, 12, 1, 0, 0, 5, tzinfo=UTC)
    queued = await world.module.list_unembedded_versions(UnembeddedVersionsQuery())
    assert {(v.library, v.ref) for v in queued.versions} >= {(LIB, "v2")}
    assert (await world.module.embed_batch(command)).embedded == 1


async def test_embedding_counts_to_the_embedding_instance_and_library_rows_never_a_user() -> None:
    world = await _build(embedding=True)

    await world.module.embed_batch(await _plan(world))

    assert {(k.scope_kind, k.scope_id) for k in world.ledger.rows} == {
        ("embedding", ""),
        ("instance", ""),
        ("library", LIB),
    }


async def test_a_library_over_its_budget_pauses_only_its_own_embedding() -> None:
    world = await _build(embedding=True, budgets=Budgets(limits=(_limit("library"),)))
    await _spend(world, "library", LIB, DAY, USD)

    with pytest.raises(AiBudgetReachedError):
        await world.module.embed_batch(await _plan(world))
    queued = await world.module.list_unembedded_versions(UnembeddedVersionsQuery())

    assert {v.library for v in queued.versions} == {OTHER}
    assert (await world.module.embed_batch(await _plan(world, OTHER))).embedded == 1


# ---------------------------------------------------------------- the usage report


async def test_the_usage_shows_spend_and_budget_left_per_scope() -> None:
    world = await _build(
        ModelRole.LLM,
        budgets=Budgets(
            limits=(_limit("instance", usd=2), _limit("user", MONTH, usd=None, tokens=4000)),
            llm_searches_per_minute=30,
        ),
    )
    await _spend(world, "instance", "", DAY, USD)
    await _spend(world, "user", ADA, MONTH, 0)

    usage = await world.module.get_ai_usage()

    assert usage.llm_searches_per_minute == 30
    assert [(s.scope, s.id) for s in usage.scopes] == [
        ("instance", ""),
        ("embedding", ""),
        ("user", ADA),
    ]
    instance, embedding, ada = usage.scopes
    assert (instance.day.usd, instance.day.tokens, instance.month.usd) == (1.0, 1000, 0.0)
    (daily,) = instance.budgets
    assert (daily.usd_limit, daily.usd_left, daily.reached) == (2.0, 1.0, False)
    assert daily.resets_at == datetime(2026, 12, 1, tzinfo=UTC)
    assert embedding.budgets == []
    (monthly,) = ada.budgets
    assert (monthly.tokens_limit, monthly.tokens_left, monthly.usd_limit) == (4000, 3000, None)


# ---------------------------------------------------------------- the ledger


async def test_a_replayed_entry_is_counted_once() -> None:
    ledger = InMemorySpendLedger()
    key = SpendKey(scope_kind="instance", scope_id="", window=DAY, window_start=T0.date())
    replayed = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=DAY,
        window_start=T0.date(),
        input_tokens=10,
        requests=1,
        token="response-1",
    )

    await ledger.add([replayed])
    await ledger.add([replayed])
    await ledger.add([replace(replayed, token=None)])

    assert (await ledger.get([key]))[key].input_tokens == 20


async def test_a_read_only_process_adds_its_own_spend_to_the_shared_rows() -> None:
    shared = InMemorySpendLedger()
    key = SpendKey(scope_kind="library", scope_id=LIB, window=DAY, window_start=T0.date())
    await shared.add([_entry(key, usd=3)])
    stdio = ReadOnlySpendLedger(shared=shared)

    await stdio.add([_entry(key, usd=4)])

    assert (await stdio.get([key]))[key].usd_micros == 7
    assert [r.usd_micros for r in await stdio.since(T0.date())] == [7]
    assert (await shared.get([key]))[key].usd_micros == 3  # never written


@dataclass(slots=True)
class CountingTracer:
    """A ``SearchTracer`` that only counts fallbacks."""

    fallbacks: list[tuple[str, str]] = field(default_factory=list)
    untraced: UntracedSearches = field(default_factory=UntracedSearches)

    def span(self, name: str, *, mode: str, query: str | None = None, **attributes: str | None):
        return self.untraced.span(name, mode=mode, query=query, **attributes)

    def fallback(self, *, mode: str, reason: str) -> None:
        self.fallbacks.append((mode, reason))


async def test_each_degraded_search_is_counted_by_mode_and_reason() -> None:
    tracer = CountingTracer()
    world = await _build(ModelRole.LLM, budgets=Budgets(llm_searches_per_minute=1), tracer=tracer)

    await _search(world, "agentic")
    await _search(world, "agentic")
    await world.module.query_docs(QueryDocsQuery(library_id=LIB, query="token"), caller=ADA)

    assert tracer.fallbacks == [("bm25", "llm_rate_limited")]


async def test_the_budget_is_applied_to_the_choice_itself_so_every_later_stage_sees_it() -> None:
    # A rerank stage that reads the choice after the pipeline (#261) must see rerank off too.
    ledger = InMemorySpendLedger()
    clock = Clock()
    modes = RetrievalModes(
        pipelines={},
        roles=Roles(frozenset({ModelRole.RERANKER, ModelRole.LLM})),
        library_modes=InMemoryLibraryModes(),
        spend=AiSpend(ledger=ledger, budgets=Budgets(limits=(_limit("library"),)), clock=clock),
    )
    choice = ModeChoice(mode=AGENTIC, rerank=True, cheaper=BM25)
    assert await modes.within_budget(choice, library=LIB.upper(), caller=ADA) == replace(
        choice, caller=ADA
    )
    key = SpendKey(scope_kind="library", scope_id=LIB, window=DAY, window_start=clock.at.date())
    await ledger.add([_entry(key, usd=USD)])

    within = await modes.within_budget(choice, library=LIB.upper(), caller=ADA)

    assert within == ModeChoice(
        mode=BM25,
        rerank=False,
        cheaper=BM25,
        fallback_reason=FallbackReason.LLM_BUDGET_REACHED,
        caller=ADA,
    )


async def test_the_in_memory_ledger_forgets_replay_tokens_of_windows_that_are_over() -> None:
    ledger = InMemorySpendLedger()

    def response(day: date, token: str) -> list[SpendEntry]:
        return [
            SpendEntry(
                scope_kind="instance",
                scope_id="",
                window=window,
                window_start=window.start(datetime(day.year, day.month, day.day, tzinfo=UTC)),
                input_tokens=1,
                requests=1,
                token=token,
            )
            for window in SpendWindow
        ]

    await ledger.add(response(date(2026, 10, 30), "old"))
    await ledger.add(response(date(2026, 11, 30), "recent"))
    await ledger.add(response(date(2026, 12, 2), "new"))

    assert {(t, k.window, k.window_start) for t, k in ledger.replays} == {
        ("recent", DAY, date(2026, 11, 30)),  # two days back: still within reach
        ("recent", MONTH, date(2026, 11, 1)),
        ("new", DAY, date(2026, 12, 2)),
        ("new", MONTH, date(2026, 12, 1)),
    }


async def test_a_search_of_an_unknown_version_uses_up_no_llm_search() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(llm_searches_per_minute=1))

    for ref in ("v9", "v8"):
        with pytest.raises(VersionNotIndexedError):
            await world.module.search_docs(
                SearchDocsQuery(library=LIB, ref=ref, query="token", mode="agentic"), caller=ADA
            )

    assert (await _search(world, "agentic"))[:2] == (AGENTIC, None)


# ---------------------------------------------------------------- a library's own budgets (#102)


def test_a_library_has_at_most_one_own_budget_per_window_and_only_for_itself() -> None:
    with pytest.raises(InvalidBudgetError):
        LibraryAi(budgets=(_limit("user"),))
    with pytest.raises(InvalidBudgetError):
        LibraryAi(budgets=(_limit("library"), _limit("library", usd=None, tokens=5)))
    own = LibraryAi(budgets=(_limit("library", MONTH),))

    assert (own.budget(MONTH), own.budget(DAY), own.is_default) == (
        _limit("library", MONTH),
        None,
        False,
    )


def test_the_tighter_of_a_librarys_own_budget_and_the_instances_applies() -> None:
    budgets = Budgets(
        limits=(
            _limit("instance", usd=10),
            _limit("library", usd=2, tokens=1000),
            _limit("user", MONTH, usd=5),
        )
    )
    own = (_limit("library", usd=1, tokens=None), _limit("library", MONTH, usd=None, tokens=50))

    merged = budgets.for_library(own)

    assert budgets.for_library(()) is budgets
    assert set(merged.limits) == {
        _limit("instance", usd=10),
        _limit("user", MONTH, usd=5),
        _limit("library", usd=1, tokens=1000),  # its dollars, the instance's tokens
        _limit("library", MONTH, usd=None, tokens=50),  # only its own for the month
    }


def test_a_librarys_ceiling_is_the_lowest_instance_or_per_library_limit_of_the_window() -> None:
    budgets = Budgets(
        limits=(
            _limit("instance", usd=10, tokens=500),
            _limit("library", usd=2),
            _limit("user", usd=0.5),
            _limit("embedding", MONTH, usd=0.1),
        )
    )

    day, month = budgets.ceiling(DAY), budgets.ceiling(MONTH)

    assert (day.usd_micros, day.tokens) == (2 * USD, 500)
    assert (month.usd_micros, month.tokens) == (None, None)


@pytest.mark.parametrize(
    ("own", "what"),
    [
        (_limit("library", usd=3), "daily_usd"),
        (_limit("library", usd=None, tokens=501), "daily_tokens"),
    ],
)
def test_a_librarys_own_budget_above_the_instances_is_refused(own: BudgetLimit, what: str) -> None:
    budgets = Budgets(limits=(_limit("library", usd=2), _limit("instance", usd=None, tokens=500)))

    with pytest.raises(LibraryBudgetAboveInstanceError, match=what) as raised:
        budgets.check_library([own])

    assert raised.value.code == "budget_above_instance"
    budgets.check_library([_limit("library", usd=2, tokens=500), _limit("library", MONTH)])
    Budgets().check_library([_limit("library", usd=1000)])  # no instance limit: anything goes


async def test_a_librarys_own_budget_is_stored_shown_with_its_ceilings_and_cleared() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("library", usd=2),)))

    shown = await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(
            library=LIB.upper(), budgets=LibraryBudgets(daily_usd=1.5, monthly_tokens=10)
        )
    )
    read = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    cleared = await world.module.set_library_retrieval(SetLibraryRetrievalCommand(library=LIB))

    assert shown.budgets == read.budgets == LibraryBudgets(daily_usd=1.5, monthly_tokens=10)
    assert shown.budget_ceilings == LibraryBudgets(daily_usd=2.0)
    assert cleared.budgets == LibraryBudgets()


async def test_a_librarys_own_budget_above_the_instances_is_not_stored() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("library", usd=2),)))

    with pytest.raises(LibraryBudgetAboveInstanceError):
        await world.module.set_library_retrieval(
            SetLibraryRetrievalCommand(library=LIB, budgets=LibraryBudgets(daily_usd=3))
        )

    read = await world.module.get_library_retrieval(GetLibraryRetrievalQuery(library=LIB))
    assert read.budgets == LibraryBudgets()


async def test_a_librarys_own_budget_skips_its_llm_step_and_no_other_librarys() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("library", usd=5),)))
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, budgets=LibraryBudgets(daily_usd=1))
    )
    await _spend(world, "library", LIB, DAY, USD)
    await _spend(world, "library", OTHER, DAY, USD)

    assert (await _search(world, "agentic"))[:2] == (BM25, FallbackReason.LLM_BUDGET_REACHED)
    assert (await _search(world, "agentic", library=OTHER))[:2] == (AGENTIC, None)


async def test_a_librarys_own_budget_works_without_any_instance_limit() -> None:
    world = await _build(ModelRole.LLM)
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, budgets=LibraryBudgets(daily_tokens=500))
    )
    await _spend(world, "library", LIB, DAY, 0)  # 1000 tokens

    assert (await _search(world, "agentic"))[:2] == (BM25, FallbackReason.LLM_BUDGET_REACHED)


async def test_a_librarys_own_budget_pauses_its_embedding() -> None:
    world = await _build(embedding=True)
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, budgets=LibraryBudgets(monthly_usd=1))
    )
    await _spend(world, "library", LIB, MONTH, USD)

    with pytest.raises(AiBudgetReachedError):
        await world.module.embed_batch(await _plan(world))
    queued = await world.module.list_unembedded_versions(UnembeddedVersionsQuery())

    assert {v.library for v in queued.versions} == {OTHER}


async def test_the_usage_shows_a_librarys_own_budget_where_it_is_tighter() -> None:
    world = await _build(ModelRole.LLM, budgets=Budgets(limits=(_limit("library", usd=2),)))
    await world.module.set_library_retrieval(
        SetLibraryRetrievalCommand(library=LIB, budgets=LibraryBudgets(daily_usd=1))
    )
    await _spend(world, "library", LIB, DAY, USD)
    await _spend(world, "library", OTHER, DAY, USD)

    usage = await world.module.get_ai_usage()

    limits = {
        s.id: [(b.usd_limit, b.reached) for b in s.budgets]
        for s in usage.scopes
        if s.scope == "library"
    }
    assert limits == {LIB: [(1.0, True)], OTHER: [(2.0, False)]}
