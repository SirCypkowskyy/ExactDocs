"""The documentation arms' servers (#495): ExactDocs, Context7 and Grounded Docs, each as shipped.

- ``exactdocs``: ``exactdocs serve --stdio`` over the golden corpus, imported at the pinned
  commits once per embedding model (``harness.exactdocs_toolset``).
- ``context7``: the official Context7 MCP server, ``@upstash/context7-mcp`` at a pinned release
  installed from npm with its registry integrity hash checked (``grounded_docs_cli.npm_install``),
  over stdio. It answers from Context7's hosted index with ``CONTEXT7_API_KEY``, the only
  credential it gets; ``CONTEXT7_API_URL`` sends it elsewhere (the tests' stand-in API).
- ``grounded-docs``: Grounded Docs' MCP server in its read-only mode, over HTTP on loopback, on the
  data directory the Grounded Docs benchmark (#534) indexes every pinned version into
  (``grounded_docs_cli.indexed``, kept in ``~/.cache/exactdocs/grounded-docs``: a version already
  indexed at its pinned commit is not indexed again).

``ArmServers.tools`` runs an arm's server for the time of a block and records what ran
(``described``) for the report. The agent gets only the arm's tools (``Arm.tools``,
``harness.only_its_tools``).
"""

import contextlib
import importlib.metadata
import os
import re
import shutil
import tempfile
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote

from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset, ProcessToolCallback, ToolResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_evals import Dataset

from agent_bench.arms import CONTEXT7, EXACTDOCS, GROUNDED_DOCS, NONE, Arm
from agent_bench.harness import (
    EMBEDDING_VARIABLE,
    Recorder,
    RetrievalConfig,
    Section,
    exactdocs_toolset,
    import_golden,
    recorded_call,
)
from agent_bench.redact import SECRET_NAME, safe_url
from exactdocs.bootstrap.settings import Settings
from retrieval_eval import grounded_docs
from retrieval_eval.context7 import API_BASE, API_KEY_VARIABLE
from retrieval_eval.dataset import Answer, CaseInfo, Question
from retrieval_eval.golden import Project, default_cache_dir
from retrieval_eval.golden_cli import ImportedVersion
from retrieval_eval.grounded_docs_cli import (
    NodeGroundedDocs,
    Plan,
    home_dir,
    indexed,
    install,
    npm_install,
    write_config,
)
from retrieval_eval.openai_embeddings import load_local

CONTEXT7_PACKAGE: Final[str] = "@upstash/context7-mcp"
"""The official Context7 MCP server's npm package."""
CONTEXT7_VERSION: Final[str] = "4.5.0"
"""The release run: pinned, never ``latest``; the one ExactDocs' context7-compatible tools mirror
(``tests/contracts/context7``)."""
CONTEXT7_INTEGRITY: Final[str] = (
    "sha512-BTMM4j2ZuZdAHE1sERUCcty1eRcom4LCE04iv2XIi9b9RKhJKQsXMG7gZLgx7FX5uyyaW6xki7ReuhRM4bphZQ=="
)
"""The npm registry's integrity hash of ``CONTEXT7_VERSION``'s tarball: the install is refused
without it."""
CONTEXT7_URL_VARIABLE: Final[str] = "CONTEXT7_API_URL"
"""Where the Context7 server sends its requests when set; Context7's hosted API otherwise."""
CONTEXT7_TELEMETRY_OFF: Final[dict[str, str]] = {"OTEL_SDK_DISABLED": "true"}
"""The Context7 server's OpenTelemetry metrics, off: they change nothing it answers."""
READ_ONLY: Final[dict[str, str]] = {"DOCS_MCP_READ_ONLY": "true"}
"""Grounded Docs' read-only mode: it lists no indexing tool."""
DEFAULT_GROUNDED_DOCS: Final[str] = "full-text"
"""The Grounded Docs configuration of the ``grounded-docs`` arm when none is given: no model,
full-text search, as ``exactdocs`` defaults to BM25."""
READ_PAGE: Final[str] = "read_page"
"""Grounded Docs' tool that returns a page, in parts when it is long."""
SOURCE_LINE: Final[re.Pattern[str]] = re.compile(r"\A> Source: (\S+)")
"""The first line of a ``read_page`` answer: the page's URL."""
PART_NOTICE: Final[str] = "> Showing chunks "
"""How a ``read_page`` answer that holds only part of the page says so."""
SERVER_SECONDS: Final[float] = 120.0
"""How long a server may take to start its MCP session, and a tool call to answer: pydantic-ai's
default of 5 seconds for the first is too short on a busy machine."""


