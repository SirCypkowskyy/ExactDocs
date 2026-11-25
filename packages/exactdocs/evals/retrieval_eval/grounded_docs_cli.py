"""``just grounded-bench``: Grounded Docs on the golden set, next to ExactDocs (#492).

For each configuration (``grounded_docs.CONFIGURATIONS``), a pinned Grounded Docs release, installed
from npm into a cache directory and checked against its registry integrity hash, indexes every
pinned version of the golden corpus into a data directory of its own: the files the ExactDocs
importer takes at the pinned commit are written to a folder, byte for byte, and its ``scrape``
command indexes that folder (``file://``) as the project's library at the version's name. Then its
MCP server answers every golden question through ``search_docs`` with the case's library and
version and ``TOP_K`` results, and the text scorer scores the results. ExactDocs' BM25 at
``default`` answers the same questions in the same run, scored the same way, and every
configuration is tested against it, case by case.

Grounded Docs runs with its documented defaults: its own configuration file is written with
telemetry off and the corpus folder as the one root it may read, and nothing else. The crawl's
depth and page limits are raised only where a version's folder is deeper or larger than they
allow, so that every article is offered. The vector configuration's embedding model is served by
``openai_embeddings`` (the model ExactDocs pulled) at ``OPENAI_API_BASE``. CI never runs this:
the quick tests replay recorded responses. See docs/evals.md#grounded-docs.
"""

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final, Protocol
from urllib.parse import unquote

from fastmcp import Client

from exactdocs.bootstrap.settings import Settings
from retrieval_eval.dataset import RetrievalDataset, fingerprint
from retrieval_eval.fixture import model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    PinnedVersion,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import import_corpus, selected
from retrieval_eval.grounded_docs import (
    CONFIGURATIONS,
    INTEGRITY,
    PACKAGE,
    RECORDED,
    RECORDED_CHUNKING,
    SEARCH_TOOL,
    TEXT_BASELINE,
    TOP_K,
    VERSION,
    Baseline,
    Configuration,
    Embedded,
    EmbeddingInfo,
    GroundedDocsReport,
    Recorded,
    RunResult,
    VersionIndex,
    cases_not_indexed,
    markdown,
    paired,
    problems,
    split_results,
    tokens_interval,
)
from retrieval_eval.ingestion_cli import CONFIGURATIONS as CHUNKINGS
from retrieval_eval.ingestion_cli import article_files
from retrieval_eval.openai_embeddings import Endpoint, LocalEmbedding, Served, load_local, serve
from retrieval_eval.retrieval_bench import RetrievalBenchReport
from retrieval_eval.retrieval_bench_cli import environment
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.text_bench import TextAnswer, TextResult, TextRow, scorer_settings, text_row
from retrieval_eval.text_bench_cli import bm25_results
from retrieval_eval.text_match import SectionIndex

REPORT_DIR: Final[Path] = Path("reports/evals")
"""Where ``grounded-docs.json`` and ``grounded-docs.md`` are written, by default."""
RESULTS_DIR: Final[Path] = Path(__file__).parents[1] / "results"
"""The recorded runs in the repository (``retrieval.json`` is read from it)."""
REPORT_NAME: Final[str] = "grounded-docs"
"""The report's file name, without the extension."""
STORE_MARKER: Final[str] = "exactdocs-bench.json"
"""Written in a data directory after each version is indexed: what ``--resume`` skips."""
DUMMY_KEY: Final[str] = "local"
"""``OPENAI_API_KEY`` for the local endpoint, which checks none: Grounded Docs needs one set."""
SERVED_BY: Final[str] = (
    "retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched)"
)
"""What serves the embedding model, as the report names it."""
REQUEST_TIMEOUT_MS: Final[int] = 300_000
"""``embeddings.requestTimeoutMs``, the one setting changed from its default (30,000): the local
endpoint embeds on the CPU, one request at a time, and Grounded Docs sends several at once, so a
request can wait longer than 30 seconds for its answer; the client then gives up and sends it
again. It sets how long Grounded Docs waits for an embedding, nothing it indexes or ranks."""
START_SECONDS: Final[float] = 120.0
"""How long the MCP server may take to answer its first request."""
SEARCH_SECONDS: Final[float] = 120.0
"""How long one question may take."""
_PROVIDER_PREFIXES: Final[tuple[str, ...]] = (
    "OPENAI_",
    "AZURE_OPENAI_",
    "GOOGLE_",
    "AWS_",
    "BEDROCK_",
    "DOCS_MCP_",
)
"""Variables a run does not inherit: provider credentials and Grounded Docs' own settings."""
_ALWAYS: Final[dict[str, str]] = {"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}
"""Set for every command: no browser download (local files need none)."""


def home_dir() -> Path:
    """Where Grounded Docs is installed and its data directories kept, by default.

    Returns:
        ``<the golden cache's parent>/grounded-docs`` (``~/.cache/exactdocs/grounded-docs``).
    """
    return default_cache_dir().parent / "grounded-docs"


@dataclass(frozen=True, slots=True, kw_only=True)
class Stored:
    """What a data directory holds for one library version."""

    pages: frozenset[str]
    """The URLs of its pages."""
    chunks: int
    """Its chunks."""
    embedded: int
    """Its chunks with a vector."""


type Search = Callable[[str, str, str], Awaitable[str]]
"""Ask one question: ``(library, version, query)`` to the tool's response text."""


class GroundedDocs(Protocol):
    """A Grounded Docs installation (``NodeGroundedDocs``; tests replay recorded responses)."""

    def describe(self) -> dict[str, str]:
        """Name what runs.

        Returns:
            ``node`` and anything else the report records about the tool.
        """
        ...

    async def settings(self, store: Path, variables: Mapping[str, str]) -> dict[str, Any]:
        """Read the configuration in effect.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Returns:
            The settings, as ``docs-mcp-server config`` prints them.
        """
        ...

    async def index(
        self,
        store: Path,
        variables: Mapping[str, str],
        version: tuple[str, str],
        folder: Path,
        limits: tuple[int, int],
    ) -> None:
        """Index a folder as a library version.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.
            version: The library and version names.
            folder: The folder.
            limits: The crawl's maximum depth and pages.
        """
        ...

    def stored(self, store: Path) -> dict[tuple[str, str], Stored]:
        """Read what a data directory holds.

        Args:
            store: The data directory.

        Returns:
            Each ``(library, version)``'s pages and chunks.
        """
        ...

    def serving(
        self, store: Path, variables: Mapping[str, str]
    ) -> contextlib.AbstractAsyncContextManager[Search]:
        """Run the MCP server on a data directory.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Returns:
            A context that yields the search while the server runs.
        """
        ...


def _clean_environment(variables: Mapping[str, str]) -> dict[str, str]:
    """The environment of a Grounded Docs command: this one's, without provider variables.

    Args:
        variables: What the configuration sets.

    Returns:
        The environment.
    """
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(_PROVIDER_PREFIXES)}
    return inherited | _ALWAYS | dict(variables)


