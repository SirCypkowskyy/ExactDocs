"""Run the dataset through each mode, aggregate the metrics and apply the gates.

The gates (docs/decisions/ai-retrieval.md, *Evaluation*):

- the wrong-version rate must be 0 for every mode that ran, whatever its recall;
- the gating mode's recall@5 may not drop more than ``MAX_RECALL_DROP_POINTS`` below the baseline
  stored on ``develop`` (other modes only report the drop);
- a mode may become a default only when its recall@5 beats BM25's by ``DEFAULT_MARGIN_POINTS``
  with a wrong-version rate of 0 (reported as ``eligible_as_default``).
"""

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from statistics import fmean
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict
from pydantic_evals.reporting import EvaluationReport, ReportCase

from exactdocs.retrieval.dtos import GetLibraryRetrievalQuery, LibraryRetrievalOut
from exactdocs.retrieval.models import ModelRole, RetrievalMode
from exactdocs.retrieval.ports.driving import GetLibraryRetrieval, SearchDocs
from retrieval_eval.dataset import Answer, CaseInfo, Question, RetrievalDataset
from retrieval_eval.evaluators import (
    RECALL_AT,
    RECIPROCAL_RANK,
    RIGHT_VERSION,
    TOKENS,
    USD,
    Cost,
    VersionAndRank,
    recall_key,
)
from retrieval_eval.retrievers import Retriever, SearchDocsRetriever

MAX_RECALL_DROP_POINTS: Final[float] = 2.0
"""How far recall@5 may fall below the baseline, in percentage points."""
DEFAULT_MARGIN_POINTS: Final[float] = 5.0
"""How far a mode's recall@5 must beat BM25's, in points, before it may become a default."""
BASELINE_FILE: Final[Path] = Path(__file__).with_name("baseline.json")
"""The stored baseline; CI compares with the copy on ``develop``."""
_EPSILON: Final[float] = 1e-9
"""Float noise tolerated when comparing points."""
_DIGITS: Final[int] = 4
"""Rates are rounded to this many decimals, so a stored baseline reads plainly."""


class Tier(StrEnum):
    """Where a mode runs for real (docs/evals.md, *Tiers*)."""

    EVERY_PR = "every_pr"
    """Model-free: runs on every pull request and gates it."""
    LOCAL = "local"
    """Local models (the ``[local]`` extra): runs without secrets, report-only on pull requests."""
    PROVIDER = "provider"
    """A hosted LLM: only by hand (``--allow-providers``), never in CI's pull request jobs."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalMode:
    """A retrieval mode the suite knows, and the tier it runs in."""

    mode: RetrievalMode
    """The mode, as a search names it."""
    tier: Tier
    """Where it runs for real."""

    @property
    def gating(self) -> bool:
        """Say whether a recall drop of this mode fails the suite (a wrong version always does).

        Returns:
            True for the model-free mode that every pull request runs.
        """
        return self.tier is Tier.EVERY_PR


MODES: Final[tuple[EvalMode, ...]] = (
    EvalMode(mode=RetrievalMode.BM25, tier=Tier.EVERY_PR),
    EvalMode(mode=RetrievalMode.HYBRID, tier=Tier.LOCAL),
    EvalMode(mode=RetrievalMode.HYBRID_HYDE, tier=Tier.PROVIDER),
    EvalMode(mode=RetrievalMode.AGENTIC, tier=Tier.PROVIDER),
)
"""Every retrieval mode, in ``RetrievalMode`` order; a new mode must be given a tier here."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModeMetrics(_Model):
    """One mode's numbers over the whole dataset."""

    questions: int
    """Cases that ran."""
    answerable: int
    """Of those, cases whose version has an answer (recall and MRR are over these)."""
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    """Mean reciprocal rank of the expected section."""
    wrong_version_rate: float
    """Share of questions with at least one result of another version; must be 0."""
    latency_p50_ms: float
    latency_p95_ms: float
    tokens_per_question: float
    usd_per_question: float


