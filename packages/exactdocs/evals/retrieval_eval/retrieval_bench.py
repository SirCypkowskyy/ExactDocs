"""The retrieval benchmark's metrics, report, recommendation and check (#347).

Every configuration of the matrix (``retrieval_bench_cli``) answers the golden set at every
chunking configuration; each answer becomes a ``Row``, and the rows give the metrics overall, by
question kind and by project. Definitions are in docs/evals.md#the-retrieval-benchmark.
"""

import math
from collections.abc import Callable, Sequence
from enum import StrEnum
from statistics import fmean
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Case

from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.evaluators import SectionMatch, rank_of, same_section, wrong_version_hits
from retrieval_eval.suite import DEFAULT_MARGIN_POINTS, MAX_RECALL_DROP_POINTS, percentile

SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed (#349 reads it)."""
NDCG_AT: Final[int] = 10
"""The cut-off of nDCG."""
_DIGITS: Final[int] = 4
"""Rates are rounded to this many decimals."""
_USD_DIGITS: Final[int] = 6
"""USD per question is rounded to a millionth of a dollar."""
_EPSILON: Final[float] = 1e-9
"""Float noise tolerated when comparing points."""
NOT_MEASURED: Final[str] = "not measured yet: needs a real-providers run"
"""What the summary says of the hosted budget until a real-providers run measured it."""


class Budget(StrEnum):
    """What a configuration needs to run: no model, local models only, or a hosted model."""

    NONE = "none"
    LOCAL = "local"
    HOSTED = "hosted"


BUDGETS: Final[tuple[Budget, ...]] = (Budget.NONE, Budget.LOCAL, Budget.HOSTED)
"""The budgets, cheapest first."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Row(_Model):
    """One case as a configuration answered it."""

    kind: str
    """The case's golden kind."""
    project: str
    """The case's project."""
    answerable: bool
    """The version has an answer (the case expects sections)."""
    rank: int | None
    """Rank of the first expected section (as recall counts it); None when it is not returned."""
    ndcg: float
    """nDCG@10 of the answer (0 for an unanswerable case)."""
    sections: int
    """How many sections the case expects (0 when unanswerable)."""
    section_ranks: tuple[int, ...]
    """The rank at which each expected section was found in the top 10 (``section_ranks``)."""
    wrong_version: bool
    """A result is of another version."""
    empty: bool
    """Nothing came back: the only "no answer" signal ``search_docs`` gives."""
    search_ms: float
    """How long the search took."""
    tokens: int
    """Model tokens it cost."""
    usd: float
    """What it cost in USD."""


def section_ranks(
    expected: Sequence[Hit], hits: Sequence[Hit], matches: SectionMatch = same_section
) -> tuple[int, ...]:
    """The ranks, in the top 10, of the hits that answer an expected section.

    A hit counts when it answers an expected section no earlier hit answered, so a section found
    twice counts once.

    Args:
        expected: The sections that answer the case.
        hits: What the configuration returned, best first.
        matches: When a hit answers an expected section.

    Returns:
        One rank per expected section found, ascending.
    """
    left = list(expected)
    ranks = []
    for rank, hit in enumerate(hits[:NDCG_AT], start=1):
        found = next((e for e in left if matches(e, hit)), None)
        if found is not None:
            left.remove(found)
            ranks.append(rank)
    return tuple(ranks)


def ndcg_at(
    expected: Sequence[Hit], hits: Sequence[Hit], matches: SectionMatch = same_section
) -> float:
    """nDCG@10 with binary relevance over the expected sections.

    The relevant hits are those of ``section_ranks``. DCG sums ``1 / log2(rank + 1)`` over them;
    the ideal DCG puts every expected section first (up to 10).

    Args:
        expected: The sections that answer the case.
        hits: What the configuration returned, best first.
        matches: When a hit answers an expected section.

    Returns:
        DCG / ideal DCG, in [0, 1]; 0 when nothing is expected.
    """
    dcg = sum(1 / math.log2(rank + 1) for rank in section_ranks(expected, hits, matches))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(expected), NDCG_AT) + 1))
    return dcg / ideal if ideal else 0.0


