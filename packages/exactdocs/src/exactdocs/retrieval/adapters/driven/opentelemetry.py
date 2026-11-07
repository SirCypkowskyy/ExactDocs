"""Search spans through the OpenTelemetry API (OPS-01): the SDK, if any, is set up elsewhere."""

from contextlib import AbstractContextManager
from dataclasses import dataclass

from opentelemetry import trace

from exactdocs.retrieval.constants import (
    ATTRIBUTE_PREFIX,
    MODE_ATTRIBUTE,
    QUERY_ATTRIBUTE,
    SPAN_PREFIX,
    TRACER_NAME,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenTelemetrySearchTracer:
    """Implements ``ports.driven.SearchTracer`` with spans of the global tracer provider.

    The query text is left out unless ``record_query_text`` is set: queries can hold code,
    customer names or secrets, and a trace backend is usually readable by more people.
    """

    record_query_text: bool = False
    """Add the query text to the search's span (``exactdocs.query``)."""
    provider: trace.TracerProvider | None = None
    """Where the spans go; ``None``: the global provider (what ``start_telemetry`` set up)."""

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[object]:
        """Start ``retrieval.<name>`` as the current span.

        Args:
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode, recorded as ``exactdocs.retrieval.mode``.
            query: The query text, recorded only with ``record_query_text``.
            attributes: Further labels, recorded as ``exactdocs.<name>``; ``None`` ones are not.

        Returns:
            The span's context manager.
        """
        labels = {
            f"{ATTRIBUTE_PREFIX}{key}": value
            for key, value in attributes.items()
            if value is not None
        }
        labels[MODE_ATTRIBUTE] = mode
        if self.record_query_text and query is not None:
            labels[QUERY_ATTRIBUTE] = query
        tracer = trace.get_tracer(TRACER_NAME, tracer_provider=self.provider)
        return tracer.start_as_current_span(f"{SPAN_PREFIX}{name}", attributes=labels)