def context7_home() -> Path:
    """Where the Context7 MCP server is installed, by default.

    Returns:
        ``<the golden cache's parent>/context7-mcp`` (``~/.cache/exactdocs/context7-mcp``).
    """
    return default_cache_dir().parent / "context7-mcp"


def grounded_docs_config(name: str) -> RetrievalConfig:
    """Name a Grounded Docs configuration for the ``grounded-docs`` arm.

    Args:
        name: One of ``grounded_docs.CONFIGURATIONS``.

    Returns:
        The configuration as the arm's setup holds it: its name, no setting.

    Raises:
        ValueError: An unknown configuration.
    """
    known = [c.name for c in grounded_docs.CONFIGURATIONS]
    if name not in known:
        message = f"unknown Grounded Docs configuration {name!r}; they are {', '.join(known)}"
        raise ValueError(message)
    return RetrievalConfig(name=name, env={})


def context7_environment(key: str) -> dict[str, str]:
    """The Context7 server's environment: this process's without its credentials, and the key.

    Args:
        key: The Context7 API key.

    Returns:
        The variables: none of the agents' keys, ``CONTEXT7_API_KEY``, telemetry off.
    """
    inherited = {n: v for n, v in os.environ.items() if not SECRET_NAME.search(n)}
    return {**inherited, API_KEY_VARIABLE: key, **CONTEXT7_TELEMETRY_OFF}


def context7_toolset(node: Path, entry: Path, key: str, log_file: Path) -> MCPToolset[Recorder]:
    """The official Context7 MCP server over stdio, every call recorded.

    Args:
        node: The ``node`` executable.
        entry: The package's ``dist/index.js``.
        key: The Context7 API key.
        log_file: Where the server's stderr goes.

    Returns:
        The toolset; entering it starts the server, leaving it stops it.
    """
    transport = StdioTransport(
        command=str(node),
        args=[str(entry), "--transport", "stdio"],
        env=context7_environment(key),
        log_file=log_file,
    )
    return MCPToolset(
        transport, process_tool_call=recorded_call, id=CONTEXT7, init_timeout=SERVER_SECONDS
    )


def _text(result: ToolResult) -> str:
    """A text tool's result as one string.

    Args:
        result: What the tool returned.

    Returns:
        Its text blocks, joined; empty for a structured result.
    """
    texts = result if isinstance(result, list) else [result]
    return "\n".join(t for t in texts if isinstance(t, str))


def page_read(
    result: ToolResult, args: Mapping[str, Any], corpus: Path, libraries: Mapping[str, str]
) -> Section | None:
    """Read a ``read_page`` answer: the pinned version's article the agent read whole, if it did.

    Grounded Docs indexed each version from ``<corpus>/<project>/<version>/``, the files the
    ExactDocs importer takes at the pinned commit under their repository paths, so a page's URL
    names the project, the version and the article. A page returned in parts counts only when one
    answer held all of it (``startChunk`` 0 and no "Showing chunks" notice); its search results
    are passages, like ExactDocs' snippets, and never count.

    Args:
        result: The tool's answer.
        args: The model's arguments.
        corpus: The corpus folder the versions were indexed from.
        libraries: Each project's ExactDocs library ID.

    Returns:
        The whole article read; ``None`` for a part, an error or a page outside the corpus.
    """
    text = _text(result)
    source = SOURCE_LINE.match(text)
    if source is None or PART_NOTICE in text or args.get("startChunk", 0):
        return None
    prefix = corpus.resolve().as_uri() + "/"
    if not source[1].startswith(prefix):
        return None
    project, _, rest = unquote(source[1].removeprefix(prefix)).partition("/")
    version, _, article = rest.partition("/")
    library = libraries.get(project)
    if library is None or not article:
        return None
    return Section(library=library, version=version, article=article, whole_article=True)


def grounded_docs_hook(corpus: Path, libraries: Mapping[str, str]) -> ProcessToolCallback:
    """Grounded Docs' ``process_tool_call`` hook: record the call and the whole pages read.

    Args:
        corpus: The corpus folder the versions were indexed from.
        libraries: Each project's ExactDocs library ID.

    Returns:
        The hook.
    """

    async def hook(
        ctx: RunContext[Recorder], call_tool: CallToolFunc, name: str, args: dict[str, Any]
    ) -> ToolResult:
        """Call the tool, record the call, and the article when it returned a whole page.

        Args:
            ctx: The run; its deps are the run's ``Recorder``.
            call_tool: Calls the tool on the server.
            name: The tool.
            args: The model's arguments.

        Returns:
            The tool's result, unchanged.
        """
        result = await recorded_call(ctx, call_tool, name, args)
        if name == READ_PAGE and (read := page_read(result, args, corpus, libraries)):
            ctx.deps.read.append(read)
        return result

    return hook


