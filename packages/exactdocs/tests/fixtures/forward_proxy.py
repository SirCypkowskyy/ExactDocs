"""A forward proxy on 127.0.0.1 for the outbound tests (#538): CONNECT tunnels and plain HTTP.

Hosts are never resolved: ``routes`` maps the names a test uses (``git.example.test:80``) to
the loopback servers that stand for them, so a request that reached such a host can only have
gone through this proxy (``.test`` names resolve nowhere). Every request is recorded, as
``CONNECT host:port`` or ``GET http://host/path``. With ``credentials`` the proxy answers 407
unless the request carries them (``Proxy-Authorization: Basic``); a host it has no route for is
refused with 403, as a corporate proxy's policy would.

Plain HTTP keeps the client's connection open from one request to the next, as a real proxy does
(#589): each request goes to its host on a connection of its own, and the proxy reads the next
one from the client. It closes the client's connection only after an answer whose head says
``Connection: close``: a refusal, an answer its head does not delimit, or one to a client that
asked to close. A client that reuses its connections (httpx, curl) then never sends a request
into a connection the proxy is closing, which failed as "Server disconnected without sending a
response".
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
FORBIDDEN = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
"""The answer for a host the proxy has no route to."""
HOP_BY_HOP = frozenset({"connection", "keep-alive", "proxy-authorization", "proxy-connection"})
"""Headers about one connection, which the proxy does not pass on."""


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


@dataclass(slots=True)
class _Stream:
    """One side of a connection, read head by head: what was read past one is kept for the next."""

    sock: socket.socket
    buffer: bytes = b""

    def _more(self) -> bool:
        with contextlib.suppress(OSError):
            if chunk := self.sock.recv(65536):
                self.buffer += chunk
                return True
        return False

    def until(self, mark: bytes) -> bytes | None:
        """Read up to the end of ``mark``; ``None`` if the peer closed or sent too much first."""
        while mark not in self.buffer:
            if len(self.buffer) >= HEAD_LIMIT or not self._more():
                return None
        found, _, self.buffer = self.buffer.partition(mark)
        return found + mark

    def exactly(self, size: int) -> bytes | None:
        """Read ``size`` bytes; ``None`` if the peer closed first."""
        while len(self.buffer) < size:
            if not self._more():
                return None
        found, self.buffer = self.buffer[:size], self.buffer[size:]
        return found

    def take(self) -> bytes:
        """Everything read and not used yet."""
        found, self.buffer = self.buffer, b""
        return found


@dataclass(frozen=True, slots=True)
class _Request:
    """The head of one request a client sent the proxy."""

    method: str
    target: str
    version: str
    headers: list[tuple[str, str]]

    def header(self, name: str) -> str | None:
        return next((v.strip() for k, v in self.headers if k.lower() == name), None)


def _read_head(client: _Stream) -> _Request | None:
    head = client.until(b"\r\n\r\n")
    if head is None:
        return None
    lines = head.removesuffix(b"\r\n\r\n").decode("latin-1").split("\r\n")
    method, target, version = lines[0].split(" ", 2)
    headers = [(k, v) for k, _, v in (line.partition(":") for line in lines[1:] if ":" in line)]
    return _Request(method, target, version, headers)


def _body(client: _Stream, request: _Request) -> bytes | None:
    """Read a request's body as its head delimits it: ``Content-Length``, chunked, or none.

    Returns:
        The body as the client sent it; ``None`` if the client closed before its end.
    """
    if (request.header("transfer-encoding") or "").lower() != "chunked":
        return client.exactly(int(request.header("content-length") or 0))
    body = b""
    while (line := client.until(b"\r\n")) is not None:
        body += line
        if not (size := int(line.split(b";")[0], 16)):  # the last chunk, then trailers
            while (line := client.until(b"\r\n")) not in {None, b"\r\n"}:
                body += line
            return None if line is None else body + line
        if (chunk := client.exactly(size + 2)) is None:
            return None
        body += chunk
    return None


def _forwarded(request: _Request, origin: str) -> bytes:
    """The request's head as the origin server gets it: origin-form, no proxy headers, closed."""
    kept = [f"{k}:{v}" for k, v in request.headers if k.lower() not in HOP_BY_HOP]
    head = "\r\n".join([f"{request.method} {origin} {request.version}", *kept])
    return f"{head}\r\nConnection: close\r\n\r\n".encode("latin-1")


