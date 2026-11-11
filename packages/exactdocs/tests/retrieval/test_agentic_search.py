"""RET-04: agentic retrieval browses one version in Code Mode, bounded, and justifies its picks.

The agent is the real one (pydantic-ai, harness Code Mode, Monty, ``SpendLimits``) on scripted
``FunctionModel``s (``scripted_explorer``): no provider is called. Where only the pipeline's own
rules are under test, a Protocol-shaped ``Explorer`` double stands in for the agent.
"""

import asyncio
import logging
import unicodedata
from collections.abc import Collection, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings, InstrumentedModel

from exactdocs.retrieval.adapters.driven.ai_explorer import PydanticAiExplorer
from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
)
from exactdocs.retrieval.constants import (
    AGENT_STEP_ARGUMENT_CHARS,
    EXPLORER_TOOLS,
    MAX_EXPLORED_STEPS,
    MAX_JUSTIFICATION_CHARS,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    IndexManifestCommand,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.errors import (
    AgentStoppedError,
    InvalidAgentBoundsError,
    UnavailableModeError,
)
from exactdocs.retrieval.models import (
    AgentBounds,
    AgentPick,
    AgentRun,
    ArticleEntry,
    BudgetLimit,
    Budgets,
    ChunkId,
    DocTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModelRef,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SourceHost,
    SpendWindow,
    TagFilter,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import DocsBrowser, Explorer, SpendLedger
from exactdocs.retrieval.use_cases import VersionBrowser
from exactdocs_kernel import Clock
from scripted_explorer import (
    ScriptedModels,
    answer,
    browsing,
    code_results,
    greedy,
    run_code,
    sandbox_hog,
)

LIB = "/acme/payments"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
CORP = ProviderProfile(
    name="corp",
    kind=ProviderKind.OPENAI_COMPATIBLE,
    origin=ProfileOrigin.CONFIGURATION,
    base_url="https://llm.example.com/v1",
)
QUESTION = "how does RetryPolicy retry failed calls"
GUIDE = {
    "resilience": [
        "RetryPolicy decides how often a failed call runs again.",
        "Calls that time out are sent once more after a short pause (backoff).",
    ],
    "auth": ["Rotate the API token without downtime; RetryPolicy does not apply."],
    "paging": ["Use the cursor to read the next page."],
}
OLD_GUIDE = {"resilience": ["RetryPolicy retries three times in v1, failed calls included."]}


class FixedClock:
    def now(self) -> datetime:
        return T0


@dataclass(slots=True)
class Catalog:
    """Each version's active manifest, and its articles (``VersionArticles``)."""

    versions: dict[str, SearchableVersion] = field(default_factory=dict)
    articles: dict[str, dict[str, str]] = field(default_factory=dict)
    """Markdown by path, per manifest."""

    def add(self, ref: str, manifest: str, blobs: dict[str, list[str]]) -> None:
        self.versions[ref] = SearchableVersion(
            library=LIB,
            version=ref,
            manifest_id=manifest,
            commit_sha=manifest[-1] * 40,
            repository_url="https://github.com/acme/payments",
            host=SourceHost.GITHUB,
        )
        self.articles[manifest] = {
            f"docs/{blob}.md": "\n\n".join(texts) for blob, texts in blobs.items()
        }

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return self.versions.get(ref or "v2") if library == LIB else None

    async def statuses(self, manifest_ids: Collection[str]) -> dict[str, ManifestStatus]:
        return dict.fromkeys(manifest_ids, ManifestStatus.ACTIVE)

    async def active_id(self, target: DocTarget) -> str | None:
        found = self.versions.get(target.version)
        return None if found is None else found.manifest_id


def _tags_of(path: str) -> list[str]:
    return ["security"] if path == "docs/auth.md" else []


@dataclass(slots=True)
class Articles:
    """The ``VersionArticles`` double: the catalog's articles of each manifest."""

    catalog: Catalog
    fail_with: str | None = None
    """Every read raises a ``RuntimeError`` with this text, as a broken database would."""

    async def list(
        self, version: SearchableVersion, prefix: str, limit: int, tag_filter: TagFilter
    ) -> Sequence[ArticleEntry]:
        stored = self.catalog.articles[version.manifest_id]
        paths = sorted(p for p in stored if p.startswith(prefix) and tag_filter.keeps(_tags_of(p)))
        return [ArticleEntry(path=p, title=p.title()) for p in paths[:limit]]

    async def read(self, version: SearchableVersion, path: str) -> str | None:
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        return self.catalog.articles[version.manifest_id].get(path)


@dataclass(slots=True)
class Tracer:
    """A ``SearchTracer`` double: the spans opened and the fallbacks counted."""

    opened: list[str] = field(default_factory=list)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[_Span]:
        del mode, query, attributes
        self.opened.append(name)
        return nullcontext(_Span())

    def fallback(self, *, mode: str, reason: str) -> None:
        self.fallbacks.append((mode, reason))


class _Span:
    def answered_by(self, mode: str) -> None:
        del mode


@dataclass(slots=True)
class StoppingExplorer:
    """An ``Explorer`` double: it stops the way it is told, or sleeps, or raises."""

    error: Exception | None = None
    sleep: float = 0.0
    picks: Sequence[AgentPick] = ()
    runs: list[AgentRun] = field(default_factory=list)

    async def explore(
        self,
        model: object,
        browser: DocsBrowser,
        run: AgentRun,
        *,
        ledger: SpendLedger,
        clock: Clock,
    ) -> Sequence[AgentPick]:
        del model, ledger, clock
        self.runs.append(run)
        await browser.search_docs(run.question, 5)
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.error is not None:
            raise self.error
        return self.picks


@dataclass(slots=True)
class World:
    module: RetrievalModule
    catalog: Catalog
    ledger: InMemorySpendLedger
    tracer: Tracer
    models: ScriptedModels
    chunks: InMemoryChunkRepository
    index: InMemorySearchIndex


async def _world(
    model: Model | None = None,
    *,
    explorer: Explorer | None = None,
    bounds: AgentBounds | None = None,
    budgets: Budgets | None = None,
    modes: InMemoryLibraryModes | None = None,
    reads_fail_with: str | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    ledger = InMemorySpendLedger()
    tracer = Tracer()
    models = ScriptedModels(model=model or browsing())
    module = RetrievalModule.build(
        searchable=catalog,
        libraries=InMemoryLibraries(),
        defaults=InMemoryDefaultVersions(),
        manifests=catalog,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=modes or InMemoryLibraryModes(),
        configured_profiles=[CORP],
        instance_roles=InstanceRoles(llm=ModelRef(profile="corp", model="explorer")),
        models=models,
        clock=FixedClock(),
        tracer=tracer,
        spend=ledger,
        budgets=budgets,
        explorer=explorer or PydanticAiExplorer(),
        version_articles=Articles(catalog=catalog, fail_with=reads_fail_with),
        agent_bounds=bounds,
    )
    world = World(
        module=module,
        catalog=catalog,
        ledger=ledger,
        tracer=tracer,
        models=models,
        chunks=chunks,
        index=index,
    )
    await _import(world, "v1", "m1", OLD_GUIDE)
    await _import(world, "v2", "m2", GUIDE)
    return world


async def _import(world: World, ref: str, manifest: str, blobs: dict[str, list[str]]) -> None:
    await world.module.index_manifest(
        IndexManifestCommand(
            manifest_id=manifest,
            library=LIB,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=f"docs/{blob}.md",
                    blob_sha=f"{blob}-{ref}",
                    tags=["security"] if blob == "auth" else [],
                    chunks=[
                        ChunkIn(
                            heading_path=[blob.title(), f"S{i}"],
                            occurrence_index=0,
                            content=text,
                            content_hash=f"h-{blob}-{i}",
                            anchor=f"s{i}",
                        )
                        for i, text in enumerate(texts)
                    ],
                )
                for blob, texts in blobs.items()
            ],
        )
    )
    world.catalog.add(ref, manifest, blobs)


async def _search(
    world: World, *, ref: str = "v2", tags: Sequence[str] = (), limit: int = 5
) -> SearchDocsResult:
    return await world.module.search_docs(
        SearchDocsQuery(
            library=LIB, ref=ref, query=QUESTION, mode="agentic", limit=limit, tags=list(tags)
        )
    )


async def _v1_chunk(world: World) -> str:
    old = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v1", query="RetryPolicy", mode="bm25")
    )
    return old.results[0].chunk_id