def grounded_docs_toolset(
    url: str, corpus: Path, libraries: Mapping[str, str]
) -> MCPToolset[Recorder]:
    """Grounded Docs' MCP server at a URL, every call and whole page read recorded.

    Args:
        url: Its MCP endpoint.
        corpus: The corpus folder the versions were indexed from.
        libraries: Each project's ExactDocs library ID.

    Returns:
        The toolset.
    """
    return MCPToolset(
        url,
        process_tool_call=grounded_docs_hook(corpus, libraries),
        id=GROUNDED_DOCS,
        init_timeout=SERVER_SECONDS,
        read_timeout=SERVER_SECONDS,
    )


def label(arm: Arm, config: RetrievalConfig | None) -> str:
    """Name a setup as the report's tables do.

    Args:
        arm: The arm.
        config: Its configuration.

    Returns:
        ``context7``, or ``grounded-docs (full-text)`` for an arm with a configuration.
    """
    return f"{arm.name} ({config.name})" if config else arm.name


def _node() -> Path:
    """Find Node.js, which runs the Context7 and Grounded Docs servers.

    Returns:
        The ``node`` executable.

    Raises:
        RuntimeError: It is not on ``PATH``.
    """
    node = shutil.which("node")
    if node is None:
        message = (
            "the context7 and grounded-docs arms need Node.js 22 or later (node is not on PATH)"
        )
        raise RuntimeError(message)
    return Path(node)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- imports are cached
