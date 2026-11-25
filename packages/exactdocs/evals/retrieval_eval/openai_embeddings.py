"""A local OpenAI-compatible embeddings endpoint for another tool's benchmark run (#492).

Grounded Docs reaches an embedding model through an OpenAI-compatible server (``OPENAI_API_BASE``).
To measure it with the model ExactDocs' best local configuration uses, this serves that model,
loaded from the folder ``exactdocs models pull`` filled (the same ONNX file, at the same pinned
revision, through fastembed as ExactDocs loads it), at ``POST /v1/embeddings`` on the loopback
interface. It speaks the part of the API an embeddings client uses: ``input`` as a string or a
list of strings, ``encoding_format`` ``float`` or ``base64``, and ``usage`` with the tokens the
model's tokenizer counts. It runs in a thread of the benchmark's process and counts what it
embedded. See docs/evals/grounded-docs.md.
"""

import base64
import importlib
import json
import struct
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, override

from exactdocs.bootstrap.constants import LOCAL_MEMORY_ARENA, LOCAL_SDK_MODULE
from exactdocs.bootstrap.local_models import model_folder, onnx_threads, read_marker

PATH: Final[str] = "/v1/embeddings"
"""Where the endpoint answers, under the base URL ``http://127.0.0.1:<port>/v1``."""
MODELS_PATH: Final[str] = "/v1/models"
"""The model list some clients read first."""
_MAX_BODY: Final[int] = 64 * 1024 * 1024
"""The largest request body read (a batch of a few hundred long chunks is far below it)."""

