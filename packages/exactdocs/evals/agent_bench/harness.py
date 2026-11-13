"""Run an agent against ExactDocs as shipped and record what it did with the MCP tools.

The server is the real CLI, ``exactdocs serve --stdio``, over a data directory the golden corpus
was imported into with the real importer (``golden_cli.import_corpus``). The agent gets that
server's tools and nothing else; a ``process_tool_call`` hook records every call, the sections
the agent read in full and the retrieval modes that answered.
"""

import contextlib
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from fastmcp.client.transports import StdioTransport
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, RunContext, capture_run_messages
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.mcp import CallToolFunc, MCPToolset, ToolResult
from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import UsageLimits
from pydantic_evals import Case, Dataset

from exactdocs.retrieval.adapters.driven.genai_prices import GenaiPrices
from exactdocs.retrieval.constants import TOKENS_PER_MILLION
from fixture_import import embed_fixture
from retrieval_eval.dataset import Hit, Question
from retrieval_eval.fixture import configured_container
from retrieval_eval.golden import Corpus, GoldenCase, Project
from retrieval_eval.golden_cli import ImportedVersion, import_corpus

AGENT_INSTRUCTIONS: Final[str] = """\
You help a developer with the libraries their project depends on. Your only source of \
documentation is the ExactDocs tools: find the library, search the documentation of exactly the \
version the project uses, and read the sections you need before answering.

Answer the question briefly, from what you read. If the documentation of that version does not \
answer it, say that the documentation does not cover it. Do not answer from memory or from \
another version of the library."""
"""The agent's instructions: the same for every model and case."""
PROMPT: Final[str] = "My project uses {title} at version {version}.\n\n{query}"
"""The user prompt: what a coding agent knows from the project (the dependency and its version)
and the question. Neither the ExactDocs library ID nor anything of the expected answer."""
EMBEDDING_VARIABLE: Final[str] = "EXACTDOCS_AI__EMBEDDING__MODEL"
"""The setting whose value decides whether a configuration needs its own embedded import."""
SETTING_PREFIX: Final[str] = "EXACTDOCS_AI__"
"""What a retrieval configuration's ``key=value`` settings are prefixed with."""
ARGS_SHOWN: Final[int] = 200
"""Characters of a tool call's arguments kept in the record."""
CHUNK_LINE: Final[re.Pattern[str]] = re.compile(r"^Chunk: (\S+)$", re.MULTILINE)
"""The chunk ID line of each block ``query-docs`` returns."""
READ_CHUNK: Final[str] = "read_chunk"
"""The tool that returns one chunk in full."""
READ_ARTICLE: Final[str] = "read_article"
"""The tool that returns a whole article."""
QUERY_DOCS: Final[str] = "query-docs"
"""The context7-compatible tool that returns chunks in full, as text."""
SEARCHES: Final[frozenset[str]] = frozenset({"search_docs", "search_all_docs"})
"""The tools that report the retrieval mode that answered."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Section(_Model):
    """One section the agent read in full (or a whole article)."""

    library: str
    """Library ID."""
    version: str
    """The version (ref) it was read from."""
    article: str
    """The article path."""
    heading_path: list[str] = Field(default_factory=list)
    """The section's headings from the top one; empty for a whole article."""
    chunk_id: str = ""
    """The chunk ID; empty for a whole article."""
    whole_article: bool = False
    """The agent read the whole article (``read_article``), so every section of it."""


class ToolCall(_Model):
    """One tool call the agent made."""

    name: str
    """The tool."""
    args: str
    """Its arguments as JSON, cut to ``ARGS_SHOWN`` characters."""
    seconds: float
    """How long the call took."""
    error: str | None = None
    """What the tool raised, when it failed."""


