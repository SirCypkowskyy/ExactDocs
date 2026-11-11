"""The pydantic-ai side of ``ai_explorer``: loaded only once an agentic search runs (RET-04).

The agent runs in harness **Code Mode**: its only model-visible tool is ``run_code``, and the
read tools (``list_articles``, ``article_outline``, ``read_article``, ``read_chunk``,
``search_docs``) are functions with typed returns that exist only inside its Monty sandbox
(never IPython). They read through the ``DocsBrowser`` the agent gets as ``deps``, bound to the
one version searched: no tool argument names a library or a version.

A run is bounded by ``UsageLimits`` (tool calls, ``run_code`` included, requests and tokens),
Code Mode's ``max_tool_calls`` per snippet, Monty's resource limits, and the harness
``SpendLimits`` over the spend ledger (#95). Passing any of them ends the run: a Monty limit that
Code Mode would hand back to the model as a retry ends it too (``_RunEnders``). So does a read that
fails on the host: its error is recorded by class and the sandbox sees only ``READ_FAILED``, so no
SQL, DSN or path reaches the model, a result or a span.

Telemetry: the model is instrumented with ``include_content=False`` (the factory's, or ours when
it is not), so the agent run, each model request and each tool call get a span without prompts,
answers or tool arguments; the read tools' spans nest inside ``run_code``'s. Token usage goes to
the global meter (``gen_ai.client.token.usage``).
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

import pydantic_monty
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import (
    AbstractCapability,
    ValidatedToolArgs,
    WrapToolExecuteHandler,
)
from pydantic_ai.exceptions import (
    AgentRunError,
    ToolRetryError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings, InstrumentedModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.code_mode import CodeMode
from pydantic_ai_harness.spend import SpendLimitExceeded

from exactdocs.retrieval.adapters.driven.ai_guidance_sdk import (
    UsageFloor,
    guidance_capabilities,
    guidance_workspace,
)
from exactdocs.retrieval.adapters.driven.harness_spend import agent_limits
from exactdocs.retrieval.constants import (
    AGENT_SEARCH_LIMIT,
    EXPLORER_GUIDANCE,
    EXPLORER_INSTRUCTIONS,
    EXPLORER_TOOLS,
    EXPLORER_TRUSTED_GUIDANCE,
    MAX_AGENT_PICKS,
    READ_FAILED,
    RUN_CODE,
    SANDBOX_LIMIT_MARKERS,
)
from exactdocs.retrieval.errors import AgentStoppedError, ProviderUnsupportedError
from exactdocs.retrieval.models import (
    AgentBounds,
    AgentPick,
    AgentRun,
    FallbackReason,
    GuidanceFiles,
    OutlineNode,
)
from exactdocs.retrieval.ports.driven import DocsBrowser, SpendLedger
from exactdocs_kernel import Clock


class ArticleItem(TypedDict):
    """An article of the version."""

    path: str
    """Its path, the argument of ``article_outline`` and ``read_article``."""
    title: str
    """Its title."""


class OutlineHeading(TypedDict):
    """One heading of an article's outline."""

    heading_path: list[str]
    """The heading and its parents, outermost first."""
    chunk_id: str | None
    """The chunk holding the heading, for ``read_chunk``; null when none records it."""


class ArticleOutlineResult(TypedDict):
    """An article's headings in document order (no body text)."""

    path: str
    """The article."""
    found: bool
    """False when the version has no article at this path."""
    headings: list[OutlineHeading]
    """Every heading, in document order."""


class ArticleRead(TypedDict):
    """An article's Markdown."""

    path: str
    """The article."""
    found: bool
    """False when the version has no article at this path."""
    content: str
    """Its text, verbatim; empty when not found."""
    truncated: bool
    """True when the text was cut."""


class ChunkRead(TypedDict):
    """One chunk (a section) of the version."""

    chunk_id: str
    """Its ID."""
    found: bool
    """False when the version has no such chunk."""
    article_path: str
    """The article it belongs to; empty when not found."""
    heading_path: list[str]
    """Its headings, outermost first."""
    content: str
    """Its text, verbatim; empty when not found."""
    prev_chunk_id: str | None
    """The chunk before it in the article."""
    next_chunk_id: str | None
    """The chunk after it in the article."""


class SearchHitItem(TypedDict):
    """One BM25 hit of ``search_docs``."""

    chunk_id: str
    """The chunk's ID, for ``read_chunk`` and the answer."""
    article_path: str
    """Its article."""
    heading_path: list[str]
    """Its headings, outermost first."""
    snippet: str
    """The matching part of its text."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Reads:
    """The agent's ``deps``: the browser of the version searched, and its failed reads."""

    browser: DocsBrowser
    """The read tools, bound to the version searched."""
    failures: list[str] = field(default_factory=list)
    """The class of each exception a read raised; any ends the run (``agent_failed``)."""


