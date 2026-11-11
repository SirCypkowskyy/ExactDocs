"""How the suite asks a mode: a ``Retriever`` answers one question with ranked hits."""

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from exactdocs.retrieval.dtos import ReadChunkQuery, SearchDocsQuery
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import ReadChunk, SearchDocs
from retrieval_eval.dataset import Answer, Hit, Question
from retrieval_eval.evaluators import RECALL_AT


class Retriever(Protocol):
    """Answers a question in one retrieval mode."""

    async def answer(self, question: Question) -> Answer:
        """Search the question's version.

        Args:
            question: The query and the version it is pinned to.

        Returns:
            The hits, best first, with the version each came from and what the answer cost.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchDocsRetriever:
    """Asks the app's ``SearchDocs`` use case, in one mode, for the top ``max(RECALL_AT)`` hits.

    The version of every hit is taken from the chunk itself, not from the answer: each chunk ID is
    read back with ``ReadChunk``, which serves it from the version its ID was issued for. So a
    chunk of another version that a search lets through is caught even when the answer labels it
    with the version asked for. The pinned commit is taken from the repository. Latency is the
    search alone, without those reads. Tokens and USD are what the spend ledger grew by during the
    search (the query's embedding in a hybrid mode), when ``spent`` is given; 0 otherwise.
    """

    search: SearchDocs
    """The use case under test."""
    read_chunk: ReadChunk
    """Reads a chunk back by its ID, from the version that ID names."""
    library: str
    """The fixture library's ID."""
    mode: str
    """The retrieval mode asked for."""
    commits: Mapping[str, str]
    """The commit SHA each version points at."""
    spent: Callable[[], Awaitable[tuple[int, float]]] | None = None
    """Reads what the instance's models have cost so far (tokens, USD), from the spend ledger;
    the difference around a search is that search's cost (the query's embedding)."""

    async def answer(self, question: Question) -> Answer:
        """Search the question's version in ``mode``, then read every hit back by its ID.

        Args:
            question: The query and its version.

        Returns:
            The hits as the use case ranked them, each with the version and commit of its chunk.
        """
        before = await self.spent() if self.spent is not None else (0, 0.0)
        started = time.perf_counter()
        result = await self.search(
            SearchDocsQuery(
                library=self.library,
                ref=question.version,
                query=question.query,
                tags=list(question.tags),
                tags_match=TagMatch(question.tags_match),
                limit=max(RECALL_AT),
                mode=self.mode,
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        after = await self.spent() if self.spent is not None else (0, 0.0)
        hits = []
        for found in result.results:
            chunk = await self.read_chunk(ReadChunkQuery(chunk_id=found.chunk_id))
            same_library = chunk.library.casefold() == self.library.casefold()
            hits.append(
                Hit(
                    version=chunk.version if same_library else f"{chunk.library}/{chunk.version}",
                    article=chunk.article_path,
                    heading_path=list(chunk.heading_path),
                    commit_sha=chunk.commit_sha,
                )
            )
        return Answer(
            hits=hits,
            pinned_commit=self.commits.get(question.version),
            answered_by=result.retrieval_mode.value,
            reranked=result.reranked,
            fallback_reason=None
            if result.fallback_reason is None
            else result.fallback_reason.value,
            search_ms=elapsed_ms,
            tokens=after[0] - before[0],
            usd=after[1] - before[1],
        )
