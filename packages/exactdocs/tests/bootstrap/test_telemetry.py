# ruff: file-ignore[suspicious-subprocess-import, subprocess-without-shell-equals-true]
"""OPS-01: with ``EXACTDOCS_TELEMETRY=otlp`` traces reach the operator's collector, without query
text unless they opted in; health checks get no span; off, nothing is set up at all.

The end-to-end tests set up process-wide OpenTelemetry providers, so they run in a process of
their own (``test_telemetry_end_to_end_in_its_own_process``).
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import SecretStr

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.otlp import redact_query, scrub
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.telemetry import (
    TracedJobHandler,
    is_untraced,
    search_tracer,
    traced_jobs,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    CreateLibraryCommand,
    HostKind,
    StoreManifestCommand,
)
from exactdocs.catalog.models import RefKind as CatalogRefKind
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.ingestion.models import Job, JobId, JobKind, RefKind
from exactdocs.retrieval.adapters.driven.opentelemetry import OpenTelemetrySearchTracer
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from exactdocs_kernel import SystemClock
from otlp_collector import Collector, Span, collecting, shut_telemetry_down

RUN = "EXACTDOCS_TELEMETRY_E2E"  # set in the process the end-to-end tests run in
QUERY = "retry_policy"
LIBRARY = "/acme/payments"
REF = "v1.4.0"
HORSE = "correct horse battery staple"
LIBRARY_NAME = "paymentsxyz"  # a name only a search would contain
TOO_LONG = "LONGSECRET77 " + "x" * 1100  # over MAX_QUERY: a validation error quotes it
REFUSED = "SECRETLIMIT"  # not a number: a validation error quotes it
SEARCH_ROUTE = "/api/v1/libraries/{owner}/{repo}/search"


def recorded(provider_spans: InMemorySpanExporter) -> list[ReadableSpan]:
    return list(provider_spans.get_finished_spans())


def provider_with(*processors: Any) -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    for processor in processors:
        provider.add_span_processor(processor)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


# ----------------------------------------------------------------- pieces


def test_the_values_of_query_text_parameters_are_redacted_and_the_rest_kept() -> None:
    assert redact_query("q=retry_policy&ref=v1.4.0&tags=a&tags=b") == (
        "q=REDACTED&ref=v1.4.0&tags=a&tags=b"
    )
    assert redact_query("libraryId=%2Facme%2Fpayments&query=how+to+retry&type=json") == (
        "libraryId=%2Facme%2Fpayments&query=REDACTED&type=json"
    )
    # A repository URL can carry a token.
    assert redact_query("url=https%3A%2F%2Fx%3Asecret%40git.example.com") == "url=REDACTED"
    assert redact_query("q=") == "q=REDACTED"
    assert redact_query("libraryName=payments&query=x") == "libraryName=REDACTED&query=REDACTED"


def test_a_request_span_keeps_its_path_but_loses_the_query_text() -> None:
    provider, exporter = provider_with()

    attributes = {"url.path": "/api/v1/search", "url.query": f"q={QUERY}&limit=5"}
    provider.get_tracer("t").start_span("GET", attributes=attributes).end()

    (span,) = recorded(exporter)
    assert dict(scrub(span).attributes or {}) == {
        "url.path": "/api/v1/search",
        "url.query": "q=REDACTED&limit=5",
    }


def test_an_mcp_span_does_not_say_who_called() -> None:
    provider, exporter = provider_with()

    attributes = {"mcp.method.name": "tools/call", "enduser.id": "acct-1", "enduser.scope": "read"}
    provider.get_tracer("t").start_span("tools/call search_docs", attributes=attributes).end()

    (span,) = recorded(exporter)
    assert dict(scrub(span).attributes or {}) == {"mcp.method.name": "tools/call"}


def test_a_failed_span_keeps_the_exception_type_but_not_its_text() -> None:
    provider, exporter = provider_with()
    error = ValueError(f"1 validation error: input_value='{QUERY}'")

    span = provider.get_tracer("t").start_span("tools/call search_docs")
    span.record_exception(error)
    span.set_status(StatusCode.ERROR, str(error))
    span.end()

    (finished,) = recorded(exporter)
    scrubbed = scrub(finished)
    assert QUERY in str(finished.events[0].attributes)  # sanity: the raw span has it
    assert scrubbed.status.status_code is StatusCode.ERROR
    assert scrubbed.status.description is None
    assert dict(scrubbed.events[0].attributes or {}) == {
        "exception.type": "ValueError",
        "exception.escaped": "False",
    }


def test_health_checks_get_no_request_span() -> None:
    assert is_untraced({"type": "http", "path": "/api/health"})
    assert is_untraced({"type": "http", "path": "/healthz"})
    assert is_untraced({"type": "http", "path": "/readyz"})
    assert not is_untraced({"type": "http", "path": "/api/v1/search"})


def test_the_metrics_scrape_gets_no_request_span_or_metric() -> None:
    assert is_untraced({"type": "http", "path": "/metrics"})


def test_off_nothing_is_traced() -> None:
    handlers = {JobKind("import"): object()}

    assert search_tracer(Settings()) is None
    assert traced_jobs(Settings(), handlers) is handlers  # ty: ignore[invalid-argument-type]


def test_with_metrics_on_searches_and_jobs_are_observed_without_query_text() -> None:
    handlers = {JobKind("import"): object()}
    settings = Settings(metrics=True)

    tracer = search_tracer(settings)
    traced = traced_jobs(settings, handlers)  # ty: ignore[invalid-argument-type]

    assert isinstance(tracer, OpenTelemetrySearchTracer)
    assert not tracer.record_query_text
    assert isinstance(traced[JobKind("import")], TracedJobHandler)


class Quiet:
    async def report(self, **_: Any) -> None: ...
    async def problem(self, *_: Any) -> None: ...
    async def chunking(self, **_: Any) -> None: ...
    async def parsing(self, **_: Any) -> None: ...


def job(kind: str) -> Job:
    return Job.queued(
        job_id=JobId("j1"),
        kind=JobKind(kind),
        library=LIBRARY,
        version=REF,
        commit_sha="a" * 40,
        ref_kind=RefKind.TAG,
        now=SystemClock().now(),
    )


async def test_a_job_runs_inside_a_span_named_after_its_kind() -> None:
    provider, exporter = provider_with()
    ran: list[str] = []

    async def handler(job: Job, progress: object, /) -> None:
        del progress
        ran.append(job.id)

    traced = TracedJobHandler(kind=JobKind("refresh"), handler=handler, provider=provider)
    await traced(job("refresh"), Quiet())  # ty: ignore[invalid-argument-type]

    (span,) = recorded(exporter)
    assert ran == ["j1"]
    assert span.name == "ingestion.refresh"
    assert dict(span.attributes or {}) == {
        "exactdocs.job.id": "j1",
        "exactdocs.job.kind": "refresh",
        "exactdocs.library": LIBRARY,
        "exactdocs.version": REF,
    }


def job_points(reader: InMemoryMetricReader) -> list[dict[str, object]]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        {"name": metric.name, "count": point.count, **dict(point.attributes or {})}
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
        if isinstance(point, HistogramDataPoint)
    ]


async def test_every_job_is_timed_by_kind_without_its_library() -> None:
    reader = InMemoryMetricReader()

    async def handler(job: Job, progress: object, /) -> None:
        del job, progress

    traced = TracedJobHandler(
        kind=JobKind("import"),
        handler=handler,
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    await traced(job("import"), Quiet())  # ty: ignore[invalid-argument-type]
    await traced(job("import"), Quiet())  # ty: ignore[invalid-argument-type]

    assert job_points(reader) == [
        {"name": "exactdocs.job.duration", "count": 2, "exactdocs.job.kind": "import"}
    ]


async def test_a_failing_job_is_timed_with_its_error_type() -> None:
    reader = InMemoryMetricReader()

    async def handler(job: Job, progress: object, /) -> None:
        del job, progress
        message = "remote unreachable"
        raise RuntimeError(message)

    traced = TracedJobHandler(
        kind=JobKind("refresh"),
        handler=handler,
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    with pytest.raises(RuntimeError):
        await traced(job("refresh"), Quiet())  # ty: ignore[invalid-argument-type]

    assert job_points(reader) == [
        {
            "name": "exactdocs.job.duration",
            "count": 1,
            "exactdocs.job.kind": "refresh",
            "error.type": "RuntimeError",
        }
    ]


async def test_a_failing_job_fails_its_span_and_still_raises() -> None:
    provider, exporter = provider_with()

    async def handler(job: Job, progress: object, /) -> None:
        del job, progress
        message = "remote unreachable"
        raise RuntimeError(message)

    traced = TracedJobHandler(kind=JobKind("import"), handler=handler, provider=provider)
    with pytest.raises(RuntimeError, match="unreachable"):
        await traced(job("import"), Quiet())  # ty: ignore[invalid-argument-type]

    (span,) = recorded(exporter)
    assert not span.status.is_ok


# ----------------------------------------------------------------- end to end, own process


@pytest.fixture
def query_text() -> bool:
    """Whether the operator opted in to query text; a test parametrizes it to say yes."""
    return False


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch, query_text: bool) -> Iterator[Collector]:
    """Telemetry on, to a collector on loopback; set before the container reads the settings.

    Yields:
        The collector.
    """
    with collecting() as collector:
        monkeypatch.setenv("EXACTDOCS_TELEMETRY", "otlp")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.url)
        monkeypatch.setenv("OTEL_BSP_SCHEDULE_DELAY", "50")  # export within the test
        monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "200")
        monkeypatch.setenv("EXACTDOCS_TELEMETRY_QUERY_TEXT", "true" if query_text else "false")
        yield collector
        shut_telemetry_down()


@pytest.fixture
async def app(collector: Collector) -> AsyncIterator[FastAPI]:
    """The app, running with telemetry on, with an admin and one indexed version.

    Yields:
        The running app.
    """
    del collector  # only its order matters: telemetry is on before the container is built
    container = Container.build(Settings())
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await index_one_version(container)
        yield app


async def index_one_version(container: Container) -> None:
    await container.catalog.create_library(
        CreateLibraryCommand(
            id=LIBRARY,
            title="Payments",
            source_url="https://github.com/acme/payments",
            host=HostKind.GITHUB,
            default_branch="main",
        )
    )
    text = "Set `retry_policy` to choose how calls are repeated."
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref=REF,
            kind=CatalogRefKind.TAG,
            commit_sha="b" * 40,
            articles=[
                ArticleIn(
                    path="docs/retries.md",
                    blob_sha="c" * 40,
                    content_version=1,
                    title="Retries",
                    content=text,
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=LIBRARY,
            ref=REF,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path="docs/retries.md",
                    blob_sha="c" * 40,
                    chunks=[
                        ChunkIn(
                            heading_path=["Retries"],
                            occurrence_index=0,
                            content=text,
                            content_hash="h",
                            anchor="retries",
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def search_everywhere(app: FastAPI) -> None:
    """Search over REST (path and context7 routes) and MCP; check health on the way."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        login = await client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
        assert login.status_code == 201
        token = (await client.post("/api/v1/tokens", json={"name": "agent"})).json()["token"]
        assert (await client.get("/api/health")).status_code == 200
        found = await client.get(
            f"/api/v1/libraries{LIBRARY}/search", params={"q": QUERY, "ref": REF}
        )
        assert found.json()["results"], found.text
        docs = await client.get(
            "/api/v1/c7/docs", params={"libraryId": f"{LIBRARY}/{REF}", "query": QUERY}
        )
        assert docs.status_code == 200, docs.text
        named = await client.get(
            "/api/v1/c7/search", params={"libraryName": LIBRARY_NAME, "query": QUERY}
        )
        assert named.status_code == 200, named.text

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    transport = StreamableHttpTransport(
        "http://localhost/mcp",
        headers={"authorization": f"Bearer {token}"},
        httpx_client_factory=factory,
    )
    async with Client(transport) as mcp:
        result = await mcp.call_tool(
            "search_docs", {"library": LIBRARY, "ref": REF, "query": QUERY}
        )
        assert result.structured_content
        assert result.structured_content["results"]
        # Refused arguments: their validation errors quote the input.
        for arguments in [
            {"library": LIBRARY, "ref": REF, "query": TOO_LONG},
            {"library": LIBRARY, "ref": REF, "query": QUERY, "limit": REFUSED},
        ]:
            refused = await mcp.call_tool("search_docs", arguments, raise_on_error=False)
            assert refused.is_error


