"""RET-04: agentic retrieval browses one version in Code Mode, bounded, and justifies its picks.

The agent is the real one (pydantic-ai, harness Code Mode, Monty, ``SpendLimits``) on scripted
``FunctionModel``s (``scripted_explorer``): no provider is called. Where only the pipeline's own
rules are under test, a Protocol-shaped ``Explorer`` double stands in for the agent.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Collection, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from opentelemetry import trace
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
from exactdocs.retrieval.adapters.driven.opentelemetry import (
    OpenTelemetryAgentReads,
    OpenTelemetrySearchTracer,
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
    AgentRead,
    AgentRun,
    AiCaller,
    ArticleEntry,
    ArticleText,
    BudgetLimit,
    Budgets,
    ChunkId,
    DocTarget,
    FallbackReason,
    InstanceRoles,
    LibraryAi,
    ManifestStatus,
    ModelRef,
    Outline,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    RetrievalMode,
    SearchableVersion,
    SearchHit,
    ServedArticle,
    ServedArticles,
    SourceHost,
    SpendWindow,
    StoredChunk,
    TagFilter,
)
from exactdocs.retrieval.module import RetrievalModule
from exactdocs.retrieval.ports.driven import DocsBrowser, Explorer, SearchTracer, SpendLedger
from exactdocs.retrieval.use_cases import VersionBrowser
from exactdocs_kernel import Clock
from scripted_explorer import (
    ScriptedModels,
    answer,
    browsing,
    code_results,
    greedy,
    looping,
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

    serve_from: str | None = None
    """Answer from this manifest instead of the one asked for, as after a re-sync."""

    async def list(
        self, version: SearchableVersion, prefix: str, limit: int, tag_filter: TagFilter
    ) -> ServedArticles | None:
        manifest = self.serve_from or version.manifest_id
        stored = self.catalog.articles[manifest]
        paths = sorted(p for p in stored if p.startswith(prefix) and tag_filter.keeps(_tags_of(p)))
        entries = tuple(ArticleEntry(path=p, title=p.title()) for p in paths[:limit])
        return ServedArticles(manifest_id=manifest, articles=entries)

    async def read(self, version: SearchableVersion, path: str) -> ServedArticle | None:
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        manifest = self.serve_from or version.manifest_id
        content = self.catalog.articles[manifest].get(path)
        return None if content is None else ServedArticle(manifest_id=manifest, content=content)


@dataclass(slots=True)
class Tracer:
    """A ``SearchTracer`` double: the spans opened and the fallbacks counted."""

    opened: list[str] = field(default_factory=list)
    fallbacks: list[tuple[str, str]] = field(default_factory=list)
    cache_hits: list[tuple[str, str]] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[_Span]:
        del mode, query, attributes
        self.opened.append(name)
        return nullcontext(_Span())

    def fallback(self, *, mode: str, reason: str) -> None:
        self.fallbacks.append((mode, reason))

    def cache_hit(self, *, cache: str, mode: str) -> None:
        self.cache_hits.append((cache, mode))


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
class RecordedReads:
    """An ``AgentReads`` double: the run's trace, read by read."""

    reads: list[AgentRead] = field(default_factory=list)

    def record(self, read: AgentRead) -> None:
        self.reads.append(read)


@dataclass(slots=True)
class World:
    module: RetrievalModule
    catalog: Catalog
    ledger: InMemorySpendLedger
    tracer: Tracer
    models: ScriptedModels
    chunks: InMemoryChunkRepository
    index: InMemorySearchIndex
    reads: RecordedReads