class AgentRun(_Model):
    """What the agent did for one question: the task output the judge grades."""

    answer: str
    """The agent's final answer (empty when the run failed)."""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    """Every tool call, in order."""
    read: list[Section] = Field(default_factory=list)
    """The sections (and whole articles) the agent read in full, in order."""
    retrieval_modes: list[str] = Field(default_factory=list)
    """``<mode>`` or ``<mode> (<fallback reason>)`` of each search, in order."""
    input_tokens: int = 0
    """Input tokens over every model request of the run."""
    output_tokens: int = 0
    """Output tokens over every model request of the run."""
    requests: int = 0
    """Model requests."""
    usd: float | None = None
    """What the tokens cost; ``None`` when the model is not in the price list."""
    seconds: float = 0.0
    """Wall time of the run."""
    error: str | None = None
    """Why the run ended without an answer (a usage limit, a provider error)."""


class BenchInfo(_Model):
    """A case's metadata in the benchmark: its kind, project and what a correct answer holds."""

    kind: str
    """The golden kind (``unanswerable``: the version does not answer it)."""
    project: str
    """The golden project ID."""
    title: str
    """The project's display name, as the agent is told it."""
    library: str
    """The ExactDocs library ID the project is imported under."""
    reference: str
    """The reference answer."""
    facts: list[str] = Field(default_factory=list)
    """The facts a correct answer must contain; empty when unanswerable."""
    hits: list[Hit] = Field(default_factory=list)
    """The sections that answer it."""


type BenchDataset = Dataset[Question, AgentRun, BenchInfo]
"""The benchmark's dataset: golden questions, the agent's runs, each case's expectations."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalConfig:
    """One retrieval configuration: the ``EXACTDOCS_AI__...`` settings the server runs with."""

    name: str
    """Its name in the report."""
    env: Mapping[str, str]
    """The settings, as environment variables, on top of the process's environment."""

    @classmethod
    def parse(cls, text: str) -> RetrievalConfig:
        """Read ``name[:key=value,...]``; each key is an AI setting path (``embedding.model``).

        Args:
            text: E.g. ``hybrid:mode=hybrid,embedding.model=eval:text-embedding-3-small``.

        Returns:
            The configuration; ``mode=bm25`` becomes ``EXACTDOCS_AI__MODE=bm25``.

        Raises:
            ValueError: No name, or a setting without ``=``.
        """
        name, _, settings = text.partition(":")
        if not name.strip():
            message = f"retrieval configuration {text!r} has no name"
            raise ValueError(message)
        env = {}
        for item in filter(None, (s.strip() for s in settings.split(","))):
            key, equals, value = item.partition("=")
            if not equals or not key.strip():
                message = f"retrieval configuration {text!r}: {item!r} is not key=value"
                raise ValueError(message)
            env[SETTING_PREFIX + key.strip().upper().replace(".", "__")] = value.strip()
        return cls(name=name.strip(), env=env)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- the hook fills it
class Recorder:
    """One run's record, passed to the agent as its deps so concurrent runs stay apart."""

    calls: list[ToolCall] = field(default_factory=list)
    """Every tool call."""
    read: list[Section] = field(default_factory=list)
    """Sections read in full."""
    modes: list[str] = field(default_factory=list)
    """The retrieval mode of each search."""

    async def take(self, name: str, result: ToolResult, call_tool: CallToolFunc) -> None:
        """Keep what a tool result says the agent read, and how a search was answered.

        Args:
            name: The tool.
            result: What it returned (structured content, or text blocks).
            call_tool: Calls a tool on the same server, outside the agent's run: resolves the
                chunk IDs of a ``query-docs`` answer to their sections.
        """
        if name == READ_CHUNK and isinstance(result, dict):
            self.read.append(_section(result))
        elif name == READ_ARTICLE and isinstance(result, dict):
            self.read.append(
                Section(
                    library=result["library"],
                    version=result["ref"],
                    article=result["path"],
                    whole_article=True,
                )
            )
        elif name == QUERY_DOCS:
            texts = result if isinstance(result, list) else [result]
            text = "\n".join(t for t in texts if isinstance(t, str))
            for chunk_id in CHUNK_LINE.findall(text):
                chunk = await call_tool(READ_CHUNK, {"chunk_id": chunk_id})
                if isinstance(chunk, dict):
                    self.read.append(_section(chunk))
        elif name in SEARCHES and isinstance(result, dict):
            reason = result.get("fallback_reason")
            mode = str(result.get("retrieval_mode"))
            self.modes.append(f"{mode} ({reason})" if reason else mode)