EXPECTED = {
    "retrieval.search_docs",
    "retrieval.search_docs.version",
    "retrieval.search_docs.rank",
    "retrieval.search_docs.chunks",
    "retrieval.query_docs",
    "tools/call search_docs",
}


def names(spans: list[Span]) -> set[str]:
    return {s.name for s in spans}


def tool_calls(spans: list[Span]) -> list[Span]:
    return [s for s in spans if s.name == "tools/call search_docs"]


@pytest.mark.skipif(not os.environ.get(RUN), reason="runs in its own process")
async def test_traces_reach_the_collector_without_query_text(
    collector: Collector, app: FastAPI
) -> None:
    await search_everywhere(app)

    spans = collector.wait_for(
        lambda found: names(found) >= EXPECTED and len(tool_calls(found)) >= 3  # 2 refused
    )
    requests = [s for s in spans if "http.request.method" in s.attributes]
    assert SEARCH_ROUTE in {s.attributes.get("http.route") for s in requests}
    assert "/api/health" not in {s.attributes.get("url.path") for s in requests}
    searches = [s for s in spans if s.name == "retrieval.search_docs"]
    assert {s.attributes["exactdocs.retrieval.mode"] for s in searches} == {"bm25"}
    # Nowhere: no span name, attribute, event or status, and no metric holds the search input.
    received = collector.received()
    for text in [QUERY, LIBRARY_NAME, "LONGSECRET77", REFUSED]:
        assert text.encode() not in received, text
    # Nor who called: no MCP span names the caller.
    assert not [s for s in spans if {"enduser.id", "enduser.scope"} & s.attributes.keys()]