class _ReadFailedError(RuntimeError):
    """What the sandbox sees when a read fails: a fixed text, never the host's error."""

    def __init__(self) -> None:
        """Say a read failed, and nothing else."""
        super().__init__(READ_FAILED)


class _HostFailureError(Exception):
    """A read failed on the host (the database, the catalog): the run ends."""


async def _guarded[T](ctx: RunContext[Reads], read: Callable[[DocsBrowser], Awaitable[T]]) -> T:
    """Run one read; a host error is recorded by class and replaced by a fixed one.

    The host's message (SQL, a DSN, a path) never reaches the sandbox, the model or a span;
    ``_RunEnders`` ends the run once the snippet returns.

    Args:
        ctx: The run.
        read: The read, given the browser.

    Returns:
        What the read returned.

    Raises:
        _ReadFailedError: The read raised anything.
    """
    # Gathered rather than caught, so the fixed error is raised with no chained host error
    # (a span's stack trace would quote it).
    (outcome,) = await asyncio.gather(read(ctx.deps.browser), return_exceptions=True)
    if isinstance(outcome, Exception):
        ctx.deps.failures.append(type(outcome).__name__)
        raise _ReadFailedError
    if isinstance(outcome, BaseException):  # cancellation and the like pass through
        raise outcome
    return outcome


async def list_articles(ctx: RunContext[Reads], prefix: str = "") -> list[ArticleItem]:
    """List the articles of the documentation, by path.

    Args:
        ctx: The run; its ``deps`` reads the version searched.
        prefix: Only articles inside this folder (e.g. ``guide``); empty for every article.

    Returns:
        The articles (at most 200).
    """
    found = await _guarded(ctx, lambda browser: browser.list_articles(prefix))
    return [ArticleItem(path=a.path, title=a.title) for a in found]


def _headings(nodes: Sequence[OutlineNode], parents: tuple[str, ...]) -> list[OutlineHeading]:
    """Flatten an outline's tree in document order.

    Args:
        nodes: Sibling headings.
        parents: The headings above them.

    Returns:
        Each heading with its path and chunk, then the headings under it.
    """
    flat: list[OutlineHeading] = []
    for node in nodes:
        path = (*parents, node.heading)
        chunk = None if node.entry is None else str(node.entry.chunk_id)
        flat.append(OutlineHeading(heading_path=list(path), chunk_id=chunk))
        flat.extend(_headings(node.children, path))
    return flat


async def article_outline(ctx: RunContext[Reads], path: str) -> ArticleOutlineResult:
    """Read the headings of one article, each with the chunk that holds it (no body text).

    Args:
        ctx: The run; its ``deps`` reads the version searched.
        path: The article's path, as ``list_articles`` gives it.

    Returns:
        The headings in document order.
    """
    found = await _guarded(ctx, lambda browser: browser.article_outline(path))
    if found is None:
        return ArticleOutlineResult(path=path, found=False, headings=[])
    headings = _headings(found.sections, ())
    if found.preamble is not None:
        preamble = OutlineHeading(heading_path=[], chunk_id=str(found.preamble.chunk_id))
        headings.insert(0, preamble)
    return ArticleOutlineResult(path=path, found=True, headings=headings)


async def read_article(ctx: RunContext[Reads], path: str) -> ArticleRead:
    """Read one article's Markdown (long articles are cut; prefer outlines and chunks).

    Args:
        ctx: The run; its ``deps`` reads the version searched.
        path: The article's path, as ``list_articles`` gives it.

    Returns:
        The article's text.
    """
    found = await _guarded(ctx, lambda browser: browser.read_article(path))
    if found is None:
        return ArticleRead(path=path, found=False, content="", truncated=False)
    return ArticleRead(path=path, found=True, content=found.content, truncated=found.truncated)


async def read_chunk(ctx: RunContext[Reads], chunk_id: str) -> ChunkRead:
    """Read one chunk (a section of an article) by its ID.

    Args:
        ctx: The run; its ``deps`` reads the version searched.
        chunk_id: An ID an outline or a search returned.

    Returns:
        The chunk's text and where it is.
    """
    found = await _guarded(ctx, lambda browser: browser.read_chunk(chunk_id))
    if found is None:
        return ChunkRead(
            chunk_id=chunk_id,
            found=False,
            article_path="",
            heading_path=[],
            content="",
            prev_chunk_id=None,
            next_chunk_id=None,
        )
    row = found.row
    return ChunkRead(
        chunk_id=str(row.chunk_id),
        found=True,
        article_path=row.article_path,
        heading_path=list(found.chunk.heading_path),
        content=found.chunk.content,
        prev_chunk_id=None if row.prev_chunk_id is None else str(row.prev_chunk_id),
        next_chunk_id=None if row.next_chunk_id is None else str(row.next_chunk_id),
    )


