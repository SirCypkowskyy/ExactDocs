"""Each arm's MCP server over HTTP on loopback, for the CLIs to reach through the gate.

The servers are the agent benchmark's (``agent_bench.servers.ArmServers``), as shipped, over HTTP
because a CLI in a container reaches them through the gate's forward:

- ``exactdocs``: ``exactdocs serve`` over the golden corpus imported at the pinned commits (the
  agent benchmark's import), the way a team reaches an instance: MCP over HTTP with an API token
  (an admin and a token are created in the imported data directory; the token goes in the CLI's
  MCP configuration). The server answers the host name the containers use
  (``EXACTDOCS_ALLOWED_HOSTS``).
- ``context7``: the pinned official Context7 MCP server with ``--transport http``. Over HTTP it
  reads the API key from each request, so the CLI's MCP configuration sends ``CONTEXT7_API_KEY``
  as a header, as Context7 documents for its remote server: the key sits in the run's home, where
  the agent could read it, and is scrubbed from what the report keeps.
- ``grounded-docs``: Grounded Docs' read-only MCP server over its index of the pinned versions,
  already HTTP.

Each endpoint says which tools the server lists, which of them the arm gets (``Arm.tools``) and
which it must not (``excluded``, turned off in each CLI's configuration).
"""

import asyncio
import contextlib
import importlib.metadata
import os
import secrets
import socket
import sys
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlsplit

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr

from agent_bench.arms import CONTEXT7, EXACTDOCS, GROUNDED_DOCS, NONE, Arm
from agent_bench.harness import RetrievalConfig, server_environment
from agent_bench.servers import ArmServers, label
from exactdocs.identity.dtos import CreateFirstAdminCommand, CreateTokenCommand
from harness_bench.container import SERVICES_HOST
from retrieval_eval.context7 import API_KEY_VARIABLE
from retrieval_eval.fixture import configured_container

MCP_PATH: Final[str] = "/mcp"
"""The MCP endpoint's path on each server."""
READY_SECONDS: Final[float] = 180.0
"""How long a server may take to answer after it starts."""
SERVER_ERROR: Final[int] = 500
"""The first status that says a server is not ready yet."""
ADMIN: Final[str] = "harness-bench"
"""The admin account created in the imported data directory, and its token's name."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint:
    """An arm's MCP server on loopback."""

    name: str
    """Its name in the CLIs' configuration: the arm's, ``_`` for ``-``."""
    address: tuple[str, int]
    """Where it listens (loopback)."""
    path: str = MCP_PATH
    """Its MCP path."""
    headers: Mapping[str, str] = field(default_factory=dict)
    """What every request carries (ExactDocs' API token, Context7's key)."""
    tools: tuple[str, ...] = ()
    """The tools the arm gets."""
    excluded: tuple[str, ...] = ()
    """The tools the server lists that the arm must not get."""


class ArmEndpoints(Protocol):
    """Serves each arm's MCP server for the time of a block."""

    @property
    def described(self) -> dict[str, dict[str, str]]:
        """What ran for each setup: the server, its release, the tools the agent got."""
        ...

    def endpoint(
        self, arm: Arm, config: RetrievalConfig | None
    ) -> AbstractAsyncContextManager[Endpoint | None]:
        """Serve an arm's server for the block.

        Args:
            arm: The arm.
            config: Its configuration (``exactdocs``, ``grounded-docs``).

        Returns:
            The endpoint's context; ``None`` for ``none``.
        """
        ...


