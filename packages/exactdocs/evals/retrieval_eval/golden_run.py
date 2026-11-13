"""Run a retrieval mode over the golden set: one library per project, one dataset for all.

The retrieval suite (``suite.py``) asks one library, the fixture's. The golden set's cases name
their project, and each project is its own library (``Project.library``), so ``GoldenRetriever``
sends every question to its project's library through the suite's own ``SearchDocsRetriever``,
and ``run_golden`` scores the whole set with the suite's evaluators and ``evaluate_mode``. The
ingestion benchmark (#346) runs BM25 this way; the retrieval benchmark (#347) can run any mode.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic_evals import Dataset

from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question, RetrievalDataset
from retrieval_eval.evaluators import Cost, SectionMatch, VersionAndRank, same_section
from retrieval_eval.golden import Corpus
from retrieval_eval.retrievers import Retriever, SearchDocsRetriever
from retrieval_eval.suite import MODES, EvalMode, ModeOutcome, RetrievalUnderTest, evaluate_mode

type HeldHeadings = Callable[[Hit], frozenset[tuple[str, ...]]]
"""The heading paths the chunk a hit came from holds (its own and every merged heading)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldenRetriever:
    """Implements ``Retriever``: answers each question from its project's library."""

    projects: Mapping[str, Retriever]
    """The retriever of each project's library, by project ID."""

    async def answer(self, question: Question) -> Answer:
        """Ask the question's project.

        Args:
            question: A golden question (its ``project`` is set).

        Returns:
            That library's answer.

        Raises:
            ValueError: The question names no project of the corpus.
        """
        retriever = self.projects.get(question.project or "")
        if retriever is None:
            message = f"no library for project {question.project!r}"
            raise ValueError(message)
        return await retriever.answer(question)


def golden_retriever(retrieval: RetrievalUnderTest, corpus: Corpus, mode: str) -> GoldenRetriever:
    """Build the retriever that asks each project's library in one mode.

    Args:
        retrieval: The app's retrieval module, with the corpus imported (``import_corpus``).
        corpus: The corpus: each project's library and pinned commits.
        mode: The retrieval mode.

    Returns:
        The retriever.
    """
    return GoldenRetriever(
        projects={
            project.id: SearchDocsRetriever(
                search=retrieval.search_docs,
                read_chunk=retrieval.read_chunk,
                library=project.library,
                mode=mode,
                commits={v.name: v.commit for v in project.versions},
            )
            for project in corpus.projects
        }
    )


def nested_match(held: HeldHeadings) -> SectionMatch:
    """Build the match rule that holds whatever depth a configuration cuts at.

    A hit of the expected version and article answers the expected section when its heading path
    is the expected one; or the expected path is a non-empty prefix of it (a finer cut: the hit is
    part of the expected section); or its path is a prefix of the expected one and its chunk holds
    the expected heading (a coarser cut merged the section into it).

    Args:
        held: The heading paths the chunk of a hit holds.

    Returns:
        The rule.
    """

    def matches(expected: Hit, hit: Hit) -> bool:
        """Tell whether ``hit`` answers ``expected``.

        Args:
            expected: The expected section.
            hit: A returned hit.

        Returns:
            True when it does, by the rule above.
        """
        if (hit.version, hit.article) != (expected.version, expected.article):
            return False
        want, got = tuple(expected.heading_path), tuple(hit.heading_path)
        if got == want or (want and got[: len(want)] == want):
            return True
        return want[: len(got)] == got and want in held(hit)

    return matches


async def run_golden(
    dataset: RetrievalDataset,
    retriever: Retriever,
    *,
    mode: EvalMode = MODES[0],
    matches: SectionMatch = same_section,
) -> ModeOutcome:
    """Run the golden set through a retriever and score it as the suite scores a mode.

    Args:
        dataset: The golden set (``load_golden``); its evaluators are replaced.
        retriever: Answers each question (``golden_retriever``).
        mode: The mode it answers in, for the outcome (BM25 by default).
        matches: When a hit counts as the expected section.

    Returns:
        The mode's outcome: recall@1/5/10 and MRR over the answerable cases, the wrong-version
        cases, the misses.
    """
    scored = Dataset[Question, Answer, CaseInfo](
        name=dataset.name,
        cases=list(dataset.cases),
        evaluators=[VersionAndRank(matches=matches), Cost()],
    )
    return await evaluate_mode(scored, mode, retriever)
