"""The benchmark's report: one row per question, a summary per agent model and retrieval setup."""

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import EvaluationReport

from agent_bench.harness import (
    AgentRun,
    BenchInfo,
    ToolCall,
    grounded,
    read_other_versions,
)
from agent_bench.judge import GRADE, GRADES, WRONG_VERSION
from retrieval_eval.dataset import Question

ERROR: Final[str] = "error"
"""The grade of a question the run or the judge failed on (it is not correct either)."""
CORRECT: Final[str] = "correct"
"""The grade that counts as accurate."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QuestionResult(_Model):
    """One question asked of one agent model under one retrieval configuration."""

    agent_model: str
    """The agent's model."""
    retrieval: str
    """The retrieval configuration's name."""
    case: str
    """The golden case's name."""
    project: str
    """The golden project."""
    kind: str
    """The golden kind."""
    version: str
    """The version asked about."""
    question: str
    """The question."""
    reference: str = ""
    """The case's reference answer."""
    facts: list[str] = Field(default_factory=list)
    """The facts a correct answer must contain."""
    grade: str
    """One of ``judge.GRADES``, or ``error``."""
    wrong_version: bool = False
    """The judge found something true of another version only."""
    grounded: bool | None = None
    """The agent read every answering section; ``None`` when the case has none."""
    other_versions_read: list[str] = Field(default_factory=list)
    """``<version>:<article>`` the agent read of the asked library at another version."""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    """The agent's tool calls."""
    chunks_read: list[str] = Field(default_factory=list)
    """``<chunk ID>@<version>`` of each chunk read in full (``<article>@<version>`` for a whole
    article)."""
    retrieval_modes: list[str] = Field(default_factory=list)
    """How each search was answered."""
    input_tokens: int = 0
    """The agent's input tokens."""
    output_tokens: int = 0
    """The agent's output tokens."""
    usd: float | None = None
    """What the agent's tokens cost; ``None`` when unpriced."""
    seconds: float = 0.0
    """The run's wall time."""
    answer: str = ""
    """The agent's answer."""
    judge_reason: str = ""
    """The judge's reason (or what failed)."""


class Breakdown(_Model):
    """Accuracy over a subset of questions (one kind, one project)."""

    questions: int
    """Questions in the subset."""
    correct: int
    """Graded correct."""
    accuracy: float
    """``correct / questions``."""


class CellSummary(_Model):
    """One agent model under one retrieval configuration."""

    agent_model: str
    """The agent's model."""
    retrieval: str
    """The retrieval configuration."""
    questions: int
    """Questions asked."""
    grades: dict[str, int]
    """How many questions got each grade (``error`` included)."""
    accuracy: float
    """Share graded correct."""
    wrong_version: int
    """Answers the judge found wrong for the version (true of another version only)."""
    grounded_share: float | None
    """Of the answerable questions, the share where the agent read every answering section."""
    read_other_versions: int
    """Questions where the agent read something of the asked library at another version."""
    tool_calls_per_question: float
    """Mean tool calls."""
    tokens_per_question: float
    """Mean input plus output tokens."""
    usd_per_question: float | None
    """Mean USD; ``None`` when a run was unpriced."""
    seconds_p50: float
    """Median wall time per question."""
    retrieval_modes: dict[str, int]
    """How the searches were answered (``<mode>`` or ``<mode> (<fallback reason>)``), counted."""
    by_kind: dict[str, Breakdown]
    """Accuracy per golden kind."""
    by_project: dict[str, Breakdown]
    """Accuracy per golden project."""


class CorpusCommit(_Model):
    """One imported version: the commit the manifest pins and the one the catalog recorded."""

    project: str
    """The golden project."""
    version: str
    """The version."""
    pinned_commit: str
    """From ``corpus.yaml``."""
    imported_commit: str
    """What the import recorded."""


