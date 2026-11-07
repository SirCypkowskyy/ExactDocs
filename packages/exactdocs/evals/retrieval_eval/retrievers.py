"""How the suite asks a mode: a ``Retriever`` answers one question with ranked hits."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from exactdocs.retrieval.dtos import SearchDocsQuery
from exactdocs.retrieval.models import TagMatch
from exactdocs.retrieval.ports.driving import SearchDocs
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

    The pinned commit is taken from the repository, not from the answer, so a result read from
    another commit counts as another version even if the answer says otherwise. Tokens and USD are
    0 until the AI modes report their spend (the spend ledger of the decision record).
    """

    search: SearchDocs
    """The use case under test."""
    library: str
    """The fixture library's ID."""
    mode: str
    """The retrieval mode asked for."""
    commits: Mapping[str, str]
    """The commit SHA each version points at."""

    async def answer(self, question: Question) -> Answer:
        """Search the question's version in ``mode``.

        Args:
            question: The query and its version.

        Returns:
            The hits as the use case ranked them.
        """
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
        return Answer(
            hits=[
                Hit(
                    version=result.version,
                    article=hit.article_path,
                    heading_path=list(hit.heading_path),
                    commit_sha=hit.commit_sha,
                )
                for hit in result.results
            ],
            pinned_commit=self.commits.get(question.version),
            answered_by=result.retrieval_mode.value,
        )