@pytest.mark.skipif(not os.environ.get(RUN), reason="runs in its own process")
@pytest.mark.parametrize("query_text", [True])
async def test_the_query_text_is_kept_only_when_the_operator_opted_in(
    query_text: bool, collector: Collector, app: FastAPI
) -> None:
    assert query_text
    await search_everywhere(app)

    spans = collector.wait_for(lambda found: names(found) >= EXPECTED)
    searches = [s for s in spans if s.name == "retrieval.search_docs"]
    assert {s.attributes.get("exactdocs.query") for s in searches} == {QUERY}
    request = next(s for s in spans if s.attributes.get("http.route") == SEARCH_ROUTE)
    assert f"q={QUERY}" in str(request.attributes["url.query"])
    # So the scrubbing is what keeps the refused inputs out by default: here they arrive.
    calls = tool_calls(collector.wait_for(lambda found: len(tool_calls(found)) >= 3))
    assert b"LONGSECRET77" in collector.received()
    assert any("enduser.id" in s.attributes for s in calls), [s.attributes for s in calls]


# ----------------------------------------------------------------- Prometheus, own process


@pytest.fixture
def with_otlp() -> bool:
    """Whether the OTLP export is on as well; a test parametrizes it to say yes."""
    return False


@pytest.fixture
async def metered_app(monkeypatch: pytest.MonkeyPatch, with_otlp: bool) -> AsyncIterator[FastAPI]:
    """The app with ``EXACTDOCS_METRICS`` on (and OTLP too, if asked), an admin and one version.

    Yields:
        The running app.
    """
    monkeypatch.setenv("EXACTDOCS_METRICS", "true")
    monkeypatch.delenv("EXACTDOCS_TELEMETRY_QUERY_TEXT", raising=False)
    if not with_otlp:
        # A collector in the environment exports nothing without EXACTDOCS_TELEMETRY=otlp.
        monkeypatch.delenv("EXACTDOCS_TELEMETRY", raising=False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://203.0.113.9:4318")
    container = Container.build(Settings())
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        await index_one_version(container)
        yield app


def use_an_llm() -> None:
    """Record what pydantic-ai records per model call, through the global OpenTelemetry API."""
    usage = metrics.get_meter("pydantic-ai").create_histogram(
        "gen_ai.client.token.usage", unit="{token}", description="Measures number of tokens used"
    )
    for kind, tokens in [("input", 120), ("output", 40)]:
        usage.record(
            tokens,
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "test-model",
                "gen_ai.token.type": kind,
            },
        )