class ModeOutcome(_Model):
    """What happened to one mode: its metrics, or why it did not run."""

    mode: RetrievalMode
    tier: Tier
    gating: bool
    status: Literal["ran", "unavailable", "skipped"]
    reason: str | None = None
    """Why it did not run: the model roles it lacks, or the tier it needs."""
    metrics: ModeMetrics | None = None
    wrong_version_cases: list[str] = []
    """Cases with a result of another version, and the offending results."""
    errors: list[str] = []
    """Cases whose search raised, with the error."""
    misses: list[str] = []
    """Answerable cases whose section was not in the top 10."""
    fallbacks: int = 0
    """Cases a cheaper mode answered."""
    baseline_recall_at_5: float | None = None
    recall_at_5_delta_points: float | None = None
    """recall@5 minus the baseline's, in points."""
    eligible_as_default: bool | None = None
    """Beats BM25's recall@5 by the margin with no wrong version; None for BM25 itself."""


class SuiteReport(_Model):
    """The run: every mode's outcome, the gates' verdict, and why."""

    dataset: str
    cases: int
    passed: bool
    problems: list[str]
    """What failed the suite."""
    warnings: list[str]
    """What a report-only mode got worse at, without failing the suite."""
    modes: list[ModeOutcome]


def _percentile(values: Sequence[float], share: float) -> float:
    """Nearest-rank percentile; 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return fmean(items) if items else 0.0


def _score(case: ReportCase[Question, Answer, CaseInfo], name: str) -> float:
    return float(case.scores[name].value)


def metrics_of(report: EvaluationReport[Question, Answer, CaseInfo]) -> ModeMetrics:
    """Aggregate one mode's report.

    Args:
        report: The evaluated cases (a case whose search raised counts as a question too).

    Returns:
        Recall@1/5/10 and MRR over answerable cases, the wrong-version rate over all questions,
        latency percentiles and cost per question.
    """
    cases = report.cases
    answerable = [c for c in cases if recall_key(1) in c.scores]
    wrong = [c for c in cases if not c.assertions[RIGHT_VERSION].value]
    questions = len(cases) + len(report.failures)
    latencies = [c.task_duration * 1000 for c in cases]
    return ModeMetrics(
        questions=questions,
        answerable=len(answerable),
        recall_at_1=round(_mean(_score(c, recall_key(1)) for c in answerable), _DIGITS),
        recall_at_5=round(_mean(_score(c, recall_key(5)) for c in answerable), _DIGITS),
        recall_at_10=round(_mean(_score(c, recall_key(10)) for c in answerable), _DIGITS),
        mrr=round(_mean(_score(c, RECIPROCAL_RANK) for c in answerable), _DIGITS),
        wrong_version_rate=round(len(wrong) / questions if questions else 0.0, _DIGITS),
        latency_p50_ms=round(_percentile(latencies, 0.5), 3),
        latency_p95_ms=round(_percentile(latencies, 0.95), 3),
        tokens_per_question=_mean(_score(c, TOKENS) for c in cases),
        usd_per_question=_mean(_score(c, USD) for c in cases),
    )


async def evaluate_mode(
    dataset: RetrievalDataset, mode: EvalMode, retriever: Retriever
) -> ModeOutcome:
    """Run every case through ``retriever`` and aggregate.

    Args:
        dataset: The cases.
        mode: The mode the retriever answers in.
        retriever: How to ask that mode.

    Returns:
        The mode's metrics, the cases with a wrong version, the errors and the misses.
    """
    report = await dataset.evaluate(
        retriever.answer,
        name=mode.mode.value,
        task_name=mode.mode.value,
        max_concurrency=1,  # latency is measured per question, not under contention
        progress=False,
    )
    wrong = [
        f"{c.name}: {c.assertions[RIGHT_VERSION].reason}"
        for c in report.cases
        if not c.assertions[RIGHT_VERSION].value
    ]
    misses = [
        c.name
        for c in report.cases
        if recall_key(max(RECALL_AT)) in c.scores and not c.scores[recall_key(max(RECALL_AT))].value
    ]
    failed = [f"{c.name}: {c.error_message}" for c in report.failures]
    failed += [
        f"{c.name}: evaluator {f.name}: {f.error_message}"
        for c in report.cases
        for f in c.evaluator_failures
    ]
    return ModeOutcome(
        mode=mode.mode,
        tier=mode.tier,
        gating=mode.gating,
        status="ran",
        metrics=metrics_of(report),
        wrong_version_cases=sorted(wrong),
        errors=sorted(failed),
        misses=sorted(misses),
        fallbacks=sum(1 for c in report.cases if c.output.answered_by not in {None, mode.mode}),
    )


def with_evaluators(dataset: RetrievalDataset) -> RetrievalDataset:
    """Add the suite's evaluators to a dataset (they are not part of the YAML).

    Args:
        dataset: The cases.

    Returns:
        The same dataset, evaluating version, rank and cost.
    """
    if not dataset.evaluators:
        dataset.add_evaluator(VersionAndRank())
        dataset.add_evaluator(Cost())
    return dataset


def _not_running(
    mode: EvalMode, status: LibraryRetrievalOut, *, allow_providers: bool
) -> ModeOutcome:
    """The outcome of a mode that will not run, or a ``ran`` placeholder for one that will."""
    if mode.mode not in status.available_modes:
        configured = set(status.configured_roles)
        missing = [r.value for r in ModelRole if r in mode.mode.roles and r not in configured]
        plural = "s" if len(missing) > 1 else ""
        reason = (
            f"needs the {' and '.join(missing)} role{plural}, not configured"
            if missing
            else "this build has no pipeline for it yet"
        )
        return ModeOutcome(
            mode=mode.mode, tier=mode.tier, gating=mode.gating, status="unavailable", reason=reason
        )
    if mode.tier is Tier.PROVIDER and not allow_providers:
        return ModeOutcome(
            mode=mode.mode,
            tier=mode.tier,
            gating=mode.gating,
            status="skipped",
            reason="calls a hosted model: run by hand with --allow-providers",
        )
    return ModeOutcome(mode=mode.mode, tier=mode.tier, gating=mode.gating, status="ran")


class RetrievalUnderTest(Protocol):
    """The parts of the app's ``RetrievalModule`` the suite uses."""

    @property
    def search_docs(self) -> SearchDocs:
        """The search every mode answers through."""
        ...

    @property
    def get_library_retrieval(self) -> GetLibraryRetrieval:
        """Which modes can run now, and which model roles are configured."""
        ...


