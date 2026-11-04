"""RUN-03: ExactDocs connects to nothing but 127.0.0.1 and the git server it was pointed at.

The whole loop (import over git/HTTP, REST search, MCP ``search_docs`` and ``query-docs``) runs
under a socket guard that refuses every connection and name lookup except loopback addresses.

What the guard proves, and what it cannot:

- Python sockets in this process (httpx, asyncio, FastMCP, the database drivers, DNS lookups) are
  fully covered; any attempt is refused and recorded, so swallowing the error does not hide it.
- ``git`` runs as a child process, whose sockets the guard cannot see. For git the test pins
  what it *was told*: every process spawned is git or ssh-keygen, every URL on a command line is
  the fixture server, no ssh is started, and the environment keeps ``GIT_ALLOW_PROTOCOL``
  limited to file/http/https/ssh (``ext::``/``fd::``/``git://`` are refused by git itself).
  Redirects to another host are covered by the token tests (``test_private_repositories``);
  submodules and LFS are off in the config we write.
- Not covered: a git or OS-level helper that dials out of its own accord. A network namespace
  would cover that, but needs privileges CI runners do not grant by default.
"""

import asyncio
import json
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastmcp import Client, settings
from fastmcp.client.transports import StreamableHttpTransport
from opentelemetry import trace
from pydantic import SecretStr

