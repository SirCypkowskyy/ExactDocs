"""A fake model gateway on 127.0.0.1 for the AI provider tests (pytest and behave).

It speaks just enough of three dialects for one minimal call each: OpenAI Chat Completions and
Embeddings (``/v1/chat/completions``, ``/v1/embeddings``), Anthropic Messages (``/v1/messages``)
and the Cohere-compatible rerank (``/v1/rerank``); a path with ``/broken/`` answers
404. It records every request (method, path,
headers, body), so a test can see what was sent and with which credentials. A second instance
serves as a trap: pointed to by ``OPENAI_BASE_URL`` and the like, it must receive nothing.
Given a ``hold`` event, it answers embedding requests only once the event is set, so a test can
look at an instance while an embedding run is in progress. Embeddings are one fixed small vector,
or ``term_vector``'s hashed bag of words with ``by_terms`` (texts sharing terms are near, so hybrid
search can be tested end to end); setting ``FakeGateway.broken`` makes every embedding request
fail with 400, as a provider that refuses the call.
"""

import hashlib
import json
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from exactdocs.retrieval.models import identifier_tokens

DIMENSIONS = 3
TERM_DIMENSIONS = 256
"""The size of ``term_vector``'s vectors."""
FILLER = frozenset({"a", "an", "and", "do", "does", "how", "i", "is", "of", "the", "to", "what"})
"""Words ``term_vector`` leaves out."""


def term_vector(text: str) -> list[float]:
    """Hash each term of a text into one of ``TERM_DIMENSIONS`` dimensions (a bag of words).

    Args:
        text: The text.

    Returns:
        The vector; its first value is a small constant, so it is never all zeros.
    """
    values = [0.0] * TERM_DIMENSIONS
    values[0] = 0.01
    for term in identifier_tokens(text).split():
        if term not in FILLER:
            digest = hashlib.blake2b(term.encode(), digest_size=8).digest()
            values[1 + int.from_bytes(digest) % (TERM_DIMENSIONS - 1)] += 1.0
    return values


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
    broken: threading.Event = field(default_factory=threading.Event)
    """Once set, every embedding request is refused with 400."""

    @property
    def v1(self) -> str:
        """The OpenAI-style base URL.

        Returns:
            ``<url>/v1``.
        """
        return f"{self.url}/v1"


def _answer(
    path: str, body: dict[str, Any], embed: Callable[[str], list[float]]
) -> dict[str, Any] | None:
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
        texts = inputs if isinstance(inputs, list) else [inputs]
        return {
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": embed(str(text))}
                for i, text in enumerate(texts)
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


HOLD_SECONDS = 60.0
"""The longest an embedding request waits for its ``hold`` event."""


def _fixed_vector(text: str) -> list[float]:
    del text
    return [0.1] * DIMENSIONS


@contextmanager
def gateway(
    hold: threading.Event | None = None, *, by_terms: bool = False
) -> Generator[FakeGateway]:
    """Serve a fake gateway on a free loopback port until the block ends.

    Args:
        hold: When given, embedding requests wait until it is set (at most ``HOLD_SECONDS``).
        by_terms: Embed with ``term_vector`` instead of one fixed vector.

    Yields:
        The gateway.
    """
    seen: list[Seen] = []
    broken = threading.Event()
    embed = term_vector if by_terms else _fixed_vector

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
            embedding = self.path.split("?")[0].endswith("/embeddings")
            if hold is not None and embedding:
                hold.wait(HOLD_SECONDS)
            if embedding and broken.is_set():
                answer, status = None, 400
            else:
                answer = _answer(self.path.split("?")[0], body, embed)
                status = 200 if answer is not None else 404
            payload = json.dumps(answer or {"error": "not found"}).encode()
            self.send_response(status)
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
        yield FakeGateway(url=f"http://127.0.0.1:{server.server_port}", seen=seen, broken=broken)
    finally:
        server.shutdown()
        server.server_close()