async def run_modes(
    dataset: RetrievalDataset,
    *,
    retrieval: RetrievalUnderTest,
    library: str,
    commits: Mapping[str, str],
    modes: Sequence[EvalMode] = MODES,
    allow_providers: bool = False,
) -> list[ModeOutcome]:
    """Run every mode the app can run now; record the others as unavailable or skipped.

    Args:
        dataset: The cases, with the suite's evaluators.
        retrieval: The app's retrieval module.
        library: The fixture library's ID.
        commits: The commit SHA each version points at.
        modes: The modes to try.
        allow_providers: Run modes that call a hosted model (never in CI's pull request jobs).

    Returns:
        One outcome per mode, in order.
    """
    status = await retrieval.get_library_retrieval(GetLibraryRetrievalQuery(library=library))
    outcomes = []
    for mode in modes:
        outcome = _not_running(mode, status, allow_providers=allow_providers)
        if outcome.status == "ran":
            retriever = SearchDocsRetriever(
                search=retrieval.search_docs, library=library, mode=mode.mode.value, commits=commits
            )
            outcome = await evaluate_mode(dataset, mode, retriever)
        outcomes.append(outcome)
    return outcomes


def read_baseline(path: Path) -> dict[str, float]:
    """Read the stored recall@5 per mode.

    Args:
        path: A baseline written by ``baseline_of``; a missing file is an empty baseline.

    Returns:
        recall@5 per mode name.
    """
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {mode: float(values["recall_at_5"]) for mode, values in data["modes"].items()}


def baseline_of(report: SuiteReport) -> str:
    """Write the baseline of a run: the ranking metrics of every mode that ran.

    Latency is left out: it depends on the machine, not on the change.

    Args:
        report: The run.

    Returns:
        The JSON to store as ``baseline.json``.
    """
    modes = {
        o.mode.value: o.metrics.model_dump(
            include={"recall_at_1", "recall_at_5", "recall_at_10", "mrr", "wrong_version_rate"}
        )
        for o in report.modes
        if o.metrics is not None
    }
    note = "Written by `just eval --write-baseline`; CI compares with the copy on develop."
    return json.dumps({"note": note, "modes": modes}, indent=2) + "\n"


def _points(value: float) -> float:
    return round(value * 100, 2)