async def _world(
    model: Model | None = None,
    *,
    explorer: Explorer | None = None,
    bounds: AgentBounds | None = None,
    budgets: Budgets | None = None,
    modes: InMemoryLibraryModes | None = None,
    reads_fail_with: str | None = None,
    search_tracer: SearchTracer | None = None,
) -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    catalog = Catalog()
    ledger = InMemorySpendLedger()
    tracer = Tracer()
    models = ScriptedModels(model=model or browsing())
    reads = RecordedReads()
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
        tracer=search_tracer or tracer,
        spend=ledger,
        budgets=budgets,
        explorer=explorer or PydanticAiExplorer(),
        version_articles=Articles(catalog=catalog, fail_with=reads_fail_with),
        agent_bounds=bounds,
        agent_reads=reads,
    )
    world = World(
        module=module,
        catalog=catalog,
        ledger=ledger,
        tracer=tracer,
        models=models,
        chunks=chunks,
        index=index,
        reads=reads,
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
    world = await _world(sandbox_hog("1 + 1", vary=True), bounds=AgentBounds(max_requests=3))

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_LIMIT_REACHED


@pytest.mark.parametrize(
    "code",
    [
        "while True:\n    pass",
        "x = [0] * 50_000_000\nlen(x)",
        "for i in range(100):\n    await list_articles(prefix=str(i))",  # new arguments: no loop
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


HOST_ERROR_SNIPPETS = [
    "await read_article(path='docs/paging.md')",
    (
        "try:\n    await read_article(path='docs/paging.md')\n"
        "except Exception as e:\n    x = str(e)\n"
        "await list_articles()"
    ),
]
HOST_ERROR_IDS = ["uncaught", "caught by the snippet"]


@pytest.mark.parametrize("code", HOST_ERROR_SNIPPETS, ids=HOST_ERROR_IDS)
async def test_a_host_error_ends_the_run_and_its_text_goes_nowhere(
    code: str, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[str] = []
    model = InstrumentedModel(
        _reading(code, sent), InstrumentationSettings(include_content=True)
    )  # content on: the explorer replaces it with its own instrumentation
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


RUN = "EXACTDOCS_AGENTIC_SPANS_E2E"
"""Set in the process the span test runs in: it sets the global tracer provider, once."""


@pytest.fixture(scope="module")
def process_spans() -> InMemorySpanExporter:
    """Record every span of the process on the global tracer provider, set once (own process).

    Returns:
        The exporter holding the finished spans.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def global_spans(process_spans: InMemorySpanExporter) -> InMemorySpanExporter:
    """The process's span exporter, emptied for this test.

    Returns:
        The exporter.
    """
    process_spans.clear()
    return process_spans


@pytest.mark.skipif(not os.environ.get(RUN), reason="runs in its own process")
@pytest.mark.parametrize("code", HOST_ERROR_SNIPPETS, ids=HOST_ERROR_IDS)
async def test_a_host_error_reaches_no_span(code: str, global_spans: InMemorySpanExporter) -> None:
    sent: list[str] = []
    # A model that records content: the explorer re-instruments it, on the global provider.
    model = InstrumentedModel(_reading(code, sent), InstrumentationSettings(include_content=True))
    world = await _world(model, reads_fail_with=SECRET, search_tracer=OpenTelemetrySearchTracer())

    result = await _search(world)

    assert result.fallback_reason is FallbackReason.AGENT_FAILED
    spans = global_spans.get_finished_spans()
    names = {s.name for s in spans}
    # The spans that would carry the error exist: the agent stage, the run, run_code, the read.
    assert {
        "retrieval.search_docs.agent",
        "invoke_agent exactdocs-explorer",
        "execute_tool run_code",
        "execute_tool read_article",
    } <= names, names
    # The read's span records the guard's fixed error, never the host's exception.
    (failed_read,) = [s for s in spans if s.name == "execute_tool read_article"]
    raised = [dict(e.attributes or {}) for e in failed_read.events if e.name == "exception"]
    assert [str(e.get("exception.type")).rsplit(".", 1)[-1] for e in raised] == [
        "_ReadFailedError"
    ], raised
    for span in spans:
        assert "S3CRET-MARKER" not in repr(dict(span.attributes or {})), span.name
        assert "S3CRET-MARKER" not in (span.status.description or ""), span.name
        for event in span.events:
            assert "S3CRET-MARKER" not in repr(dict(event.attributes or {})), span.name


@pytest.mark.skipif(bool(os.environ.get(RUN)), reason="this is the run itself")
def test_host_errors_reach_no_span_in_their_own_process() -> None:
    """One process: a process's tracer provider is set once and cannot be replaced."""
    run = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header",
            f"{__file__}::test_a_host_error_reaches_no_span",
        ],
        env={**os.environ, RUN: "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    assert f"{len(HOST_ERROR_IDS)} passed" in run.stdout, run.stdout[-1000:]


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
    # 61 searches, 60 of them the same: no loop here, the text is under test.
    bounds = AgentBounds(max_tool_calls=200, sandbox_suspensions=1000, max_repeated_calls=100)
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


async def test_a_library_s_own_tighter_budget_ends_the_agent_s_run() -> None:
    modes = InMemoryLibraryModes()
    own = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=10)
    await modes.save(LIB, None, LibraryAi(budgets=(own,)))
    roomy = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1_000_000)
    world = await _world(budgets=Budgets(limits=(roomy,)), modes=modes)

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (
        RetrievalMode.BM25,
        FallbackReason.LLM_BUDGET_REACHED,
    )
    spent = [row for key, row in world.ledger.rows.items() if key.scope_kind == "library"]
    assert spent
    assert all(row.input_tokens > 10 for row in spent)  # the first request, then refused


async def test_without_a_library_budget_the_instance_s_roomy_one_lets_the_agent_answer() -> None:
    roomy = BudgetLimit(scope_kind="library", window=SpendWindow.DAY, tokens=1_000_000)
    world = await _world(budgets=Budgets(limits=(roomy,)))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.AGENTIC, None)


# ---------------------------------------------------------------- the caller's scope: deps (#99)

SCOPE_WORDS = ("library", "version", "ref", "manifest", "tag", "caller", "user", "ctx", "deps")
"""Names no model-visible tool parameter may have: the scope comes from the agent's deps only."""


async def test_the_caller_s_scope_is_the_agent_s_deps_never_a_tool_argument() -> None:
    seen: list[AgentInfo] = []

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        if code_results(messages):
            return answer(info, [])
        return run_code("await list_articles()")

    await _search(await _world(FunctionModel(script)))

    (tool,) = seen[0].function_tools
    parameters = list(tool.parameters_json_schema["properties"])
    assert set(parameters) <= {"code", "restart"}  # Code Mode's own
    assert not [p for p in parameters for w in SCOPE_WORDS if w in p.split("_")]
    signatures = [
        line
        for line in (tool.description or "").splitlines()
        if line.lstrip().startswith("async def")
    ]
    assert len(signatures) == len(EXPLORER_TOOLS)
    for line in signatures:
        names = re.findall(r"(\w+)\s*:", line.split("(", 1)[1].rsplit(")", 1)[0])
        assert names, line
        assert not [n for n in names for w in SCOPE_WORDS if w in n.split("_")], line


async def test_a_snippet_cannot_widen_its_scope_with_an_argument() -> None:
    foreign = await _v1_chunk(await _world())
    sent: list[str] = []

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.append(repr(messages))
        if len(sent) == 1:
            return run_code(f"await read_chunk(chunk_id={foreign!r}, version='v1')")
        return answer(info, [{"chunk_id": foreign, "justification": "From v1."}])

    world = await _world(FunctionModel(script))

    result = await _search(world)

    assert foreign not in [r.chunk_id for r in result.results]
    assert not any(OLD_GUIDE["resilience"][0] in text for text in sent)  # v1 was never read
    assert all(r.pinned_manifest == "m2" for r in world.reads.reads)


# ---------------------------------------------------------------- the output guardrail (#99)


async def _explore(
    world: World, model: Model, browser: DocsBrowser, *, limit: int = 10
) -> Sequence[AgentPick]:
    run = AgentRun(
        question=QUESTION,
        limit=limit,
        bounds=AgentBounds(),
        budgets=Budgets(),
        caller=AiCaller(library=LIB),
    )
    return await PydanticAiExplorer().explore(
        model, browser, run, ledger=world.ledger, clock=FixedClock()
    )


def _browser(world: World, *, tags: Sequence[str] = ()) -> VersionBrowser:
    return VersionBrowser(
        version=world.catalog.versions["v2"],
        chunks=world.chunks,
        search=world.index,
        articles=Articles(catalog=world.catalog),
        tag_filter=TagFilter(tags=tuple(tags)),
    )


async def test_the_output_guardrail_rejects_picks_the_caller_may_not_see(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world()
    foreign = await _v1_chunk(world)
    auth = (await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query="token downtime", mode="bm25")
    )).results[0].chunk_id  # fmt: skip
    untagged = (await world.module.search_docs(
        SearchDocsQuery(library=LIB, ref="v2", query="backoff", mode="bm25")
    )).results[0]  # fmt: skip
    assert untagged.article_path == "docs/resilience.md"  # in the pinned version, but untagged
    model = browsing(picks=2, extra=[foreign, "0" * 32, untagged.chunk_id, auth])

    picks = await _explore(world, model, _browser(world, tags=["security"]))

    ids = [p.chunk_id for p in picks]
    assert foreign not in ids
    assert "0" * 32 not in ids
    assert untagged.chunk_id not in ids  # the pinned version holds it; the caller's tags do not
    assert set(ids) == {auth}  # the search found it within the tags, and the agent added it too
    (warning,) = [r.getMessage() for r in caplog.records if "output guardrail" in r.getMessage()]
    assert "rejected 3 pick(s)" in warning
    assert foreign not in caplog.text