type Embed = Callable[[Sequence[str]], list[list[float]]]
"""Embeds texts, one vector per text, in order."""
type CountTokens = Callable[[Sequence[str]], int]
"""Counts the model tokens of texts."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- counts as it serves
class Served:
    """What the endpoint has embedded so far."""

    requests: int = 0
    """Requests answered."""
    texts: int = 0
    """Texts embedded."""
    tokens: int = 0
    """Model tokens of those texts (before the model's truncation)."""
    seconds: float = 0.0
    """Time spent embedding."""
    abandoned: int = 0
    """Requests embedded but not delivered: the client had closed the connection (it gave up
    waiting, and may have sent the request again)."""
    errors: list[str] = field(default_factory=list)
    """Requests refused, and why."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalEmbedding:
    """A pulled local embedding model, as the endpoint serves it."""

    model: str
    """Its name, as fastembed lists it (``BAAI/bge-small-en-v1.5``)."""
    revision: str | None
    """The Hub commit it was pulled at (from the pull marker)."""
    dimensions: int | None
    """Its vector size."""
    embed: Embed
    """Embeds texts."""
    count: CountTokens
    """Counts their tokens."""


def load_local(models_dir: Path, model: str) -> LocalEmbedding:
    """Load a pulled embedding model offline, as ExactDocs' ``local`` profile loads it.

    Args:
        models_dir: Where ``exactdocs models pull`` put it (``EXACTDOCS_MODELS_DIR``).
        model: Its name.

    Returns:
        The model, ready to embed.

    Raises:
        FileNotFoundError: It was not pulled there.
    """
    folder = model_folder(models_dir, model)
    marker = read_marker(folder)
    if marker is None:
        message = f"{model} is not in {models_dir}: run `exactdocs models pull {model}`"
        raise FileNotFoundError(message)
    sdk = importlib.import_module(LOCAL_SDK_MODULE)  # fastembed: the [local] extra
    loaded = sdk.load_embedding(
        model, folder, models_dir, threads=onnx_threads(), arena=LOCAL_MEMORY_ARENA
    )

    def embed(texts: Sequence[str]) -> list[list[float]]:
        """Embed texts as documents, as ExactDocs embeds its chunks.

        Args:
            texts: The texts.

        Returns:
            One vector per text.
        """
        return [[float(x) for x in vector] for vector in loaded.passage_embed(list(texts))]

    def count(texts: Sequence[str]) -> int:
        """Count the tokens of texts with the model's tokenizer.

        Args:
            texts: The texts.

        Returns:
            Their tokens.
        """
        return int(loaded.token_count(list(texts)))

    return LocalEmbedding(
        model=marker.model,
        revision=marker.revision,
        dimensions=marker.dimensions,
        embed=embed,
        count=count,
    )


def encoded(vector: Sequence[float], encoding: str) -> list[float] | str:
    """Encode a vector as the request asked.

    Args:
        vector: The vector.
        encoding: ``float`` or ``base64`` (little-endian 32-bit floats, as the OpenAI API sends).

    Returns:
        The list of floats, or its base64 text.
    """
    if encoding == "base64":
        return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")
    return list(vector)


def response(
    texts: Sequence[str], vectors: Sequence[Sequence[float]], model: str, tokens: int, encoding: str
) -> dict[str, object]:
    """The body of an embeddings response.

    Args:
        texts: The texts embedded.
        vectors: Their vectors, in order.
        model: The model's name, as the request gave it.
        tokens: Their tokens.
        encoding: ``float`` or ``base64``.

    Returns:
        The JSON object the OpenAI API returns.
    """
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": encoded(v, encoding)}
            for i, v in enumerate(vectors[: len(texts)])
        ],
        "model": model,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


def parse_request(body: bytes) -> tuple[list[str], str, str]:
    """Read an embeddings request.

    Args:
        body: The request's JSON body.

    Returns:
        The texts, the model named and the encoding asked for.

    Raises:
        ValueError: The body is not an embeddings request of text.
    """
    data = json.loads(body)
    if not isinstance(data, dict):
        data = {}
    raw = data.get("input")
    texts = [raw] if isinstance(raw, str) else raw
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        message = "the body is not a JSON object whose input is a string or a list of strings"
        raise ValueError(message)
    encoding = str(data.get("encoding_format") or "float")
    if encoding not in {"float", "base64"}:
        message = f"encoding_format {encoding!r} is not float or base64"
        raise ValueError(message)
    return texts, str(data.get("model") or ""), encoding


@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint:
    """A running endpoint."""

    base_url: str
    """``http://127.0.0.1:<port>/v1``: what ``OPENAI_API_BASE`` is set to."""
    served: Served
    """What it has embedded so far."""


@contextmanager
def serve(embed: Embed, count: CountTokens, model: str) -> Generator[Endpoint]:
    """Serve a model at ``POST /v1/embeddings`` on a free loopback port, in a thread.

    One request is embedded at a time (the model's ONNX session uses the cores itself).

    Args:
        embed: Embeds texts.
        count: Counts their tokens.
        model: The model's name, listed at ``/v1/models``.

    Yields:
        The endpoint, until the block ends.
    """
    served = Served()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        """Answers the embeddings API."""

        @override
        def log_message(self, format: str, *args: object) -> None:
            """Log nothing: the benchmark reports what was served.

            Args:
                format: The message's format.
                *args: Its values.
            """

        def _send(self, status: HTTPStatus, body: dict[str, object]) -> None:
            """Send a JSON response; count it abandoned when the client is gone.

            Args:
                status: The status.
                body: The JSON body.
            """
            data = json.dumps(body).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except BrokenPipeError, ConnectionResetError:
                with lock:
                    served.abandoned += 1
                self.close_connection = True

        def do_GET(self) -> None:
            """List the model."""
            if self.path.rstrip("/") != MODELS_PATH:
                self._send(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
                return
            entry = {"id": model, "object": "model", "owned_by": "local"}
            self._send(HTTPStatus.OK, {"object": "list", "data": [entry]})

        def do_POST(self) -> None:
            """Embed the request's texts."""
            if self.path.rstrip("/") != PATH:
                self._send(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                texts, named, encoding = parse_request(self.rfile.read(min(length, _MAX_BODY)))
            except ValueError as error:
                with lock:
                    served.errors.append(str(error))
                self._send(HTTPStatus.BAD_REQUEST, {"error": {"message": str(error)}})
                return
            with lock:
                started = time.perf_counter()
                vectors = embed(texts) if texts else []
                tokens = count(texts) if texts else 0
                served.seconds += time.perf_counter() - started
                served.requests += 1
                served.texts += len(texts)
                served.tokens += tokens
            self._send(HTTPStatus.OK, response(texts, vectors, named or model, tokens, encoding))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="embeddings", daemon=True)
    thread.start()
    try:
        yield Endpoint(base_url=f"http://127.0.0.1:{server.server_address[1]}/v1", served=served)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
