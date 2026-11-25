"""Telemetry (OPS-01): traces to a collector, metrics for Prometheus; off by default.

``EXACTDOCS_TELEMETRY=otlp`` exports to the operator's collector; ``EXACTDOCS_METRICS`` serves
``/metrics`` for Prometheus. Only the OpenTelemetry *API* is imported here, which records nothing
until an SDK is set up. The SDK (``bootstrap/otel_sdk.py``) is loaded by ``start_telemetry`` when
the operator turned either on, never otherwise: a default process has no SDK, no provider, no
exporter and no ``/metrics``.
"""

import hmac
import importlib
import logging
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from http import HTTPStatus
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import metrics, trace
from pydantic import SecretStr

from exactdocs.bootstrap.constants import (
    ERROR_TYPE_ATTRIBUTE,
    JOB_DURATION_BUCKETS,
    JOB_DURATION_METRIC,
    JOB_KIND_ATTRIBUTE,
    JOB_TRACER_NAME,
    METRICS_PATH,
    OTLP_ENDPOINT_VARIABLE,
    SDK_MODULE,
    UNTRACED_PATHS,
)
from exactdocs.bootstrap.rest import ErrorResponse
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.models import Job, JobKind
from exactdocs.ingestion.ports.driven import JobHandler, JobProgress
from exactdocs.retrieval.adapters.driven.opentelemetry import (
    OpenTelemetryAgentReads,
    OpenTelemetrySearchTracer,
)
from exactdocs.retrieval.ports.driven import AgentReads, SearchTracer

logger = logging.getLogger(__name__)


def start_telemetry(settings: Settings, *, scraped: bool = False) -> None:
    """Set up the SDK when ``EXACTDOCS_TELEMETRY=otlp`` or ``EXACTDOCS_METRICS`` asks; else nothing.

    The providers are process-wide and OpenTelemetry does not let them be replaced: a second app
    built in the same process (tests) keeps what the first set up, its query-text setting
    included, and a warning says so. Run each telemetry configuration in a process of its own.

    Args:
        settings: The runtime configuration.
        scraped: The process serves ``/metrics`` (HTTP), so ``EXACTDOCS_METRICS`` applies; stdio
            MCP has nowhere to serve them.
    """
    otlp_on = settings.telemetry == "otlp"
    prometheus_on = scraped and settings.metrics
    if not (otlp_on or prometheus_on):
        return
    # Loaded here, not imported at the top: with both off the SDK is never loaded.
    sdk = importlib.import_module(SDK_MODULE)
    if otlp_on and not sdk.exports("TRACES"):
        logger.warning(
            "EXACTDOCS_TELEMETRY=otlp, but no OTLP endpoint is set (%s): no traces are exported",
            OTLP_ENDPOINT_VARIABLE,
        )
    try:
        network = settings.outbound()
    except ValueError:
        network = None  # the container's build says what is wrong with them, and stops
    configured = sdk.configure_sdk(
        otlp=otlp_on,
        prometheus=prometheus_on,
        record_query_text=settings.telemetry_query_text,
        network=network,
    )
    if not configured:
        logger.warning("telemetry was already set up in this process; it is left as it is")