async def test_an_answer_within_the_scope_passes_the_guardrail_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world()

    picks = await _explore(world, browsing(picks=3), _browser(world))

    assert len(picks) == 3
    assert "output guardrail" not in caplog.text


@dataclass(slots=True)
class FailingAdmission:
    """A browser whose guardrail check fails on the host, as a broken database would."""

    browser: VersionBrowser
    message: str

    async def list_articles(self, prefix: str = "") -> Sequence[ArticleEntry]:
        return await self.browser.list_articles(prefix)

    async def article_outline(self, path: str) -> Outline | None:
        return await self.browser.article_outline(path)

    async def read_article(self, path: str) -> ArticleText | None:
        return await self.browser.read_article(path)

    async def read_chunk(self, chunk_id: str) -> StoredChunk | None:
        return await self.browser.read_chunk(chunk_id)

    async def search_docs(self, query: str, limit: int) -> Sequence[tuple[SearchHit, StoredChunk]]:
        return await self.browser.search_docs(query, limit)

    async def admit(self, chunk_ids: Sequence[str]) -> Sequence[str]:
        del chunk_ids
        raise RuntimeError(self.message)


async def test_a_guardrail_check_that_fails_on_the_host_ends_the_run_without_its_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world()
    marker = "postgresql://u:S3CRET-MARK@db"
    browser = FailingAdmission(browser=_browser(world), message=marker)

    with pytest.raises(AgentStoppedError) as stopped:
        await _explore(world, browsing(), browser)

    assert (stopped.value.reason, stopped.value.detail) == ("agent_failed", "RuntimeError")
    assert "S3CRET-MARK" not in caplog.text


