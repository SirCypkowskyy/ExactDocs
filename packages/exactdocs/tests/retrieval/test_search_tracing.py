"""OPS-01: every search and each of its stages is a span, in its mode; query text only on opt-in."""

import contextlib
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryDefaultVersions,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
)
from exactdocs.retrieval.adapters.driven.opentelemetry import OpenTelemetrySearchTracer
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    IndexManifestCommand,
    QueryDocsQuery,
    ResolveLibraryIdQuery,
    SearchAllQuery,
    SearchDocsQuery,
)
from exactdocs.retrieval.errors import VersionNotIndexedError
from exactdocs.retrieval.models import (
    CatalogLibrary,
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SourceHost,
)
from exactdocs.retrieval.module import RetrievalModule

LIB = "/acme/payments"
QUERY = "retry_policy"
VERSION = SearchableVersion(
    library=LIB,
    version="v1.4.0",
    manifest_id="m14",
    commit_sha="b" * 40,
    repository_url="https://github.com/acme/payments",
    host=SourceHost.GITHUB,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Opened:
    name: str
    mode: str
    query: str | None
    attributes: dict[str, str | None]


@dataclass(slots=True)
class RecordingTracer:
    """A test double of ``SearchTracer``: what was opened, in order."""

    opened: list[Opened] = field(default_factory=list)

    def span(
        self, name: str, *, mode: str, query: str | None = None, **attributes: str | None
    ) -> AbstractContextManager[object]:
        self.opened.append(Opened(name=name, mode=mode, query=query, attributes=attributes))
        return nullcontext()

    @property
    def names(self) -> list[str]:
        return [o.name for o in self.opened]


@dataclass(slots=True)
class OneVersion:
    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        return VERSION if library == LIB and ref in {None, "v1.4.0"} else None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


async def build(tracer: RecordingTracer | None) -> RetrievalModule:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    versions = OneVersion()
    module = RetrievalModule.build(
        defaults=InMemoryDefaultVersions(versions=[VERSION]),
        libraries=InMemoryLibraries(
            libraries=[
                CatalogLibrary(
                    id=LIB,
                    title="Payments",
                    description="",
                    source_url=VERSION.repository_url,
                    default_version="v1.4.0",
                    versions=("v1.4.0",),
                    version_count=1,
                )
            ]
        ),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        tracer=tracer,
    )
    await module.index_manifest(
        IndexManifestCommand(
            manifest_id="m14",
            library=LIB,
            ref="v1.4.0",
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path="docs/guide/resilience.md",
                    blob_sha="b14",
                    chunks=[
                        ChunkIn(
                            heading_path=["Guide", "retry_policy"],
                            occurrence_index=0,
                            content="Set `retry_policy` to choose.",
                            content_hash="h",
                            anchor="retry_policy",
                        )
                    ],
                )
            ],
        )
    )
    return module


async def test_a_search_and_each_of_its_stages_get_a_span_in_the_mode_it_ran() -> None:
    tracer = RecordingTracer()
    retrieval = await build(tracer)

    result = await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="v1.4.0", query=QUERY))

    assert result.results
    assert tracer.names == [
        "search_docs",
        "search_docs.version",
        "search_docs.rank",
        "search_docs.chunks",
    ]
    assert {o.mode for o in tracer.opened} == {"bm25"}
    search = tracer.opened[0]
    assert search.attributes == {"library": LIB, "ref": "v1.4.0"}
    # The query text is handed over apart from the labels, so an adapter can leave it out.
    assert search.query == QUERY
    assert all(QUERY not in str(o.attributes) for o in tracer.opened)