async def search_docs(ctx: RunContext[Reads], query: str, limit: int = 10) -> list[SearchHitItem]:
    """Search the documentation with keywords (BM25); identifiers and exact words work best.

    Args:
        ctx: The run; its ``deps`` reads the version searched.
        query: The words to look for.
        limit: How many hits at most (1 to 20).

    Returns:
        The best hits, best first.
    """
    wanted = min(limit, AGENT_SEARCH_LIMIT)
    found = await _guarded(ctx, lambda browser: browser.search_docs(query, wanted))
    return [
        SearchHitItem(
            chunk_id=str(hit.chunk_id),
            article_path=chunk.row.article_path,
            heading_path=list(chunk.chunk.heading_path),
            snippet=hit.snippet,
        )
        for hit, chunk in found
    ]


def read_tools() -> tuple[Callable[..., Awaitable[object]], ...]:
    """Name the read tools, callable only inside ``run_code``.

    Returns:
        ``list_articles``, ``article_outline``, ``read_article``, ``read_chunk``, ``search_docs``.
    """
    return (list_articles, article_outline, read_article, read_chunk, search_docs)


class _Pick(BaseModel):
    """A chunk that answers the question."""

    model_config = ConfigDict(use_attribute_docstrings=True, extra="ignore")

    chunk_id: str
    """A chunk ID a read function returned."""
    justification: str
    """One sentence: why this chunk answers the question."""


class _Answer(BaseModel):
    """The chunks that answer the question, best first."""

    model_config = ConfigDict(use_attribute_docstrings=True, extra="ignore")

    picks: list[_Pick] = Field(max_length=MAX_AGENT_PICKS)
    """The chunks, best first; empty when nothing answers the question."""


class _SandboxLimitError(Exception):
    """A ``run_code`` snippet tripped one of Monty's resource limits: the run ends."""


def _tripped(error: BaseException) -> bool:
    """Say whether a failed tool call was Monty stopping a snippet at a resource limit.

    Code Mode reports it as a retry for the model (``ToolRetryError`` from a ``ModelRetry``
    raised from Monty's error); the error chain still holds Monty's error.

    Args:
        error: What the tool call raised.

    Returns:
        True for a time, memory or host-interaction limit, or a sandbox worker that crashed.
    """
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, pydantic_monty.MontyCrashedError):
            return True
        if isinstance(seen, pydantic_monty.MontyRuntimeError):
            message = seen.display(format="msg")
            return any(marker in message for marker in SANDBOX_LIMIT_MARKERS)
        seen = seen.__cause__ or seen.__context__
    return False


class _RunEnders(AbstractCapability[Reads]):
    """Ends the run on a tripped Monty limit or a failed read, instead of a model retry.

    Both are checked when a ``run_code`` call ends; a failed read ends the run even when the
    snippet caught its error.
    """

    async def wrap_tool_execute(
        self,
        ctx: RunContext[Reads],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: WrapToolExecuteHandler,
    ) -> object:
        """Run the tool; for ``run_code``, end the run on a tripped limit or a failed read.

        Args:
            ctx: The run.
            call: The tool call.
            tool_def: The tool's definition.
            args: Its validated arguments.
            handler: Runs the tool.

        Returns:
            What the tool returned.

        Raises:
            _HostFailureError: A read of the snippet failed on the host.
            _SandboxLimitError: The snippet tripped a resource limit.
        """
        del tool_def
        if call.tool_name != RUN_CODE:
            return await handler(args)
        try:
            result = await handler(args)
        except ToolRetryError as error:
            if ctx.deps.failures:
                raise _HostFailureError from None
            if _tripped(error):
                raise _SandboxLimitError from error
            raise
        if ctx.deps.failures:
            raise _HostFailureError
        return result


def _instrumented(model: object) -> InstrumentedModel:
    """Narrow the factory's handle to a pydantic-ai model instrumented without content.

    Args:
        model: What ``ModelFactory.chat_model`` returned.

    Returns:
        The model: the factory's when it records no content, else instrumented here with
        ``include_content=False`` (the agent run then records its own and its tools' spans too).

    Raises:
        ProviderUnsupportedError: The handle is not a pydantic-ai model.
    """
    if not isinstance(model, Model):
        role, reason = "llm", "it built no chat model"
        raise ProviderUnsupportedError(role, reason)
    if isinstance(model, InstrumentedModel):
        if not model.instrumentation_settings.include_content:
            return model
        model = model.wrapped
    return InstrumentedModel(model, InstrumentationSettings(include_content=False))


