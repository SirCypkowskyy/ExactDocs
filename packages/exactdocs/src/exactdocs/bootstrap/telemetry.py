"""Telemetry (OPS-01): off by default; with ``EXACTDOCS_TELEMETRY=otlp``, traces to a collector.

Only the OpenTelemetry *API* is imported here, which records nothing until an SDK is set up.
The SDK (``bootstrap/otlp.py``) is loaded by ``start_telemetry`` when the operator turned
telemetry on, never otherwise: a default process has no SDK, no provider and no exporter.
"""

import importlib
import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace

from exactdocs.bootstrap.constants import (
    JOB_TRACER_NAME,
    OTLP_ENDPOINT_VARIABLE,
    OTLP_MODULE,
    PROBE_PATHS,
)
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.models import Job, JobKind
from exactdocs.ingestion.ports.driven import JobHandler, JobProgress
from exactdocs.retrieval.adapters.driven.opentelemetry import OpenTelemetrySearchTracer
from exactdocs.retrieval.ports.driven import SearchTracer

logger = logging.getLogger(__name__)


def start_telemetry(settings: Settings) -> None:
    """Set up the trace export when ``EXACTDOCS_TELEMETRY=otlp``; do nothing otherwise.

    The providers are process-wide and OpenTelemetry does not let them be replaced: a second app
    built in the same process (tests) keeps what the first set up, its query-text setting
    included, and a warning says so. Run each telemetry configuration in a process of its own.

    Args:
        settings: The runtime configuration.
    """
    if settings.telemetry != "otlp":
        return
    # Loaded here, not imported at the top: with telemetry off the SDK is never loaded.
    otlp = importlib.import_module(OTLP_MODULE)
    if not otlp.exports("TRACES"):
        logger.warning(
            "EXACTDOCS_TELEMETRY=otlp, but no OTLP endpoint is set (%s): no traces are exported",
            OTLP_ENDPOINT_VARIABLE,
        )
    if not otlp.configure_otlp(record_query_text=settings.telemetry_query_text):
        logger.warning("telemetry was already set up in this process; it is left as it is")


def search_tracer(settings: Settings) -> SearchTracer | None:
    """Return what records search spans when telemetry is on.

    Args:
        settings: The runtime configuration.

    Returns:
        The OpenTelemetry tracer, or ``None`` (nothing is recorded) when telemetry is off.
    """
    if settings.telemetry != "otlp":
        return None
    return OpenTelemetrySearchTracer(record_query_text=settings.telemetry_query_text)


def traced_jobs(
    settings: Settings, handlers: Mapping[JobKind, JobHandler]
) -> Mapping[JobKind, JobHandler]:
    """Give every job (import, refresh i.e. sync, collect...) a span when telemetry is on.

    Args:
        settings: The runtime configuration.
        handlers: What runs each job kind.

    Returns:
        The handlers, each wrapped in a span when telemetry is on; as given otherwise.
    """
    if settings.telemetry != "otlp":
        return handlers
    return {kind: TracedJobHandler(kind=kind, handler=h) for kind, h in handlers.items()}


def is_untraced(scope: MutableMapping[str, Any]) -> bool:
    """Tell FastAPI's built-in OpenTelemetry which requests get no span: the health checks.

    Args:
        scope: The ASGI scope of the request.

    Returns:
        Whether the request is a health check.
    """
    return scope.get("path") in PROBE_PATHS


@dataclass(frozen=True, slots=True, kw_only=True)
class TracedJobHandler:
    """Implements ingestion's ``JobHandler``: the handler, inside an ``ingestion.<kind>`` span.

    The span names the job, library and version; a failure is recorded on it by the API.
    """

    kind: JobKind
    """The job kind the handler runs: ``import``, ``refresh`` (a branch sync), ``collect``..."""
    handler: JobHandler
    """What runs the job."""
    provider: trace.TracerProvider | None = None
    """Where the spans go; ``None``: the global provider (what ``start_telemetry`` set up)."""

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the job inside its span.

        Args:
            job: The job to run.
            progress: Where the job reports how far it got.
        """
        attributes = {
            "exactdocs.job.id": job.id,
            "exactdocs.job.kind": self.kind,
            "exactdocs.library": job.library,
        }
        if job.version is not None:
            attributes["exactdocs.version"] = job.version
        with trace.get_tracer(JOB_TRACER_NAME, tracer_provider=self.provider).start_as_current_span(
            f"ingestion.{self.kind}", attributes=attributes
        ):
            await self.handler(job, progress)