# ---------------------------------------------------------------- answers from the pinned version


async def test_agentic_results_carry_a_justification_and_the_explored_path() -> None:
    world = await _world()

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.AGENTIC, None)
    assert result.results
    top = result.results[0]
    assert top.article_path == "docs/resilience.md"
    assert top.justification == "Its section Resilience > S0 answers it."
    assert top.explored_path == [f"search_docs({QUESTION})"]
    assert world.models.chat_models == ["corp:explorer"]  # the llm role's model, resolved now
    assert "search_docs.agent" in world.tracer.opened


async def test_picks_from_another_version_or_made_up_are_dropped() -> None:
    foreign = await _v1_chunk(await _world())  # chunk IDs hash the version: the same in any world
    world = await _world(browsing(extra=[foreign, "0" * 64]))

    result = await _search(world, limit=10)

    ids = [r.chunk_id for r in result.results]
    assert foreign not in ids
    assert "0" * 64 not in ids
    assert ids  # the agent's real picks remain
    assert {r.commit_sha for r in result.results} == {"2" * 40}


async def test_picks_outside_the_tag_filter_are_dropped() -> None:
    world = await _world()

    result = await _search(world, tags=["security"])

    assert result.results
    assert {r.article_path for r in result.results} == {"docs/auth.md"}


