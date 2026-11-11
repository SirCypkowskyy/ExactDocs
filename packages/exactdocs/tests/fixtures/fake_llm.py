"""A fake model gateway on 127.0.0.1 for the AI provider tests (pytest and behave).

It speaks just enough of four dialects for one minimal call each: OpenAI Chat Completions and
Embeddings (``/v1/chat/completions``, ``/v1/embeddings``), Anthropic Messages (``/v1/messages``),
the Cohere-compatible rerank (``.../rerank`` with ``documents``) and TEI's ``/rerank`` (with
``texts``). A reranker scores the documents in the reverse of the order they were sent (the last
one best), so a test can tell a reranked order from the order it sent. A path with ``/broken/``
answers 404; one with ``/slow/`` answers after ``SLOW_SECONDS`` (a reranker that times out). It
records every request (method, path, headers, body), so a test can see what was sent and with
which credentials. A second instance serves as a trap: pointed to by ``OPENAI_BASE_URL`` and the
like, it must receive nothing. Given a ``hold`` event, it answers embedding requests only once the
event is set, so a test can look at an instance while an embedding run is in progress.
"""

import json
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DIMENSIONS = 3
SLOW_SECONDS = 1.0
"""How long a ``/slow/`` path takes to answer."""


def reversed_scores(count: int) -> list[float]:
    """The scores the fake reranker gives ``count`` documents: the last one sent is the best.

    Args:
        count: How many documents were sent.

    Returns:
        One score per document, in the order they were sent.
    """
    return [(i + 1) / count for i in range(count)]


@dataclass(frozen=True, slots=True, kw_only=True)
class Seen:
    """One request the gateway received."""

    method: str
    """HTTP method."""
    path: str
    """Path with query."""
    headers: dict[str, str]
    """Headers, names in lower case."""
    body: dict[str, Any]
    """The JSON body (empty when there was none)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeGateway:
    """A running fake gateway."""

    url: str
    """``http://127.0.0.1:<port>``."""
    seen: list[Seen] = field(default_factory=list)
    """Every request, in order."""

    @property
    def v1(self) -> str:
        """The OpenAI-style base URL.

        Returns:
            ``<url>/v1``.
        """
        return f"{self.url}/v1"


def _rerank(body: dict[str, Any]) -> dict[str, Any] | list[Any]:
    """Answer a rerank in the dialect of its body, best first.

    Args:
        body: TEI's (``texts``) or the Cohere-compatible one (``documents``).

    Returns:
        TEI's bare list of ``index`` and ``score``, or Cohere's ``results``.
    """
    tei = "texts" in body
    scores = reversed_scores(len(body["texts"] if tei else body.get("documents", [])))
    ranked = sorted(enumerate(scores), key=lambda pair: -pair[1])
    if tei:
        return [{"index": i, "score": score} for i, score in ranked]
    return {"results": [{"index": i, "relevance_score": score} for i, score in ranked]}


def _answer(path: str, body: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
    model = body.get("model", "unknown")
    if "/broken/" in path:
        return None
    if path.endswith("/chat/completions"):
        return {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
    if path.endswith("/embeddings"):
        inputs = body.get("input", [])
        count = len(inputs) if isinstance(inputs, list) else 1
        return {
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1] * DIMENSIONS}
                for i in range(count)
            ],
            "model": model,
            "usage": {"prompt_tokens": 3, "total_tokens": 3},
        }
    if path.endswith("/messages"):
        return {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 1},
        }
    if path.endswith("/rerank"):
        return _rerank(body)
    return None


HOLD_SECONDS = 60.0
"""The longest an embedding request waits for its ``hold`` event."""


@contextmanager
def gateway(hold: threading.Event | None = None) -> Generator[FakeGateway]:
    """Serve a fake gateway on a free loopback port until the block ends.

    Args:
        hold: When given, embedding requests wait until it is set (at most ``HOLD_SECONDS``).

    Yields:
        The gateway.
    """
    seen: list[Seen] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else {}
            seen.append(
                Seen(
                    method="POST",
                    path=self.path,
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=body,
                )
            )
            if "/slow/" in self.path:
                time.sleep(SLOW_SECONDS)
            if hold is not None and self.path.split("?")[0].endswith("/embeddings"):
                hold.wait(HOLD_SECONDS)
            answer = _answer(self.path.split("?")[0], body)
            payload = json.dumps({"error": "not found"} if answer is None else answer).encode()
            self.send_response(200 if answer is not None else 404)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            seen.append(Seen(method="GET", path=self.path, headers=dict(self.headers), body={}))
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            del code, size

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield FakeGateway(url=f"http://127.0.0.1:{server.server_port}", seen=seen)
    finally:
        server.shutdown()
        server.server_close()