def _guidance_words(guidance: GuidanceFiles | None) -> str:
    """Say in the instructions how to take the repository's notes.

    Args:
        guidance: The run's files, if any.

    Returns:
        Nothing without guidance; the untrusted-note wording, and for a trusted library also
        the wording that introduces its root file.
    """
    if guidance is None:
        return ""
    return EXPLORER_GUIDANCE + (EXPLORER_TRUSTED_GUIDANCE if guidance.trusted else "")


def _code_mode(bounds: AgentBounds) -> CodeMode[Reads]:
    """Put the read tools behind ``run_code``, within Monty's resource limits.

    Args:
        bounds: The run's limits.

    Returns:
        The capability.
    """
    return CodeMode(
        tools=list(EXPLORER_TOOLS),
        max_tool_calls=bounds.max_tool_calls,
        resource_limits={
            "max_duration_secs": bounds.sandbox_seconds,
            "max_memory": bounds.sandbox_memory,
            "max_suspensions": bounds.sandbox_suspensions,
        },
    )


async def explore(
    model: object,
    browser: DocsBrowser,
    run: AgentRun,
    *,
    ledger: SpendLedger,
    clock: Clock,
) -> list[AgentPick]:
    """Run the explorer agent on the question and return its picks.

    Args:
        model: The ``llm`` role's pydantic-ai model.
        browser: The read tools on the version searched (the agent's ``deps``).
        run: The question, the limits and who pays.
        ledger: The spend rows the harness ``SpendLimits`` reads and records to.
        clock: Decides the spend windows.

    Returns:
        At most ``run.limit`` picks, best first, as the model wrote them.

    Raises:
        AgentStoppedError: A budget (``llm_budget_reached``), a limit (``agent_limit_reached``)
            or a failure (``agent_failed``) ended the run.
    """
    limits = agent_limits(
        ledger=ledger, budgets=run.budgets, caller=run.caller, clock=clock.now, price=run.price
    )
    bounds = run.bounds
    usage = UsageLimits(
        request_limit=bounds.max_requests,
        total_tokens_limit=bounds.max_tokens,
        tool_calls_limit=bounds.max_tool_calls,
    )
    guidance = run.guidance
    chat = _instrumented(model)
    if guidance:  # it streams: a stream that reports no usage is counted by its characters
        chat = InstrumentedModel(UsageFloor(chat.wrapped), chat.instrumentation_settings)
    agent = Agent(
        chat,
        name="exactdocs-explorer",
        deps_type=Reads,
        output_type=_Answer,
        instructions=EXPLORER_INSTRUCTIONS + _guidance_words(guidance),
        tools=read_tools(),
        capabilities=[
            _code_mode(bounds),
            limits.spend,
            _RunEnders(),
            *(guidance_capabilities(guidance) if guidance else ()),
        ],
    )
    reads = Reads(browser=browser)
    # Repo guidance (RET-08): only this version's files, in a read-only workspace of their own.
    workspace = guidance_workspace(guidance) if guidance else None
    try:
        result = await agent.run(run.question, deps=reads, usage_limits=usage, workspace=workspace)
    except SpendLimitExceeded as error:  # a UsageLimitExceeded too: checked first
        reason, detail = FallbackReason.LLM_BUDGET_REACHED, "spend limit"
        raise AgentStoppedError(reason.value, detail) from error
    except UsageLimitExceeded as error:
        reason, detail = FallbackReason.AGENT_LIMIT_REACHED, "usage limit"
        raise AgentStoppedError(reason.value, detail) from error
    except _HostFailureError as error:
        reason, detail = FallbackReason.AGENT_FAILED, ",".join(dict.fromkeys(reads.failures))
        raise AgentStoppedError(reason.value, detail) from error
    except _SandboxLimitError as error:
        reason, detail = FallbackReason.AGENT_LIMIT_REACHED, "sandbox limit"
        raise AgentStoppedError(reason.value, detail) from error
    except (UnexpectedModelBehavior, AgentRunError) as error:
        reason, detail = FallbackReason.AGENT_FAILED, type(error).__name__
        raise AgentStoppedError(reason.value, detail) from error
    picks = result.output.picks[: run.limit]
    return [AgentPick(chunk_id=p.chunk_id, justification=p.justification) for p in picks]