class RunMeta(_Model):
    """What a run needs to be reproduced."""

    started_at: str
    """When it started (UTC, ISO 8601)."""
    exactdocs_version: str
    """The installed ExactDocs."""
    git_commit: str
    """The repository's commit the benchmark ran from."""
    agent_models: list[str]
    """The agent models."""
    judge_model: str
    """The judge's model."""
    retrieval: dict[str, dict[str, str]]
    """Each retrieval configuration's settings (``EXACTDOCS_AI__...``)."""
    max_requests: int
    """The model-request limit per question."""
    concurrency: int
    """Questions asked at once."""
    cases: int
    """Questions per agent model and configuration."""
    agent_instructions: str
    """The agent's instructions."""
    prompt: str
    """The user prompt's template."""
    corpus: list[CorpusCommit]
    """Every imported version and its commit."""


class BenchReport(_Model):
    """The whole run."""

    meta: RunMeta
    """How it ran."""
    cells: list[CellSummary]
    """One summary per agent model and retrieval configuration."""
    questions: list[QuestionResult]
    """Every question's record."""


def results_of(
    report: EvaluationReport[Question, AgentRun, BenchInfo], agent_model: str, retrieval: str
) -> list[QuestionResult]:
    """Flatten one evaluation into question records.

    Args:
        report: The evaluated cases of one agent model and configuration.
        agent_model: The agent's model.
        retrieval: The configuration's name.

    Returns:
        One record per case; a case whose task or judge failed is graded ``error``.
    """
    rows = []
    for case in report.cases:
        run, info = case.output, case.metadata
        if info is None:
            continue
        label = case.labels.get(GRADE)
        wrong = case.assertions.get(WRONG_VERSION)
        failures = "; ".join(f"{f.name}: {f.error_message}" for f in case.evaluator_failures)
        rows.append(
            QuestionResult(
                agent_model=agent_model,
                retrieval=retrieval,
                case=case.name,
                project=info.project,
                kind=info.kind,
                version=case.inputs.version,
                question=case.inputs.query,
                reference=info.reference,
                facts=info.facts,
                grade=label.value if label else ERROR,
                wrong_version=bool(wrong and wrong.value),
                grounded=grounded(info, run),
                other_versions_read=read_other_versions(case.inputs, info, run),
                tool_calls=run.tool_calls,
                chunks_read=[
                    f"{s.article if s.whole_article else s.chunk_id}@{s.version}" for s in run.read
                ],
                retrieval_modes=run.retrieval_modes,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                usd=run.usd,
                seconds=run.seconds,
                answer=run.answer,
                judge_reason=(label.reason or "") if label else failures,
            )
        )
    for failure in report.failures:
        info = failure.metadata
        rows.append(
            QuestionResult(
                agent_model=agent_model,
                retrieval=retrieval,
                case=failure.name,
                project=info.project if info else "",
                kind=info.kind if info else "",
                version=failure.inputs.version,
                question=failure.inputs.query,
                reference=info.reference if info else "",
                facts=info.facts if info else [],
                grade=ERROR,
                judge_reason=f"the task failed: {failure.error_message}",
            )
        )
    return rows


