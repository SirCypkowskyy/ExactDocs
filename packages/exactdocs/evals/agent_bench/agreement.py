"""Judge agreement: export answers for hand labelling, then compare the labels with the judge.

``sample`` writes a YAML file of answers with blank ``grade`` and ``wrong_version`` fields; the
judge's own grades are left out so they cannot steer the labeller. ``agreement`` reads the file
back once labelled and compares each label with the judge's grade in the report.
"""

import hashlib
from collections import Counter
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from agent_bench.arms import blind
from agent_bench.judge import GRADES
from agent_bench.report import BenchReport, QuestionResult, counted

ID_DIGITS: Final[int] = 12
"""Hex digits of an answer's ID."""

SAMPLE_SIZE: Final[int] = 50
"""Answers in a labelling sample by default (the issue asks for at least 50)."""
LABELLING_HEADER: Final[str] = """\
# Label each answer against its reference and facts, at its version: set `grade` to one of
#   correct            states every fact, nothing the reference contradicts
#   partially_correct  states some of the facts, nothing contradicted
#   wrong              states none, contradicts the reference, or invents an API or behaviour
#   refused            says the documentation does not cover it or that it does not know (or
#                      declines), states no facts
# For an `unanswerable` case, an answer saying the documentation does not cover it is
# `refused`, not `correct` (the report counts it as right there); answering anyway is `wrong`.
# Names of documentation tools are replaced by [redacted], as the judge read them.
# Set `wrong_version` to true when the answer states something true of another version only,
# else false. Leave `grade` blank to skip an answer. Then run `just agent-bench agreement`.
"""
"""The comment at the top of a labelling sample file: the grades as the judge applies them."""


def answer_id(row: QuestionResult) -> str:
    """Identify one answer across the report and the labels, without telling its model or arm.

    Args:
        row: The question record.

    Returns:
        12 hex digits of a hash of the agent model, arm, retrieval configuration and case, so the
        labeller, like the judge, does not learn which arm answered.
    """
    key = f"{row.agent_model} | {row.arm} | {row.retrieval} | {row.case}"
    return hashlib.sha256(key.encode()).hexdigest()[:ID_DIGITS]


def sample(report: BenchReport, size: int, seed: int) -> list[dict[str, Any]]:
    """Pick answers to label by hand, at random but reproducibly (the same seed, the same pick).

    Args:
        report: The run.
        size: How many (all of them when the run has fewer).
        seed: The random seed.

    Returns:
        One entry per judged answer (runs without an answer have none to label), in report order:
        the case, its reference and facts, and the answer with the arms' names removed as the
        judge read it, with ``grade`` and ``wrong_version`` blank for the labeller.
    """

    def draw(row: QuestionResult) -> str:
        """Order answers by a hash of the seed and the answer, so a sample is reproducible.

        Args:
            row: The answer.

        Returns:
            Its sort key.
        """
        return hashlib.sha256(f"{seed}:{answer_id(row)}".encode()).hexdigest()

    judged = [row for row in report.questions if counted(row) and row.answer]
    picked = {answer_id(row) for row in sorted(judged, key=draw)[:size]}
    return [
        {
            "id": answer_id(row),
            "project": row.project,
            "version": row.version,
            "kind": row.kind,
            "question": row.question,
            "reference": row.reference,
            "facts": row.facts,
            "answer": blind(row.answer),
            "grade": "",
            "wrong_version": "",
        }
        for row in judged
        if answer_id(row) in picked
    ]


class Agreement(BaseModel):
    """How often the judge's grade matches the hand label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    labelled: int
    """Answers with a hand grade."""
    agreed: int
    """Of those, the judge gave the same grade."""
    rate: float | None
    """``agreed / labelled``; ``None`` with no label."""
    wrong_version_labelled: int
    """Answers with a hand ``wrong_version``."""
    wrong_version_agreed: int
    """Of those, the judge said the same."""
    confusion: dict[str, dict[str, int]]
    """Hand grade to the judge's grades and their counts."""


def agreement(report: BenchReport, labels: list[dict[str, Any]]) -> Agreement:
    """Compare hand labels with the judge.

    Args:
        report: The run the sample was taken from.
        labels: The labelled sample; entries with a blank ``grade`` are skipped.

    Returns:
        The agreement.

    Raises:
        ValueError: An entry names an answer the report does not have, or a grade that is not
            one of ``judge.GRADES``.
    """
    judged = {answer_id(row): row for row in report.questions}
    agreed = labelled = version_labelled = version_agreed = 0
    confusion: dict[str, Counter[str]] = {}
    for entry in labels:
        row = judged.get(entry["id"])
        if row is None:
            message = f"{entry['id']!r} is not in the report"
            raise ValueError(message)
        grade = str(entry.get("grade") or "").strip()
        if grade:
            if grade not in GRADES:
                message = f"{entry['id']!r}: grade {grade!r} is not one of {', '.join(GRADES)}"
                raise ValueError(message)
            labelled += 1
            agreed += grade == row.grade
            confusion.setdefault(grade, Counter())[row.grade] += 1
        if isinstance(entry.get("wrong_version"), bool):
            version_labelled += 1
            version_agreed += entry["wrong_version"] == row.wrong_version
    return Agreement(
        labelled=labelled,
        agreed=agreed,
        rate=round(agreed / labelled, 3) if labelled else None,
        wrong_version_labelled=version_labelled,
        wrong_version_agreed=version_agreed,
        confusion={k: dict(v) for k, v in sorted(confusion.items())},
    )
