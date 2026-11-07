"""Telemetry (OPS-01): traces to a collector, metrics for Prometheus; off by default.

``EXACTDOCS_TELEMETRY=otlp`` exports to the operator's collector; ``EXACTDOCS_METRICS`` serves
``/metrics`` for Prometheus. Only the OpenTelemetry *API* is imported here, which records nothing
until an SDK is set up. The SDK (``bootstrap/otlp.py``) is loaded by ``start_telemetry`` when the
operator turned either on, never otherwise: a default process has no SDK, no provider, no exporter
and no ``/metrics``.
"""

import importlib
import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Response
from opentelemetry import metrics, trace

from exactdocs.bootstrap.constants import (
    ERROR_TYPE_ATTRIBUTE,
    JOB_DURATION_BUCKETS,
    JOB_DURATION_METRIC,
    JOB_KIND_ATTRIBUTE,
    JOB_TRACER_NAME,
    METRICS_PATH,
    OTLP_ENDPOINT_VARIABLE,
    OTLP_MODULE,
    UNTRACED_PATHS,
)
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.models import Job, JobKind
from exactdocs.ingestion.ports.driven import JobHandler, JobProgress
from exactdocs.retrieval.adapters.driven.opentelemetry import OpenTelemetrySearchTracer
from exactdocs.retrieval.ports.driven import SearchTracer

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
    sdk = importlib.import_module(OTLP_MODULE)
    if otlp_on and not sdk.exports("TRACES"):
        logger.warning(
            "EXACTDOCS_TELEMETRY=otlp, but no OTLP endpoint is set (%s): no traces are exported",
            OTLP_ENDPOINT_VARIABLE,
        )
    configured = sdk.configure_sdk(
        otlp=otlp_on, prometheus=prometheus_on, record_query_text=settings.telemetry_query_text
    )
    if not configured:
        logger.warning("telemetry was already set up in this process; it is left as it is")


def build_metrics_router() -> APIRouter:
    """``GET /metrics``: the Prometheus text exposition, for an app with ``EXACTDOCS_METRICS`` on.

    No sign-in (Prometheus scrapes with none); the Host allowlist applies, as everywhere but the
    probes. It holds no query text, library, user or caller: request metrics are by route
    template, search metrics by search, stage and mode, job metrics by kind.

    Returns:
        The router.
    """
    router = APIRouter()

    @router.get(METRICS_PATH, include_in_schema=False)
    def scrape() -> Response:  # sync: collecting is CPU work, it runs in the thread pool
        """Collect the metrics and render them for Prometheus.

        Returns:
            The text exposition.
        """
        body, content_type = importlib.import_module(OTLP_MODULE).exposition()
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
