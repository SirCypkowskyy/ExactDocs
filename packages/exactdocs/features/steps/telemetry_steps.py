"""Steps for OPS-01: a real ``exactdocs serve`` process exporting to a collector on loopback.

The server runs in a process of its own: telemetry sets up process-wide OpenTelemetry providers,
which must not leak into the other scenarios of this run.
"""

import asyncio
import os
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

import httpx
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from otlp_collector import Collector, Span, collecting
from steps.http_steps import DEMO_COOKIE, store_demo_catalog
from steps.search_steps import LIBRARY, import_versions

CLI = "from exactdocs.bootstrap.cli import main; main()"
SEARCH_ROUTE = "/api/v1/libraries/{owner}/{repo}/search"
SEARCH_SPANS = {
    "retrieval.search_docs",
    "retrieval.search_docs.version",
    "retrieval.search_docs.rank",
    "retrieval.search_docs.chunks",
}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _stop(process: subprocess.Popen[str]) -> None:
    """SIGTERM: uvicorn shuts down and the telemetry left in its buffers is flushed on exit."""
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _wait_until_serving(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"exactdocs serve exited with {process.returncode}"
            raise AssertionError(message)
        try:
            if httpx.get(f"{url}/api/health", timeout=2).status_code == HTTPStatus.OK:
                return
        except httpx.TransportError:
            time.sleep(0.1)
    message = "exactdocs serve did not answer within 60 s"
    raise AssertionError(message)


@given('telemetry is "otlp" with a local collector')
def step_telemetry_on(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.collector = stack.enter_context(collecting())
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir)
    asyncio.run(store_demo_catalog(context.settings))
    asyncio.run(import_versions(context, ["v1.3.0", "v1.4.0"]))
    port = _free_port()
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(data_dir),
        "EXACTDOCS_TELEMETRY": "otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": context.collector.url,
        # Export within the scenario: spans every 50 ms, metrics every 200 ms.
        "OTEL_BSP_SCHEDULE_DELAY": "50",
        "OTEL_METRIC_EXPORT_INTERVAL": "200",
    }
    env.pop("EXACTDOCS_DATABASE_URL", None)
    env.pop("EXACTDOCS_TELEMETRY_QUERY_TEXT", None)
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, "serve", "--port", str(port)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    stack.callback(_stop, process)
    context.server = f"http://127.0.0.1:{port}"
    _wait_until_serving(context.server, process)


@when('a user searches "{query:S}"')
def step_search_served(context: Context, query: str) -> None:
    response = httpx.get(
        f"{context.server}/api/v1/libraries{LIBRARY}/search",
        params={"q": query},
        cookies={SESSION_COOKIE: DEMO_COOKIE},
        timeout=30,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["results"], response.text


def _has_request_and_search_spans(spans: list[Span]) -> bool:
    names = {s.name for s in spans}
    routes = {s.attributes.get("http.route") for s in spans}
    return names >= SEARCH_SPANS and SEARCH_ROUTE in routes


@then("the collector receives request and search spans")
def step_spans(context: Context) -> None:
    collector: Collector = context.collector
    spans = collector.wait_for(_has_request_and_search_spans)
    modes = {s.attributes.get("exactdocs.retrieval.mode") for s in spans if s.name in SEARCH_SPANS}
    assert modes == {"bm25"}, modes
    # The health checks that waited for the server to start are not traced.
    assert "/api/health" not in {s.attributes.get("url.path") for s in spans}


@then('no span contains "{text}"')
def step_no_text(context: Context, text: str) -> None:
    collector: Collector = context.collector
    # Metrics are exported every 200 ms: give them one round to arrive as well.
    time.sleep(0.5)
    assert collector.spans()
    assert text.encode() not in collector.received()
