"""A stand-in for the Hugging Face Hub, enough for ``snapshot_download`` (#538).

It serves any repository at any revision with the same small files. ``GET /api/models/<repo>``
(``/revision/<rev>``) and ``/api/models/<repo>/tree/<rev>`` list them; ``HEAD`` and ``GET
/<repo>/resolve/<rev>/<file>`` give each one's metadata and bytes. It records every request
(method, path, ``Host``), so a test can tell the pull reached it, and through which name.
Standard library only: the integration test runs it in a container of its own
(``python3 fake_hub.py <address> <port>``).
"""

import hashlib
import json
import re
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILES = (
    "config.json",
    "model.onnx",
    "model_optimized.onnx",
    "onnx/model.onnx",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
)
"""What every repository holds: the file names fastembed's models use."""
COMMIT = "0123456789abcdef0123456789abcdef01234567"
"""The commit a revision that is not a commit resolves to."""
_INFO = re.compile(r"^/api/models/(?P<repo>[^/]+/[^/?]+)(?:/revision/(?P<rev>[^/?]+))?(?:\?|$)")
_TREE = re.compile(r"^/api/models/(?P<repo>[^/]+/[^/]+)/tree/(?P<rev>[^/?]+)")
_RESOLVE = re.compile(r"^/(?P<repo>[^/]+/[^/]+)/resolve/(?P<rev>[^/]+)/(?P<file>[^?]+)")
_JSON = {"Content-Type": "application/json"}

type Answer = tuple[int, bytes, dict[str, str]]
"""Status, body and headers."""


def content(name: str) -> bytes:
    """The bytes of a file.

    Args:
        name: Its path in the repository.

    Returns:
        Small, file-specific bytes (valid JSON).
    """
    return json.dumps({"file": name}).encode()


def _commit(revision: str | None) -> str:
    """The commit a revision names.

    Args:
        revision: A commit SHA, a branch, or ``None`` for ``main``.

    Returns:
        The revision when it is a 40-digit SHA, else ``COMMIT``.
    """
    return revision if revision and re.fullmatch(r"[0-9a-f]{40}", revision) else COMMIT


def answer(path: str) -> Answer:
    """What the Hub answers for a path.

    Args:
        path: The request's path and query.

    Returns:
        The answer; 404 for anything else.
    """
    if _TREE.match(path):
        tree = [
            {
                "type": "file",
                "path": name,
                "size": len(content(name)),
                "oid": hashlib.sha1(content(name), usedforsecurity=False).hexdigest(),
            }
            for name in FILES
        ]
        return 200, json.dumps(tree).encode(), _JSON
    if found := _INFO.match(path):
        siblings = [{"rfilename": name} for name in FILES]
        info = {"id": found["repo"], "sha": _commit(found["rev"]), "siblings": siblings}
        return 200, json.dumps(info).encode(), _JSON
    if (found := _RESOLVE.match(path)) and found["file"] in FILES:
        body = content(found["file"])
        headers = {
            "Content-Type": "application/octet-stream",
            "ETag": f'"{hashlib.sha256(body).hexdigest()}"',
            "X-Repo-Commit": _commit(found["rev"]),
        }
        return 200, body, headers
    return 404, b'{"error": "not found"}', _JSON


@dataclass(slots=True)
class FakeHub:
    """A running stand-in."""

    url: str = ""
    """``http://<host>:<port>``."""
    seen: list[tuple[str, str, str]] = field(default_factory=list)
    """``(method, path, Host header)`` of every request."""


def handler(hub: FakeHub) -> type[BaseHTTPRequestHandler]:
    """Make the request handler of a stand-in.

    Args:
        hub: Where the requests are recorded.

    Returns:
        The handler class.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True  # a kept connection: head and body without a 40 ms wait

        def _serve(self) -> None:
            hub.seen.append((self.command, self.path, self.headers.get("Host", "")))
            status, body, headers = answer(self.path)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:
            self._serve()

        def do_HEAD(self) -> None:
            self._serve()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            del code, size

    return Handler


@contextmanager
def fake_hub(host: str = "127.0.0.1", port: int = 0) -> Generator[FakeHub]:
    """Serve the stand-in until the block ends.

    Args:
        host: The address to listen on.
        port: The port; a free one when 0.

    Yields:
        The stand-in.
    """
    hub = FakeHub()
    server = ThreadingHTTPServer((host, port), handler(hub))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        hub.url = f"http://{host}:{server.server_address[1]}"
        yield hub
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), handler(FakeHub())).serve_forever()
