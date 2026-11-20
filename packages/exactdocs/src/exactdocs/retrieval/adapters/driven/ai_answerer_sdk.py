"""The pydantic-ai side of ``ai_answerer``: loaded only once a question is answered (#428).

The answering agent is the explorer's sibling (``ai_explorer_sdk``) and shares its run control:
harness **Code Mode** with ``run_code`` as the only model-visible tool, the read tools inside the
Monty sandbox only, ``UsageLimits`` (tool calls, requests, tokens), Monty's resource limits, the
harness ``SpendLimits``, ``RunEnders`` (loops, tripped limits, failed reads) and a model
instrumented without content. Its read tools take a library, but only one of the question's
scope: the ``LibrariesBrowser`` it gets as ``deps`` answers nothing for another.

It answers in Markdown with its sources (library, chunk ID, an optional quote and a reason). The
harness ``OutputGuardrail`` keeps only the citations the browser ``admit``s; only their count is
logged. A run that stops returns what it used and why, never raises for it.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_ai_harness.guardrails import GuardrailResult, OutputGuardrail

from exactdocs.retrieval.adapters.driven.ai_explorer_sdk import (
    STOPPING_ERRORS,
    ArticleItem,
    ArticleOutlineResult,
    ChunkRead,
    HostFailureError,
    Reads,
    RunEnders,
    attempt,
    code_mode,
    guarded,
    instrumented,
    outline_headings,
    stop_reason,
)
from exactdocs.retrieval.adapters.driven.harness_spend import agent_limits
from exactdocs.retrieval.constants import (
    AGENT_SEARCH_LIMIT,
    ANSWERER_INSTRUCTIONS,
    ANSWERER_TOOLS,
    MAX_ANSWER_CHARS,
    MAX_ANSWER_SOURCES,
)
from exactdocs.retrieval.models import (
    AgentRun,
    AnswerCitation,
    AnswerDraft,
    AnswerUsage,
)
from exactdocs.retrieval.ports.driven import AnswerProgress, LibrariesBrowser, SpendLedger
from exactdocs_kernel import Clock

logger = logging.getLogger(__name__)

type Ctx = RunContext[Reads[LibrariesBrowser]]
"""The run, as the read tools see it."""


def _not_found(chunk_id: str) -> ChunkRead:
    """Build what ``read_chunk`` returns for a chunk outside the scope.

    Args:
        chunk_id: The ID asked for.

    Returns:
        The read, ``found`` false.
    """
    return ChunkRead(
        chunk_id=chunk_id,
        found=False,
        article_path="",
        heading_path=[],
        content="",
        prev_chunk_id=None,
        next_chunk_id=None,
    )


async def list_libraries(ctx: Ctx) -> list[dict[str, str]]:
    """List the libraries you may read, each at the one version you read.

    Args:
        ctx: The run; its ``deps`` reads the question's libraries.

    Returns:
        ``library`` (pass it to the other functions) and ``version`` of each.
    """
    return [{"library": lib, "version": ref} for lib, ref in ctx.deps.browser.libraries()]


async def search_docs(
    ctx: Ctx, query: str, library: str | None = None, limit: int = 10
) -> list[dict[str, object]]:
    """Search the documentation with keywords (BM25); identifiers and exact words work best.

    Args:
        ctx: The run; its ``deps`` reads the question's libraries.
        query: The words to look for.
        library: One library to search (as ``list_libraries`` names it); none: all of them.
        limit: How many hits at most (1 to 20).

    Returns:
        The best hits, best first: ``library``, ``chunk_id``, ``article_path``, ``heading_path``
        and ``snippet`` of each.
    """
    wanted = min(limit, AGENT_SEARCH_LIMIT)
    found = await guarded(ctx, lambda browser: browser.search_docs(query, library, wanted))
    return [
        {
            "library": lib,
            "chunk_id": str(hit.chunk_id),
            "article_path": chunk.row.article_path,
            "heading_path": list(chunk.chunk.heading_path),
            "snippet": hit.snippet,
        }
        for lib, hit, chunk in found
    ]


async def list_articles(ctx: Ctx, library: str, prefix: str = "") -> list[ArticleItem]:
    """List the articles of one library's documentation, by path.

    Args:
        ctx: The run; its ``deps`` reads the question's libraries.
        library: The library, as ``list_libraries`` names it.
        prefix: Only articles inside this folder (e.g. ``guide``); empty for every article.

    Returns:
        The articles (at most 200); none for a library you may not read.
    """
    found = await guarded(ctx, lambda browser: browser.list_articles(library, prefix))
    return [ArticleItem(path=a.path, title=a.title) for a in found]


async def article_outline(ctx: Ctx, library: str, path: str) -> ArticleOutlineResult:
    """Read the headings of one article, each with the chunk that holds it (no body text).

    Args:
        ctx: The run; its ``deps`` reads the question's libraries.
        library: The library, as ``list_libraries`` names it.
        path: The article's path, as ``list_articles`` or ``search_docs`` gives it.

    Returns:
        The headings in document order.
    """
    found = await guarded(ctx, lambda browser: browser.article_outline(library, path))
    if found is None:
        return ArticleOutlineResult(path=path, found=False, headings=[])
    return ArticleOutlineResult(path=path, found=True, headings=outline_headings(found))


async def read_chunk(ctx: Ctx, library: str, chunk_id: str) -> ChunkRead:
    """Read one chunk (a section of an article) by its ID.

    Args:
        ctx: The run; its ``deps`` reads the question's libraries.
        library: The library, as ``list_libraries`` names it.
        chunk_id: An ID an outline or a search returned.

    Returns:
        The chunk's text and where it is.
    """
    found = await guarded(ctx, lambda browser: browser.read_chunk(library, chunk_id))
    if found is None:
        return _not_found(chunk_id)
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


class _Source(BaseModel):
    """A chunk your answer stands on."""

    model_config = ConfigDict(use_attribute_docstrings=True, extra="ignore")

    library: str
    """Its library, as a read function returned it."""
    chunk_id: str
    """Its chunk ID, as a read function returned it."""
    quote: str | None = None
    """A short passage copied verbatim from the chunk that supports the answer, if one does."""
    reason: str
    """One sentence: why this chunk supports the answer."""


class _Answer(BaseModel):
    """Your answer and its sources."""

    model_config = ConfigDict(use_attribute_docstrings=True, extra="ignore")

    answer: str = Field(max_length=MAX_ANSWER_CHARS)
    """The answer, in Markdown, from what you read only."""
    sources: list[_Source] = Field(max_length=MAX_ANSWER_SOURCES)
    """The chunks it stands on, best first; empty when the documentation does not answer it."""


async def _admitted_only(ctx: Ctx, output: object) -> GuardrailResult:
    """The output guardrail: keep only the sources the caller may be answered with.

    Args:
        ctx: The run; its ``deps`` holds the browser, bound to the question's scope.
        output: The agent's answer (an ``_Answer``).

    Returns:
        ``allow`` when every source is admitted; else ``replace`` with the admitted ones only;
        ``block`` for anything but an answer (the run then fails: ``agent_failed``).

    Raises:
        HostFailureError: The check failed on the host.
    """
    if not isinstance(output, _Answer):
        return GuardrailResult.block()
    sources = output.sources
    pairs = [(s.library, s.chunk_id) for s in sources]
    got = await attempt(ctx, lambda browser: browser.admit(pairs))
    if got is None:
        raise HostFailureError
    admitted = {(lib.casefold(), c) for lib, c in got[0]}
    kept = [s for s in sources if (s.library.strip().casefold(), s.chunk_id) in admitted]
    if len(kept) == len(sources):
        return GuardrailResult.allow()
    ctx.deps.rejected.append(len(sources) - len(kept))
    return GuardrailResult.replace(_Answer(answer=output.answer, sources=kept))


def _used(usage: RunUsage, reads: Reads[LibrariesBrowser]) -> AnswerUsage:
    """Read what a run used.

    Args:
        usage: The run's usage, as pydantic-ai counted it (also when it stopped).
        reads: The run's state, which counted every tool call.

    Returns:
        The usage.
    """
    return AnswerUsage(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        tool_calls=sum(reads.calls.values()),
    )


async def answer(
    model: object,
    browser: LibrariesBrowser,
    run: AgentRun,
    *,
    ledger: SpendLedger,
    clock: Clock,
    progress: AnswerProgress | None = None,
) -> AnswerDraft:
    """Run the answering agent on the question.

    Args:
        model: The ``llm`` role's pydantic-ai model.
        browser: The read tools on the question's libraries (the agent's ``deps``).
        run: The question, the limits and who pays; ``run.limit`` caps the sources.
        ledger: The spend rows the harness ``SpendLimits`` reads and records to.
        clock: Decides the spend windows.
        progress: Hears each tool call.

    Returns:
        The answer and its admitted citations; or, when a budget, a limit, a loop or a failure
        ended the run, why, with what it used.
    """
    limits = agent_limits(
        ledger=ledger, budgets=run.budgets, caller=run.caller, clock=clock.now, price=run.price
    )
    bounds = run.bounds
    usage_limits = UsageLimits(
        request_limit=bounds.max_requests,
        total_tokens_limit=bounds.max_tokens,
        tool_calls_limit=bounds.max_tool_calls,
    )
    agent = Agent(
        instrumented(model),
        name="exactdocs-answerer",
        deps_type=Reads[LibrariesBrowser],
        output_type=_Answer,
        instructions=ANSWERER_INSTRUCTIONS,
        tools=(list_libraries, search_docs, list_articles, article_outline, read_chunk),
        capabilities=[
            code_mode(bounds, ANSWERER_TOOLS),
            limits.spend,
            RunEnders[LibrariesBrowser](),
            OutputGuardrail[Reads[LibrariesBrowser]](guard=_admitted_only),
        ],
    )
    heard = None
    if progress is not None:
        limit = bounds.max_tool_calls

        def heard(made: int) -> None:
            """Pass a call count on.

            Args:
                made: Calls made so far.
            """
            progress.tool_call(made, limit)

    reads = Reads[LibrariesBrowser](
        browser=browser, max_repeated_calls=bounds.max_repeated_calls, progress=heard
    )
    used = RunUsage()
    try:
        result = await agent.run(run.question, deps=reads, usage_limits=usage_limits, usage=used)
    except STOPPING_ERRORS as error:
        reason, detail = stop_reason(error, reads)
        logger.warning("an agentic answer stopped: %s (%s)", reason.value, detail)
        return AnswerDraft(usage=_used(used, reads), stopped=reason)
    output = result.output
    citations = tuple(
        AnswerCitation(library=s.library, chunk_id=s.chunk_id, quote=s.quote, reason=s.reason)
        for s in output.sources[: run.limit]
    )
    return AnswerDraft(
        answer=output.answer,
        citations=citations,
        usage=_used(used, reads),
        rejected=sum(reads.rejected),
    )
