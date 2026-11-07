"""A fake model gateway on 127.0.0.1 for the AI provider tests (pytest and behave).

It speaks just enough of three dialects for one minimal call each: OpenAI Chat Completions and
Embeddings (``/v1/chat/completions``, ``/v1/embeddings``), Anthropic Messages (``/v1/messages``)
and the Cohere-compatible rerank (``/v1/rerank``); a path with ``/broken/`` answers
404. It records every request (method, path,
headers, body), so a test can see what was sent and with which credentials. A second instance
serves as a trap: pointed to by ``OPENAI_BASE_URL`` and the like, it must receive nothing.
"""

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DIMENSIONS = 3


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


def _answer(path: str, body: dict[str, Any]) -> dict[str, Any] | None:
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
        documents = body.get("documents", [])
        return {"results": [{"index": i, "relevance_score": 0.9} for i in range(len(documents))]}
    return None


@contextmanager
def gateway() -> Generator[FakeGateway]:
    """Serve a fake gateway on a free loopback port until the block ends.

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
            answer = _answer(self.path.split("?")[0], body)
            payload = json.dumps(answer or {"error": "not found"}).encode()
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
