"""The OpenTelemetry SDK behind ``EXACTDOCS_TELEMETRY=otlp`` and ``EXACTDOCS_METRICS``.

It is loaded only when one of them is on. OTLP: traces (and metrics) go over OTLP/HTTP to the
collector the standard ``OTEL_EXPORTER_OTLP_*`` variables name, and nowhere when none is named;
nothing is written to the console (stdout belongs to stdio MCP). Unless the operator opted in to
query text, every span is scrubbed on its way out: the query-text values of ``url.query``, and
exception messages and stack traces, which can quote the input (a pydantic ``ValidationError`` names
its ``input_value``).

Prometheus: one more metric reader on the same meter provider, which sends nothing; ``/metrics``
renders what it collects (``exposition``) when Prometheus asks.
"""

import os
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    EXPORTER_VARIABLE,
    OTLP_ENDPOINT_VARIABLE,
    QUERY_TEXT_PARAMETERS,
    REDACTED,
    SCRUBBED_EXCEPTION_ATTRIBUTES,
    SCRUBBED_SPAN_ATTRIBUTES,
    SERVICE_NAME,
    URL_QUERY_ATTRIBUTE,
)


def configure_sdk(*, otlp: bool, prometheus: bool, record_query_text: bool) -> bool:
    """Set up the global tracer and meter providers, their exporters and readers, once per process.

    Args:
        otlp: Export traces (and metrics, when an endpoint is named for them) over OTLP/HTTP.
        prometheus: Collect metrics for ``/metrics`` with a Prometheus reader.
        record_query_text: Keep query text and exception messages in spans (the operator opted
            in); scrubbed otherwise.

    Returns:
        Whether the providers were set up (``False``: this process already has an SDK tracer or
        meter provider, which OpenTelemetry does not let anyone replace).
    """
    if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider) or isinstance(
        metrics.get_meter_provider(), MeterProvider
    ):
        return False
    resource = _resource()
    readers: list[MetricReader] = []
    if otlp:
        tracer_provider = TracerProvider(resource=resource)
        if exports("TRACES"):
            exporter = OTLPSpanExporter()
            tracer_provider.add_span_processor(
                BatchSpanProcessor(exporter if record_query_text else ScrubbingExporter(exporter))
            )
        trace.set_tracer_provider(tracer_provider)
        if exports("METRICS"):
            readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
    if prometheus:
        readers.append(PrometheusMetricReader())
    if readers:
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    return True


def exposition() -> tuple[bytes, str]:
    """Render the metrics for a Prometheus scrape: what the Prometheus reader collects now.

    The registry is ``prometheus_client``'s default one, where the reader registered itself. Chosen
    over a dedicated ``CollectorRegistry`` because it also holds the process and Python runtime
    collectors (memory, CPU, open files, garbage collection); the price is that a dependency
    registering its own collectors there would show up too (none does today).

    Returns:
        The text exposition and its content type.
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def exports(signal: str) -> bool:
    """Tell whether a signal has somewhere to go: an OTLP endpoint and no ``none`` exporter.

    Args:
        signal: ``TRACES`` or ``METRICS``.

    Returns:
        Whether that signal is exported.
    """
    endpoint = os.environ.get(OTLP_ENDPOINT_VARIABLE) or os.environ.get(
        f"{OTLP_ENDPOINT_VARIABLE.removesuffix('ENDPOINT')}{signal}_ENDPOINT"
    )
    return bool(endpoint) and os.environ.get(EXPORTER_VARIABLE.format(signal), "otlp") == "otlp"


def _resource() -> Resource:
    """Name the service ``exactdocs`` unless ``OTEL_SERVICE_NAME`` or the resource attributes do.

    Returns:
        The resource every span and metric carries.
    """
    detected = Resource.create({"service.version": __version__})
    if str(detected.attributes.get("service.name", "")).startswith("unknown_service"):
        detected = detected.merge(Resource({"service.name": SERVICE_NAME}))
    return detected


def redact_query(query: str) -> str:
    """Replace the values of the query-text parameters of a URL query string.

    Args:
        query: The URL's query string, without the ``?``.

    Returns:
        The same parameters, in order, with ``REDACTED`` for each query-text value.
    """
    return urlencode(
        [
            (name, REDACTED if name in QUERY_TEXT_PARAMETERS else value)
            for name, value in parse_qsl(query, keep_blank_values=True)
        ]
    )


def scrub(span: ReadableSpan) -> ReadableSpan:
    """Return the span without query text: redacted ``url.query``, no exception text, no caller.

    The exception's type stays (``exception.type`` and the span's error status); its message and
    stack trace go: a validation error quotes the value it refused, e.g. the query. FastMCP's
    ``enduser.id`` and ``enduser.scope`` (who called) go as well.

    Args:
        span: A finished span.

    Returns:
        A copy of it, scrubbed.
    """
    attributes = {
        key: value
        for key, value in (span.attributes or {}).items()
        if key not in SCRUBBED_SPAN_ATTRIBUTES
    }
    query = attributes.get(URL_QUERY_ATTRIBUTE)
    if isinstance(query, str):
        attributes[URL_QUERY_ATTRIBUTE] = redact_query(query)
    events = [
        Event(
            event.name,
            {
                key: value
                for key, value in (event.attributes or {}).items()
                if key not in SCRUBBED_EXCEPTION_ATTRIBUTES
            },
            event.timestamp,
        )
        for event in span.events
    ]
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class ScrubbingExporter(SpanExporter):
    """Hands spans to the OTLP exporter only once they are ``scrub``-bed."""

    def __init__(self, exporter: SpanExporter) -> None:
        """Wrap the exporter.

        Args:
            exporter: Where the scrubbed spans go.
        """
        self._exporter = exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export the scrubbed copies.

        Args:
            spans: Finished spans.

        Returns:
            What the OTLP exporter returned.
        """
        return self._exporter.export([scrub(span) for span in spans])

    def shutdown(self) -> None:
        """Shut the OTLP exporter down."""
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Flush the OTLP exporter.

        Args:
            timeout_millis: How long to wait at most.

        Returns:
            Whether it flushed in time.
        """
        return self._exporter.force_flush(timeout_millis)
