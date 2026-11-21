"""#428: an agent answers a question from chosen libraries, with checked sources and bounds.

The agent runs for real (pydantic-ai, harness Code Mode, Monty) on a scripted ``FunctionModel``
(``scripted_explorer``), over in-memory adapters: no provider is called.
"""

import asyncio
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from exactdocs.retrieval.adapters.driven.ai_answerer import PydanticAiAnswerer
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryCallRates,
    InMemoryChunkRepository,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
)
from exactdocs.retrieval.dtos import (
    AnswerQuery,
    AnswerResult,
    ArticleChunksIn,
    ChunkIn,
    IndexManifestCommand,
)
from exactdocs.retrieval.errors import UnavailableModeError, VersionNotIndexedError
from exactdocs.retrieval.models import (
    Access,
    AgentBounds,
    AgentRun,
    AiCaller,
    AnswerDraft,
    BudgetLimit,
    Budgets,
    DocTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModelCheck,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    SearchableVersion,
    SourceHost,
    SpendWindow,
    ThinkingLevel,
    model_markdown,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import (
    Answerer,
    AnswerProgress,
    LibrariesBrowser,
    Reranker,
    SpendLedger,
)
from exactdocs_kernel import Clock
from scripted_explorer import answering, greedy, looping

PAYMENTS = "/acme/payments"
BILLING = "/acme/billing"
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
DOCS = {
    PAYMENTS: {"resilience": ["RetryPolicy decides how often a failed call runs again."]},
    BILLING: {"invoices": ["Invoices retry failed calls to the payment provider, with backoff."]},
}
QUESTION = "retry failed calls"


class FixedClock:
    def now(self) -> datetime:
        return T0


@dataclass(slots=True)
class Models:
    """``ModelFactory`` handing out one scripted chat model."""

    model: object

    def unsupported(self, profile: ProviderProfile) -> str | None:
        del profile

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        del profile, model, thinking
        return self.model

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        del profile, model

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        raise NotImplementedError(profile.name + model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        raise NotImplementedError(profile.name + model)

    async def release(self, name: str) -> None:
        del name

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        del thinking
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


@dataclass(slots=True)
class Catalog:
    versions: dict[str, SearchableVersion] = field(default_factory=dict)

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del ref
        return self.versions.get(library.casefold())

    async def all(self) -> Sequence[SearchableVersion]:
        return sorted(self.versions.values(), key=lambda v: v.library)

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        return dict.fromkeys(manifest_ids, ManifestStatus.ACTIVE)


@dataclass(slots=True)
class Readable:
    hidden: set[str] = field(default_factory=set)

    async def allows(self, library: str, access: Access) -> bool:
        del access
        return library.casefold() not in self.hidden

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        return frozenset(lib.casefold() for lib in libraries if lib.casefold() not in self.hidden)


@dataclass(slots=True)
class Hanging:
    """An ``Answerer`` that never answers (a provider that hangs)."""

    async def answer(
        self,
        model: object,
        browser: LibrariesBrowser,
        run: AgentRun,
        *,
        ledger: SpendLedger,
        clock: Clock,
        progress: AnswerProgress | None = None,
    ) -> AnswerDraft:
        del model, browser, run, ledger, clock, progress
        await asyncio.sleep(10)
        return AnswerDraft()


@dataclass(slots=True)
class Heard:
    """An ``AnswerProgress`` that keeps what it heard."""

    calls: list[tuple[int, int]] = field(default_factory=list)

    def tool_call(self, made: int, limit: int) -> None:
        self.calls.append((made, limit))


@dataclass(slots=True)
class World:
    module: RetrievalModule
    modes: InMemoryLibraryModes
    ledger: InMemorySpendLedger
    access: Readable


async def _world(
    model: object | None = None,
    *,
    llm: bool = True,
    budgets: Budgets | None = None,
    bounds: AgentBounds | None = None,
    answerer: Answerer | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    modes = InMemoryLibraryModes()
    ledger = InMemorySpendLedger()
    access = Readable()
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=catalog,
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes,
        configured_profiles=[CORP],
        instance_roles=InstanceRoles(llm=ModelRef(profile="corp", model="m") if llm else None),
        models=Models(model=model or answering()),
        clock=FixedClock(),
        spend=ledger,
        budgets=budgets,
        call_rates=InMemoryCallRates(),
        answerer=answerer or PydanticAiAnswerer(),
        agent_bounds=bounds,
        access=access,
    )
    for n, (library, docs) in enumerate(DOCS.items(), start=1):
        manifest = f"m{n}"
        await module.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest,
                library=library,
                ref="v1",
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(
                        path=f"docs/{blob}.md",
                        blob_sha=f"{blob}-{library}",
                        chunks=[
                            ChunkIn(
                                heading_path=[blob.title()],
                                occurrence_index=0,
                                content=text,
                                content_hash=f"h-{blob}-{i}",
                                anchor="",
                            )
                            for i, text in enumerate(texts)
                        ],
                    )
                    for blob, texts in docs.items()
                ],
            )
        )
        catalog.versions[library.casefold()] = SearchableVersion(
            library=library,
            version="v1",
            manifest_id=manifest,
            commit_sha=str(n) * 40,
            repository_url=f"https://github.com{library}",
            host=SourceHost.GITHUB,
        )
    return World(module=module, modes=modes, ledger=ledger, access=access)


async def _ask(world: World, *libraries: str, progress: Heard | None = None) -> AnswerResult:
    query = AnswerQuery(question=QUESTION, libraries=list(libraries))
    return await world.module.answer_question(query, caller="u1", progress=progress)