async def scrape(app: FastAPI, host: str = "localhost") -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://{host}"
    ) as prometheus:
        return await prometheus.get("/metrics")


def sampled(text: str, name: str, **labels: str) -> float:
    """The sum of the samples of ``name`` that carry every one of ``labels``."""
    total = 0.0
    for line in text.splitlines():
        if line.startswith((f"{name}{{", f"{name} ")) and all(
            f'{label}="{value}"' in line for label, value in labels.items()
        ):
            total += float(line.rsplit(" ", 1)[-1])
    return total


@pytest.mark.skipif(not os.environ.get(RUN), reason="runs in its own process")
async def test_prometheus_scrapes_request_search_and_llm_metrics_without_query_text(
    metered_app: FastAPI,
) -> None:
    await search_everywhere(metered_app)
    use_an_llm()

    scraped = await scrape(metered_app)

    assert scraped.status_code == 200, scraped.text
    assert scraped.headers["content-type"].startswith("text/plain")
    text = scraped.text
    requests = "http_server_request_duration_seconds_count"
    assert sampled(text, requests, http_route=SEARCH_ROUTE, http_response_status_code="200") == 1
    assert sampled(text, requests, http_route="/api/v1/c7/docs") == 1
    assert sampled(text, requests, http_route="/mcp")  # MCP requests
    searches = "exactdocs_search_duration_seconds_count"
    for search in ["search_docs", "query_docs"]:
        assert sampled(text, searches, exactdocs_search=search, exactdocs_search_stage="total",
                       exactdocs_retrieval_mode="bm25"), search  # fmt: skip
    assert sampled(text, searches, exactdocs_search="search_docs", exactdocs_search_stage="rank")
    tokens = "gen_ai_client_token_usage_sum"  # pydantic-ai's, once the AI modes record it
    assert sampled(text, tokens, gen_ai_token_type="input") == 120
    assert sampled(text, tokens, gen_ai_token_type="output") == 40
    # The probe asked by search_everywhere and this scrape are not requests anyone monitors.
    assert "/api/health" not in text
    assert 'http_route="/metrics"' not in text
    # Nothing a user typed, no library, no caller.
    for secret in [QUERY, LIBRARY_NAME, "LONGSECRET77", REFUSED, LIBRARY, "payments", '"ada"']:
        assert secret not in text, secret
    assert "enduser" not in text
    # The DNS-rebinding guard covers the scrape like every other path.
    assert (await scrape(metered_app, host="rebinding.example")).status_code == 400