def row_of(
    case: Case[Question, Answer, CaseInfo], answer: Answer, matches: SectionMatch = same_section
) -> Row:
    """Score one answer.

    Args:
        case: The golden case.
        answer: What the configuration returned for it.
        matches: When a hit answers an expected section.

    Returns:
        The row.
    """
    expected = case.expected_output.hits if case.expected_output else []
    return Row(
        kind=case.metadata.kind if case.metadata else "",
        project=case.inputs.project or "",
        answerable=bool(expected),
        rank=rank_of(expected[0], answer, matches) if expected else None,
        ndcg=ndcg_at(expected, answer.hits, matches),
        sections=len(expected),
        section_ranks=section_ranks(expected, answer.hits, matches),
        wrong_version=bool(wrong_version_hits(case.inputs, answer)),
        empty=not answer.hits,
        search_ms=answer.search_ms or 0.0,
        tokens=answer.tokens,
        usd=answer.usd,
    )


class BenchMetrics(_Model):
    """A configuration's numbers over a set of cases (all, one kind or one project)."""

    questions: int
    answerable: int
    unanswerable: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    """Over answerable cases: the first expected section is in the top k."""
    mrr: float
    """Over answerable cases: mean of 1 / the rank of the first expected section."""
    ndcg_at_10: float
    """Over answerable cases: nDCG@10, binary relevance over every expected section."""
    section_recall_at_5: float
    section_recall_at_10: float
    """Over answerable cases: the share of a case's expected sections in the top k, averaged
    (differs from recall@k only for cases that expect several sections, such as cross-page)."""
    wrong_version_rate: float
    """Over every case: share with a result of another version; must be 0."""
    unanswerable_clean_rate: float | None
    """Over unanswerable cases: share that returned nothing of another version."""
    no_answer_rate: float | None
    """Over unanswerable cases: share that signalled no answer (came back empty)."""
    answerable_empty_rate: float | None
    """Over answerable cases: share that came back empty (a "no answer" that was wrong)."""
    latency_p50_ms: float
    latency_p95_ms: float
    """Nearest-rank percentiles of the search time, one question at a time."""
    tokens_per_question: float
    usd_per_question: float


def _mean(values: list[float]) -> float:
    return round(fmean(values), _DIGITS) if values else 0.0


def _share(rows: list[Row], test: Callable[[Row], bool]) -> float | None:
    return round(sum(map(test, rows)) / len(rows), _DIGITS) if rows else None


def metrics_of(rows: Sequence[Row]) -> BenchMetrics:
    """Aggregate rows.

    Args:
        rows: The cases' rows.

    Returns:
        The metrics; rates over an empty set are 0 (ranks) or None (the conditional rates).
    """
    answerable = [r for r in rows if r.answerable]
    unanswerable = [r for r in rows if not r.answerable]

    def recall(k: int) -> float:
        """Recall at ``k``.

        Args:
            k: The cut-off.

        Returns:
            The share of answerable rows ranked within ``k``.
        """
        return _mean([1.0 if r.rank is not None and r.rank <= k else 0.0 for r in answerable])

    def sections(k: int) -> float:
        """Section recall at ``k``.

        Args:
            k: The cut-off.

        Returns:
            The mean share of each answerable row's expected sections ranked within ``k``.
        """
        return _mean([sum(rank <= k for rank in r.section_ranks) / r.sections for r in answerable])

    latencies = [r.search_ms for r in rows]
    return BenchMetrics(
        questions=len(rows),
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        recall_at_1=recall(1),
        recall_at_5=recall(5),
        recall_at_10=recall(10),
        mrr=_mean([1 / r.rank if r.rank else 0.0 for r in answerable]),
        ndcg_at_10=_mean([r.ndcg for r in answerable]),
        section_recall_at_5=sections(5),
        section_recall_at_10=sections(10),
        wrong_version_rate=_share(list(rows), lambda r: r.wrong_version) or 0.0,
        unanswerable_clean_rate=_share(unanswerable, lambda r: not r.wrong_version),
        no_answer_rate=_share(unanswerable, lambda r: r.empty),
        answerable_empty_rate=_share(answerable, lambda r: r.empty),
        latency_p50_ms=round(percentile(latencies, 0.5), 3),
        latency_p95_ms=round(percentile(latencies, 0.95), 3),
        tokens_per_question=round(fmean(r.tokens for r in rows), 1) if rows else 0.0,
        usd_per_question=round(fmean(r.usd for r in rows), _USD_DIGITS) if rows else 0.0,
    )