def _answer(upstream: socket.socket, client: socket.socket, request: _Request) -> bool:
    """Pass the origin's answer on to the client.

    The origin closes after it (``_forwarded`` asks it to), so all it sends is the answer. The
    client's connection stays open when the answer's head delimits it (HTTP/1.1 with
    ``Content-Length``, chunked, or no body) and the client did not ask to close; otherwise the
    head the client gets says ``Connection: close``.

    Returns:
        Whether the client's connection stays open for another request.
    """
    origin = _Stream(upstream)
    head = origin.until(b"\r\n\r\n")
    if head is None:
        return False  # it closed without an answer: so does the proxy
    status, *lines = head.removesuffix(b"\r\n\r\n").decode("latin-1").split("\r\n")
    version, code, *_ = status.split(" ", 2)
    headers = [(k, v.strip()) for k, _, v in (line.partition(":") for line in lines if ":" in line)]
    named = {k.lower(): v.lower() for k, v in headers}
    delimited = (
        request.method == "HEAD"
        or code in {"204", "304"}
        or "content-length" in named
        or named.get("transfer-encoding") == "chunked"
    )
    keep = (
        delimited
        and version == request.version == "HTTP/1.1"
        and (request.header("connection") or "").lower() != "close"
    )
    kept = [f"{k}: {v}" for k, v in headers if k.lower() not in HOP_BY_HOP]
    closing = [] if keep else ["Connection: close"]
    client.sendall("\r\n".join([status, *kept, *closing, "", ""]).encode("latin-1") + origin.take())
    with contextlib.suppress(OSError):
        while chunk := upstream.recv(65536):
            client.sendall(chunk)
    return keep


def _forward(proxy: ForwardProxy, client: _Stream, request: _Request) -> bool:
    """Send one plain HTTP request to its host, on a connection of its own, and pass the answer on.

    Returns:
        Whether the client's connection stays open for another request.
    """
    parts = urlsplit(request.target)
    address = proxy.routes.get(f"{parts.hostname}:{parts.port or 80}".lower())
    if address is None:
        client.sock.sendall(FORBIDDEN)
        return False
    body = _body(client, request)
    if body is None:
        return False
    origin = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    with socket.create_connection(address, timeout=30) as upstream:
        upstream.sendall(_forwarded(request, origin) + body)
        return _answer(upstream, client.sock, request)


def _tunnel(proxy: ForwardProxy, client: _Stream, request: _Request) -> None:
    """Open a CONNECT tunnel to the host and copy bytes both ways until they close."""
    address = proxy.routes.get(request.target.lower())
    if address is None:
        client.sock.sendall(FORBIDDEN)
        return
    with socket.create_connection(address, timeout=30) as upstream:
        client.sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        upstream.sendall(client.take())  # a TLS hello sent with the head
        back = threading.Thread(target=_pipe, args=(upstream, client.sock), daemon=True)
        back.start()
        _pipe(client.sock, upstream)
        back.join(timeout=60)


def _handler(proxy: ForwardProxy) -> type[socketserver.BaseRequestHandler]:
    wanted = (
        None
        if proxy.credentials is None
        else "Basic " + base64.b64encode(proxy.credentials.encode()).decode()
    )

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            client = _Stream(self.request)
            while (request := _read_head(client)) is not None:
                proxy.seen.append(f"{request.method} {request.target}")
                asked = proxy.credentials is not None  # read now: a test may change it
                if asked and request.header("proxy-authorization") != wanted:
                    client.sock.sendall(DENIED)
                    return
                if request.method == "CONNECT":
                    _tunnel(proxy, client, request)
                    return
                if not _forward(proxy, client, request):
                    return

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
