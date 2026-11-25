"""The gate: the only way out of a harness run's network.

A run's container sits on an internal Docker network with no route out (``container``). The gate
listens on that network's gateway address, in this process, and is the run's only way out:

- an HTTPS proxy (``HTTPS_PROXY`` in the container) that tunnels ``CONNECT`` only to the hosts it
  allows (the model provider's) and refuses every other host, recording each one, so a CLI's
  telemetry, update checks or a web tool it was not supposed to have show up in the report;
- forwards: a port per service the run may reach (the arm's MCP server, a stand-in provider), each
  connected to that service on this machine's loopback.

Where this process itself reaches the internet through a proxy (``HTTPS_PROXY`` here), the gate's
tunnels go through it, unless ``NO_PROXY`` names the host.
"""

import asyncio
import base64
import contextlib
import urllib.request
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote, urlsplit

HEAD_LIMIT: Final[int] = 64 * 1024
"""The longest request head the proxy reads."""
HEAD_SECONDS: Final[float] = 30.0
"""How long a client may take to send its request head."""
CONNECT_SECONDS: Final[float] = 30.0
"""How long opening a tunnel or a forward may take."""
CHUNK: Final[int] = 64 * 1024
"""Bytes copied at a time."""
FORBIDDEN: Final[bytes] = (
    b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
)
"""The answer to a host the gate does not allow."""
BAD_GATEWAY: Final[bytes] = (
    b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
)
"""The answer when an allowed host cannot be reached."""
ESTABLISHED: Final[bytes] = b"HTTP/1.1 200 Connection established\r\n\r\n"
"""The answer that opens a tunnel."""


@dataclass(
    slots=True, kw_only=True
)  # conventions: allow-mutable-dataclass -- it counts connections
class GateLog:
    """What went through the gate, and what it refused."""

    allowed: Counter[str] = field(default_factory=Counter)
    """Tunnels opened, by ``host:port``."""
    denied: Counter[str] = field(default_factory=Counter)
    """Requests refused, by ``host:port`` (or the request line of one that was not ``CONNECT``)."""
    forwarded: Counter[str] = field(default_factory=Counter)
    """Connections forwarded, by service."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenGate:
    """A gate that is listening."""

    proxy: str
    """The proxy's URL, as the run reaches it (``http://<gateway>:<port>``)."""
    forwards: Mapping[str, tuple[str, int]]
    """Each service's address as the run reaches it, by name."""
    log: GateLog
    """What went through it."""

    def url(self, name: str, path: str = "") -> str:
        """A forwarded service's URL.

        Args:
            name: The service.
            path: The path on it (``/mcp``).

        Returns:
            ``http://<gateway>:<port><path>``.
        """
        host, port = self.forwards[name]
        return f"http://{host}:{port}{path}"


def upstream_for(host: str) -> tuple[str, int, str | None] | None:
    """The proxy this process reaches a host through, if any.

    Args:
        host: The host.

    Returns:
        The proxy's host, port and ``Proxy-Authorization`` value; ``None`` when the host is
        reached directly (no ``HTTPS_PROXY``, or ``NO_PROXY`` names it).
    """
    proxies = urllib.request.getproxies_environment()
    proxy = proxies.get("https")
    if not proxy or urllib.request.proxy_bypass_environment(host, proxies):
        return None
    parts = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
    auth = None
    if parts.username:
        user = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
        auth = "Basic " + base64.b64encode(user.encode()).decode()
    return parts.hostname or "", parts.port or 80, auth


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy one direction of a connection until it ends.

    Args:
        reader: Where the bytes come from.
        writer: Where they go.
    """
    with contextlib.suppress(ConnectionError, OSError, asyncio.IncompleteReadError):
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
    with contextlib.suppress(ConnectionError, OSError, RuntimeError):
        if writer.can_write_eof():
            writer.write_eof()


async def _join(
    a: tuple[asyncio.StreamReader, asyncio.StreamWriter],
    b: tuple[asyncio.StreamReader, asyncio.StreamWriter],
) -> None:
    """Copy both directions between two connections, then close them.

    Args:
        a: One connection.
        b: The other.
    """
    try:
        await asyncio.gather(_pipe(a[0], b[1]), _pipe(b[0], a[1]))
    finally:
        for _, writer in (a, b):
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()


async def _tunnel(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a connection to an allowed host, through this process's proxy where it has one.

    Args:
        host: The host.
        port: Its port.

    Returns:
        The connection, ready for the client's bytes.

    Raises:
        ConnectionError: The proxy refused the tunnel.
    """
    upstream = upstream_for(host)
    if upstream is None:
        return await asyncio.open_connection(host, port)
    proxy_host, proxy_port, auth = upstream
    reader, writer = await asyncio.open_connection(proxy_host, proxy_port)
    head = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if auth:
        head += f"Proxy-Authorization: {auth}\r\n"
    writer.write((head + "\r\n").encode())
    await writer.drain()
    answer = await reader.readuntil(b"\r\n\r\n")
    status = answer.split(b" ", 2)[1:2]
    if status != [b"200"]:
        writer.close()
        message = f"the proxy refused {host}:{port}: {answer.splitlines()[0]!r}"
        raise ConnectionError(message)
    return reader, writer