async def test_the_agent_answers_at_most_the_limit() -> None:
    world = await _world(browsing(picks=3))

    result = await _search(world, limit=1)

    assert len(result.results) == 1


async def test_the_browser_reads_only_the_pinned_manifest() -> None:
    world = await _world()
    foreign = await _v1_chunk(world)
    browser = VersionBrowser(
        version=world.catalog.versions["v2"],
        chunks=world.chunks,
        search=world.index,
        articles=Articles(catalog=world.catalog),
    )

    assert await browser.read_chunk(foreign) is None
    hits = await browser.search_docs("RetryPolicy", 10)
    assert hits
    assert {chunk.manifest_id for _, chunk in hits} == {"m2"}
    assert [a.path for a in await browser.list_articles("docs/")] == [
        "docs/auth.md",
        "docs/paging.md",
        "docs/resilience.md",
    ]
    outline = await browser.article_outline("docs/resilience.md")
    assert outline is not None
    assert [n.heading for n in outline.sections] == ["Resilience"]
    article = await browser.read_article("docs/paging.md")
    assert article is not None
    assert article.content == GUIDE["paging"][0]
    assert await browser.read_article("docs/missing.md") is None
    assert browser.path_to("docs/paging.md") == (
        f"read_chunk({foreign})",
        "search_docs(RetryPolicy)",
        "list_articles(docs/)",
        "article_outline(docs/resilience.md)",
        "read_article(docs/paging.md)",
    )


# ---------------------------------------------------------------- Code Mode


async def test_the_read_tools_exist_only_inside_run_code_with_typed_returns() -> None:
    seen: list[AgentInfo] = []

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        if code_results(messages):
            return answer(info, [])
        return run_code("await list_articles()")

    world = await _world(FunctionModel(script))

    await _search(world)

    (tool,) = seen[0].function_tools
    assert tool.name == "run_code"
    described = tool.description or ""
    for name in EXPLORER_TOOLS:
        assert f"async def {name}(" in described, name
    for typed in ["-> list[ArticleItem]", "-> ArticleOutlineResult", "-> ArticleRead",
                  "-> ChunkRead", "-> list[SearchHitItem]"]:  # fmt: skip
        assert typed in described, typed
    assert "class SearchHitItem(TypedDict)" in described
    assert "ctx" not in described  # the version is the agent's deps, never an argument