def free_port() -> int:
    """Find a free port on loopback.

    Returns:
        The port.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def listed_tools(url: str, headers: Mapping[str, str]) -> list[str]:
    """List the tools an MCP server over HTTP offers.

    Args:
        url: Its MCP endpoint.
        headers: What every request carries.

    Returns:
        The tools' names, sorted.
    """
    async with Client(StreamableHttpTransport(url, headers=dict(headers))) as client:
        return sorted(t.name for t in await client.list_tools())


async def wait_ready(url: str, process: asyncio.subprocess.Process | None = None) -> None:
    """Wait until a server answers a URL.

    Args:
        url: A URL it answers once it is up (its health check).
        process: The server's process: stop waiting when it ends.

    Raises:
        RuntimeError: It ended, or did not answer within ``READY_SECONDS``.
    """
    deadline = asyncio.get_running_loop().time() + READY_SECONDS
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process is not None and process.returncode is not None:
                message = f"the server at {url} ended with status {process.returncode}"
                raise RuntimeError(message)
            with contextlib.suppress(httpx.HTTPError):
                if (await client.get(url)).status_code < SERVER_ERROR:
                    return
            await asyncio.sleep(0.5)
    message = f"the server at {url} did not answer within {READY_SECONDS:.0f} s"
    raise RuntimeError(message)


async def api_token(data_dir: Path, env: Mapping[str, str]) -> str:
    """Create an admin and an API token in an imported data directory.

    Args:
        data_dir: The data directory (no account in it yet).
        env: The configuration's settings, as the server runs with them.

    Returns:
        The token.
    """
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        container = configured_container(data_dir)
        async with container.running(jobs=False):
            admin = await container.identity.create_first_admin(
                CreateFirstAdminCommand(
                    username=ADMIN, password=SecretStr(secrets.token_urlsafe(24))
                )
            )
            grant = await container.identity.create_token(admin, CreateTokenCommand(name=ADMIN))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return grant.token


@contextlib.asynccontextmanager
async def _process(
    argv: list[str], env: Mapping[str, str], log: Path
) -> AsyncGenerator[asyncio.subprocess.Process]:
    """Run a server process for the block, its output in a log.

    Args:
        argv: Its command line.
        env: Its environment.
        log: Where its output goes.

    Yields:
        The process; it is stopped after the block.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        process = await asyncio.create_subprocess_exec(
            *argv, env=dict(env), stdout=out, stderr=out, stdin=asyncio.subprocess.DEVNULL
        )
        try:
            yield process
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 20)
                except TimeoutError:
                    process.kill()
                    await process.wait()


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- tokens are cached
class HttpArmServers:
    """The agent benchmark's arm servers, served over HTTP on loopback."""

    servers: ArmServers
    """The servers (imports, installs, indexes) of the agent benchmark."""
    tokens: dict[Path, str] = field(default_factory=dict)
    """The API token created in each imported data directory."""

    @property
    def described(self) -> dict[str, dict[str, str]]:
        """What ran for each setup.

        Returns:
            By setup label: the server, its release, its configuration, the tools the agent got.
        """
        return self.servers.described

    @contextlib.asynccontextmanager
    async def endpoint(
        self, arm: Arm, config: RetrievalConfig | None
    ) -> AsyncGenerator[Endpoint | None]:
        """Serve an arm's server for the block.

        Args:
            arm: The arm.
            config: Its configuration.

        Yields:
            The endpoint; ``None`` for ``none``.

        Raises:
            ValueError: ``exactdocs`` or ``grounded-docs`` without a configuration.
        """
        if arm.name == NONE:
            yield None
            return
        async with contextlib.AsyncExitStack() as stack:
            if arm.name == EXACTDOCS and config is not None:
                address, headers, about = await self._exactdocs(stack, config)
            elif arm.name == CONTEXT7:
                address, headers, about = await self._context7(stack)
            elif arm.name == GROUNDED_DOCS and config is not None:
                url, _, about = await self.servers.grounded_docs_served(stack, config)
                parts = urlsplit(url)
                address, headers = (parts.hostname or "127.0.0.1", parts.port or 80), {}
            else:
                message = f"the {arm.name} arm needs a configuration"
                raise ValueError(message)
            listed = await listed_tools(f"http://{address[0]}:{address[1]}{MCP_PATH}", headers)
            offered = tuple(n for n in listed if arm.tools is None or n in arm.tools)
            self.servers.described[label(arm, config)] = {**about, "tools": ", ".join(offered)}
            yield Endpoint(
                name=arm.name.replace("-", "_"),
                address=address,
                headers=headers,
                tools=offered,
                excluded=tuple(n for n in listed if n not in offered),
            )

    async def _exactdocs(
        self, stack: contextlib.AsyncExitStack, config: RetrievalConfig
    ) -> tuple[tuple[str, int], dict[str, str], dict[str, str]]:
        """Import the corpus (once per embedding model) and serve ExactDocs over HTTP.

        Args:
            stack: Holds the server for the block.
            config: The retrieval configuration.

        Returns:
            Its address, the headers (its API token) and what it is.
        """
        data_dir = await self.servers.imported(config)
        if data_dir not in self.tokens:
            self.tokens[data_dir] = await api_token(data_dir, config.env)
        port = free_port()
        env = server_environment(config.env, data_dir) | {"EXACTDOCS_ALLOWED_HOSTS": SERVICES_HOST}
        command = Path(sys.executable).with_name("exactdocs")
        process = await stack.enter_async_context(
            _process(
                [str(command), "serve", "--host", "127.0.0.1", "--port", str(port)],
                env,
                self.servers.work_dir / f"server-{config.name}-http.log",
            )
        )
        await wait_ready(f"http://127.0.0.1:{port}/api/health", process)
        about = {
            "server": "exactdocs serve (HTTP, an API token)",
            "version": importlib.metadata.version("exactdocs"),
        }
        headers = {"Authorization": f"Bearer {self.tokens[data_dir]}"}
        return ("127.0.0.1", port), headers, about

    async def _context7(
        self, stack: contextlib.AsyncExitStack
    ) -> tuple[tuple[str, int], dict[str, str], dict[str, str]]:
        """Install the pinned Context7 MCP server (once) and serve it over HTTP.

        Args:
            stack: Holds the server for the block.

        Returns:
            Its address, the headers (the API key, as Context7 reads it over HTTP) and what it is.
        """
        node, entry, key, about = self.servers.context7_installed()
        port = free_port()
        env = {n: v for n, v in os.environ.items() if n != API_KEY_VARIABLE}
        env["OTEL_SDK_DISABLED"] = "true"
        process = await stack.enter_async_context(
            _process(
                [str(node), str(entry), "--transport", "http", "--port", str(port)],
                env,
                self.servers.work_dir / "server-context7-http.log",
            )
        )
        await wait_ready(f"http://127.0.0.1:{port}/ping", process)
        about = {**about, "server": f"{about['server']} (HTTP, the key as a header)"}
        return ("127.0.0.1", port), {API_KEY_VARIABLE: key}, about
