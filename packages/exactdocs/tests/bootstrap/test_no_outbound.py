# ruff: file-ignore[suspicious-subprocess-import, subprocess-without-shell-equals-true, start-process-with-partial-path, pytest-fixture-autouse, complex-structure]
"""RUN-03: ExactDocs connects to nothing but loopback and the git server it was pointed at.

The whole loop (import over git/HTTP, REST search, MCP ``search_docs`` and ``query-docs``) runs
under a socket guard that refuses every connection, datagram and name lookup except loopback.

What is *observed* and what is only *pinned*:

- Observed, Python: every socket the Python process opens (httpx, asyncio, FastMCP, DB drivers)
  and every name lookup goes through the guard, which refuses and records anything but loopback,
  also from a thread after the test body ended (the fixture checks again at teardown). REST and
  MCP run over ``ASGITransport``, so they open no socket at all.
- Observed, git (where ``unshare -rn`` works): ``test_in_a_network_namespace_...`` re-runs the
  loop, and a redirect to another host, inside a fresh network namespace whose only interface is
  loopback. The kernel then refuses everything else, whatever git, ssh or a helper tries. It is
  skipped where unprivileged user namespaces are unavailable.
- Pinned, git (everywhere else): git is a child process, so the guard cannot see its sockets.
  The test records every process the product starts (``subprocess.Popen``, ``os.posix_spawn``,
  ``os.system``) and asserts what git was *told*: only git/ssh-keygen run, no ssh URL, the only
  URL is the fixture server, ``GIT_ALLOW_PROTOCOL`` is the restricted set, no proxy variable.
- git follows an HTTP redirect on its first request (``http.followRedirects=initial``) and honours
  proxy variables when they are set; the test clears the latter. See ``git_cli.py``.
- ``localhost`` and ``::ffff:127.0.0.1`` are refused on purpose (fail closed): use 127.0.0.1.
- Dependency audit: fastmcp and mcp only emit OpenTelemetry spans through ``opentelemetry-api``
  (no SDK, so nothing is exported); neither they nor uvicorn or pydantic call an analytics or
  error-reporting endpoint; the one PyPI call, FastMCP's update check, is forced off.
"""

import asyncio
import fcntl
import http.server
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client, settings
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr

from app_lifespan import serving
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
from exactdocs.ingestion.errors import RepositoryUnreachableError
from exactdocs.ingestion.models import Job, JobId, RefKind, RepositoryUrl
from exactdocs.ingestion.use_cases import ImportVersionUseCase
from exactdocs_kernel import SystemClock
from fixture_repo import DocsRepo, git

LIBRARY = "/fixture/docs-repo"
REF = "v1.3.0"
HORSE = "correct horse battery staple"
LOOPBACK = {"127.0.0.1", "::1"}
PROXY_VARIABLES = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
IN_NETNS = "EXACTDOCS_IN_NETNS"  # set for the re-run inside the network namespace
NOWHERE = "203.0.113.9"  # TEST-NET-3 (RFC 5737): documentation addresses, never routed
IN_NAMESPACE_TESTS = (
    "test_the_whole_loop_touches_nothing_but_loopback_and_the_fixture_git_server",
    "test_a_redirect_to_another_host_leads_nowhere",
)


@pytest.fixture(autouse=True)
def loopback_up() -> None:
    """Inside the namespace the loopback interface starts down: bring it up (SIOCSIFFLAGS)."""
    if os.environ.get(IN_NETNS):
        iff_up = 1
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
            fcntl.ioctl(control, 0x8914, struct.pack("16sH14x", b"lo", iff_up))


@pytest.fixture(autouse=True)
def no_proxy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """git honours proxy variables (so traffic would go to the proxy): the test starts without."""
    for name in os.environ:
        if name.lower() in PROXY_VARIABLES:
            monkeypatch.delenv(name)