# ---------------------------------------------------------------- loop detection (#99)


@pytest.mark.parametrize("repeated", ["read", "run_code"])
async def test_the_same_call_three_times_ends_the_run_and_bm25_answers(repeated: str) -> None:
    world = await _world(looping(3, in_one_snippet=repeated == "read"))

    result = await _search(world)

    assert result.retrieval_mode is RetrievalMode.BM25
    assert result.fallback_reason is FallbackReason.AGENT_LOOP_DETECTED
    assert result.results
    assert all(r.justification is None and not r.explored_path for r in result.results)
    assert world.tracer.fallbacks == [("bm25", "agent_loop_detected")]


async def test_twice_is_no_loop() -> None:
    world = await _world(looping(2))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.AGENTIC, None)


async def test_the_operator_sets_how_many_repeats_make_a_loop() -> None:
    world = await _world(looping(4), bounds=AgentBounds(max_repeated_calls=5))

    result = await _search(world)

    assert (result.retrieval_mode, result.fallback_reason) == (RetrievalMode.AGENTIC, None)


async def test_the_repeated_read_and_every_read_after_it_never_run() -> None:
    world = await _world(looping(6))

    await _search(world)

    searches = [r for r in world.reads.reads if r.tool == "search_docs"]
    assert len(searches) == 2  # the third, same as the first two, is refused, as is the rest


