"""Judge agreement: export answers for hand labelling, then compare the labels with the judge.

``sample`` writes a YAML file of answers with blank ``grade`` and ``wrong_version`` fields; the
judge's own grades are left out so they cannot steer the labeller. ``agreement`` reads the file
back once labelled and compares each label with the judge's grade in the report.
"""

import hashlib
from collections import Counter
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from agent_bench.judge import GRADES
from agent_bench.report import BenchReport, QuestionResult

SAMPLE_SIZE: Final[int] = 50
"""Answers in a labelling sample by default (the issue asks for at least 50)."""


def answer_id(row: QuestionResult) -> str:
    """Identify one answer across the report and the labels.

    Args:
        row: The question record.

    Returns:
        ``<agent model> | <retrieval> | <case>``.
    """
    return f"{row.agent_model} | {row.retrieval} | {row.case}"


def sample(report: BenchReport, size: int, seed: int) -> list[dict[str, Any]]:
    """Pick answers to label by hand, at random but reproducibly (the same seed, the same pick).

    Args:
        report: The run.
        size: How many (all of them when the run has fewer).
        seed: The random seed.

    Returns:
        One entry per answer, in report order: the case, its reference and facts, and the
        answer, with ``grade`` and ``wrong_version`` blank for the labeller.
    """

    def draw(row: QuestionResult) -> str:
        """Order answers by a hash of the seed and the answer, so a sample is reproducible.

        Args:
            row: The answer.

        Returns:
            Its sort key.
        """
        return hashlib.sha256(f"{seed}:{answer_id(row)}".encode()).hexdigest()

    picked = {answer_id(row) for row in sorted(report.questions, key=draw)[:size]}
    return [
        {
            "id": answer_id(row),
            "project": row.project,
            "version": row.version,
            "kind": row.kind,
            "question": row.question,
            "reference": row.reference,
            "facts": row.facts,
            "answer": row.answer,
            "grade": "",
            "wrong_version": "",
        }
        for row in report.questions
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