def _breakdown(rows: Sequence[QuestionResult], key: Callable[[QuestionResult], str]) -> dict:
    """Accuracy per value of ``key``.

    Args:
        rows: The questions.
        key: What to group by.

    Returns:
        Group to its breakdown, sorted by group.
    """
    groups: defaultdict[str, list[QuestionResult]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return {
        name: Breakdown(
            questions=len(group),
            correct=(correct := sum(r.grade == CORRECT for r in group)),
            accuracy=round(correct / len(group), 3),
        )
        for name, group in sorted(groups.items())
    }


def _mean(values: Iterable[float]) -> float:
    """The mean, 0 for nothing.

    Args:
        values: The numbers.

    Returns:
        Their mean, rounded to 3 places.
    """
    values = list(values)
    return round(statistics.fmean(values), 3) if values else 0.0


def summarize(agent_model: str, retrieval: str, rows: Sequence[QuestionResult]) -> CellSummary:
    """Aggregate one agent model under one configuration.

    Args:
        agent_model: The agent's model.
        retrieval: The configuration's name.
        rows: Its questions.

    Returns:
        The summary.
    """
    answerable = [r.grounded for r in rows if r.grounded is not None]
    priced = [r.usd for r in rows if r.usd is not None]
    counts = Counter(r.grade for r in rows)
    return CellSummary(
        agent_model=agent_model,
        retrieval=retrieval,
        questions=len(rows),
        grades={grade: counts[grade] for grade in (*GRADES, ERROR)},
        accuracy=round(counts[CORRECT] / len(rows), 3) if rows else 0.0,
        wrong_version=sum(r.wrong_version for r in rows),
        grounded_share=round(sum(answerable) / len(answerable), 3) if answerable else None,
        read_other_versions=sum(bool(r.other_versions_read) for r in rows),
        tool_calls_per_question=_mean(len(r.tool_calls) for r in rows),
        tokens_per_question=_mean(r.input_tokens + r.output_tokens for r in rows),
        usd_per_question=round(statistics.fmean(priced), 6)
        if rows and len(priced) == len(rows)
        else None,
        seconds_p50=round(statistics.median(r.seconds for r in rows), 3) if rows else 0.0,
        retrieval_modes=dict(Counter(m for r in rows for m in r.retrieval_modes)),
        by_kind=_breakdown(rows, lambda r: r.kind),
        by_project=_breakdown(rows, lambda r: r.project),
    )


def _share(value: float | None) -> str:
    """Show a share as a percentage.

    Args:
        value: A share, or ``None``.

    Returns:
        ``87.5 %`` or ``n/a``.
    """
    return "n/a" if value is None else f"{value * 100:.1f} %"


def markdown(report: BenchReport) -> str:
    """Render the report for a person (and ``$GITHUB_STEP_SUMMARY``).

    Args:
        report: The run.

    Returns:
        Markdown: the run's setup, a table per agent model and configuration, accuracy per kind
        and per project.
    """
    meta = report.meta
    lines = [
        "# Agent benchmark",
        "",
        (
            f"{meta.cases} golden questions per agent model and retrieval configuration; "
            f"judge `{meta.judge_model}`; ExactDocs {meta.exactdocs_version} at "
            f"`{meta.git_commit[:12]}`; at most {meta.max_requests} model requests per question."
        ),
        "",
        (
            "| Agent model | Retrieval | Accuracy | Partial | Wrong | Refused | Errors "
            "| Wrong for the version | Read the answer | Read another version | Tool calls/q "
            "| Tokens/q | USD/q | p50 s |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report.cells:
        usd = "unpriced" if c.usd_per_question is None else f"{c.usd_per_question:.5f}"
        lines.append(
            f"| `{c.agent_model}` | {c.retrieval} | {_share(c.accuracy)} "
            f"| {c.grades['partially_correct']} | {c.grades['wrong']} | {c.grades['refused']} "
            f"| {c.grades[ERROR]} | {c.wrong_version} | {_share(c.grounded_share)} "
            f"| {c.read_other_versions} | {c.tool_calls_per_question} | {c.tokens_per_question} "
            f"| {usd} | {c.seconds_p50} |"
        )
    for title, field in (("kind", "by_kind"), ("project", "by_project")):
        groups = sorted({g for c in report.cells for g in getattr(c, field)})
        lines += ["", f"## Accuracy per {title}", ""]
        lines.append("| Agent model | Retrieval | " + " | ".join(groups) + " |")
        lines.append("|---|---|" + "---|" * len(groups))
        for c in report.cells:
            cells = getattr(c, field)
            shown = [
                f"{_share(cells[g].accuracy)} ({cells[g].questions})" if g in cells else ""
                for g in groups
            ]
            lines.append(f"| `{c.agent_model}` | {c.retrieval} | " + " | ".join(shown) + " |")
    lines += ["", "## Retrieval configurations", ""]
    for name, env in meta.retrieval.items():
        settings = ", ".join(f"`{k}={v}`" for k, v in env.items()) or "the environment's"
        modes = Counter[str]()
        for c in report.cells:
            if c.retrieval == name:
                modes.update(c.retrieval_modes)
        answered = ", ".join(f"{mode}: {n}" for mode, n in sorted(modes.items())) or "no search"
        lines.append(f"- **{name}**: {settings}; searches answered by {answered}")
    return "\n".join(lines) + "\n"
