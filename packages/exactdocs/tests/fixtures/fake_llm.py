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
event is set, so a test can look at an instance while an embedding run is in progress. Embeddings
are one fixed small vector, or ``term_vector``'s hashed bag of words with ``by_terms`` (texts
sharing terms are near, so hybrid search can be tested end to end); setting
``FakeGateway.broken`` makes every embedding request fail with 400, as a provider that refuses the
call; ``FakeGateway.chat_broken`` does the same for chat completions. A chat completion that offers
an output tool (the LLM judge, #96) is answered with a call of it that rates each
``<candidate id="...">`` of the prompt, the last one best (as the reranker does); with
``FakeGateway.judge_rogue`` set, the ratings also name an ID the prompt did not hold.
"""

import hashlib
import json
import re
import threading
import time
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


ROGUE_ID = "c999"
"""The candidate ID a rogue judge rates although it was not given."""
_CANDIDATE = re.compile(r'<candidate id="(c[0-9]+)">')


def _judged(body: dict[str, Any], *, rogue: bool) -> dict[str, Any] | None:
    """Answer a chat completion that offers an output tool with ratings of its candidates.

    Args:
        body: The chat completion request.
        rogue: Also rate ``ROGUE_ID``, which the prompt did not hold.

    Returns:
        A completion whose one tool call rates the candidates (the last best), or ``None`` when
        the request offers no tool.
    """
    tools = body.get("tools") or []
    if not tools:
        return None
    prompt = " ".join(
        str(m.get("content")) for m in body.get("messages", []) if m.get("role") == "user"
    )
    ids = _CANDIDATE.findall(prompt)
    ratings = [{"id": i, "score": min(10, n)} for n, i in enumerate(ids)]
    if rogue:
        ratings.append({"id": ROGUE_ID, "score": 10})
    call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": tools[0]["function"]["name"],
            "arguments": json.dumps({"response": ratings}),
        },
    }
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "unknown"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }


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
    broken: threading.Event = field(default_factory=threading.Event)
    """Once set, every embedding request is refused with 400."""
    chat_broken: threading.Event = field(default_factory=threading.Event)
    """Once set, every chat completion is refused with 400."""
    judge_rogue: threading.Event = field(default_factory=threading.Event)
    """Once set, the judge's ratings also name ``ROGUE_ID``, an ID it was not given."""

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


def _chat(model: str) -> dict[str, Any]:
    """Answer a plain chat completion with ``OK``.

    Args:
        model: The model asked for.

    Returns:
        The completion.
    """
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


def _answer(
    path: str, body: dict[str, Any], embed: Callable[[str], list[float]], *, rogue: bool = False
) -> dict[str, Any] | list[Any] | None:
    model = body.get("model", "unknown")
    if "/broken/" in path:
        return None
    if path.endswith("/chat/completions"):
        return _judged(body, rogue=rogue) or _chat(model)
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
        return _rerank(body)
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
    chat_broken = threading.Event()
    judge_rogue = threading.Event()
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
            if "/slow/" in self.path:
                time.sleep(SLOW_SECONDS)
            embedding = self.path.split("?")[0].endswith("/embeddings")
            if hold is not None and embedding:
                hold.wait(HOLD_SECONDS)
            chat = self.path.split("?")[0].endswith("/chat/completions")
            if (embedding and broken.is_set()) or (chat and chat_broken.is_set()):
                answer, status = None, 400
            else:
                answer = _answer(self.path.split("?")[0], body, embed, rogue=judge_rogue.is_set())
                status = 200 if answer is not None else 404
            payload = json.dumps({"error": "not found"} if answer is None else answer).encode()
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
        yield FakeGateway(
            url=f"http://127.0.0.1:{server.server_port}",
            seen=seen,
            broken=broken,
            chat_broken=chat_broken,
            judge_rogue=judge_rogue,
        )
    finally:
        server.shutdown()
        server.server_close()