from exactdocs.bootstrap.bridges import (
    CatalogLibrarySources,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.ingestion.adapters.driven.git_cli import ALLOWED_PROTOCOLS, GitCli
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.memory import InMemoryCredentialVault
from exactdocs.ingestion.models import Job, JobId, RefKind
from exactdocs.ingestion.use_cases import ImportVersionUseCase
from exactdocs_kernel import SystemClock
from fixture_repo import DocsRepo, git

LIBRARY = "/fixture/docs-repo"
REF = "v1.3.0"
HORSE = "correct horse battery staple"
LOOPBACK = {"127.0.0.1", "::1"}


@pytest.fixture
def attempts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refuse every non-loopback connection or lookup.

    Returns:
        The list the guard appends every refused attempt to.
    """
    refused: list[str] = []

    def host_of(address: Any) -> str | None:  # AF_UNIX addresses are local files: allowed
        return str(address[0]) if isinstance(address, tuple) else None

    def check(what: str, host: Any) -> None:
        if host is not None and host not in LOOPBACK:
            refused.append(f"{what} {host}")
            message = f"outbound {what} to {host} refused by the test's socket guard"
            raise OSError(message)

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        check("connect", host_of(address))
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check("connect", host_of(address))
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        check("lookup", host if isinstance(host, str) else None)
        return real_getaddrinfo(host, *args, **kwargs)

    def refuse_lookup(host: str, *_: Any) -> Any:
        check("lookup", host)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", refuse_lookup)
    monkeypatch.setattr(socket, "gethostbyname_ex", refuse_lookup)
    return refused


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[str, ...], dict[str, str]]]:
    """Record every child process (argv, environment); git's sockets are invisible to the guard.

    The remote URL is not on git's command line (we write it into the work folder's config), so
    the config's ``url`` is recorded as an extra argument ``url=...`` at spawn time.
    """
    seen: list[tuple[tuple[str, ...], dict[str, str]]] = []
    real = asyncio.create_subprocess_exec

    async def spy(*argv: Any, **kwargs: Any) -> Any:
        args = tuple(map(str, argv))
        config = Path(args[args.index("-C") + 1], ".git", "config") if "-C" in args else None
        if config and config.exists():
            args += tuple(
                f"url={json.loads(line.split('=', 1)[1])}"
                for line in config.read_text("utf-8").splitlines()
                if line.strip().startswith("url =")
            )
        seen.append((args, dict(kwargs.get("env") or {})))
        return await real(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    return seen


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield container


def mcp_client(app: Any, token: str) -> Client[StreamableHttpTransport]:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    return Client(
        StreamableHttpTransport(
            "http://localhost/mcp",
            headers={"authorization": f"Bearer {token}"},
            httpx_client_factory=factory,
        )
    )


def test_the_guard_itself_refuses_other_hosts(attempts: list[str]) -> None:
    with pytest.raises(OSError, match="refused"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)  # resolves, then connects
    with pytest.raises(OSError, match="refused"), socket.socket() as raw:
        raw.connect(("93.184.216.34", 80))
    with pytest.raises(OSError, match="refused"):
        socket.getaddrinfo("example.com", 80)
    assert attempts == ["lookup 93.184.216.34", "connect 93.184.216.34", "lookup example.com"]


def test_nothing_that_phones_home_is_on_by_default() -> None:
    assert settings.check_for_updates == "off"  # FastMCP's PyPI update check
    assert Settings().telemetry == "off"
    assert Settings().metrics is False
    # Logfire / the OpenTelemetry SDK are only configured for EXACTDOCS_TELEMETRY=otlp (OPS-01).
    assert "logfire" not in sys.modules
    assert type(trace.get_tracer_provider()).__name__ == "ProxyTracerProvider"  # no SDK set up


async def test_the_whole_loop_touches_nothing_but_loopback_and_the_fixture_git_server(
    container: Container,
    docs_repo: DocsRepo,
    attempts: list[str],
    spawned: list[tuple[tuple[str, ...], dict[str, str]]],
) -> None:
    assert docs_repo.http_url.startswith("http://127.0.0.1:")
    await container.catalog.create_library(
        CreateLibraryCommand(
            id=LIBRARY,
            title="Docs",
            source_url=docs_repo.http_url,
            host=HostKind.GIT,
            default_branch="main",
            include_paths=["docs/"],
        )
    )
    # Import through the real importer and git, over HTTP.
    job = Job.queued(
        job_id=JobId("j"),
        kind="import",  # ty: ignore[invalid-argument-type]
        library=LIBRARY,
        version=REF,
        commit_sha=git("rev-parse", f"{REF}^{{commit}}", cwd=docs_repo.path),
        ref_kind=RefKind.TAG,
        now=SystemClock().now(),
    )
    c = container
    importer = ImportVersionUseCase(
        gateway=GitCli.locate(),
        chunker=MarkdownChunker(),
        sources=CatalogLibrarySources(c.catalog.get_library),
        versions=CatalogVersionPublisher(
            c.catalog.store_manifest,
            c.catalog.activate_manifest,
            c.catalog.discard_pending_manifests,
            c.catalog.apply_readme,
        ),
        index=RetrievalChunkIndex(
            c.retrieval.index_manifest,
            c.retrieval.get_chunk_sets,
            c.retrieval.discard_pending_chunks,
            c.retrieval.remove_chunks,
        ),
        refresh=False,
        vault=InMemoryCredentialVault(),
    )

    class Quiet:
        async def report(self, **_: Any) -> None: ...
        async def problem(self, *_: Any) -> None: ...
        async def chunking(self, **_: Any) -> None: ...

    await importer(job, Quiet())  # ty: ignore[invalid-argument-type]

    app = create_app(container)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            login = await client.post(
                "/api/v1/session", json={"username": "ada", "password": HORSE}
            )
            assert login.status_code == 201
            token = (await client.post("/api/v1/tokens", json={"name": "agent"})).json()["token"]
            rest = await client.get(
                "/api/v1/libraries/fixture/docs-repo/search", params={"q": "token", "ref": REF}
            )
        async with mcp_client(app, token) as mcp:
            search = await mcp.call_tool(
                "search_docs", {"library": LIBRARY, "ref": REF, "query": "token"}
            )
            docs = await mcp.call_tool(
                "query-docs", {"libraryId": f"{LIBRARY}/{REF}", "query": "token"}
            )

    assert rest.status_code == 200
    assert rest.json()["results"]
    assert search.structured_content
    assert search.structured_content["results"]
    assert not docs.is_error
    assert sum(len(block.text) for block in docs.content) > 0

    assert attempts == []  # no Python connection or lookup beyond loopback was even tried

    # git: only what it was told, since its sockets are invisible to the guard.
    assert spawned, "the import must have run git"
    for argv, env in spawned:
        assert Path(argv[0]).name in {"git", "ssh-keygen"}, argv
        assert env["GIT_ALLOW_PROTOCOL"] == ALLOWED_PROTOCOLS or Path(argv[0]).name != "git"
        assert not any(arg.startswith("ssh://") or "@" in arg for arg in argv), argv
        urls = [arg.removeprefix("url=") for arg in argv if "://" in arg]
        assert set(urls) <= {docs_repo.http_url}, urls
    assert any(f"url={docs_repo.http_url}" in argv for argv, _ in spawned), spawned