# ---------------------------------------------------------------- limits end the run


async def test_more_tool_calls_than_allowed_end_the_run_and_bm25_answers() -> None:
    world = await _world(greedy(30), bounds=AgentBounds(max_tool_calls=20))

    result = await _search(world)

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.AGENT_LIMIT_REACHED
    assert result.results
    assert all(r.justification is None and not r.explored_path for r in result.results)
    assert world.tracer.fallbacks == [("bm25", "agent_limit_reached")]


async def test_more_model_requests_than_allowed_end_the_run() -> None:
    world = await _world(sandbox_hog("1 + 1"), bounds=AgentBounds(max_requests=3))

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_LIMIT_REACHED


@pytest.mark.parametrize(
    "code",
    [
        "while True:\n    pass",
        "x = [0] * 50_000_000\nlen(x)",
        "for i in range(100):\n    await list_articles()",
    ],
    ids=["time", "memory", "suspensions"],
)
async def test_a_snippet_past_a_sandbox_limit_ends_the_run_at_once(code: str) -> None:
    requests: list[int] = []
    bounds = AgentBounds(
        max_tool_calls=200, sandbox_seconds=0.5, sandbox_memory=16 * 1024 * 1024,
        sandbox_suspensions=50,
    )  # fmt: skip
    world = await _world(sandbox_hog(code, requests), bounds=bounds)

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_LIMIT_REACHED
    assert len(requests) == 1  # not handed back to the model as a retry


async def test_an_agent_past_its_time_falls_back() -> None:
    explorer = StoppingExplorer(sleep=5)
    world = await _world(explorer=explorer, bounds=AgentBounds(timeout=0.05, sandbox_seconds=0.01))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.AGENT_LIMIT_REACHED,
    )


async def test_a_failing_agent_falls_back_and_logs_no_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    explorer = StoppingExplorer(error=RuntimeError(f"provider said no to {QUESTION}"))
    world = await _world(explorer=explorer)

    with caplog.at_level(logging.WARNING):
        result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_FAILED
    assert result.results  # BM25 answered
    assert "RuntimeError" in caplog.text
    assert QUESTION not in caplog.text


async def test_an_agent_that_never_answers_validly_falls_back() -> None:
    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return ModelResponse(parts=[_bad_output(info)])

    world = await _world(FunctionModel(script))

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_FAILED


def _bad_output(info: AgentInfo) -> ToolCallPart:
    return ToolCallPart(info.output_tools[0].name, {"picks": "not a list"})


# ---------------------------------------------------------------- budgets (#95)


async def test_a_budget_used_up_during_the_run_ends_it_with_llm_budget_reached() -> None:
    limit = BudgetLimit(scope_kind="instance", window=SpendWindow.DAY, tokens=10)
    world = await _world(budgets=Budgets(limits=(limit,)))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    spent = [row for key, row in world.ledger.rows.items() if key.scope_kind == "instance"]
    assert spent
    assert all(row.requests >= 1 and row.input_tokens > 10 for row in spent)  # the first request


async def test_the_run_counts_to_the_instance_library_and_caller() -> None:
    world = await _world()

    await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query=QUESTION, mode="agentic"), caller="acct-1"
    )

    scopes = {(k.scope_kind, k.scope_id, k.window) for k in world.ledger.rows}
    for window in SpendWindow:
        assert ("instance", "", window) in scopes
        assert ("library", LIB, window) in scopes
        assert ("user", "acct-1", window) in scopes


async def test_a_library_with_ai_off_never_runs_the_agent() -> None:
    modes = InMemoryLibraryModes()
    await modes.save(LIB, None, LibraryAi(enabled=False))
    explorer = StoppingExplorer()
    world = await _world(explorer=explorer, modes=modes)

    with pytest.raises(UnavailableModeError):
        await _search(world)
    assert not explorer.runs


# ---------------------------------------------------------------- telemetry


