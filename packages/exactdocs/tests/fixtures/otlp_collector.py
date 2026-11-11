"""A stand-in OpenTelemetry collector: an OTLP/HTTP endpoint on 127.0.0.1 that keeps what it gets.

Shared by pytest and behave (``context`` steps). Requests are kept as they arrived (raw bytes, to
search for text that must never leave) and trace requests are decoded into spans.
"""

import gzip
import http.server
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from opentelemetry import metrics, trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

TRACES = "/v1/traces"


@dataclass(frozen=True, slots=True, kw_only=True)
class Span:
    name: str
    attributes: dict[str, object]
    span_id: str = ""
    """Hex; empty when unknown."""
    parent_span_id: str = ""
    """Hex; empty for a root span."""


@dataclass(slots=True)
class Collector:
    url: str = ""
    requests: list[tuple[str, bytes]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def spans(self) -> list[Span]:
        with self.lock:
            bodies = [body for path, body in self.requests if path == TRACES]
        found = []
        for body in bodies:
            request = ExportTraceServiceRequest.FromString(body)
            for resource in request.resource_spans:
                for scope in resource.scope_spans:
                    found += [
                        Span(
                            name=s.name,
                            attributes={a.key: _value(a.value) for a in s.attributes},
                            span_id=s.span_id.hex(),
                            parent_span_id=s.parent_span_id.hex(),
                        )
                        for s in scope.spans
                    ]
        return found

    def received(self) -> bytes:
        """Everything that arrived, traces, metrics and logs, as one blob of bytes."""
        with self.lock:
            return b"\n".join(body for _, body in self.requests)

    def wait_for(self, done: Callable[[list[Span]], bool], timeout: float = 30) -> list[Span]:
        deadline = time.monotonic() + timeout
        while not done(spans := self.spans()):
            if time.monotonic() > deadline:
                names = sorted({s.name for s in spans})
                message = f"the collector did not get the spans expected; it has {names}"
                raise AssertionError(message)
            time.sleep(0.05)
        return spans


def _value(value: object) -> object:
    kind = value.WhichOneof("value")  # ty: ignore[unresolved-attribute]
    return getattr(value, kind) if kind else None


@contextmanager
def collecting() -> Generator[Collector]:
    """Serve a collector on a free loopback port for the duration of the block.

    Yields:
        The collector; its ``url`` is what ``OTEL_EXPORTER_OTLP_ENDPOINT`` should be.
    """
    collector = Collector()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            with collector.lock:
                collector.requests.append((self.path, body))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            """Stay quiet."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    collector.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield collector
    finally:
        server.shutdown()
        server.server_close()


def shut_telemetry_down() -> None:
    """Flush and stop this process's SDK providers while the collector still listens.

    Otherwise they export once more at exit, to a collector that is gone, and retry for seconds.
    """
    tracer_provider, meter_provider = trace.get_tracer_provider(), metrics.get_meter_provider()
    assert isinstance(tracer_provider, TracerProvider), tracer_provider
    tracer_provider.shutdown()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.shutdown()
