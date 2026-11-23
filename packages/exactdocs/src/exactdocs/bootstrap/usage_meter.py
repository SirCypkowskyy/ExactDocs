"""Usage counting where REST and MCP serve reads, searches and answers (#510).

The usage domain counts; which served request is a read, a search or an answer is decided here,
where bootstrap hands the driving ports to the REST and MCP adapters. Each counted port is
wrapped: the request is served first, then counted in memory (it never waits for the database)
with the account and API token of the request (``bootstrap.caller``). A request that fails is
not counted. Calls made inside the server (the answering agent's own reads, the jobs) use the
unwrapped ports and count nothing; so does a stdio MCP process, which opens the database
read-only. A background loop writes the counts every ``USAGE_FLUSH_SECONDS``.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from exactdocs.bootstrap.caller import current_account_id, current_api_identity
from exactdocs.bootstrap.cancellation import being_cancelled
from exactdocs.bootstrap.constants import USAGE_STOP_SECONDS
from exactdocs.catalog import CatalogModule
from exactdocs.catalog.dtos import Article, GetArticleQuery
from exactdocs.catalog.ports.driving import GetArticle
from exactdocs.retrieval import RetrievalModule
from exactdocs.retrieval.dtos import (
    AnswerQuery,
    AnswerResult,
    ChunkOut,
    QueryDocsQuery,
    QueryDocsResult,
    ReadChunkQuery,
    SearchAllQuery,
    SearchAllResult,
    SearchDocsQuery,
    SearchDocsResult,
)
from exactdocs.retrieval.ports.driven import AnswerProgress
from exactdocs.retrieval.ports.driving import (
    AnswerQuestion,
    QueryDocs,
    ReadChunk,
    SearchAllLibraries,
    SearchDocs,
)
from exactdocs.usage.dtos import FlushUsageCommand, RecordUsageCommand
from exactdocs.usage.models import Operation
from exactdocs.usage.ports.driving import FlushUsage, RecordUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageMeter:
    """Counts a served request to the account and API token of the current request."""

    record_usage: RecordUsage
    """The usage domain's in-memory count."""

    async def count(self, operation: Operation, libraries: Iterable[str]) -> None:
        """Count one request; a failure is logged and never fails the request.

        Args:
            operation: What the request did.
            libraries: The libraries it was about.
        """
        try:
            identity = current_api_identity()
            await self.record_usage(
                RecordUsageCommand(
                    operation=operation,
                    libraries=list(libraries),
                    account_id=current_account_id(),
                    token_id=None if identity is None else identity.token_id,
                )
            )
        except Exception:
            logger.warning("could not count a %s", operation.value, exc_info=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredGetArticle:
    """Catalog's ``GetArticle``, each article served counted as a read."""

    get_article: GetArticle
    """The catalog's use case."""
    meter: UsageMeter
    """Counts the read."""

    async def __call__(self, query: GetArticleQuery) -> Article:
        """Read the article, then count it.

        Args:
            query: The version and the article path.

        Returns:
            The article.
        """
        article = await self.get_article(query)
        await self.meter.count(Operation.READ, [article.library])
        return article


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredReadChunk:
    """Retrieval's ``ReadChunk``, each chunk served counted as a read."""

    read_chunk: ReadChunk
    """Retrieval's use case."""
    meter: UsageMeter
    """Counts the read."""

    async def __call__(self, query: ReadChunkQuery) -> ChunkOut:
        """Read the chunk, then count it.

        Args:
            query: The chunk ID.

        Returns:
            The chunk.
        """
        chunk = await self.read_chunk(query)
        await self.meter.count(Operation.READ, [chunk.library])
        return chunk


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredSearchDocs:
    """Retrieval's ``SearchDocs``, each search of one library counted to it."""

    search_docs: SearchDocs
    """Retrieval's use case."""
    meter: UsageMeter
    """Counts the search."""

    async def __call__(
        self, query: SearchDocsQuery, *, caller: str | None = None
    ) -> SearchDocsResult:
        """Search, then count it.

        Args:
            query: The search.
            caller: The account searching (its spend and rate limit).

        Returns:
            The results.
        """
        result = await self.search_docs(query, caller=caller)
        await self.meter.count(Operation.SEARCH, [result.library])
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredSearchAll:
    """Retrieval's ``SearchAllLibraries``: a search of several libraries counts to none."""

    search_all_libraries: SearchAllLibraries
    """Retrieval's use case."""
    meter: UsageMeter
    """Counts the search."""

    async def __call__(
        self, query: SearchAllQuery, *, caller: str | None = None
    ) -> SearchAllResult:
        """Search, then count it: to its one library when it was narrowed to one.

        Args:
            query: The query, the libraries, the filters and the limit.
            caller: The account searching.

        Returns:
            The results.
        """
        result = await self.search_all_libraries(query, caller=caller)
        libraries = [query.library] if query.library else query.libraries
        await self.meter.count(Operation.SEARCH, libraries)
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredQueryDocs:
    """Retrieval's ``QueryDocs`` (MCP ``query-docs``, REST ``/c7/docs``), counted as a search."""

    query_docs: QueryDocs
    """Retrieval's use case."""
    meter: UsageMeter
    """Counts the search."""

    async def __call__(
        self, query: QueryDocsQuery, *, caller: str | None = None
    ) -> QueryDocsResult:
        """Look the docs up, then count it.

        Args:
            query: The library ID and the question.
            caller: The account asking.

        Returns:
            The chunks that fit the budget.
        """
        result = await self.query_docs(query, caller=caller)
        await self.meter.count(Operation.SEARCH, [result.library])
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class MeteredAnswer:
    """Retrieval's ``AnswerQuestion``, each answer counted (to its library when only one)."""

    answer_question: AnswerQuestion
    """Retrieval's use case."""
    meter: UsageMeter
    """Counts the answer."""

    async def __call__(
        self,
        query: AnswerQuery,
        *,
        caller: str | None = None,
        progress: AnswerProgress | None = None,
    ) -> AnswerResult:
        """Answer, then count it.

        Args:
            query: The question, the libraries and the filters.
            caller: The account asking.
            progress: Hears each tool call.

        Returns:
            The answer.
        """
        result = await self.answer_question(query, caller=caller, progress=progress)
        read = [library.library for library in result.libraries]
        await self.meter.count(Operation.ANSWER, read or query.libraries)
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class CountedPorts:
    """The driving ports whose requests are counted, as the REST and MCP adapters get them."""

    get_article: GetArticle
    """Reads an article: a read."""
    read_chunk: ReadChunk
    """Reads a chunk: a read."""
    search_docs: SearchDocs
    """Searches one library: a search."""
    search_all_libraries: SearchAllLibraries
    """Searches several libraries: a search."""
    query_docs: QueryDocs
    """``query-docs``: a search."""
    answer_question: AnswerQuestion
    """The answering agent: an answer."""


def counted(
    catalog: CatalogModule, retrieval: RetrievalModule, meter: UsageMeter | None
) -> CountedPorts:
    """Return the ports the adapters serve reads, searches and answers with.

    Args:
        catalog: The catalog module.
        retrieval: The retrieval module.
        meter: Counts each request; ``None`` counts nothing (a read-only stdio process).

    Returns:
        The ports, wrapped to count when there is a meter.
    """
    if meter is None:
        return CountedPorts(
            get_article=catalog.get_article,
            read_chunk=retrieval.read_chunk,
            search_docs=retrieval.search_docs,
            search_all_libraries=retrieval.search_all_libraries,
            query_docs=retrieval.query_docs,
            answer_question=retrieval.answer_question,
        )
    return CountedPorts(
        get_article=MeteredGetArticle(get_article=catalog.get_article, meter=meter),
        read_chunk=MeteredReadChunk(read_chunk=retrieval.read_chunk, meter=meter),
        search_docs=MeteredSearchDocs(search_docs=retrieval.search_docs, meter=meter),
        search_all_libraries=MeteredSearchAll(
            search_all_libraries=retrieval.search_all_libraries, meter=meter
        ),
        query_docs=MeteredQueryDocs(query_docs=retrieval.query_docs, meter=meter),
        answer_question=MeteredAnswer(answer_question=retrieval.answer_question, meter=meter),
    )


@asynccontextmanager
async def flushing(flush: FlushUsage, *, every: float) -> AsyncGenerator[None]:
    """Write the usage counts every ``every`` seconds while the block runs, and once at the end.

    A write that fails keeps its counts for the next one (logged). The last write waits at most
    ``USAGE_STOP_SECONDS``; what it could not write is lost, and logged.

    Args:
        flush: The usage domain's write of the pending counts.
        every: Seconds between writes.

    Yields:
        Nothing: the block runs while the writes go on.
    """

    async def loop() -> None:
        """Write the counts, then wait, until cancelled."""
        while True:
            await asyncio.sleep(every)
            try:
                await flush(FlushUsageCommand())
            except Exception:
                if being_cancelled():  # the error replaced the server's stop: stop all the same
                    raise
                logger.warning("writing the usage counts failed; retried soon", exc_info=True)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=USAGE_STOP_SECONDS)
        if done and not task.cancelled() and (error := task.exception()) is not None:
            logger.warning("writing the usage counts failed while it stopped", exc_info=error)
        try:
            async with asyncio.timeout(USAGE_STOP_SECONDS):
                await flush(FlushUsageCommand())
        except Exception:
            logger.warning("the last usage counts could not be written", exc_info=True)