def build_metrics_router(*, token: SecretStr | None = None) -> APIRouter:
    """``GET /metrics``: the Prometheus text exposition, for an app with ``EXACTDOCS_METRICS`` on.

    No account sign-in (Prometheus has none): with ``token`` (``EXACTDOCS_METRICS_TOKEN``) a
    scrape must send it as a bearer token, else it gets 401; without, anyone who reaches the port
    may scrape. The Host allowlist applies either way, as everywhere but the probes. The metrics
    hold no query text, library, user or caller: request metrics are by route template, search
    metrics by search, stage and mode, job metrics by kind.

    Args:
        token: The bearer token a scrape must send; ``None``: none is needed.

    Returns:
        The router.
    """
    router = APIRouter()
    expected = token.get_secret_value().encode() if token else None

    @router.get(METRICS_PATH, include_in_schema=False)
    def scrape(request: Request) -> Response:  # sync: collecting is CPU work, in the thread pool
        """Collect the metrics and render them for Prometheus, if the scrape may have them.

        Args:
            request: The scrape.

        Returns:
            The text exposition, or 401 when a token is configured and was not sent.
        """
        if expected is not None:
            scheme, _, sent = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(sent.encode(), expected):
                body = ErrorResponse(
                    error="unauthenticated",
                    detail="send EXACTDOCS_METRICS_TOKEN as a bearer token to scrape /metrics",
                )
                return JSONResponse(
                    body.model_dump(),
                    status_code=HTTPStatus.UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        body, content_type = importlib.import_module(SDK_MODULE).exposition()
        return Response(content=body, media_type=content_type)

    return router


def _observed(settings: Settings) -> bool:
    """Tell whether anything records searches and jobs: traces, metrics or both.

    Args:
        settings: The runtime configuration.

    Returns:
        Whether ``EXACTDOCS_TELEMETRY=otlp`` or ``EXACTDOCS_METRICS`` is on.
    """
    return settings.telemetry == "otlp" or settings.metrics


def search_tracer(settings: Settings) -> SearchTracer | None:
    """Return what records search spans and durations when telemetry or metrics are on.

    Args:
        settings: The runtime configuration.

    Returns:
        The OpenTelemetry tracer, or ``None`` (nothing is recorded) when both are off.
    """
    if not _observed(settings):
        return None
    return OpenTelemetrySearchTracer(record_query_text=settings.telemetry_query_text)


def agent_reads(settings: Settings) -> AgentReads | None:
    """Return what records the agentic explorer's reads in the trace when telemetry is on.

    Args:
        settings: The runtime configuration.

    Returns:
        The span-event recorder, or ``None`` (nothing is recorded) when both are off.
    """
    if not _observed(settings):
        return None
    return OpenTelemetryAgentReads()


def traced_jobs(
    settings: Settings, handlers: Mapping[JobKind, JobHandler]
) -> Mapping[JobKind, JobHandler]:
    """Give every job (import, refresh i.e. sync, collect...) a span and a duration, if observed.

    That is when telemetry or metrics are on.

    Args:
        settings: The runtime configuration.
        handlers: What runs each job kind.

    Returns:
        The handlers, each wrapped when telemetry or metrics are on; as given otherwise.
    """
    if not _observed(settings):
        return handlers
    return {kind: TracedJobHandler(kind=kind, handler=h) for kind, h in handlers.items()}


def traced_job(settings: Settings) -> Callable[[JobKind, JobHandler], JobHandler]:
    """Give a handler the ingestion module adds itself (``push``) a span and a duration.

    That is when telemetry or metrics are on, as ``traced_jobs`` does for the given handlers.

    Args:
        settings: The runtime configuration.

    Returns:
        What wraps one handler; it returns the handler as given when nothing is observed.
    """
    if not _observed(settings):
        return _as_given
    return _traced


def _as_given(kind: JobKind, handler: JobHandler) -> JobHandler:
    """Return the handler unchanged.

    Args:
        kind: The job kind it runs.
        handler: What runs the job.

    Returns:
        ``handler``.
    """
    del kind
    return handler


def _traced(kind: JobKind, handler: JobHandler) -> JobHandler:
    """Wrap the handler in a span and a duration.

    Args:
        kind: The job kind it runs.
        handler: What runs the job.

    Returns:
        The traced handler.
    """
    return TracedJobHandler(kind=kind, handler=handler)


def is_untraced(scope: MutableMapping[str, Any]) -> bool:
    """Tell FastAPI's built-in OpenTelemetry which requests get no span and no request metric.

    Those are the health checks and the metrics scrapes, which poll on a timer.

    Args:
        scope: The ASGI scope of the request.

    Returns:
        Whether the request is a health check or a scrape.
    """
    return scope.get("path") in UNTRACED_PATHS


@dataclass(frozen=True, slots=True, kw_only=True)
class TracedJobHandler:
    """Implements ingestion's ``JobHandler``: the handler, inside a span and timed.

    The span is ``ingestion.<kind>``, the histogram ``exactdocs.job.duration``. The span names
    the job, library and version; a failure is recorded on it by the API. The metric names only
    the kind, and the exception class when the job failed: a library name
    could be private, and it would make a series per library.
    """

    kind: JobKind
    """The job kind the handler runs: ``import``, ``refresh`` (a branch sync), ``collect``..."""
    handler: JobHandler
    """What runs the job."""
    provider: trace.TracerProvider | None = None
    """Where the spans go; ``None``: the global provider (what ``start_telemetry`` set up)."""
    meter_provider: metrics.MeterProvider | None = None
    """Where the durations go; ``None``: the global provider (what ``start_telemetry`` set up)."""
    _duration: metrics.Histogram = field(init=False, repr=False)
    """The histogram, created once: a proxy until ``start_telemetry`` sets the global provider."""

    def __post_init__(self) -> None:
        """Create the histogram."""
        meter = metrics.get_meter(JOB_TRACER_NAME, meter_provider=self.meter_provider)
        duration = meter.create_histogram(
            JOB_DURATION_METRIC,
            unit="s",
            description="How long ExactDocs jobs (imports, syncs...) ran.",
            explicit_bucket_boundaries_advisory=list(JOB_DURATION_BUCKETS),
        )
        object.__setattr__(self, "_duration", duration)  # frozen: set once, here

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the job inside its span, and record how long it ran.

        Args:
            job: The job to run.
            progress: Where the job reports how far it got.
        """
        attributes = {
            "exactdocs.job.id": job.id,
            JOB_KIND_ATTRIBUTE: self.kind,
            "exactdocs.library": job.library,
        }
        if job.version is not None:
            attributes["exactdocs.version"] = job.version
        labels = {JOB_KIND_ATTRIBUTE: str(self.kind)}
        started = perf_counter()
        try:
            tracer = trace.get_tracer(JOB_TRACER_NAME, tracer_provider=self.provider)
            with tracer.start_as_current_span(f"ingestion.{self.kind}", attributes=attributes):
                await self.handler(job, progress)
        except BaseException as error:
            labels[ERROR_TYPE_ATTRIBUTE] = type(error).__qualname__
            raise
        finally:
            self._duration.record(max(0.0, perf_counter() - started), labels)