async def test_every_search_entry_point_is_traced_by_stage() -> None:
    tracer = RecordingTracer()
    retrieval = await build(tracer)

    await retrieval.search_all_libraries(SearchAllQuery(query=QUERY))
    await retrieval.query_docs(QueryDocsQuery(library_id=f"{LIB}/v1.4.0", query=QUERY))
    await retrieval.resolve_library_id(ResolveLibraryIdQuery(library_name="payments", query=QUERY))

    assert tracer.names == [
        "search_all_libraries",
        "search_all_libraries.versions",
        "search_all_libraries.rank",
        "search_all_libraries.chunks",
        "query_docs",
        "query_docs.version",
        "query_docs.rank",
        "query_docs.chunks",
        "resolve_library_id",
        "resolve_library_id.versions",
        "resolve_library_id.rank",
        "resolve_library_id.chunks",
    ]


async def test_a_version_that_is_not_indexed_ends_the_trace_at_the_version_stage() -> None:
    tracer = RecordingTracer()
    retrieval = await build(tracer)

    with pytest.raises(VersionNotIndexedError):
        await retrieval.search_docs(SearchDocsQuery(library=LIB, ref="v1.2.0", query=QUERY))

    assert tracer.names == ["search_docs", "search_docs.version"]


async def test_without_a_tracer_searches_answer_the_same() -> None:
    traced, untraced = await build(RecordingTracer()), await build(None)
    query = SearchDocsQuery(library=LIB, ref="v1.4.0", query=QUERY)

    assert await traced.search_docs(query) == await untraced.search_docs(query)


# ----------------------------------------------------------------- the OpenTelemetry adapter


def spans_of(record_query_text: bool) -> list[dict[str, object]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = OpenTelemetrySearchTracer(record_query_text=record_query_text, provider=provider)
    with (
        tracer.span("search_docs", mode="bm25", query=QUERY, library=LIB, ref=None),
        tracer.span("search_docs.rank", mode="bm25"),
    ):
        pass
    return [{"name": s.name, **dict(s.attributes or {})} for s in exporter.get_finished_spans()]


def test_the_adapter_records_mode_and_labels_but_no_query_text_by_default() -> None:
    rank, search = spans_of(record_query_text=False)

    assert search == {
        "name": "retrieval.search_docs",
        "exactdocs.retrieval.mode": "bm25",
        "exactdocs.library": LIB,
    }
    assert rank == {"name": "retrieval.search_docs.rank", "exactdocs.retrieval.mode": "bm25"}


def test_the_adapter_records_the_query_text_only_when_told_to() -> None:
    _, search = spans_of(record_query_text=True)

    assert search["exactdocs.query"] == QUERY


# ----------------------------------------------------------------- metrics


def search_metrics(*, record_query_text: bool, fail: bool = False) -> list[dict[str, object]]:
    """Time a search and its rank stage (failing, if asked) and return the recorded points."""
    reader = InMemoryMetricReader()
    tracer = OpenTelemetrySearchTracer(
        record_query_text=record_query_text,
        provider=TracerProvider(),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    with (
        contextlib.suppress(VersionNotIndexedError),
        tracer.span("search_docs", mode="bm25", query=QUERY, library=LIB, ref="v1.4.0"),
        tracer.span("search_docs.rank", mode="bm25"),
    ):
        if fail:
            raise VersionNotIndexedError(LIB, "v1.4.0")
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


def test_every_search_and_stage_is_timed_by_mode_without_library_or_query() -> None:
    points = search_metrics(record_query_text=True)  # even with the query text opted in

    assert sorted(points, key=str) == sorted(
        [
            {
                "name": "exactdocs.search.duration",
                "count": 1,
                "exactdocs.search": "search_docs",
                "exactdocs.search.stage": "total",
                "exactdocs.retrieval.mode": "bm25",
            },
            {
                "name": "exactdocs.search.duration",
                "count": 1,
                "exactdocs.search": "search_docs",
                "exactdocs.search.stage": "rank",
                "exactdocs.retrieval.mode": "bm25",
            },
        ],
        key=str,
    )


def test_a_failed_search_is_timed_with_its_error_type() -> None:
    points = search_metrics(record_query_text=False, fail=True)

    assert {p["error.type"] for p in points} == {"VersionNotIndexedError"}