class ArmServers:
    """Builds each arm's toolsets, with its server as shipped (none for ``none``)."""

    projects: Sequence[Project]
    """The projects of the asked cases."""
    repos: Mapping[str, Path]
    """Each project's cached repository."""
    work_dir: Path
    """Where the data directories and the server logs go."""
    grounded_home: Path = field(default_factory=home_dir)
    """Where Grounded Docs, its data directories and the corpus folder are kept (#534's)."""
    models_dir: Path | None = None
    """Where ``exactdocs models pull`` put the embedding model of a Grounded Docs configuration
    with one; ExactDocs' models directory when ``None``."""
    context7_home: Path = field(default_factory=context7_home)
    """Where the Context7 MCP server is installed."""
    imports: dict[str, Path] = field(default_factory=dict)
    """The data directory of each embedding model the corpus was imported for."""
    records: list[ImportedVersion] = field(default_factory=list)
    """Every imported version, from the first import."""
    described: dict[str, dict[str, str]] = field(default_factory=dict)
    """What ran for each setup (``label``): the server, its release, the tools the agent got."""

    async def imported(self, config: RetrievalConfig) -> Path:
        """Import the corpus for an ``exactdocs`` configuration, once per embedding model.

        Args:
            config: The retrieval configuration.

        Returns:
            The data directory the corpus is imported into (embedded with its model): a new one in
            the work directory, so a work directory kept from an earlier run (``--resume``) is
            never imported into twice.
        """
        embedding = config.env.get(EMBEDDING_VARIABLE, os.environ.get(EMBEDDING_VARIABLE, ""))
        if embedding not in self.imports:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            data_dir = Path(
                tempfile.mkdtemp(prefix=f"data-{len(self.imports)}-", dir=self.work_dir)
            )
            records = await import_golden(data_dir, self.projects, self.repos, config.env)
            self.imports[embedding] = data_dir
            self.records = self.records or records
        return self.imports[embedding]

    @contextlib.asynccontextmanager
    async def tools(
        self, arm: Arm, config: RetrievalConfig | None
    ) -> AsyncGenerator[Sequence[AbstractToolset[Recorder]]]:
        """Give an arm its toolsets for the block.

        Args:
            arm: The arm.
            config: Its configuration (``exactdocs``, ``grounded-docs``).

        Yields:
            The toolsets; the arm's server runs for the block.

        Raises:
            ValueError: ``exactdocs`` or ``grounded-docs`` without a configuration.
        """
        if arm.name == NONE:
            yield []
            return
        async with contextlib.AsyncExitStack() as stack:
            if arm.name == EXACTDOCS and config is not None:
                data_dir = await self.imported(config)
                log_file = self.work_dir / f"server-{config.name}.log"
                toolset = exactdocs_toolset(data_dir, config.env, log_file)
                about = {
                    "server": "exactdocs serve --stdio",
                    "version": importlib.metadata.version("exactdocs"),
                }
            elif arm.name == CONTEXT7:
                toolset, about = self._context7()
            elif arm.name == GROUNDED_DOCS and config is not None:
                toolset, about = await self._grounded_docs(stack, config)
            else:
                message = f"the {arm.name} arm needs a configuration"
                raise ValueError(message)
            server = await stack.enter_async_context(toolset)
            listed = sorted(t.name for t in await server.list_tools())
            offered = [n for n in listed if arm.tools is None or n in arm.tools]
            self.described[label(arm, config)] = {**about, "tools": ", ".join(offered)}
            yield [server]

    def context7_installed(self) -> tuple[Path, Path, str, dict[str, str]]:
        """Install the pinned Context7 MCP server (once).

        Returns:
            ``node``, the package's entry point, the API key, and what it is.

        Raises:
            RuntimeError: No API key, no Node.js, or the install failed.
        """
        key = os.environ.get(API_KEY_VARIABLE, "").strip()
        if not key:
            message = f"the context7 arm needs a Context7 API key in {API_KEY_VARIABLE}"
            raise RuntimeError(message)
        node = _node()
        entry = npm_install(
            self.context7_home / CONTEXT7_VERSION,
            CONTEXT7_PACKAGE,
            CONTEXT7_VERSION,
            CONTEXT7_INTEGRITY,
            offline=False,
        )
        self.work_dir.mkdir(parents=True, exist_ok=True)
        api = os.environ.get(CONTEXT7_URL_VARIABLE) or API_BASE
        about = {
            "server": f"{CONTEXT7_PACKAGE} {CONTEXT7_VERSION}",
            "integrity": CONTEXT7_INTEGRITY,
            "api": safe_url(api),
            "api_key": f"{API_KEY_VARIABLE} set",
        }
        return node, entry, key, about

    def _context7(self) -> tuple[MCPToolset[Recorder], dict[str, str]]:
        """Install the pinned Context7 MCP server (once) and build its toolset.

        Returns:
            The toolset and what it is.
        """
        node, entry, key, about = self.context7_installed()
        toolset = context7_toolset(node, entry, key, self.work_dir / "server-context7.log")
        return toolset, {**about, "server": f"{about['server']} (stdio)"}

    async def grounded_docs_served(
        self, stack: contextlib.AsyncExitStack, config: RetrievalConfig
    ) -> tuple[str, Path, dict[str, str]]:
        """Index the asked projects for a Grounded Docs configuration and start its server.

        Args:
            stack: Holds the embedding endpoint and the server for the block.
            config: The configuration (``grounded_docs_config``).

        Returns:
            The server's MCP URL (on loopback), the corpus folder it indexed and what it is.
        """
        configuration = next(c for c in grounded_docs.CONFIGURATIONS if c.name == config.name)
        home = self.grounded_home.resolve()
        write_config(home / "config.yaml", home / "corpus")
        tool: NodeGroundedDocs = install(home, offline=False)
        models_dir = self.models_dir or Settings().effective_models_dir
        plan = Plan(
            projects=self.projects,
            repos=self.repos,
            dataset=Dataset[Question, Answer, CaseInfo](name="golden", cases=[]),
            home=home,
            models_dir=models_dir,
            resume=True,
        )
        ready = await stack.enter_async_context(
            indexed(tool, plan, configuration, lambda model: load_local(models_dir, model))
        )
        url = await stack.enter_async_context(
            tool.listening(ready.store, {**ready.variables, **READ_ONLY})
        )
        about = {
            "server": f"{grounded_docs.PACKAGE} {grounded_docs.VERSION} (read-only, HTTP)",
            "integrity": grounded_docs.INTEGRITY,
            "configuration": f"{configuration.name}: {configuration.about}",
            "indexed": (
                f"{len(ready.indexing)} pinned versions, "
                f"{sum(v.chunks for v in ready.indexing):,} chunks"
            ),
            **tool.describe(),
        }
        return url, home / "corpus", about

    async def _grounded_docs(
        self, stack: contextlib.AsyncExitStack, config: RetrievalConfig
    ) -> tuple[MCPToolset[Recorder], dict[str, str]]:
        """Index the asked projects for a Grounded Docs configuration and build its toolset.

        Args:
            stack: Holds the embedding endpoint and the server for the block.
            config: The configuration (``grounded_docs_config``).

        Returns:
            The toolset (not entered) and what it is.
        """
        url, corpus, about = await self.grounded_docs_served(stack, config)
        libraries = {p.id: p.library for p in self.projects}
        return grounded_docs_toolset(url, corpus, libraries), about