async def test_the_agent_answers_with_checked_sources_from_the_chosen_libraries() -> None:
    world = await _world()

    result = await _ask(world, PAYMENTS, BILLING)

    assert result.fallback_reason is None
    assert "RetryPolicy" in result.answer
    assert {s.library for s in result.sources} <= {PAYMENTS, BILLING}
    assert result.sources
    for source in result.sources:
        assert source.version == "v1"
        assert (
            source.quote is None
            or source.quote
            in DOCS[source.library][source.article_path.removeprefix("docs/").removesuffix(".md")][
                0
            ]
        )
    assert result.usage.requests >= 1
    assert result.usage.tool_calls >= 1


async def test_a_cited_chunk_of_a_library_not_chosen_is_dropped() -> None:
    world = await _world()
    other = await _ask(world, BILLING)
    foreign = other.sources[0].chunk_id
    world = await _world(answering(extra=[{"library": BILLING, "chunk_id": foreign}]))

    result = await _ask(world, PAYMENTS)

    assert result.sources
    assert all(s.library == PAYMENTS for s in result.sources)


async def test_a_made_up_quote_is_not_returned() -> None:
    world = await _world(answering(quote=False))

    result = await _ask(world, PAYMENTS)

    assert result.sources
    assert all(s.quote is None for s in result.sources)


async def test_a_run_past_its_tool_calls_stops_with_what_it_read() -> None:
    world = await _world(greedy(30), bounds=AgentBounds(max_tool_calls=5))

    result = await _ask(world)

    assert (result.answer, result.fallback_reason) == ("", FallbackReason.AGENT_LIMIT_REACHED)
    assert result.usage.tool_calls >= 1
    assert result.usage.max_tool_calls == 5


async def test_a_looping_agent_is_stopped() -> None:
    world = await _world(looping(3))

    result = await _ask(world)

    assert result.fallback_reason is FallbackReason.AGENT_LOOP_DETECTED


async def test_a_hanging_model_stops_at_the_time_limit() -> None:
    bounds = AgentBounds(timeout=0.2, sandbox_seconds=0.1)
    world = await _world(bounds=bounds, answerer=Hanging())

    result = await _ask(world)

    assert result.fallback_reason is FallbackReason.AGENT_LIMIT_REACHED


async def test_a_used_up_library_budget_answers_nothing_and_runs_no_agent() -> None:
    limit = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=10)
    world = await _world(budgets=Budgets(limits=(limit,)))
    await world.module.answer_question(AnswerQuery(question=QUESTION, libraries=[BILLING]))
    before = dict(world.ledger.rows)

    result = await _ask(world, PAYMENTS, BILLING)

    assert result.fallback_reason is FallbackReason.LLM_BUDGET_REACHED
    assert result.usage.requests == 0
    assert dict(world.ledger.rows) == before


async def test_the_run_counts_to_the_caller_and_every_library_it_reads() -> None:
    world = await _world()

    await _ask(world, PAYMENTS, BILLING)

    scopes = {(k.scope_kind, k.scope_id) for k in world.ledger.rows}
    assert {("user", "u1"), ("instance", ""), ("library", PAYMENTS), ("library", BILLING)} <= {
        (kind, i if kind != "library" else next(lib for lib in DOCS if lib.casefold() == i))
        for kind, i in scopes
    }


async def test_progress_hears_every_tool_call_out_of_the_limit() -> None:
    world = await _world()
    heard = Heard()

    result = await _ask(world, progress=heard)

    assert heard.calls
    assert [made for made, _ in heard.calls] == sorted(made for made, _ in heard.calls)
    assert heard.calls[-1] == (result.usage.tool_calls, result.usage.max_tool_calls)


async def test_a_library_with_ai_off_is_never_read() -> None:
    world = await _world()
    world.modes.overrides[BILLING.casefold()] = LibraryAi(enabled=False)

    result = await _ask(world, PAYMENTS, BILLING)
    only_off = await _ask(world, BILLING)

    assert result.libraries_without_ai == [BILLING]
    assert all(s.library == PAYMENTS for s in result.sources)
    assert only_off.fallback_reason is FallbackReason.MODE_UNAVAILABLE
    assert only_off.usage.requests == 0


async def test_a_library_the_caller_may_not_read_is_refused() -> None:
    world = await _world()
    world.access.hidden.add(BILLING.casefold())

    with pytest.raises(VersionNotIndexedError):
        await _ask(world, BILLING)
    result = await _ask(world)

    assert [lib.library for lib in result.libraries] == [PAYMENTS]


async def test_without_an_llm_role_answers_are_unavailable() -> None:
    world = await _world(llm=False)

    available = await world.module.get_answer_availability()
    with pytest.raises(UnavailableModeError, match="llm"):
        await _ask(world)

    assert (available.available, available.reason) == (False, "no llm role is configured")


def test_an_answer_keeps_its_line_breaks_but_no_control_characters() -> None:
    assert model_markdown("# Title\n\n- a\x1b[31m\r\n- b\x00", 100) == "# Title\n\n- a[31m\n- b"
    assert model_markdown("x" * 20, 10) == "xxxxxxx..."


def test_a_caller_of_several_libraries_counts_to_each() -> None:
    caller = AiCaller(library="/a/a", user="u", also=("/b/b", "/a/a"))

    assert caller.scopes() == (
        ("instance", ""),
        ("library", "/a/a"),
        ("library", "/b/b"),
        ("user", "u"),
    )