def _section(chunk: Mapping[str, Any]) -> Section:
    """Read a ``read_chunk`` result.

    Args:
        chunk: Its structured content.

    Returns:
        The section.
    """
    return Section(
        library=chunk["library"],
        version=chunk["version"],
        article=chunk["article_path"],
        heading_path=list(chunk["heading_path"]),
        chunk_id=chunk["chunk_id"],
    )


async def record_tool_call(
    ctx: RunContext[Recorder], call_tool: CallToolFunc, name: str, args: dict[str, Any]
) -> ToolResult:
    """The toolset's ``process_tool_call`` hook: call the tool and record it in the run's deps.

    Args:
        ctx: The run; its deps are the run's ``Recorder``.
        call_tool: Calls the tool on the server.
        name: The tool.
        args: The model's arguments.

    Returns:
        The tool's result, unchanged.
    """
    shown = json.dumps(args, ensure_ascii=False, sort_keys=True)[:ARGS_SHOWN]
    started = time.perf_counter()
    try:
        result = await call_tool(name, args)
    except Exception as error:
        seconds = round(time.perf_counter() - started, 3)
        ctx.deps.calls.append(ToolCall(name=name, args=shown, seconds=seconds, error=str(error)))
        raise
    seconds = round(time.perf_counter() - started, 3)
    ctx.deps.calls.append(ToolCall(name=name, args=shown, seconds=seconds))
    await ctx.deps.take(name, result, call_tool)
    return result


def grounded(info: BenchInfo, run: AgentRun) -> bool | None:
    """Tell whether the agent read every section that answers the case.

    A section counts when the agent read its chunk (``read_chunk``, or ``query-docs`` which
    returns chunks in full) or its whole article (``read_article``), of the asked library and the
    section's version. Search snippets do not count.

    Args:
        info: The case's expectations.
        run: What the agent did.

    Returns:
        True or False; ``None`` for a case with no answering section (unanswerable).
    """
    if not info.hits:
        return None
    return all(
        any(
            s.library == info.library
            and s.version == hit.version
            and s.article == hit.article
            and (s.whole_article or s.heading_path == hit.heading_path)
            for s in run.read
        )
        for hit in info.hits
    )


def read_other_versions(question: Question, info: BenchInfo, run: AgentRun) -> list[str]:
    """List what the agent read of the asked library at another version than the question's.

    Args:
        question: The question, with its version.
        info: The case, with its library.
        run: What the agent did.

    Returns:
        ``<version>:<article>`` of each such read, in order.
    """
    return [
        f"{s.version}:{s.article}"
        for s in run.read
        if s.library == info.library and s.version != question.version
    ]


def usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Price a run's tokens with the bundled price list (ExactDocs' own ``GenaiPrices``).

    Args:
        model: A pydantic-ai model name, ``<provider>:<model>`` (``google-gla`` is looked up as
            ``google``).
        input_tokens: Input tokens.
        output_tokens: Output tokens.

    Returns:
        US dollars, or ``None`` when the model is not in the list (a stand-in, a local model).
    """
    provider, colon, name = model.partition(":")
    if not colon or not name:
        return None
    kind = provider.partition("-")[0]
    prices = GenaiPrices()
    per_input = prices.input_usd_per_million(kind, f"{kind}/{name}")
    if per_input is None:
        return None
    per_output = prices.output_usd_per_million(kind, f"{kind}/{name}") or 0.0
    return (input_tokens * per_input + output_tokens * per_output) / TOKENS_PER_MILLION


def bench_dataset(cases: Sequence[tuple[str, GoldenCase]], corpus: Corpus) -> BenchDataset:
    """Turn golden cases into the benchmark's dataset.

    Args:
        cases: ``(project, case)`` pairs (``golden.load_cases``).
        corpus: The corpus manifest, for each project's title and library ID.

    Returns:
        One case per golden case, its expectations in the metadata.

    Raises:
        ValueError: A case's project is not in the corpus, or it has no expected output.
    """
    bench = []
    for project_id, case in cases:
        project = corpus.project(project_id)
        expected = case.expected_output
        if project is None or expected is None or case.metadata is None:
            message = f"{case.name}: not a valid golden case; run `just golden-validate`"
            raise ValueError(message)
        info = BenchInfo(
            kind=case.metadata.kind,
            project=project.id,
            title=project.title,
            library=project.library,
            reference=expected.reference or "",
            facts=expected.facts,
            hits=expected.hits,
        )
        bench.append(Case(name=case.name, inputs=case.inputs, metadata=info))
    return Dataset[Question, AgentRun, BenchInfo](name="golden-agent", cases=bench)


@contextlib.contextmanager
def environment(env: Mapping[str, str]) -> Generator[None]:
    """Set environment variables for the block, then restore them.

    Args:
        env: The variables.

    Yields:
        Nothing; the variables are set inside the block.
    """
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def import_golden(
    data_dir: Path, projects: Sequence[Project], repos: Mapping[str, Path], env: Mapping[str, str]
) -> list[ImportedVersion]:
    """Import every pinned version of the projects, then embed them when a model is configured.

    The container is configured from the environment plus ``env``, as the server will be, so a
    configuration with an embedding model gets an import embedded with that model.

    Args:
        data_dir: An empty data directory.
        projects: The projects.
        repos: Each project's cached repository (``golden.fetch``).
        env: The configuration's settings.

    Returns:
        One record per version, with the commit the catalog recorded.
    """
    with environment(env):
        container = configured_container(data_dir)
        async with container.running(jobs=False):
            records = await import_corpus(container, projects, dict(repos))
            await embed_fixture(container)  # as the embed jobs would; a no-op without a model
    return records


def exactdocs_toolset(
    data_dir: Path, env: Mapping[str, str], log_file: Path
) -> MCPToolset[Recorder]:
    """The MCP tools of ExactDocs as shipped: ``exactdocs serve --stdio`` on a data directory.

    Args:
        data_dir: The imported data directory.
        env: The configuration's settings, on top of this process's environment.
        log_file: Where the server's stderr goes.

    Returns:
        The toolset; entering it starts the server, leaving it stops it.
    """
    command = Path(sys.executable).with_name("exactdocs")  # the console script of this install
    transport = StdioTransport(
        command=str(command),
        args=["serve", "--stdio"],
        env={**os.environ, **env, "EXACTDOCS_DATA_DIR": str(data_dir)},
        log_file=log_file,
    )
    return MCPToolset(transport, process_tool_call=record_tool_call, id="exactdocs")


def asker(
    agent: Agent[Recorder, str], model: str, titles: Mapping[str, str], *, max_requests: int
) -> Callable[[Question], Awaitable[AgentRun]]:
    """Build the benchmark's task: ask the agent one question and record the run.

    Args:
        agent: The agent, with the ExactDocs toolset.
        model: The model's name, for the price.
        titles: Each project's display name, as the agent is told it.
        max_requests: The most model requests one question may take.

    Returns:
        The task; a run that fails (a usage limit, a provider error) returns its record with
        the error and no answer instead of raising.
    """

    async def ask(question: Question) -> AgentRun:
        """Ask one question.

        Args:
            question: The golden question.

        Returns:
            The run's record.
        """
        recorder = Recorder()
        prompt = PROMPT.format(
            title=titles.get(question.project or "", question.project or ""),
            version=question.version,
            query=question.query,
        )
        answer, error = "", None
        started = time.perf_counter()
        with capture_run_messages() as messages:
            try:
                result = await agent.run(
                    prompt, deps=recorder, usage_limits=UsageLimits(request_limit=max_requests)
                )
                answer = result.output
            except AgentRunError as failure:
                error = f"{type(failure).__name__}: {failure}"
        seconds = round(time.perf_counter() - started, 3)
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        input_tokens = sum(r.usage.input_tokens for r in responses)
        output_tokens = sum(r.usage.output_tokens for r in responses)
        return AgentRun(
            answer=answer,
            tool_calls=recorder.calls,
            read=recorder.read,
            retrieval_modes=recorder.modes,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requests=len(responses),
            usd=usd(model, input_tokens, output_tokens),
            seconds=seconds,
            error=error,
        )

    return ask