def _target(line: str) -> tuple[str, str, int] | None:
    """Read a ``CONNECT`` request line.

    Args:
        line: The request line.

    Returns:
        ``host:port`` as asked, the host (lower case) and the port; ``None`` for another method.
    """
    method, _, rest = line.partition(" ")
    target = rest.partition(" ")[0]
    host, colon, port = target.rpartition(":")
    if method.upper() != "CONNECT" or not colon or not port.isdigit():
        return None
    return target, host.strip("[]").lower(), int(port)


@dataclass(
    slots=True, kw_only=True
)  # conventions: allow-mutable-dataclass -- it tracks connections
class _Gate:
    """The gate's connection handlers."""

    hosts: frozenset[tuple[str, int]]
    """The ``(host, port)`` the proxy tunnels to."""
    log: GateLog = field(default_factory=GateLog)
    """What went through it."""
    active: set[asyncio.StreamWriter] = field(default_factory=set)
    """Every connection still open, closed when the gate closes."""

    async def _refuse(self, writer: asyncio.StreamWriter, answer: bytes) -> None:
        """Answer a proxy client with an error and close the connection.

        Args:
            writer: The client.
            answer: The error response.
        """
        writer.write(answer)
        with contextlib.suppress(ConnectionError, OSError):
            await writer.drain()
        writer.close()

    async def proxy(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one proxy client: tunnel an allowed ``CONNECT``, refuse everything else.

        Args:
            reader: The client's bytes.
            writer: The answer.
        """
        self.active.add(writer)
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_SECONDS)
        except TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError:
            writer.close()
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        target = _target(line)
        if target is None or (target[1], target[2]) not in self.hosts:
            self.log.denied[target[0] if target else line[:200]] += 1
            await self._refuse(writer, FORBIDDEN)
            return
        try:
            remote = await asyncio.wait_for(_tunnel(target[1], target[2]), CONNECT_SECONDS)
        except (TimeoutError, OSError, ConnectionError, asyncio.IncompleteReadError) as error:
            self.log.denied[f"{target[0]} (unreachable: {type(error).__name__})"] += 1
            await self._refuse(writer, BAD_GATEWAY)
            return
        self.log.allowed[target[0]] += 1
        self.active.add(remote[1])
        writer.write(ESTABLISHED)
        await writer.drain()
        await _join((reader, writer), remote)

    def forward(
        self, name: str, to: tuple[str, int]
    ) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
        """Build the callback that forwards one service.

        Args:
            name: The service.
            to: Where it listens.

        Returns:
            The callback.
        """

        async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Connect one client to the service.

            Args:
                reader: The client's bytes.
                writer: The answer.
            """
            self.active.add(writer)
            try:
                remote = await asyncio.wait_for(asyncio.open_connection(*to), CONNECT_SECONDS)
            except TimeoutError, OSError:
                self.log.denied[f"{name} (unreachable)"] += 1
                writer.close()
                return
            self.log.forwarded[name] += 1
            self.active.add(remote[1])
            await _join((reader, writer), remote)

        return serve


@contextlib.asynccontextmanager
async def opened(
    bind: str,
    *,
    allowed: Collection[tuple[str, int]],
    forwards: Mapping[str, tuple[str, int]],
) -> AsyncGenerator[OpenGate]:
    """Open the gate on an address for the block.

    Args:
        bind: The address it listens on (the run network's gateway; loopback for a process run).
        allowed: The ``(host, port)`` the proxy tunnels to; every other one is refused.
        forwards: Each service the run may reach, by name: the ``(host, port)`` it is forwarded to.

    Yields:
        The open gate: the proxy's URL, each forward's address and the log.
    """
    gate = _Gate(hosts=frozenset((h.lower(), p) for h, p in allowed))
    servers = [await asyncio.start_server(gate.proxy, bind, 0, limit=HEAD_LIMIT)]
    addresses: dict[str, tuple[str, int]] = {}
    for name, to in forwards.items():
        server = await asyncio.start_server(gate.forward(name, to), bind, 0)
        servers.append(server)
        addresses[name] = (bind, server.sockets[0].getsockname()[1])
    port = servers[0].sockets[0].getsockname()[1]
    try:
        yield OpenGate(proxy=f"http://{bind}:{port}", forwards=addresses, log=gate.log)
    finally:
        for server in servers:
            server.close()
        for writer in gate.active:  # a tunnel the CLI left open ends with the run
            writer.close()
        for server in servers:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(server.wait_closed(), 5)