class ModelInfo(_Model):
    """One model a configuration called, as exactly as the run can name it."""

    role: str
    """``embedding``, ``reranker``, ``llm`` or ``judge``."""
    model: str
    """``<profile>:<model>`` as the role names it."""
    kind: str | None = None
    """The profile's kind (``local``, ``openai``, ...)."""
    base_url: str | None = None
    """The profile's endpoint, for a hosted one."""
    revision: str | None = None
    """A local model's Hub commit (from its pull marker)."""
    dimensions: int | None = None
    """An embedding model's vector size, when known."""


class IndexCost(_Model):
    """What embedding the whole corpus took, once per embedding model and chunking."""

    seconds: float
    tokens: int
    usd: float


class ConfigResult(_Model):
    """One configuration at one chunking configuration."""

    configuration: str
    chunking: str
    budget: Budget
    mode: str
    """The retrieval mode asked for."""
    rerank: str | None = None
    """``cross_encoder``, ``judge`` or None."""
    status: Literal["ran", "unavailable", "skipped"]
    reason: str | None = None
    """Why it did not run."""
    models: list[ModelInfo] = []
    settings: dict[str, Any] = {}
    """The ``ai`` settings it ran with (roles, rerank, timeouts, HyDE and agentic limits)."""
    metrics: BenchMetrics | None = None
    by_kind: dict[str, BenchMetrics] = {}
    by_project: dict[str, BenchMetrics] = {}
    index: IndexCost | None = None
    """What embedding the corpus for its embedding model took (None: no embedding model)."""
    fallbacks: int = 0
    """Cases a cheaper mode answered."""
    reranked: int = 0
    rerank_fallbacks: int = 0
    """Cases with results that a configured reranker did not reorder (failed or timed out)."""
    misses: int = 0
    """Answerable cases whose first expected section was not in the top 10."""
    errors: list[str] = []
    wrong_version_cases: list[str] = []
    left_version_cases: list[str] = []
    """Agentic runs whose trace read outside the version asked for."""

    def with_breakdowns(self, rows: Sequence[Row]) -> Self:
        """Add the metrics overall, by question kind and by project.

        Args:
            rows: Every case's row.

        Returns:
            A copy with ``metrics``, ``by_kind`` and ``by_project``.
        """

        def by(key: Callable[[Row], str]) -> dict[str, BenchMetrics]:
            """Group the rows.

            Args:
                key: The group of a row.

            Returns:
                The metrics of each group, by name.
            """
            groups: dict[str, list[Row]] = {}
            for row in rows:
                groups.setdefault(key(row), []).append(row)
            return {name: metrics_of(group) for name, group in sorted(groups.items())}

        return self.model_copy(
            update={
                "metrics": metrics_of(rows),
                "by_kind": by(lambda r: r.kind),
                "by_project": by(lambda r: r.project),
            }
        )


class Recommendation(_Model):
    """The default named for one budget."""

    budget: Budget
    configuration: str | None
    """None: nothing of this budget (or cheaper) was measured."""
    chunking: str | None
    usd_per_1000_questions: float | None
    reasons: list[str]


