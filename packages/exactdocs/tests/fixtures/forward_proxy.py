"""A forward proxy on 127.0.0.1 for the outbound tests (#538): CONNECT tunnels and plain HTTP.

Hosts are never resolved: ``routes`` maps the names a test uses (``git.example.test:80``) to
the loopback servers that stand for them, so a request that reached such a host can only have
gone through this proxy (``.test`` names resolve nowhere). Every request is recorded, as
``CONNECT host:port`` or ``GET http://host/path``. With ``credentials`` the proxy answers 407
unless the request carries them (``Proxy-Authorization: Basic``); a host it has no route for is
refused with 403, as a corporate proxy's policy would.
"""

import base64
import contextlib
import socket
import socketserver
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pytest

from exactdocs_kernel import OUTBOUND_VARIABLES

HEAD_LIMIT = 64 * 1024
"""Longest request head the proxy reads."""
DENIED = (
    b"HTTP/1.1 407 Proxy Authentication Required\r\n"
    b'Proxy-Authenticate: Basic realm="test"\r\n'
    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
)
"""The answer to a request without the proxy's credentials."""


@dataclass(slots=True)
class ForwardProxy:
    """A running proxy."""

    url: str = ""
    """``http://127.0.0.1:<port>``, without credentials."""
    routes: dict[str, tuple[str, int]] = field(default_factory=dict)
    """``host:port`` (lower case) -> the loopback address it stands for."""
    credentials: str | None = None
    """``user:password`` the proxy asks for; ``None``: it asks for none."""
    seen: list[str] = field(default_factory=list)
    """Every request: ``CONNECT host:port`` or ``<METHOD> <absolute URL>``."""

    def url_with(self, credentials: str) -> str:
        """The proxy's URL with credentials in it.

        Args:
            credentials: ``user:password``.

        Returns:
            ``http://user:password@127.0.0.1:<port>``.
        """
        return self.url.replace("://", f"://{credentials}@", 1)

    def hosts(self) -> set[str]:
        """The ``host:port`` of every request it received.

        Returns:
            The hosts, lower case.
        """
        found = set()
        for line in self.seen:
            method, _, target = line.partition(" ")
            if method == "CONNECT":
                found.add(target.lower())
            else:
                parts = urlsplit(target)
                found.add(f"{parts.hostname}:{parts.port or 80}".lower())
        return found


def _pipe(source: socket.socket, sink: socket.socket) -> None:
    """Copy bytes until the source closes, then end the sink's writing side.

    Args:
        source: Where bytes come from.
        sink: Where they go.
    """
    with contextlib.suppress(OSError):
        while chunk := source.recv(65536):
            sink.sendall(chunk)
    with contextlib.suppress(OSError):
        sink.shutdown(socket.SHUT_WR)


@dataclass(frozen=True, slots=True)
class _Request:
    """The head of one request a client sent the proxy."""

    method: str
    target: str
    version: str
    headers: list[tuple[str, str]]
    rest: bytes
    """What the client sent after the head (a body, or a TLS hello)."""

    def header(self, name: str) -> str | None:
        return next((v.strip() for k, v in self.headers if k.lower() == name), None)


def _read_head(client: socket.socket) -> _Request | None:
    head = b""
    while b"\r\n\r\n" not in head and len(head) < HEAD_LIMIT:
        chunk = client.recv(65536)
        if not chunk:
            return None
        head += chunk
    head, _, rest = head.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target, version = lines[0].split(" ", 2)
    headers = [(k, v) for k, _, v in (line.partition(":") for line in lines[1:] if ":" in line)]
    return _Request(method, target, version, headers, rest)


def _forwarded(request: _Request, origin: str) -> bytes:
    """The request as the origin server gets it: origin-form, no proxy headers, then closed."""
    dropped = {"proxy-authorization", "proxy-connection", "connection"}
    kept = [f"{k}:{v}" for k, v in request.headers if k.lower() not in dropped]
    head = "\r\n".join([f"{request.method} {origin} {request.version}", *kept])
    return f"{head}\r\nConnection: close\r\n\r\n".encode("latin-1") + request.rest


def _handler(proxy: ForwardProxy) -> type[socketserver.BaseRequestHandler]:
    wanted = (
        None
        if proxy.credentials is None
        else "Basic " + base64.b64encode(proxy.credentials.encode()).decode()
    )

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            client: socket.socket = self.request
            request = _read_head(client)
            if request is None:
                return
            proxy.seen.append(f"{request.method} {request.target}")
            asked = proxy.credentials is not None  # read now: a test may change it
            if asked and request.header("proxy-authorization") != wanted:
                client.sendall(DENIED)
                return
            if request.method == "CONNECT":
                authority, first = request.target.lower(), request.rest
            else:
                parts = urlsplit(request.target)
                authority = f"{parts.hostname}:{parts.port or 80}".lower()
                origin = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                first = _forwarded(request, origin)
            address = proxy.routes.get(authority)
            if address is None:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            with socket.create_connection(address, timeout=30) as upstream:
                if request.method == "CONNECT":
                    client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                upstream.sendall(first)
                back = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
                back.start()
                _pipe(client, upstream)
                back.join(timeout=60)

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextlib.contextmanager
def forward_proxy(
    routes: dict[str, tuple[str, int]] | None = None, *, credentials: str | None = None
) -> Generator[ForwardProxy]:
    """Run a forward proxy on a free loopback port until the block ends.

    Args:
        routes: ``host:port`` -> the loopback address that stands for it.
        credentials: ``user:password`` the proxy asks for.

    Yields:
        The proxy.
    """
    proxy = ForwardProxy(routes=dict(routes or {}), credentials=credentials)
    server = _Server(("127.0.0.1", 0), _handler(proxy))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proxy.url = f"http://127.0.0.1:{server.server_address[1]}"
        yield proxy
    finally:
        server.shutdown()
        server.server_close()


OUTBOUND_OVERRIDES = (
    "EXACTDOCS_HTTP_PROXY",
    "EXACTDOCS_HTTPS_PROXY",
    "EXACTDOCS_NO_PROXY",
    "EXACTDOCS_CA_BUNDLE",
)
"""The ``EXACTDOCS_`` variables that replace the standard ones."""


def clear_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start a test without the outbound settings of the machine it runs on.

    A developer's or CI runner's ``HTTPS_PROXY``, ``NO_PROXY`` or CA bundle must neither help
    nor break a test: the ones it needs, it sets itself.

    Args:
        monkeypatch: The test's monkeypatch, which restores them afterwards.
    """
    for name in (*OUTBOUND_VARIABLES, *OUTBOUND_OVERRIDES):
        monkeypatch.delenv(name, raising=False)