def judge(
    dataset: str, cases: int, outcomes: Sequence[ModeOutcome], baseline: Mapping[str, float]
) -> SuiteReport:
    """Apply the gates.

    Args:
        dataset: The dataset's name.
        cases: How many cases it has.
        outcomes: Every mode's outcome.
        baseline: recall@5 per mode, from ``develop``.

    Returns:
        The report: passed only with no wrong version and no error in any mode, and no recall@5
        drop beyond the limit in a gating mode.
    """
    problems: list[str] = []
    warnings: list[str] = []
    bm25 = next((o.metrics for o in outcomes if o.mode is RetrievalMode.BM25 and o.metrics), None)
    judged = []
    for outcome in outcomes:
        metrics = outcome.metrics
        if metrics is None:
            judged.append(outcome)
            continue
        name = outcome.mode.value
        if outcome.wrong_version_cases:
            problems.append(
                f"{name}: {len(outcome.wrong_version_cases)} question(s) got a result of another "
                f"version (wrong-version rate {metrics.wrong_version_rate:.3f}, must be 0)"
            )
        if outcome.errors:
            problems.append(f"{name}: {len(outcome.errors)} question(s) failed to run")
        base = baseline.get(name)
        delta = None if base is None else _points(metrics.recall_at_5 - base)
        if delta is not None and delta < -MAX_RECALL_DROP_POINTS - _EPSILON:
            drop = (
                f"{name}: recall@5 {_points(metrics.recall_at_5)} is {-delta} points below the "
                f"baseline {_points(base or 0.0)} (at most {MAX_RECALL_DROP_POINTS} allowed)"
            )
            (problems if outcome.gating else warnings).append(drop)
        eligible = None
        if outcome.mode is not RetrievalMode.BM25 and bm25 is not None:
            margin = _points(metrics.recall_at_5 - bm25.recall_at_5)
            eligible = (
                margin >= DEFAULT_MARGIN_POINTS - _EPSILON and not outcome.wrong_version_cases
            )
        judged.append(
            outcome.model_copy(
                update={
                    "baseline_recall_at_5": base,
                    "recall_at_5_delta_points": delta,
                    "eligible_as_default": eligible,
                }
            )
        )
    if not any(o.metrics for o in judged):
        problems.append("no mode ran")
    return SuiteReport(
        dataset=dataset,
        cases=cases,
        passed=not problems,
        problems=problems,
        warnings=warnings,
        modes=judged,
    )


def _cell(value: float | None, *, points: bool = False, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{_points(value):g}" if points else f"{value:.{digits}f}"


def markdown(report: SuiteReport) -> str:
    """Render the report as a CI job summary.

    Args:
        report: The run.

    Returns:
        A Markdown table per mode, then the verdict and its reasons.
    """
    verdict = "passed" if report.passed else "failed"
    lines = [
        f"## Retrieval eval: {verdict}",
        "",
        (
            f"{report.cases} questions of the `{report.dataset}` dataset, per mode. Recall and MRR "
            "are over the questions whose version has an answer; recall@5 delta is against the "
            "baseline on `develop`."
        ),
        "",
        (
            "| mode | status | recall@1 | recall@5 | recall@10 | MRR | wrong version | p50 ms "
            "| p95 ms | tokens/q | USD/q | recall@5 delta | default-eligible |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for o in report.modes:
        m = o.metrics
        if m is None:
            lines.append(f"| {o.mode} | {o.status}: {o.reason} |" + " - |" * 11)
            continue
        delta = "-" if o.recall_at_5_delta_points is None else f"{o.recall_at_5_delta_points:+g}"
        eligible = {None: "-", True: "yes", False: "no"}[o.eligible_as_default]
        lines.append(
            f"| {o.mode} | {o.status} | {_cell(m.recall_at_1, points=True)} "
            f"| {_cell(m.recall_at_5, points=True)} | {_cell(m.recall_at_10, points=True)} "
            f"| {_cell(m.mrr)} | {_cell(m.wrong_version_rate)} "
            f"| {_cell(m.latency_p50_ms, digits=1)} | {_cell(m.latency_p95_ms, digits=1)} "
            f"| {_cell(m.tokens_per_question, digits=0)} | {_cell(m.usd_per_question, digits=4)} "
            f"| {delta} | {eligible} |"
        )
    lines.append("")
    lines.extend(f"- **Failed:** {p}" for p in report.problems)
    lines.extend(f"- **Warning:** {w}" for w in report.warnings)
    for o in report.modes:
        lines.extend(f"- `{o.mode}` wrong version: {c}" for c in o.wrong_version_cases)
        lines.extend(f"- `{o.mode}` error: {c}" for c in o.errors)
        if o.misses:
            lines.append(f"- `{o.mode}` not in the top 10: " + "; ".join(o.misses))
    return "\n".join(lines) + "\n"