class RetrievalBenchReport(_Model):
    """The benchmark's JSON report (``retrieval.json``), documented in docs/evals.md."""

    schema_version: int = SCHEMA_VERSION
    golden: str
    """The golden set's fingerprint."""
    cases: int
    projects: list[str]
    corpus: list[dict[str, str]]
    """Every pinned version: ``project``, ``version``, ``commit``."""
    environment: dict[str, str]
    """The ExactDocs commit, Python, platform, CPU and the versions of the libraries that run
    the models."""
    chunkings: list[dict[str, Any]]
    """Each chunking configuration: ``name``, ``about`` and its library settings."""
    results: list[ConfigResult]
    recommendations: list[Recommendation]


def _clean(result: ConfigResult) -> bool:
    return (
        result.metrics is not None
        and not result.wrong_version_cases
        and not result.left_version_cases
        and not result.errors
        and not result.rerank_fallbacks
    )


def _points(value: float) -> float:
    return round(value * 100, 1)


def _rank_key(result: ConfigResult) -> tuple[float, ...]:
    m = result.metrics
    if m is None:
        return (-1.0,)
    return (m.recall_at_5, m.ndcg_at_10, m.mrr, -m.usd_per_question, -m.latency_p95_ms)


def _numbers(result: ConfigResult) -> str:
    m = result.metrics
    if m is None:
        return ""
    return (
        f"`{result.configuration}` at `{result.chunking}`: recall@5 {_points(m.recall_at_5)}%, "
        f"nDCG@10 {m.ndcg_at_10:.3f}, MRR {m.mrr:.3f}, wrong-version rate "
        f"{m.wrong_version_rate:g}, p95 {m.latency_p95_ms:.0f} ms, "
        f"${m.usd_per_question * 1000:.4f} per 1000 questions"
    )


def recommend(results: Sequence[ConfigResult]) -> list[Recommendation]:
    """Name the default for each budget, cheapest first.

    Candidates ran without a wrong version, a read outside the version, an error or a reranker
    fallback. The best of a budget (recall@5, then nDCG@10, MRR, lower cost, lower p95) becomes
    its default only when its recall@5 beats the cheaper budget's default by
    ``DEFAULT_MARGIN_POINTS``; otherwise the cheaper default stays, since it is as good for less.

    Args:
        results: Every result of the run.

    Returns:
        One recommendation per budget.
    """
    picks: list[Recommendation] = []
    previous: ConfigResult | None = None
    for budget in BUDGETS:
        own = [r for r in results if r.budget is budget and _clean(r)]
        if not own:
            why = (
                NOT_MEASURED
                if budget is Budget.HOSTED
                else f"not measured yet: no {budget} configuration ran cleanly"
            )
            picks.append(
                Recommendation(
                    budget=budget,
                    configuration=None,
                    chunking=None,
                    usd_per_1000_questions=None,
                    reasons=[why],
                )
            )
            continue
        best = max(own, key=_rank_key)
        reasons = [f"best {budget} configuration: {_numbers(best)}"]
        if previous is not None and previous.metrics and best.metrics:
            gain = _points(best.metrics.recall_at_5 - previous.metrics.recall_at_5)
            versus = f"{gain:+.1f} points of recall@5 over `{previous.configuration}`"
            if gain < DEFAULT_MARGIN_POINTS - _EPSILON:
                reasons.append(
                    f"{versus}, under the {DEFAULT_MARGIN_POINTS:g}-point margin: the cheaper "
                    f"`{previous.configuration}` at `{previous.chunking}` stays the default"
                )
                best = previous
            else:
                reasons.append(f"{versus} (margin {DEFAULT_MARGIN_POINTS:g})")
        m = best.metrics
        picks.append(
            Recommendation(
                budget=budget,
                configuration=best.configuration,
                chunking=best.chunking,
                usd_per_1000_questions=round(m.usd_per_question * 1000, 4) if m else None,
                reasons=reasons,
            )
        )
        previous = best
    return picks


