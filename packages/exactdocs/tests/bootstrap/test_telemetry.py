# ruff: file-ignore[suspicious-subprocess-import, subprocess-without-shell-equals-true]
"""OPS-01: with ``EXACTDOCS_TELEMETRY=otlp`` traces reach the operator's collector, without query
text unless they opted in; health checks get no span; off, nothing is set up at all.

The end-to-end tests set up process-wide OpenTelemetry providers, so they run in a process of
their own (``test_telemetry_end_to_end_in_its_own_process``).
"""

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


def test_off_nothing_is_traced() -> None:
    handlers = {JobKind("import"): object()}

    assert search_tracer(Settings()) is None
    assert traced_jobs(Settings(), handlers) is handlers  # ty: ignore[invalid-argument-type]


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


@pytest.mark.skipif(bool(os.environ.get(RUN)), reason="this is the run itself")
@pytest.mark.parametrize(
    "test",
    [
        "test_traces_reach_the_collector_without_query_text",
        "test_the_query_text_is_kept_only_when_the_operator_opted_in",
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