async def test_tool_calls_are_spans_inside_run_code_without_content() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    settings = InstrumentationSettings(
        include_content=False,
        tracer_provider=tracer_provider,
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    world = await _world(InstrumentedModel(browsing(), settings))

    await _search(world)

    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans if s.context is not None}
    run_codes = {
        s.context.span_id for s in spans if s.name == "execute_tool run_code" and s.context
    }
    tools = [s for s in spans if s.name.startswith("execute_tool ") and "run_code" not in s.name]
    assert {s.name.removeprefix("execute_tool ") for s in tools} == {
        "search_docs", "list_articles", "article_outline", "read_chunk",
    }  # fmt: skip
    for span in tools:
        assert span.parent is not None
        assert span.parent.span_id in run_codes, span.name
        assert by_id[span.parent.span_id].name == "execute_tool run_code"
    for span in spans:
        flat = repr(dict(span.attributes or {}))
        assert QUESTION not in flat, span.name
        assert "RetryPolicy decides" not in flat, span.name
        assert "gen_ai.tool.call.arguments" not in (span.attributes or {})
    data = reader.get_metrics_data()
    assert data is not None
    usage = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "gen_ai.client.token.usage"
        for point in metric.data.data_points
    ]
    labels = [dict(point.attributes or {}) for point in usage]
    assert {label["gen_ai.token.type"] for label in labels} == {"input", "output"}
    for label in labels:
        assert not {str(v) for v in label.values()} & {QUESTION, LIB, "acct-1"}


# ---------------------------------------------------------------- the limits themselves


@pytest.mark.parametrize(
    "field_name",
    ["max_tool_calls", "max_requests", "max_tokens", "sandbox_seconds", "sandbox_memory",
     "sandbox_suspensions", "timeout"],
)  # fmt: skip
def test_every_agent_limit_must_be_positive(field_name: str) -> None:
    with pytest.raises(InvalidAgentBoundsError, match=field_name):
        AgentBounds(**{field_name: 0})


async def test_an_explorer_stop_names_its_reason() -> None:
    explorer = StoppingExplorer(error=AgentStoppedError("llm_budget_reached", "spend limit"))
    world = await _world(explorer=explorer)

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.LLM_BUDGET_REACHED
    assert explorer.runs[0].question == QUESTION
    assert explorer.runs[0].caller.library == LIB
    assert explorer.runs[0].budgets == Budgets()


async def test_unpicked_chunks_are_not_answers() -> None:
    explorer = StoppingExplorer(picks=[AgentPick(chunk_id=ChunkId("nope"), justification="x")])
    world = await _world(explorer=explorer)

    result = await _search(world)

    assert (result.retrieval_mode, result.results) == (RetrievalMode.AGENTIC, [])


# ---------------------------------------------------------------- round 1 review


SECRET = "postgresql://exactdocs:S3CRET-MARKER@db:5432/exactdocs"
"""What a broken database's error says: it must reach neither the model, the result, a log nor
a span."""


def _reading(code: str, sent: list[str]) -> FunctionModel:
    """An agent that runs ``code`` once, records every request it is sent, then answers nothing."""

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.append(repr(messages))
        if code_results(messages):
            return answer(info, [])
        return run_code(code)

    return FunctionModel(script)


@pytest.mark.parametrize(
    "code",
    [
        "await read_article(path='docs/paging.md')",
        (
            "try:\n    await read_article(path='docs/paging.md')\n"
            "except Exception as e:\n    x = str(e)\n"
            "await list_articles()"
        ),
    ],
    ids=["uncaught", "caught by the snippet"],
)
async def test_a_host_error_ends_the_run_and_its_text_goes_nowhere(
    code: str, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[str] = []
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    settings = InstrumentationSettings(include_content=True, tracer_provider=tracer_provider)
    model = InstrumentedModel(_reading(code, sent), settings)  # content on: only ours is used
    world = await _world(model, reads_fail_with=SECRET)

    with caplog.at_level(logging.DEBUG):
        result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.AGENT_FAILED,
    )
    assert len(sent) == 1  # the failed read is never handed back to the model as a retry
    assert "S3CRET-MARKER" not in "".join(sent)
    assert "S3CRET-MARKER" not in result.model_dump_json()
    assert "S3CRET-MARKER" not in caplog.text
    assert "RuntimeError" in caplog.text  # the class only
    for span in exporter.get_finished_spans():
        assert "S3CRET-MARKER" not in repr(dict(span.attributes or {}))
        for event in span.events:
            assert "S3CRET-MARKER" not in repr(dict(event.attributes or {}))