@pytest.fixture
def attempts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Refuse every non-loopback connection, datagram or lookup.

    Yields:
        The list the guard appends every refused attempt to; it must still be empty at teardown.
    """
    refused: list[str] = []

    def check(what: str, host: Any) -> None:
        if host is not None and host not in LOOPBACK:
            refused.append(f"{what} {host}")
            message = f"outbound {what} to {host} refused by the test's socket guard"
            raise OSError(message)

    def check_address(sock: socket.socket, what: str, address: Any) -> None:
        if address is None or sock.family == socket.AF_UNIX:  # unix sockets are local files
            return
        # Anything but a (host, port, ...) tuple is an address shape we cannot judge: refuse.
        check(what, address[0] if isinstance(address, tuple) else repr(address))

    real = {
        name: getattr(socket.socket, name)
        for name in ("connect", "connect_ex", "sendto", "sendmsg")
    }
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        check_address(self, "connect", address)
        return real["connect"](self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check_address(self, "connect", address)
        return real["connect_ex"](self, address)

    def sendto(self: socket.socket, data: Any, *rest: Any) -> int:  # (data[, flags], address)
        check_address(self, "send", rest[-1])
        return real["sendto"](self, data, *rest)

    def sendmsg(self: socket.socket, buffers: Any, *rest: Any) -> int:  # (.., flags, address)
        check_address(self, "send", rest[2] if len(rest) > 2 else None)
        return real["sendmsg"](self, buffers, *rest)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        check("lookup", host if isinstance(host, str) else None)
        return real_getaddrinfo(host, *args, **kwargs)

    def refuse_lookup(host: str, *_: Any) -> Any:
        check("lookup", host)

    for name, replacement in (
        ("connect", connect), ("connect_ex", connect_ex), ("sendto", sendto), ("sendmsg", sendmsg),
    ):  # fmt: skip
        monkeypatch.setattr(socket.socket, name, replacement)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", refuse_lookup)
    monkeypatch.setattr(socket, "gethostbyname_ex", refuse_lookup)
    yield refused
    assert refused == [], "something tried to leave loopback after the test body (task or thread)"


@dataclass(frozen=True, slots=True)
class Spawn:
    argv: tuple[str, ...]
    env: dict[str, str]
    config: str  # the work folder's .git/config at spawn time ("" when there is none)


@pytest.fixture
def commit(docs_repo: DocsRepo) -> str:
    """Resolved before ``spawned`` starts recording (this uses git itself)."""
    return git("rev-parse", f"{REF}^{{commit}}", cwd=docs_repo.path)


@pytest.fixture
def spawned(commit: str, monkeypatch: pytest.MonkeyPatch) -> list[Spawn]:
    """Record every child process the product starts, whichever way it does it.

    The fixture server's own ``git http-backend`` (a stand-in for the remote) is left out. The
    remote URL is not on git's command line (it is written into the work folder's config), so
    that config is kept with each spawn.

    Returns:
        The list every spawn is appended to.
    """
    del commit  # only the order matters: it is resolved before the recording starts
    seen: list[Spawn] = []

    def record(args: Any, env: Any = None, *, cwd_args: Any = None) -> None:
        argv = tuple(map(str, [args] if isinstance(args, str | bytes | os.PathLike) else args))
        if "http-backend" in argv:
            return
        folder = argv[argv.index("-C") + 1] if "-C" in argv else cwd_args
        config = Path(folder, ".git", "config") if folder else None
        text = config.read_text("utf-8") if config and config.exists() else ""
        seen.append(Spawn(argv, dict(os.environ if env is None else env), text))

    real_init = subprocess.Popen.__init__

    def init(self: subprocess.Popen[Any], args: Any, *a: Any, **kw: Any) -> None:
        record(args, kw.get("env"))
        real_init(self, args, *a, **kw)

    monkeypatch.setattr(subprocess.Popen, "__init__", init)
    for name in ("posix_spawn", "posix_spawnp"):
        real_spawn = getattr(os, name)

        def spawn(
            path: Any,
            argv: Any,
            env: Any,
            *a: Any,
            _real: Callable[..., int] = real_spawn,
            **kw: Any,
        ) -> int:
            record(argv, env)
            return _real(path, argv, env, *a, **kw)

        monkeypatch.setattr(os, name, spawn)
    real_system = os.system

    def system(command: str) -> int:
        record(command)
        return real_system(command)

    monkeypatch.setattr(os, "system", system)
    return seen


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def app(container: Container) -> AsyncIterator[FastAPI]:
    """The app, running: its lifespan is the container's one run (#203).

    Yields:
        The running app, with its first admin.
    """
    async with serving(create_app(container)) as app:
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield app


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


# ----------------------------------------------------------------- the guard itself


async def sock_connect(address: tuple[str, int]) -> None:
    with socket.socket(socket.AF_INET) as raw:
        raw.setblocking(False)
        await asyncio.get_running_loop().sock_connect(raw, address)


def send_over_loopback(family: socket.AddressFamily, host: str) -> None:
    with (
        socket.socket(family, socket.SOCK_DGRAM) as sink,
        socket.socket(family, socket.SOCK_DGRAM) as sender,
    ):
        sink.bind((host, 0))
        sender.sendto(b"x", sink.getsockname())
        sender.sendmsg([b"x"], [], 0, sink.getsockname())
        assert sender.connect_ex(sink.getsockname()) == 0


async def test_the_guard_refuses_every_way_out_and_allows_loopback(attempts: list[str]) -> None:
    other = (NOWHERE, 80)
    loop = asyncio.get_running_loop()

    def with_socket(
        call: Callable[[socket.socket], object], kind: int = socket.SOCK_STREAM
    ) -> None:
        with socket.socket(socket.AF_INET, kind) as sock:
            call(sock)

    refused: dict[str, Callable[[], Any]] = {
        "connect": lambda: with_socket(lambda s: s.connect(other)),
        "connect_ex": lambda: with_socket(lambda s: s.connect_ex(other)),
        "sendto": lambda: with_socket(lambda s: s.sendto(b"x", other), socket.SOCK_DGRAM),
        "sendto flags": lambda: with_socket(lambda s: s.sendto(b"x", 0, other), socket.SOCK_DGRAM),
        "sendmsg": lambda: with_socket(
            lambda s: s.sendmsg([b"x"], [], 0, other), socket.SOCK_DGRAM
        ),
        "an address of unknown shape": lambda: with_socket(lambda s: s.connect("example.com")),
        "getaddrinfo": lambda: socket.getaddrinfo("example.com", 80),
        "gethostbyname": lambda: socket.gethostbyname("example.com"),
        "gethostbyname_ex": lambda: socket.gethostbyname_ex("example.com"),
        "create_connection": lambda: socket.create_connection(other, timeout=1),
        "localhost is a name": lambda: socket.getaddrinfo("localhost", 80),
    }
    for what, call in refused.items():
        with pytest.raises(OSError, match="refused"):
            call()
        assert attempts, what
        attempts.clear()
    with pytest.raises(OSError, match="refused"):
        await sock_connect(other)
    with pytest.raises(OSError, match="refused"):
        await loop.create_connection(asyncio.Protocol, *other)
    assert len(attempts) >= 2
    attempts.clear()

    # Loopback and local files are fine, in every form.
    send_over_loopback(socket.AF_INET, "127.0.0.1")
    try:
        send_over_loopback(socket.AF_INET6, "::1")
    except OSError as problem:
        pytest.skip(f"no IPv6 loopback here: {problem}")
    assert socket.getaddrinfo("127.0.0.1", 80)
    socketpair_left, socketpair_right = socket.socketpair()  # AF_UNIX
    socketpair_left.close()
    socketpair_right.close()
    assert attempts == []


def test_nothing_that_phones_home_is_on_by_default() -> None:
    assert settings.check_for_updates == "off"  # FastMCP's PyPI update check
    assert Settings().telemetry == "off"
    assert Settings().metrics is False


@pytest.mark.parametrize("inherited", [None, "stable"])
def test_a_fresh_process_has_no_update_check_and_no_telemetry_sdk(inherited: str | None) -> None:
    """In its own process, so other tests (or OPS-01's) importing logfire cannot change the answer.

    The update check stays off even when the environment asks for it.
    """
    code = (
        "import sys\n"
        "import exactdocs.bootstrap.cli, exactdocs.bootstrap.http, exactdocs.bootstrap.mcp\n"
        "from fastmcp import settings\n"
        "from opentelemetry import trace\n"
        "assert settings.check_for_updates == 'off', settings.check_for_updates\n"
        "assert 'logfire' not in sys.modules\n"
        "assert type(trace.get_tracer_provider()).__name__ == 'ProxyTracerProvider'\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "FASTMCP_CHECK_FOR_UPDATES"}
    if inherited:
        env["FASTMCP_CHECK_FOR_UPDATES"] = inherited
    run = subprocess.run(
        [sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr


# ----------------------------------------------------------------- the whole loop


async def test_the_whole_loop_touches_nothing_but_loopback_and_the_fixture_git_server(
    container: Container,
    docs_repo: DocsRepo,
    commit: str,
    attempts: list[str],
    spawned: list[Spawn],
    app: FastAPI,  # after the watches: the app starts under them
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
        commit_sha=commit,
        ref_kind=RefKind.TAG,
        now=SystemClock().now(),
    )
    c = container
    importer = ImportVersionUseCase(
        gateway=GitCli.locate(),
        chunker=MarkdownChunker(),
        sources=CatalogLibrarySources(
            get_library=c.catalog.get_library, list_renames=c.catalog.list_renames
        ),
        versions=CatalogVersionPublisher(
            store_manifest=c.catalog.store_manifest,
            activate_manifest=c.catalog.activate_manifest,
            discard_pending_manifests=c.catalog.discard_pending_manifests,
            apply_readme=c.catalog.apply_readme,
            apply_manual_tags_to=c.catalog.apply_manual_tags,
            replace_renames_of=c.catalog.replace_renames,
        ),
        index=RetrievalChunkIndex(
            index_manifest=c.retrieval.index_manifest,
            get_chunk_sets=c.retrieval.get_chunk_sets,
            discard_pending_chunks=c.retrieval.discard_pending_chunks,
            remove_chunks=c.retrieval.remove_chunks,
            retag_articles=c.retrieval.retag_articles,
        ),
        refresh=False,
        vault=InMemoryCredentialVault(),
    )

    class Quiet:
        async def report(self, **_: Any) -> None: ...
        async def problem(self, *_: Any) -> None: ...
        async def chunking(self, **_: Any) -> None: ...

        async def parsing(self, **_: Any) -> None: ...

    await importer(job, Quiet())  # ty: ignore[invalid-argument-type]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        login = await client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
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

    assert attempts == []  # no Python connection, datagram or lookup beyond loopback was tried
    assert_git_was_only_told_about(docs_repo.http_url, spawned)


def assert_git_was_only_told_about(url: str, spawned: list[Spawn]) -> None:
    """The pinned half: git's own sockets are invisible here, so check what it was given."""
    assert spawned, "the import must have run git"
    scp_like = re.compile(r"^[\w.-]+@[\w.-]+:")
    for spawn in spawned:
        tool = Path(spawn.argv[0]).name
        assert tool in {"git", "ssh-keygen"}, spawn.argv  # a new way of spawning fails here
        if tool == "git":
            assert spawn.env["GIT_ALLOW_PROTOCOL"] == ALLOWED_PROTOCOLS
            assert not PROXY_VARIABLES & {name.lower() for name in spawn.env}
        assert not any(a.startswith("ssh://") or scp_like.match(a) for a in spawn.argv), spawn.argv
        urls = {
            *(a for a in spawn.argv if "://" in a),
            *re.findall(r"[a-z+]+://[^\s\"]+", spawn.config),
        }
        assert urls <= {url}, urls
    assert any(url in spawn.config for spawn in spawned), "git was never pointed at the fixture"


# --------------------------------------------- the kernel's view: a network namespace


def _can_unshare_a_network() -> bool:
    unshare = shutil.which("unshare")
    return (
        unshare is not None
        and subprocess.run([unshare, "-rn", "true"], capture_output=True, check=False).returncode
        == 0
    )


@pytest.fixture
def redirect_to_nowhere() -> Iterator[str]:
    """A loopback server that answers every request with a redirect to a non-loopback address.

    Yields:
        Its URL, shaped like the fixture repository's.
    """

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://{NOWHERE}:81{self.path}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            """Stay quiet."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/fixture/docs-repo.git"
    server.shutdown()
    server.server_close()


@pytest.mark.skipif(not os.environ.get(IN_NETNS), reason="runs inside the network namespace")
async def test_a_redirect_to_another_host_leads_nowhere(redirect_to_nowhere: str) -> None:
    """git follows the redirect (its default); the kernel has no route, so it fails, quickly."""
    with pytest.raises(RepositoryUnreachableError):
        await GitCli.locate().list_refs(RepositoryUrl.parse(redirect_to_nowhere))


@pytest.mark.skipif(bool(os.environ.get(IN_NETNS)), reason="this is the re-run itself")
@pytest.mark.skipif(not _can_unshare_a_network(), reason="no unprivileged user/net namespaces")
def test_in_a_network_namespace_git_has_no_way_out() -> None:
    """Re-run the loop and the redirect where loopback is the only interface (observed, by the
    kernel): they pass only if nothing needed a connection to anywhere else.
    """
    tests = [f"{__file__}::{name}" for name in IN_NAMESPACE_TESTS]
    run = subprocess.run(
        [
            "unshare", "-rn", sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--no-header", *tests,
        ],
        env={**os.environ, IN_NETNS: "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    assert "2 passed" in run.stdout, run.stdout[-1000:]