def run_problems(report: RetrievalBenchReport) -> list[str]:
    """Say what fails a run, whatever its recall: another version, a read outside, an error.

    Args:
        report: The run.

    Returns:
        One problem per result and kind of failure.
    """
    problems = []
    for r in report.results:
        name = f"{r.configuration} @ {r.chunking}"
        if r.wrong_version_cases:
            problems.append(
                f"{name}: {len(r.wrong_version_cases)} question(s) got a result of another version"
            )
        if r.left_version_cases:
            problems.append(f"{name}: {len(r.left_version_cases)} run(s) read outside the version")
        if r.errors:
            problems.append(f"{name}: {len(r.errors)} question(s) failed to run")
    return problems


def check(report: RetrievalBenchReport, recorded: RetrievalBenchReport) -> list[str]:
    """Compare a run with a recorded one, for every result both ran.

    recall@5 and nDCG@10 may not drop more than ``MAX_RECALL_DROP_POINTS``, and the run's own
    problems (``run_problems``) fail it. Both must have run the same golden set on the same
    projects.

    Args:
        report: This run.
        recorded: The recorded run (``results/retrieval.json``).

    Returns:
        One problem per regression; empty when none.
    """
    if (report.golden, report.projects) != (recorded.golden, recorded.projects):
        return [
            (
                f"the recorded report measured golden set {recorded.golden} on "
                f"{', '.join(recorded.projects)}, this run {report.golden} on "
                f"{', '.join(report.projects)}: record this run (docs/evals.md)"
            )
        ]
    before = {(r.configuration, r.chunking): r.metrics for r in recorded.results}
    problems = run_problems(report)
    for r in report.results:
        then = before.get((r.configuration, r.chunking))
        if r.metrics is None or then is None:
            continue
        for metric in ("recall_at_5", "ndcg_at_10"):
            drop = _points(getattr(then, metric) - getattr(r.metrics, metric))
            if drop > MAX_RECALL_DROP_POINTS + _EPSILON:
                problems.append(
                    f"{r.configuration} @ {r.chunking}: {metric.replace('_at_', '@')} dropped "
                    f"{drop} points (at most {MAX_RECALL_DROP_POINTS})"
                )
    return problems


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _pair(m: BenchMetrics | None) -> str:
    if m is None:
        return "-"
    if not m.answerable:  # unanswerable cases: clean / no answer instead
        return f"clean {_pct(m.unanswerable_clean_rate)}, no answer {_pct(m.no_answer_rate)}"
    return f"{_pct(m.recall_at_5)} / {_pct(m.section_recall_at_5)} / {m.ndcg_at_10:.3f}"


def _breakdown(title: str, ran: Sequence[ConfigResult], pick: str) -> list[str]:
    """A table of recall@5 / nDCG@10 per result and group.

    Args:
        title: The section's heading.
        ran: The results that ran.
        pick: ``by_kind`` or ``by_project``.

    Returns:
        The lines.
    """
    groups = sorted({g for r in ran for g in getattr(r, pick)})
    lines = [
        "",
        f"## {title} (recall@5 / section recall@5 / nDCG@10)",
        "",
        "| configuration | chunking | " + " | ".join(groups) + " |",
        "|---|---|" + "---|" * len(groups),
    ]
    for r in ran:
        cells = " | ".join(_pair(getattr(r, pick).get(g)) for g in groups)
        lines.append(f"| `{r.configuration}` | `{r.chunking}` | {cells} |")
    return lines


