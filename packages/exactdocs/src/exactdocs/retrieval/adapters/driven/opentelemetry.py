"""Search spans and metrics through the OpenTelemetry API (OPS-01); the SDK is set up elsewhere."""

from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from time import perf_counter

from opentelemetry import metrics, trace

from exactdocs.retrieval.constants import (
    ATTRIBUTE_PREFIX,
    ERROR_TYPE_ATTRIBUTE,
    MODE_ATTRIBUTE,
    QUERY_ATTRIBUTE,
    SEARCH_ATTRIBUTE,
    SEARCH_DURATION_BUCKETS,
    SEARCH_DURATION_METRIC,
    SPAN_PREFIX,
    STAGE_ATTRIBUTE,
    TRACER_NAME,
    WHOLE_SEARCH,
)
from exactdocs.retrieval.ports.driven import SearchSpan


@dataclass(frozen=True, slots=True, kw_only=True)
class _OpenSpan:
    """Implements ``ports.driven.SearchSpan`` over an OpenTelemetry span and its metric labels."""

    span: trace.Span
    """The span the block runs in."""
    labels: dict[str, str]
    """The labels the duration is recorded with when the block ends."""

    def answered_by(self, mode: str) -> None:
        """Replace the mode on the span and on the duration measurement.

        Args:
            mode: The mode that answered.
        """
        self.span.set_attribute(MODE_ATTRIBUTE, mode)
        self.labels[MODE_ATTRIBUTE] = mode


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenTelemetrySearchTracer:
    """Implements ``ports.driven.SearchTracer`` with spans, each timed in a histogram.

    The spans go to the global tracer provider, the durations to the ``exactdocs.search.duration``
    histogram of the global meter provider. The query text is left out of the span unless
    ``record_query_text`` is set: queries can hold code, customer names or secrets, and a trace
    backend is usually readable by more people. The metric never carries it, nor the library or ref:
    only the search, the stage and the mode.
    """

    record_query_text: bool = False
    """Add the query text to the search's span (``exactdocs.query``)."""
    provider: trace.TracerProvider | None = None
    """Where the spans go; ``None``: the global provider (what ``start_telemetry`` set up)."""
    meter_provider: metrics.MeterProvider | None = None
    """Where the durations go; ``None``: the global provider (what ``start_telemetry`` set up)."""
    _duration: metrics.Histogram = field(init=False, repr=False)
    """The histogram, created once: a proxy until ``start_telemetry`` sets the global provider."""

    def __post_init__(self) -> None:
        """Create the histogram."""
        meter = metrics.get_meter(TRACER_NAME, meter_provider=self.meter_provider)
        duration = meter.create_histogram(
            SEARCH_DURATION_METRIC,
            unit="s",
            description="How long ExactDocs searches, and each of their stages, took.",
            explicit_bucket_boundaries_advisory=list(SEARCH_DURATION_BUCKETS),
        )
        object.__setattr__(self, "_duration", duration)  # frozen: set once, here

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[SearchSpan]:
        """Start ``retrieval.<name>`` as the current span, and time it.

        Args:
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode, recorded as ``exactdocs.retrieval.mode``.
            query: The query text, recorded only with ``record_query_text``, never in metrics.
            attributes: Further labels of the span, recorded as ``exactdocs.<name>``; ``None``
                ones are not. The metric does not get them.

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
        return self._timed(
            tracer.start_as_current_span(f"{SPAN_PREFIX}{name}", attributes=labels),
            name=name,
            mode=mode,
        )

    @contextmanager
    def _timed(
        self, span: AbstractContextManager[trace.Span], *, name: str, mode: str
    ) -> Generator[SearchSpan]:
        """Run the block inside ``span`` and record how long it took, failed or not.

        Args:
            span: The span's context manager.
            name: The search, or the search and its stage after a dot.
            mode: The retrieval mode.

        Yields:
            The span, which can still be told the mode that answered.
        """
        search, _, stage = name.partition(".")
        labels = {
            SEARCH_ATTRIBUTE: search,
            STAGE_ATTRIBUTE: stage or WHOLE_SEARCH,
            MODE_ATTRIBUTE: mode,
        }
        started = perf_counter()
        try:
            with span as current:
                yield _OpenSpan(span=current, labels=labels)
        except BaseException as error:
            labels[ERROR_TYPE_ATTRIBUTE] = type(error).__qualname__
            raise
        finally:
            self._duration.record(max(0.0, perf_counter() - started), labels)
