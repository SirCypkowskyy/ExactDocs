"""The OpenTelemetry SDK behind ``EXACTDOCS_TELEMETRY=otlp``, loaded only when it is on.

Logfire is used only as an OpenTelemetry SDK: ``send_to_logfire=False`` always (nothing goes to
Logfire's cloud) and ``console=False`` (stdout belongs to stdio MCP). Traces, metrics and logs go
over OTLP/HTTP to the collector the standard ``OTEL_EXPORTER_OTLP_*`` variables name, and nowhere
when none is named.
"""

import os
from urllib.parse import parse_qsl, urlencode

import logfire
from opentelemetry.context import Context
from opentelemetry.sdk.trace import Span, SpanProcessor

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    QUERY_TEXT_PARAMETERS,
    REDACTED,
    SERVICE_NAME,
    URL_QUERY_ATTRIBUTE,
)


def configure_otlp(*, record_query_text: bool) -> None:
    """Set up the global tracer, meter and logger providers and their OTLP exporters.

    Args:
        record_query_text: Keep query text in spans (the operator opted in); redacted otherwise.
    """
    logfire.configure(
        send_to_logfire=False,
        console=False,
        service_name=os.environ.get("OTEL_SERVICE_NAME") or SERVICE_NAME,
        service_version=__version__,
        additional_span_processors=[] if record_query_text else [QueryTextRedaction()],
        # No argument capture, no client-supplied baggage copied into spans.
        inspect_arguments=False,
        add_baggage_to_attributes=False,
        # A trace started by the caller (a `traceparent` header) is continued, not warned about.
        distributed_tracing=True,
    )


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


class QueryTextRedaction(SpanProcessor):
    """Redact query text from a request span's ``url.query`` as the span starts.

    FastAPI's built-in OpenTelemetry records the whole query string; ``/search?q=...`` would put
    every query into the traces.
    """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Rewrite ``url.query`` while the span can still be changed.

        Args:
            span: The span that just started.
            parent_context: Its parent's context (unused).
        """
        del parent_context
        query = (span.attributes or {}).get(URL_QUERY_ATTRIBUTE)
        if isinstance(query, str):
            span.set_attribute(URL_QUERY_ATTRIBUTE, redact_query(query))