@pytest.mark.skipif(not os.environ.get(RUN), reason="runs in its own process")
@pytest.mark.parametrize("with_otlp", [True])
async def test_prometheus_is_a_reader_beside_the_otlp_export(
    with_otlp: bool, collector: Collector, metered_app: FastAPI
) -> None:
    assert with_otlp
    await search_everywhere(metered_app)

    collector.wait_for(lambda found: names(found) >= EXPECTED)
    text = (await scrape(metered_app)).text

    # One meter provider, two readers: Prometheus pulls, the OTLP exporter pushes the same.
    assert sampled(text, "exactdocs_search_duration_seconds_count", exactdocs_search="search_docs")
    deadline = asyncio.get_running_loop().time() + 10
    while b"exactdocs.search.duration" not in collector.received():
        assert asyncio.get_running_loop().time() < deadline, "no metrics reached the collector"
        await asyncio.sleep(0.1)
    assert QUERY.encode() not in collector.received()
    assert QUERY not in text


@pytest.mark.skipif(bool(os.environ.get(RUN)), reason="this is the run itself")
@pytest.mark.parametrize(
    "test",
    [
        "test_traces_reach_the_collector_without_query_text",
        "test_the_query_text_is_kept_only_when_the_operator_opted_in",
        "test_prometheus_scrapes_request_search_and_llm_metrics_without_query_text",
        "test_prometheus_is_a_reader_beside_the_otlp_export",
    ],
)
def test_telemetry_end_to_end_in_its_own_process(test: str) -> None:
    """One process per test: a process's tracer provider is set once and cannot be replaced."""
    run = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header",
            f"{__file__}::{test}",
        ],
        env={**os.environ, RUN: "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    assert "1 passed" in run.stdout, run.stdout[-1000:]