async def test_a_snippet_that_catches_the_repeated_call_still_ends_the_run() -> None:
    caught = (
        "for i in range(5):\n"
        "    try:\n"
        "        await search_docs(query='x')\n"
        "    except Exception:\n"
        "        pass\n"
        "'ok'"
    )

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return answer(info, []) if code_results(messages) else run_code(caught)

    result = await _search(await _world(FunctionModel(script)))

    assert result.fallback_reason is FallbackReason.AGENT_LOOP_DETECTED


def test_one_call_is_never_a_loop() -> None:
    with pytest.raises(InvalidAgentBoundsError, match="max_repeated_calls"):
        AgentBounds(max_repeated_calls=1)


# ---------------------------------------------------------------- the run's trace (#99)


async def test_every_read_is_traced_with_its_versions_and_never_its_arguments() -> None:
    world = await _world()

    await _search(world)

    reads = world.reads.reads
    assert {r.tool for r in reads} == {"search_docs", "list_articles", "article_outline",
                                       "read_chunk"}  # fmt: skip
    assert {r.search for r in reads} == {"search_docs"}
    assert {(r.pinned_version, r.pinned_manifest) for r in reads} == {(f"{LIB}/v2", "m2")}
    assert {v for r in reads for v in r.served_versions} == {f"{LIB}/v2"}
    assert {m for r in reads for m in r.served_manifests} == {"m2"}
    assert all(QUESTION not in repr(r) for r in reads)


async def test_articles_the_catalog_serves_from_another_manifest_never_reach_the_agent() -> None:
    world = await _world()
    browser = VersionBrowser(
        version=world.catalog.versions["v2"],
        chunks=world.chunks,
        search=world.index,
        articles=Articles(catalog=world.catalog, serve_from="m1"),  # a re-sync meanwhile
        reads=world.reads,
    )

    assert await browser.list_articles() == ()
    assert await browser.read_article("docs/resilience.md") is None
    assert [(r.tool, r.served_manifests) for r in world.reads.reads] == [
        ("list_articles", ()),
        ("read_article", ()),
    ]


def test_a_read_is_an_event_of_the_current_span_without_content() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    read = AgentRead(
        search="search_docs",
        tool="read_chunk",
        pinned_version=f"{LIB}/v2",
        pinned_manifest="m2",
        served_versions=(f"{LIB}/v2",),
        served_manifests=("m2",),
    )

    with provider.get_tracer("t").start_as_current_span("execute_tool read_chunk"):
        OpenTelemetryAgentReads().record(read)

    (span,) = exporter.get_finished_spans()
    (event,) = span.events
    assert event.name == "exactdocs.agent.read"
    assert dict(event.attributes or {}) == {
        "exactdocs.agent.tool": "read_chunk",
        "exactdocs.agent.pinned_version": f"{LIB}/v2",
        "exactdocs.agent.pinned_manifest": "m2",
        "exactdocs.agent.served_versions": (f"{LIB}/v2",),
        "exactdocs.agent.served_manifests": ("m2",),
    }