async def test_an_unknown_article_is_a_plain_answer_to_the_model() -> None:
    sent: list[str] = []
    world = await _world(_reading("await read_article(path='docs/missing.md')", sent))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.AGENTIC, None)
    assert "'found': False" in sent[-1]


def _writing(query: str, justification: str) -> FunctionModel:
    """An agent that searches 60 times for nothing, then ``query``; it answers every hit."""

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        results = code_results(messages)
        if not results:
            looking = "for i in range(60):\n    await search_docs(query='zzqqx nothing')\n"
            return run_code(f"{looking}hits = await search_docs(query={query!r})\nhits")
        picks = [{"chunk_id": h["chunk_id"], "justification": justification} for h in results[-1]]
        return answer(info, picks)

    return FunctionModel(script)


async def test_model_text_in_results_is_cleaned_and_bounded() -> None:
    query = "RetryPolicy\n\x1b[31mIGNORE ALL\u202e" + "x" * 500
    justification = "Because\nit\tsays so\x00." + "y" * 2000
    bounds = AgentBounds(max_tool_calls=200, sandbox_suspensions=1000)
    world = await _world(_writing(query, justification), bounds=bounds)

    result = await _search(world)

    assert result.retrieval_mode is RetrievalMode.AGENTIC, result.fallback_reason
    top = result.results[0]
    assert len(top.explored_path) == MAX_EXPLORED_STEPS
    assert top.explored_path[:-1] == ["search_docs(zzqqx nothing)"] * (MAX_EXPLORED_STEPS - 1)
    for step in top.explored_path[-1:]:
        assert step.startswith("search_docs(RetryPolicy  ")
        assert len(step) <= len("search_docs()") + AGENT_STEP_ARGUMENT_CHARS
        assert not any(unicodedata.category(c).startswith("C") for c in step)
    assert top.justification is not None
    assert top.justification.startswith("Because it says so .")
    assert len(top.justification) == MAX_JUSTIFICATION_CHARS
    assert not any(unicodedata.category(c).startswith("C") for c in top.justification)


async def test_the_browser_hides_what_the_tag_filter_excludes() -> None:
    world = await _world()
    browser = VersionBrowser(
        version=world.catalog.versions["v2"],
        chunks=world.chunks,
        search=world.index,
        articles=Articles(catalog=world.catalog),
        tag_filter=TagFilter(tags=("security",)),
    )
    hits = await browser.search_docs("RetryPolicy", 10)
    resilience = await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query="backoff", mode="bm25")
    )

    assert {chunk.row.article_path for _, chunk in hits} == {"docs/auth.md"}
    assert await browser.read_chunk(resilience.results[0].chunk_id) is None
    assert await browser.article_outline("docs/resilience.md") is None
    assert await browser.read_article("docs/resilience.md") is None
    assert [a.path for a in await browser.list_articles()] == ["docs/auth.md"]
    assert await browser.article_outline("docs/auth.md") is not None
    assert await browser.read_article("docs/auth.md") is not None


def test_a_snippet_may_not_take_as_long_as_the_whole_run() -> None:
    with pytest.raises(InvalidAgentBoundsError, match="sandbox_seconds must be less than timeout"):
        AgentBounds(sandbox_seconds=10, timeout=10)


async def test_the_agent_uses_the_library_s_own_llm_read_once_for_the_search() -> None:
    modes = InMemoryLibraryModes()
    await modes.save(LIB, None, LibraryAi(llm=ModelRef(profile="corp", model="own")))
    world = await _world(modes=modes)

    await _search(world)

    assert world.models.chat_models == ["corp:own"]