def _free_port() -> int:
    """Pick a free loopback port.

    Returns:
        The port.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeGroundedDocs:
    """Grounded Docs from npm, run with Node.js."""

    node: Path
    """The ``node`` executable."""
    entry: Path
    """The package's ``dist/index.js``."""
    config: Path
    """Its configuration file (``--config``: read, never written)."""

    def describe(self) -> dict[str, str]:
        """Name what runs.

        Returns:
            ``node``: the Node.js version.
        """
        return {"node": _node_version(self.node)}

    async def _run(
        self, args: Sequence[str], variables: Mapping[str, str], store: Path
    ) -> tuple[int, str, str]:
        """Run one command to its end.

        Args:
            args: The command and its arguments.
            variables: The configuration's environment variables.
            store: The data directory.

        Returns:
            The exit code, the standard output and the standard error.
        """
        process = await asyncio.create_subprocess_exec(
            self.node,
            self.entry,
            *args,
            "--store-path",
            store,
            "--config",
            self.config,
            env=_clean_environment(variables),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        return (
            process.returncode or 0,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def settings(self, store: Path, variables: Mapping[str, str]) -> dict[str, Any]:
        """Read the configuration in effect.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Returns:
            The settings, as ``docs-mcp-server config`` prints them.

        Raises:
            RuntimeError: The command failed.
        """
        code, out, err = await self._run(["config", "--output", "json"], variables, store)
        if code:
            message = f"docs-mcp-server config failed ({code}): {err.strip()[-2000:]}"
            raise RuntimeError(message)
        return json.loads(out)

    async def index(
        self,
        store: Path,
        variables: Mapping[str, str],
        version: tuple[str, str],
        folder: Path,
        limits: tuple[int, int],
    ) -> None:
        """Index a folder as a library version with ``scrape``.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.
            version: The library and version names.
            folder: The folder.
            limits: The crawl's maximum depth and pages.

        Raises:
            RuntimeError: The command failed.
        """
        library, name = version
        depth, pages = limits
        code, out, err = await self._run(
            [
                "scrape",
                library,
                folder.as_uri(),
                "--version",
                name,
                "--max-depth",
                str(depth),
                "--max-pages",
                str(pages),
                "--replace",
            ],
            variables,
            store,
        )
        if code:
            message = f"scrape {library} {name} failed ({code}): {(out + err).strip()[-2000:]}"
            raise RuntimeError(message)

    def stored(self, store: Path) -> dict[tuple[str, str], Stored]:
        """Read what a data directory holds, from its SQLite database (Grounded Docs' schema).

        Args:
            store: The data directory.

        Returns:
            Each ``(library, version)``'s pages and chunks; empty without a database.
        """
        return read_store(store)

    @contextlib.asynccontextmanager
    async def serving(self, store: Path, variables: Mapping[str, str]) -> AsyncGenerator[Search]:
        """Run ``docs-mcp-server mcp`` over HTTP on a free loopback port.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.

        Yields:
            The search, through its ``search_docs`` tool.
        """
        with tempfile.TemporaryFile() as log:
            process = await self._start(store, variables, log)
            try:
                client = await _connect(
                    f"http://127.0.0.1:{process.port}/mcp", process.process, log
                )
                async with client:
                    yield _searcher(client)
            finally:
                await _stop(process.process)

    async def _start(self, store: Path, variables: Mapping[str, str], log: IO[bytes]) -> _Started:
        """Start ``docs-mcp-server mcp`` over HTTP on a free loopback port.

        Args:
            store: The data directory.
            variables: The configuration's environment variables.
            log: Where its output goes.

        Returns:
            The process and its port.
        """
        port = _free_port()
        process = await asyncio.create_subprocess_exec(
            self.node,
            self.entry,
            "mcp",
            "--protocol",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--store-path",
            store,
            "--config",
            self.config,
            env=_clean_environment(variables),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
        return _Started(process=process, port=port)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Started:
    """A server process and the port it listens on."""

    process: asyncio.subprocess.Process
    """The process."""
    port: int
    """Its port."""


def _searcher(client: Client) -> Search:
    """Ask questions through a connected client's ``search_docs`` tool.

    Args:
        client: The client, entered.

    Returns:
        The search.
    """

    async def search(library: str, version: str, query: str) -> str:
        """Ask ``search_docs`` one question.

        Args:
            library: The library.
            version: The version.
            query: The question.

        Returns:
            The tool's response text.

        Raises:
            RuntimeError: The tool returned an error.
        """
        arguments = {"library": library, "version": version, "query": query, "limit": TOP_K}
        result = await asyncio.wait_for(
            client.call_tool(SEARCH_TOOL, arguments, raise_on_error=False), SEARCH_SECONDS
        )
        text = "".join(getattr(part, "text", "") for part in result.content)
        if result.is_error:
            raise RuntimeError(text.strip()[:500])
        return text

    return search


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Stop a server process: terminate it, and kill it if it does not end in 30 seconds.

    Args:
        process: The process.
    """
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 30)
    except TimeoutError:
        process.kill()
        await process.wait()


async def _connect(url: str, process: asyncio.subprocess.Process, log: IO[bytes]) -> Client:
    """Wait until the MCP server answers, then return a client for it.

    Args:
        url: The server's MCP endpoint.
        process: The server's process.
        log: Its output.

    Returns:
        A client (not entered) whose first connection succeeded.

    Raises:
        RuntimeError: The server stopped, or did not answer in ``START_SECONDS``.
    """
    deadline = time.monotonic() + START_SECONDS
    while True:
        if process.returncode is not None:
            log.seek(0)
            message = f"the MCP server stopped ({process.returncode}): {log.read()[-2000:]!r}"
            raise RuntimeError(message)
        probe = Client(url, timeout=10)
        try:
            async with probe:
                await probe.list_tools()
        except Exception as error:
            if time.monotonic() > deadline:
                message = f"the MCP server at {url} did not answer: {error}"
                raise RuntimeError(message) from error
            await asyncio.sleep(1)
            continue
        return Client(url, timeout=SEARCH_SECONDS)


def read_store(store: Path) -> dict[tuple[str, str], Stored]:
    """Read a Grounded Docs data directory's pages and chunks per library version.

    Args:
        store: The data directory (``documents.db``, Grounded Docs 3.4's schema).

    Returns:
        Each ``(library, version)``'s pages and chunks; empty without a database.
    """
    database = store / "documents.db"
    if not database.exists():
        return {}
    query = """
        SELECT l.name, v.name, p.url,
               (SELECT count(*) FROM documents d WHERE d.page_id = p.id),
               (SELECT count(*) FROM documents d WHERE d.page_id = p.id AND d.embedding IS NOT NULL)
        FROM pages p JOIN versions v ON v.id = p.version_id JOIN libraries l ON l.id = v.library_id
    """
    pages: dict[tuple[str, str], set[str]] = {}
    counts: dict[tuple[str, str], list[int]] = {}
    with contextlib.closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        for library, version, url, chunks, embedded in db.execute(query):
            key = (str(library), str(version or ""))
            pages.setdefault(key, set()).add(str(url))
            total = counts.setdefault(key, [0, 0])
            total[0] += int(chunks)
            total[1] += int(embedded)
    return {
        key: Stored(pages=frozenset(urls), chunks=counts[key][0], embedded=counts[key][1])
        for key, urls in pages.items()
    }


def stored_dimension(store: Path) -> int | None:
    """Read the vector size Grounded Docs stores its vectors at.

    Args:
        store: The data directory.

    Returns:
        ``embedding_dimension`` from its metadata; None without one.
    """
    database = store / "documents.db"
    if not database.exists():
        return None
    with contextlib.closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        try:
            row = db.execute(
                "SELECT value FROM metadata WHERE key = 'embedding_dimension'"
            ).fetchone()
        except sqlite3.Error:
            return None
    return int(row[0]) if row else None


def _node_version(node: Path) -> str:
    """Ask Node.js for its version.

    Args:
        node: The executable.

    Returns:
        Its version (``v22.23.5``).
    """
    return subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()


def install(home: Path, *, offline: bool) -> NodeGroundedDocs:
    """Install the pinned Grounded Docs release into ``home``, or check the one there.

    ``npm install`` puts it in ``home/<VERSION>``; the registry's integrity hash in the lock file
    must be ``INTEGRITY``.

    Args:
        home: Where Grounded Docs and its data directories are kept.
        offline: Install nothing; use what is there.

    Returns:
        The installation, with its configuration file.

    Raises:
        RuntimeError: Node.js or npm is missing, the install failed, it is not there offline, or
            the installed package is not the pinned release.
    """
    prefix = home / VERSION
    entry = prefix / "node_modules" / PACKAGE / "dist" / "index.js"
    if not entry.exists():
        npm = shutil.which("npm")
        if offline or npm is None:
            why = "--offline" if offline else "npm is not on PATH"
            message = f"Grounded Docs {VERSION} is not installed in {prefix} ({why})"
            raise RuntimeError(message)
        prefix.mkdir(parents=True, exist_ok=True)
        (prefix / "package.json").write_text('{"private": true}\n', encoding="utf-8")
        done = subprocess.run(
            [npm, "install", "--no-audit", "--no-fund", f"{PACKAGE}@{VERSION}"],
            cwd=prefix,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode:
            message = f"npm install {PACKAGE}@{VERSION} failed: {done.stderr.strip()[-2000:]}"
            raise RuntimeError(message)
    lock = json.loads((prefix / "package-lock.json").read_text(encoding="utf-8"))
    package = lock.get("packages", {}).get(f"node_modules/{PACKAGE}", {})
    if (package.get("version"), package.get("integrity")) != (VERSION, INTEGRITY):
        message = (
            f"{prefix} holds {PACKAGE} {package.get('version')} ({package.get('integrity')}), "
            f"not {VERSION} ({INTEGRITY})"
        )
        raise RuntimeError(message)
    node = shutil.which("node")
    if node is None:
        message = "Grounded Docs needs Node.js 22 or later (node is not on PATH)"
        raise RuntimeError(message)
    return NodeGroundedDocs(node=Path(node), entry=entry, config=home / "config.yaml")


def write_config(path: Path, corpus: Path) -> None:
    """Write Grounded Docs' configuration file: telemetry off, the corpus the one readable root.

    And the embedding request timeout ``REQUEST_TIMEOUT_MS``; every other setting keeps its
    default (the file is read, never written, with ``--config``).

    Args:
        path: The file.
        corpus: The folder the corpus is written to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    root = json.dumps(str(corpus.resolve()))
    path.write_text(
        "app:\n"
        "  telemetryEnabled: false\n"
        "scraper:\n"
        "  security:\n"
        "    fileAccess:\n"
        "      allowedRoots:\n"
        f"        - {root}\n"
        "embeddings:\n"
        f"  requestTimeoutMs: {REQUEST_TIMEOUT_MS}\n",
        encoding="utf-8",
    )


def materialize(repo: Path, commit: str, project: Project, folder: Path) -> list[str]:
    """Write the files the importer takes at a commit to a folder, under their repository paths.

    Args:
        repo: The cached repository.
        commit: The pinned commit.
        project: The project (its docs paths).
        folder: The version's folder; emptied first.

    Returns:
        The repository paths written, sorted.
    """
    shutil.rmtree(folder, ignore_errors=True)
    written = []
    for path, data in sorted(article_files(repo, commit, project).items()):
        if data is None:
            continue
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(path)
    return written


def limits(paths: Sequence[str], defaults: tuple[int, int]) -> tuple[int, int]:
    """The crawl's depth and page limits a folder needs: the defaults, raised where too low.

    The folder is depth 0 and each folder or file in it one deeper; the crawl counts folders as
    pages too.

    Args:
        paths: The files' paths in the folder.
        defaults: Grounded Docs' ``scraper.maxDepth`` and ``scraper.maxPages``.

    Returns:
        The maximum depth and pages to pass.
    """
    depth = max((len(PurePosixPath(p).parts) for p in paths), default=0)
    folders = {str(parent) for p in paths for parent in PurePosixPath(p).parents}
    return max(defaults[0], depth), max(defaults[1], len(paths) + len(folders))


def _relative(url: str, folder: Path) -> str | None:
    """A stored page's repository path, from its ``file://`` URL.

    Args:
        url: The page's URL.
        folder: The version's folder.

    Returns:
        The path inside the folder; None for a URL outside it.
    """
    prefix = folder.resolve().as_uri() + "/"
    if not url.startswith(prefix):
        return None
    return unquote(url.removeprefix(prefix))


def _tidy(settings: object, replacements: Mapping[str, str]) -> object:
    """Replace this machine's paths in Grounded Docs' settings.

    Args:
        settings: The settings, or a part of them.
        replacements: Each path and what replaces it.

    Returns:
        The settings with the paths replaced.
    """
    if isinstance(settings, dict):
        return {k: _tidy(v, replacements) for k, v in settings.items()}
    if isinstance(settings, list):
        return [_tidy(v, replacements) for v in settings]
    if isinstance(settings, str):
        for path, name in replacements.items():
            settings = settings.replace(path, name)
    return settings


def _tidy_all(settings: Mapping[str, Any], replacements: Mapping[str, str]) -> dict[str, Any]:
    """Replace this machine's paths in every one of Grounded Docs' settings.

    Args:
        settings: The settings in effect.
        replacements: Each path and what replaces it.

    Returns:
        The settings with the paths replaced.
    """
    return {k: _tidy(v, replacements) for k, v in settings.items()}


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """What one run covers."""

    projects: Sequence[Project]
    """The projects."""
    repos: Mapping[str, Path]
    """The cached repository of each."""
    dataset: RetrievalDataset
    """The golden set, restricted to ``projects``."""
    home: Path
    """Where Grounded Docs keeps its data directories and the corpus folder."""
    models_dir: Path
    """Where ``exactdocs models pull`` put the embedding model."""
    resume: bool
    """Keep versions a data directory already holds (``STORE_MARKER``)."""


def _snapshot(served: Served | None) -> Embedded | None:
    """What an endpoint has done so far.

    Args:
        served: Its counts; None without an endpoint.

    Returns:
        A copy of them.
    """
    if served is None:
        return None
    return Embedded(
        requests=served.requests,
        texts=served.texts,
        tokens=served.tokens,
        seconds=round(served.seconds, 1),
        abandoned=served.abandoned,
    )


def _since(served: Served | None, before: Embedded | None) -> Embedded | None:
    """What an endpoint has done since a snapshot.

    Args:
        served: Its counts; None without an endpoint.
        before: The snapshot.

    Returns:
        The difference.
    """
    now = _snapshot(served)
    if now is None or before is None:
        return None
    return Embedded(
        requests=now.requests - before.requests,
        texts=now.texts - before.texts,
        tokens=now.tokens - before.tokens,
        seconds=round(now.seconds - before.seconds, 1),
        abandoned=now.abandoned - before.abandoned,
    )


def _sum(parts: Sequence[Embedded | None]) -> Embedded:
    """Add what an endpoint did in several steps.

    Args:
        parts: Each step's counts (None for none).

    Returns:
        The total.
    """
    found = [p for p in parts if p is not None]
    return Embedded(
        requests=sum(p.requests for p in found),
        texts=sum(p.texts for p in found),
        tokens=sum(p.tokens for p in found),
        seconds=round(sum(p.seconds for p in found), 1),
        abandoned=sum(p.abandoned for p in found),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Indexing:
    """Where and how a configuration indexes."""

    tool: GroundedDocs
    """Grounded Docs."""
    store: Path
    """Its data directory."""
    variables: Mapping[str, str]
    """Its environment variables."""
    defaults: tuple[int, int]
    """Its crawl depth and page defaults."""
    served: Served | None
    """The embedding endpoint's counts; None without one."""


async def _index_one(
    how: _Indexing, project: Project, pinned: PinnedVersion, folder: Path, paths: Sequence[str]
) -> VersionIndex:
    """Index one pinned version from its folder, and read back what was stored.

    Args:
        how: Where and how.
        project: The project.
        pinned: The version.
        folder: Its folder, with the importer's files written to it.
        paths: Those files' paths.

    Returns:
        The version as it was indexed.
    """
    depth, pages = limits(paths, how.defaults)
    started, before = time.perf_counter(), _snapshot(how.served)
    await how.tool.index(
        how.store, how.variables, (project.id, pinned.name), folder, (depth, pages)
    )
    seconds = round(time.perf_counter() - started, 1)
    held = how.tool.stored(how.store).get((project.id, pinned.name))
    urls = held.pages if held else frozenset()
    indexed = {r for u in urls if (r := _relative(u, folder)) is not None}
    return VersionIndex(
        project=project.id,
        version=pinned.name,
        commit=pinned.commit,
        library=project.id,
        seconds=seconds,
        offered=len(paths),
        indexed=len(urls),
        chunks=held.chunks if held else 0,
        embedded=held.embedded if held else 0,
        max_depth=depth,
        max_pages=pages,
        not_indexed=sorted(set(paths) - indexed),
        embedding=_since(how.served, before),
    )


def _kept(store: Path, *, resume: bool) -> dict[tuple[str, str], VersionIndex]:
    """Read the versions a data directory already holds, or empty it.

    Args:
        store: The data directory.
        resume: Keep what it holds (``--resume``); otherwise it is removed.

    Returns:
        Each kept version, by ``(project, version)``.
    """
    marker = store / STORE_MARKER
    if resume and marker.exists():
        found = [VersionIndex.model_validate(v) for v in json.loads(marker.read_text("utf-8"))]
        return {(v.project, v.version): v for v in found}
    if store.exists():
        shutil.rmtree(store)
    return {}


async def _index_all(
    plan: Plan, configuration: Configuration, how: _Indexing
) -> list[VersionIndex]:
    """Index every pinned version into the configuration's data directory.

    Args:
        plan: The run.
        configuration: The configuration.
        how: Where and how.

    Returns:
        Every version as it was indexed.
    """
    kept = _kept(how.store, resume=plan.resume)
    how.store.mkdir(parents=True, exist_ok=True)
    done: list[VersionIndex] = []
    for project in plan.projects:
        for pinned in project.versions:
            folder = plan.home / "corpus" / project.id / pinned.name
            paths = materialize(plan.repos[project.id], pinned.commit, project, folder)
            old = kept.get((project.id, pinned.name))
            if old is not None and old.commit == pinned.commit:
                done.append(old)
                continue
            done.append(await _index_one(how, project, pinned, folder, paths))
            (how.store / STORE_MARKER).write_text(
                json.dumps([v.model_dump() for v in done], indent=1), encoding="utf-8"
            )
            v = done[-1]
            sys.stderr.write(
                f"{configuration.name}: {project.id} {pinned.name}: {v.indexed}/{v.offered} "
                f"pages, {v.chunks} chunks, {v.seconds:.0f} s\n"
            )
    return done


async def _ask_all(
    tool: GroundedDocs, store: Path, variables: Mapping[str, str], dataset: RetrievalDataset
) -> tuple[dict[str, TextAnswer], list[str]]:
    """Ask every golden question through the MCP server.

    Args:
        tool: Grounded Docs.
        store: The data directory.
        variables: The configuration's environment variables.
        dataset: The golden set.

    Returns:
        Each case's answer, by its name, and the questions that failed.
    """
    answers: dict[str, TextAnswer] = {}
    errors: list[str] = []
    async with tool.serving(store, variables) as search:
        for case in dataset.cases:
            started = time.perf_counter()
            try:
                text = await search(
                    case.inputs.project or "", case.inputs.version, case.inputs.query
                )
            except (RuntimeError, TimeoutError) as error:
                errors.append(f"{case.name}: {error}")
                text = ""
            elapsed = (time.perf_counter() - started) * 1000
            texts = [found.content for found in split_results(text)]
            answers[case.name or ""] = TextAnswer(texts=texts, search_ms=round(elapsed, 3))
    return answers, errors


def _variables(configuration: Configuration, endpoint: Endpoint | None) -> dict[str, str]:
    """The environment variables a configuration sets.

    Args:
        configuration: The configuration.
        endpoint: The embedding endpoint, for one with an embedding model.

    Returns:
        The variables (none for full-text search).
    """
    if configuration.embedding_model is None or endpoint is None:
        return {}
    return {
        "OPENAI_API_KEY": DUMMY_KEY,
        "OPENAI_API_BASE": endpoint.base_url,
        "DOCS_MCP_EMBEDDING_MODEL": configuration.embedding_model,
    }


def _listed_articles(dataset: RetrievalDataset) -> dict[str, frozenset[tuple[str, str]]]:
    """The version and article of every section each answerable case lists, alternatives too.

    Args:
        dataset: The golden set.

    Returns:
        ``(version, article)`` pairs by case name.
    """
    return {
        c.name or "": frozenset((h.version, h.article) for h in c.expected_output.hits)
        for c in dataset.cases
        if c.expected_output and c.expected_output.hits
    }


def crawl_defaults(settings: Mapping[str, Any]) -> tuple[int, int]:
    """Grounded Docs' crawl depth and page defaults, from its settings.

    Args:
        settings: The settings in effect.

    Returns:
        ``scraper.maxDepth`` and ``scraper.maxPages`` (3 and 1,000 when they are not there).
    """
    scraper = settings.get("scraper", {})
    return int(scraper.get("maxDepth", 3)), int(scraper.get("maxPages", 1000))


def _embedding_info(
    model: LocalEmbedding | None,
    store: Path,
    indexing: Sequence[VersionIndex],
    questions: Embedded | None,
) -> EmbeddingInfo | None:
    """Describe the embedding model a configuration ran with, and what it embedded.

    Args:
        model: The model; None for full-text search.
        store: The data directory.
        indexing: Every version as it was indexed.
        questions: What embedding the questions took.

    Returns:
        The description; None without a model.
    """
    if model is None or questions is None:
        return None
    return EmbeddingInfo(
        model=model.model,
        revision=model.revision,
        dimensions=model.dimensions,
        stored_dimensions=stored_dimension(store),
        served_by=SERVED_BY,
        indexing=_sum([v.embedding for v in indexing]),
        questions=questions,
    )


async def run_configuration(
    tool: GroundedDocs,
    plan: Plan,
    configuration: Configuration,
    indexes: Mapping[str, SectionIndex],
    embedder: Callable[[str], LocalEmbedding],
) -> RunResult:
    """Index the corpus, ask every question and score the answers, for one configuration.

    Args:
        tool: Grounded Docs.
        plan: The run.
        configuration: The configuration.
        indexes: Each project's sections.
        embedder: Loads an embedding model by name (called only for a configuration with one).

    Returns:
        The configuration's result, without its paired tests.
    """
    store = plan.home / "stores" / configuration.name
    with contextlib.ExitStack() as stack:
        model, endpoint = None, None
        if configuration.embedding_model is not None:
            model = embedder(configuration.embedding_model)
            endpoint = stack.enter_context(serve(model.embed, model.count, model.model))
        variables = _variables(configuration, endpoint)
        served = endpoint.served if endpoint else None
        settings = await tool.settings(store, variables)
        how = _Indexing(
            tool=tool,
            store=store,
            variables=variables,
            defaults=crawl_defaults(settings),
            served=served,
        )
        indexing = await _index_all(plan, configuration, how)
        size = sum(f.stat().st_size for f in store.iterdir() if f.is_file())
        before = _snapshot(served)
        answers, errors = await _ask_all(tool, store, variables, plan.dataset)
        embedding = _embedding_info(model, store, indexing, _since(served, before))
    rows = [
        text_row(c, answers[c.name or ""], indexes[c.inputs.project or ""])
        for c in plan.dataset.cases
    ]
    paths = {str(store): "<store>", str(plan.home / "corpus"): "<corpus>"}
    return RunResult(
        configuration=configuration.name,
        about=configuration.about,
        settings=_tidy_all(settings, paths),
        variables={
            k: ("<endpoint>/v1" if k == "OPENAI_API_BASE" else v) for k, v in variables.items()
        },
        embedding=embedding,
        indexing=indexing,
        index_seconds=round(sum(v.seconds for v in indexing), 1),
        index_bytes=size,
        result=TextResult.of(f"Grounded Docs {configuration.name}", rows),
        context_tokens_interval=tokens_interval(rows),
        rows=sorted(rows, key=lambda r: r.case),
        versus=[],
        errors=errors,
        cases_not_indexed=cases_not_indexed(rows, _listed_articles(plan.dataset), indexing),
    )


async def exactdocs_baseline(
    plan: Plan, indexes: Mapping[str, SectionIndex], data_dir: Path
) -> list[TextRow]:
    """Ask every question with ExactDocs' BM25 at ``default``, and score it from its text.

    Args:
        plan: The run.
        indexes: Each project's sections.
        data_dir: An empty data directory.

    Returns:
        Every case's row.

    Raises:
        RuntimeError: A version was not imported at its pinned commit.
    """
    chunking = next(c for c in CHUNKINGS if c.name == RECORDED_CHUNKING)
    container = model_free_container(data_dir)
    async with container.running(jobs=False):
        records = await import_corpus(container, plan.projects, dict(plan.repos), chunking.chunking)
        if wrong := [r for r in records if r.imported_commit != r.pinned_commit]:
            names = ", ".join(f"{r.project} {r.version}" for r in wrong)
            message = f"not imported at the pinned commit: {names}"
            raise RuntimeError(message)
        found = await bm25_results(container, plan.projects, plan.dataset)
    return [
        text_row(
            c,
            TextAnswer(
                texts=list(found[c.name or ""][1]), search_ms=found[c.name or ""][0].search_ms
            ),
            indexes[c.inputs.project or ""],
        )
        for c in plan.dataset.cases
    ]


def recorded_results(
    path: Path, golden: str, projects: Sequence[str]
) -> list[tuple[Recorded, list[Any]]]:
    """Take ExactDocs' configurations of ``RECORDED`` from the recorded retrieval benchmark run.

    Args:
        path: ``results/retrieval.json``.
        golden: This run's golden set fingerprint.
        projects: This run's projects.

    Returns:
        Each configuration's record with its rows; none when the file is missing or measured
        another golden set or other projects.
    """
    if not path.exists():
        return []
    report = RetrievalBenchReport.model_validate_json(path.read_text(encoding="utf-8"))
    if (report.golden, report.projects) != (golden, list(projects)):
        return []
    picked = []
    for name in RECORDED:
        result = next(
            (
                r
                for r in report.results
                if (r.configuration, r.chunking) == (name, RECORDED_CHUNKING)
                and r.metrics is not None
                and r.rows
            ),
            None,
        )
        if result is None or result.metrics is None:
            continue
        record = Recorded(
            configuration=name,
            chunking=RECORDED_CHUNKING,
            metrics=result.metrics,
            environment={
                k: report.environment[k]
                for k in ("exactdocs_commit", "platform", "cpus")
                if k in report.environment
            },
        )
        picked.append((record, list(result.rows)))
    return picked


async def bench(
    tool: GroundedDocs,
    plan: Plan,
    configurations: Sequence[Configuration],
    embedder: Callable[[str], LocalEmbedding],
    recorded_path: Path,
) -> GroundedDocsReport:
    """Run every configuration and ExactDocs' baseline, and compare them.

    Args:
        tool: Grounded Docs.
        plan: The run.
        configurations: The configurations.
        embedder: Loads an embedding model by name.
        recorded_path: The recorded retrieval benchmark run.

    Returns:
        The report.
    """
    machine = environment()  # the commit the run starts from
    indexes = {p.id: SectionIndex.of_project(p, plan.repos[p.id]) for p in plan.projects}
    with tempfile.TemporaryDirectory(prefix="exactdocs-grounded-bench-") as tmp:
        started = time.perf_counter()
        base_rows = await exactdocs_baseline(plan, indexes, Path(tmp) / "data")
        sys.stderr.write(f"{TEXT_BASELINE}: {time.perf_counter() - started:.0f} s\n")
    golden = fingerprint(plan.dataset)
    recorded = recorded_results(recorded_path, golden, [p.id for p in plan.projects])
    runs = []
    for configuration in configurations:
        run = await run_configuration(tool, plan, configuration, indexes, embedder)
        mine = [r.row for r in run.rows]
        versus = [paired(TEXT_BASELINE, "text", [r.row for r in base_rows], mine)]
        versus.extend(
            paired(f"ExactDocs {r.configuration} @ {r.chunking}", "chunk ID", rows, mine)
            for r, rows in recorded
        )
        runs.append(run.model_copy(update={"versus": versus}))
    return GroundedDocsReport(
        golden=golden,
        cases=len(plan.dataset.cases),
        projects=[p.id for p in plan.projects],
        corpus=[
            {"project": p.id, "version": v.name, "commit": v.commit}
            for p in plan.projects
            for v in p.versions
        ],
        date=dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        tool={
            "name": "Grounded Docs",
            "package": PACKAGE,
            "version": VERSION,
            "integrity": INTEGRITY,
            "search": SEARCH_TOOL,
            "top_k": str(TOP_K),
            **tool.describe(),
        },
        environment=machine,
        scorer=scorer_settings(),
        statistics=DEFAULT_STATS,
        baseline=Baseline(
            name=TEXT_BASELINE,
            result=TextResult.of(TEXT_BASELINE, base_rows),
            context_tokens_interval=tokens_interval(base_rows),
            rows=sorted(base_rows, key=lambda r: r.case),
        ),
        recorded=[r for r, _ in recorded],
        runs=runs,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="grounded-bench",
        description="Grounded Docs on the golden set, next to ExactDocs (docs/evals.md).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch and install nothing")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument(
        "--configs",
        default=",".join(c.name for c in CONFIGURATIONS),
        help="comma-separated Grounded Docs configurations (default: %(default)s)",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=home_dir(),
        help="where Grounded Docs, its data directories and the corpus folder are kept "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="where `exactdocs models pull` put the embedding model (default: "
        "EXACTDOCS_MODELS_DIR, or models in the data directory)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="keep the versions a data directory already indexed (after an interrupted run)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help=f"the directory {REPORT_NAME}.json and {REPORT_NAME}.md go to (default: %(default)s)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument(
        "--recorded", type=Path, default=RESULTS_DIR / "retrieval.json", help=argparse.SUPPRESS
    )
    return parser


def _models_dir(given: Path | None) -> Path:
    """Where the embedding model is.

    Args:
        given: ``--models-dir``.

    Returns:
        It, or ExactDocs' models directory.
    """
    if given is not None:
        return given
    return Settings().effective_models_dir


def main(
    argv: Sequence[str] | None = None,
    tool: Callable[[Path, bool], GroundedDocs] | None = None,
    embedder: Callable[[str], LocalEmbedding] | None = None,
) -> int:
    """Run the benchmark.

    Args:
        argv: The arguments; ``sys.argv`` by default.
        tool: Builds Grounded Docs from ``(home, offline)`` (tests: a stand-in); ``install``
            by default.
        embedder: Loads an embedding model by name (tests: a stand-in); ``load_local`` from
            ``--models-dir`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched, Grounded Docs cannot be installed or
        run, or the run has problems (``grounded_docs.problems``); 2 for an unknown
        configuration.
    """
    args = _parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    wanted = [name.strip() for name in args.configs.split(",") if name.strip()]
    known = {c.name: c for c in CONFIGURATIONS}
    if unknown := sorted(set(wanted) - set(known)):
        sys.stderr.write(f"unknown configurations: {', '.join(unknown)}\n")
        return 2
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
        home = args.home.resolve()
        write_config(home / "config.yaml", home / "corpus")
        grounded = (tool or (lambda h, o: install(h, offline=o)))(home, args.offline)
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in {p.id for p in projects}]
    plan = Plan(
        projects=projects,
        repos=repos,
        dataset=golden,
        home=home,
        models_dir=_models_dir(args.models_dir),
        resume=args.resume,
    )
    try:
        report = asyncio.run(
            bench(
                grounded,
                plan,
                [known[name] for name in wanted],
                embedder or (lambda model: load_local(plan.models_dir, model)),
                args.recorded,
            )
        )
    except (RuntimeError, FileNotFoundError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{REPORT_NAME}.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    summary = markdown(report)
    (args.out / f"{REPORT_NAME}.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as out:
            out.write(summary)
    sys.stdout.write(f"report: {args.out / REPORT_NAME}.json, {args.out / REPORT_NAME}.md\n")
    found = problems(report)
    for problem in found:
        sys.stderr.write(f"problem: {problem}\n")
    return 1 if found else 0