def markdown(report: RetrievalBenchReport) -> str:
    """Render the report as a Markdown summary.

    Args:
        report: The run.

    Returns:
        The recommended defaults, every result, the breakdowns, what did not run and the models.
    """
    env = report.environment
    lines = [
        "# Retrieval benchmark",
        "",
        (
            f"The golden set's {report.cases} cases (`{report.golden}`) on "
            f"{', '.join(report.projects)}, every pinned version, per configuration and chunking. "
            f"ExactDocs `{env.get('exactdocs_commit', '?')}`, {env.get('platform', '?')}. "
            "Recall, MRR and nDCG over answerable cases; unanswerable cases scored on returning "
            "nothing of another version (clean) and on coming back empty (no answer). "
            "Definitions: docs/evals.md#the-retrieval-benchmark."
        ),
        "",
        "## Recommended defaults",
        "",
        "| budget | configuration | chunking | USD / 1000 questions | why |",
        "|---|---|---|---|---|",
    ]
    for p in report.recommendations:
        if p.configuration is None:
            lines.append(f"| {p.budget} | {p.reasons[0]} | - | - | - |")
            continue
        usd = "-" if p.usd_per_1000_questions is None else f"${p.usd_per_1000_questions:.4f}"
        why = "; ".join(p.reasons)
        lines.append(f"| {p.budget} | `{p.configuration}` | `{p.chunking}` | {usd} | {why} |")
    lines.extend(
        [
            "",
            "## Every configuration",
            "",
            (
                "| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 "
                "| MRR | nDCG@10 | wrong version | unanswerable clean / no answer "
                "| answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    ran = [r for r in report.results if r.metrics is not None]
    lines.extend(_result_line(r) for r in ran)
    lines.extend(_breakdown("By question kind", ran, "by_kind"))
    lines.extend(_breakdown("By project", ran, "by_project"))
    lines.extend(_notes(report, ran))
    return "\n".join(lines) + "\n"


def _result_line(r: ConfigResult) -> str:
    """One row of the table of every configuration.

    Args:
        r: A result that ran.

    Returns:
        The table row.
    """
    m = r.metrics
    if m is None:
        return f"| `{r.configuration}` | `{r.chunking}` | {r.budget} | {r.status} |"
    index = "-" if r.index is None else f"{r.index.seconds:.0f}"
    return (
        f"| `{r.configuration}` | `{r.chunking}` | {r.budget} | {r.status} "
        f"| {_pct(m.recall_at_1)} | {_pct(m.recall_at_5)} | {_pct(m.recall_at_10)} "
        f"| {m.mrr:.3f} | {m.ndcg_at_10:.3f} | {m.wrong_version_rate:g} "
        f"| {_pct(m.unanswerable_clean_rate)} / {_pct(m.no_answer_rate)} "
        f"| {_pct(m.answerable_empty_rate)} | {m.latency_p50_ms:.1f} | {m.latency_p95_ms:.1f} "
        f"| {m.tokens_per_question:.0f} | {m.usd_per_question * 1000:.4f} | {index} |"
    )


def _notes(report: RetrievalBenchReport, ran: Sequence[ConfigResult]) -> list[str]:
    """What did not run and why, the fallbacks, and every model that ran.

    Args:
        report: The run.
        ran: Its results that ran.

    Returns:
        The lines.
    """
    lines: list[str] = []
    skipped: dict[str, str] = {}
    for r in report.results:
        if r.metrics is None:
            skipped.setdefault(r.configuration, f"{r.status} ({r.reason})")
    if skipped:
        lines.extend(["", "## Not run", ""])
        lines.extend(f"- `{name}`: {why}" for name, why in skipped.items())
    fallbacks = [
        f"- `{r.configuration}` at `{r.chunking}`: reranker failed or timed out on "
        f"{r.rerank_fallbacks}; {r.fallbacks} answered by a cheaper mode"
        for r in ran
        if r.rerank_fallbacks or r.fallbacks
    ]
    if fallbacks:
        lines.extend(["", "## Fallbacks", "", *fallbacks])
    models: dict[str, str] = {}
    for r in ran:
        for info in r.models:
            revision = f" @ `{info.revision[:12]}`" if info.revision else ""
            models.setdefault(info.model, f"- {info.role}: `{info.model}`{revision}")
    if models:
        lines.extend(["", "## Models", "", *models.values()])
    return lines
