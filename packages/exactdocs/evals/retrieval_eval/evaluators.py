"""Per-case evaluators: where the expected section ranked, the version of every hit, the cost."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question

RECALL_AT: Final[tuple[int, ...]] = (1, 5, 10)
"""The cut-offs recall is measured at; the suite asks every mode for the largest."""
RIGHT_VERSION: Final[str] = "right_version"
"""The assertion that every hit is of the pinned version."""
RECIPROCAL_RANK: Final[str] = "reciprocal_rank"
"""1 / the rank of the expected section (0 when it is not returned)."""
TOKENS: Final[str] = "tokens"
"""The score holding the model tokens a case cost."""
USD: Final[str] = "usd"
"""The score holding what a case cost, in USD."""


def recall_key(k: int) -> str:
    """Name the recall score at ``k``.

    Args:
        k: The cut-off.

    Returns:
        ``recall@k``.
    """
    return f"recall@{k}"


def wrong_version_hits(question: Question, answer: Answer) -> list[Hit]:
    """Return the hits that are not of the version the question is pinned to.

    A hit is of another version when it names another version, or when it was read from a commit
    other than the one the pinned version points at.

    Args:
        question: The question, with its version.
        answer: What the mode returned.

    Returns:
        The offending hits, best first; empty when every hit is of the pinned version.
    """
    return [
        hit
        for hit in answer.hits
        if hit.version != question.version
        or (answer.pinned_commit is not None and hit.commit_sha not in {None, answer.pinned_commit})
    ]


def rank_of(expected: Hit, answer: Answer) -> int | None:
    """Return the 1-based rank of ``expected`` in the answer, or ``None`` when it is missing."""
    for rank, hit in enumerate(answer.hits, start=1):
        if (hit.version, hit.article, hit.heading_path) == (
            expected.version,
            expected.article,
            expected.heading_path,
        ):
            return rank
    return None


@dataclass(repr=False)
class VersionAndRank(Evaluator[Question, Answer, CaseInfo]):
    """Asserts the version of every hit; scores recall@1/5/10 and the reciprocal rank.

    Recall and rank are scored only for a case whose version has an answer; the version is
    asserted for every case, so a version with no answer must still return nothing of another.
    """

    def evaluate(
        self, ctx: EvaluatorContext[Question, Answer, CaseInfo]
    ) -> Mapping[str, EvaluationReason | float | bool]:
        """Evaluate one case.

        Args:
            ctx: The question, what the mode returned and the expected answer.

        Returns:
            ``right_version`` (with the offending hits as the reason), and for an answerable case
            ``recall@k`` per cut-off and ``reciprocal_rank``.
        """
        wrong = wrong_version_hits(ctx.inputs, ctx.output)
        reason = "; ".join(f"{h.version} {h.article} > {' > '.join(h.heading_path)}" for h in wrong)
        results: dict[str, EvaluationReason | float | bool] = {
            RIGHT_VERSION: EvaluationReason(value=not wrong, reason=reason or None)
        }
        expected = ctx.expected_output.hits if ctx.expected_output else []
        if expected:
            rank = rank_of(expected[0], ctx.output)
            for k in RECALL_AT:
                results[recall_key(k)] = 1.0 if rank is not None and rank <= k else 0.0
            results[RECIPROCAL_RANK] = 1.0 / rank if rank else 0.0
        return results


@dataclass(repr=False)
class Cost(Evaluator[Question, Answer, CaseInfo]):
    """Scores the model tokens and the USD a case cost (both 0 for a mode without a model)."""

    def evaluate(self, ctx: EvaluatorContext[Question, Answer, CaseInfo]) -> Mapping[str, float]:
        """Evaluate one case.

        Args:
            ctx: What the mode returned.

        Returns:
            ``tokens`` and ``usd``.
        """
        return {TOKENS: float(ctx.output.tokens), USD: ctx.output.usd}
