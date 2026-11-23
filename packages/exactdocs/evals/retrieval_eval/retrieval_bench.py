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
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.stats import (
    Interval,
    PairedTest,
    StatsMethod,
    interval,
    paired_binary,
    paired_mean,
)
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

    case: str = ""
    """The golden case's name: it pairs the case across configurations (#489)."""
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
        case=case.name or "",
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
    intervals: dict[str, Interval] = {}
    """The 95% interval of each rate and mean above, by field name (#489): a percentile bootstrap
    over the cases (``stats``). Empty in a result recorded without its rows."""


def _hit(row: Row, k: int) -> float:
    return 1.0 if row.rank is not None and row.rank <= k else 0.0


def _found(row: Row, k: int) -> float:
    return sum(rank <= k for rank in row.section_ranks) / row.sections


def columns_of(rows: Sequence[Row]) -> dict[str, list[float]]:
    """Each case's value of every rate and mean metric: the metric is the mean of its column.

    Args:
        rows: The cases' rows, in the order to pair them in.

    Returns:
        The values by ``BenchMetrics`` field; a rate over cases there are none of has none.
    """
    answerable = [r for r in rows if r.answerable]
    unanswerable = [r for r in rows if not r.answerable]
    return {
        "recall_at_1": [_hit(r, 1) for r in answerable],
        "recall_at_5": [_hit(r, 5) for r in answerable],
        "recall_at_10": [_hit(r, 10) for r in answerable],
        "mrr": [1 / r.rank if r.rank else 0.0 for r in answerable],
        "ndcg_at_10": [r.ndcg for r in answerable],
        "section_recall_at_5": [_found(r, 5) for r in answerable],
        "section_recall_at_10": [_found(r, 10) for r in answerable],
        "wrong_version_rate": [float(r.wrong_version) for r in rows],
        "unanswerable_clean_rate": [float(not r.wrong_version) for r in unanswerable],
        "no_answer_rate": [float(r.empty) for r in unanswerable],
        "answerable_empty_rate": [float(r.empty) for r in answerable],
        "tokens_per_question": [float(r.tokens) for r in rows],
        "usd_per_question": [r.usd for r in rows],
    }


_ROUNDING: Final[dict[str, int]] = {"tokens_per_question": 1, "usd_per_question": _USD_DIGITS}
"""Decimals of the means that are not rounded to ``_DIGITS``."""


def metrics_of(rows: Sequence[Row], method: StatsMethod = DEFAULT_STATS) -> BenchMetrics:
    """Aggregate rows.

    Args:
        rows: The cases' rows.
        method: How the intervals are computed.

    Returns:
        The metrics, with their intervals; rates over an empty set are 0 (ranks, the version,
        cost) or None (the conditional rates).
    """
    rows = sorted(rows, key=lambda r: r.case)  # the same draws for the same cases (paired)
    columns = columns_of(rows)

    def mean(name: str) -> float | None:
        """A metric's value.

        Args:
            name: Its field.

        Returns:
            The mean of its column, rounded; None for no case.
        """
        values = columns[name]
        return round(fmean(values), _ROUNDING.get(name, _DIGITS)) if values else None

    latencies = [r.search_ms for r in rows]
    spread = {
        name: found
        for name, values in columns.items()
        if (found := interval(values, method, digits=_ROUNDING.get(name, _DIGITS))) is not None
    }
    return BenchMetrics(
        questions=len(rows),
        answerable=sum(r.answerable for r in rows),
        unanswerable=sum(not r.answerable for r in rows),
        recall_at_1=mean("recall_at_1") or 0.0,
        recall_at_5=mean("recall_at_5") or 0.0,
        recall_at_10=mean("recall_at_10") or 0.0,
        mrr=mean("mrr") or 0.0,
        ndcg_at_10=mean("ndcg_at_10") or 0.0,
        section_recall_at_5=mean("section_recall_at_5") or 0.0,
        section_recall_at_10=mean("section_recall_at_10") or 0.0,
        wrong_version_rate=mean("wrong_version_rate") or 0.0,
        unanswerable_clean_rate=mean("unanswerable_clean_rate"),
        no_answer_rate=mean("no_answer_rate"),
        answerable_empty_rate=mean("answerable_empty_rate"),
        latency_p50_ms=round(percentile(latencies, 0.5), 3),
        latency_p95_ms=round(percentile(latencies, 0.95), 3),
        tokens_per_question=mean("tokens_per_question") or 0.0,
        usd_per_question=mean("usd_per_question") or 0.0,
        intervals=spread,
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


class Versus(_Model):
    """A result tested against another on the answerable cases both answered (#489)."""

    configuration: str
    """The other result's configuration."""
    chunking: str
    """The other result's chunking."""
    tests: dict[str, PairedTest]
    """By metric: McNemar for recall@1, @5 and @10, a permutation test for MRR and nDCG@10."""


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
    rows: list[Row] = []
    """Every case's outcome, by case name (#489): the intervals and the paired tests come from
    them. Empty in a result recorded before they were kept."""
    rows_from: str | None = None
    """Set when ``rows`` come from a later run of this configuration than ``metrics`` did (a
    recorded run that kept no rows, completed by a re-run whose recall, MRR, nDCG and rates
    matched it exactly): that run's commit and machine. Its ``search_ms`` are that run's, not
    the recorded latencies. None: the rows are this run's."""
    versus_default: Versus | None = None
    """Paired tests against its budget's default; None for the default itself, for a budget
    with no default, and when either has no rows."""

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
                "rows": sorted(rows, key=lambda r: r.case),
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
    test: PairedTest | None = None
    """The paired test of recall@5 of the budget's best against the cheaper budget's default
    (#489); None when there was none to compare with, or no rows to pair."""


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
    statistics: StatsMethod | None = None
    """How the intervals and paired tests were computed: seed, resamples, confidence and
    significance level (#489). None in a report recorded before them."""


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


BINARY_TESTS: Final[tuple[str, ...]] = ("recall_at_1", "recall_at_5", "recall_at_10")
"""The hit-or-miss metrics a result is tested on against another (McNemar, mid-p)."""
GRADED_TESTS: Final[tuple[str, ...]] = ("mrr", "ndcg_at_10")
"""The graded metrics a result is tested on against another (sign-flip permutation)."""


def paired_tests(
    a: ConfigResult, b: ConfigResult, method: StatsMethod = DEFAULT_STATS
) -> dict[str, PairedTest]:
    """Test result B against result A on the answerable cases both answered.

    Args:
        a: The result compared with (a default).
        b: The result tested.
        method: The seed, resamples, confidence and significance level.

    Returns:
        A test per metric of ``BINARY_TESTS`` and ``GRADED_TESTS``; empty when the two share no
        answerable case with a name (a result recorded without its rows).
    """
    theirs = {r.case: r for r in a.rows if r.answerable and r.case}
    mine = {r.case: r for r in b.rows if r.answerable and r.case}
    common = sorted(theirs.keys() & mine.keys())
    before = columns_of([theirs[c] for c in common])
    after = columns_of([mine[c] for c in common])
    tests: dict[str, PairedTest | None] = {}
    for name in BINARY_TESTS:
        hits = [v > 0 for v in before[name]], [v > 0 for v in after[name]]
        tests[name] = paired_binary(*hits, method)
    for name in GRADED_TESTS:
        tests[name] = paired_mean(before[name], after[name], method)
    return {name: test for name, test in tests.items() if test is not None}


def _p(test: PairedTest) -> str:
    return f"McNemar mid-p {test.p_value:.3g}"


def _verdict(
    previous: ConfigResult, best: ConfigResult, test: PairedTest | None, alpha: float
) -> tuple[bool, str]:
    """Decide whether a budget's best replaces the cheaper default: by the margin and the test.

    Args:
        previous: The cheaper budget's default.
        best: The budget's best result.
        test: The paired test of its recall@5 against ``previous``; None with no rows to pair.
        alpha: The significance level.

    Returns:
        Whether it does, and the reason.
    """
    then = previous.metrics.recall_at_5 if previous.metrics else 0.0
    gain = _points((best.metrics.recall_at_5 if best.metrics else 0.0) - then)
    versus = f"{gain:+.1f} points of recall@5 over `{previous.configuration}`"
    margin = f"{DEFAULT_MARGIN_POINTS:g}-point margin"
    stays = f"the cheaper `{previous.configuration}` at `{previous.chunking}` stays the default"
    if gain < DEFAULT_MARGIN_POINTS - _EPSILON:
        tested = f" ({_p(test)})" if test else ""
        return False, f"{versus}, under the {margin}{tested}: {stays}"
    if test is None:
        return False, (
            f"{versus}, over the {margin} but not tested for significance (no per-case "
            f"outcomes to pair): {stays}"
        )
    if not test.significant:
        return False, (
            f"{versus}, over the {margin} but the difference is not significant "
            f"({_p(test)}, not under {alpha:g}): {stays}"
        )
    return True, f"{versus} (margin {DEFAULT_MARGIN_POINTS:g}; significant, {_p(test)})"


def recommend(
    results: Sequence[ConfigResult], method: StatsMethod = DEFAULT_STATS
) -> list[Recommendation]:
    """Name the default for each budget, cheapest first.

    Candidates ran without a wrong version, a read outside the version, an error or a reranker
    fallback. The best of a budget (recall@5, then nDCG@10, MRR, lower cost, lower p95) becomes
    its default only when its recall@5 beats the cheaper budget's default by
    ``DEFAULT_MARGIN_POINTS`` **and** McNemar's test of the two on the same cases is significant
    (#489); otherwise the cheaper default stays, since it is as good for less as far as the golden
    set can tell.

    Args:
        results: Every result of the run.
        method: The seed, resamples, confidence and significance level of the test.

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
        test = None
        if previous is not None and previous.metrics and best.metrics:
            test = paired_tests(previous, best, method).get("recall_at_5")
            replaces, why = _verdict(previous, best, test, method.alpha)
            reasons.append(why)
            best = best if replaces else previous
        m = best.metrics
        picks.append(
            Recommendation(
                budget=budget,
                configuration=best.configuration,
                chunking=best.chunking,
                usd_per_1000_questions=round(m.usd_per_question * 1000, 4) if m else None,
                reasons=reasons,
                test=test,
            )
        )
        previous = best
    return picks


def against_defaults(
    results: Sequence[ConfigResult],
    picks: Sequence[Recommendation],
    method: StatsMethod = DEFAULT_STATS,
) -> list[ConfigResult]:
    """Test every result against its budget's default, on the cases both answered.

    Args:
        results: Every result of the run.
        picks: The default of each budget (``recommend``).
        method: The seed, resamples, confidence and significance level.

    Returns:
        The results, each with ``versus_default`` when there is a default to pair it with.
    """
    by_name = {(r.configuration, r.chunking): r for r in results}
    defaults = {p.budget: by_name.get((p.configuration or "", p.chunking or "")) for p in picks}
    tested = []
    for r in results:
        default = defaults.get(r.budget)
        same = default is not None and (default.configuration, default.chunking) == (
            r.configuration,
            r.chunking,
        )
        tests = {} if default is None or same else paired_tests(default, r, method)
        if default is None or not tests:
            tested.append(r)
            continue
        versus = Versus(configuration=default.configuration, chunking=default.chunking, tests=tests)
        tested.append(r.model_copy(update={"versus_default": versus}))
    return tested


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


def _with_ci(m: BenchMetrics, name: str) -> str:
    """A rate as a percentage, or a score, followed by its interval when it has one.

    Args:
        m: The metrics.
        name: The field: a ``recall`` is a rate, anything else a score.

    Returns:
        ``81.7% [77.2, 86.1]``, ``0.651 [0.611, 0.690]``, or the value alone.
    """
    value: float = getattr(m, name)
    spread = m.intervals.get(name)
    if "recall" in name:
        shown = _pct(value)
        return f"{shown} [{spread.low * 100:.1f}, {spread.high * 100:.1f}]" if spread else shown
    return f"{value:.3f} [{spread.low:.3f}, {spread.high:.3f}]" if spread else f"{value:.3f}"


def _pair(m: BenchMetrics | None) -> str:
    if m is None:
        return "-"
    if not m.answerable:  # unanswerable cases: clean / no answer instead
        return f"clean {_pct(m.unanswerable_clean_rate)}, no answer {_pct(m.no_answer_rate)}"
    return (
        f"{_with_ci(m, 'recall_at_5')} / {_pct(m.section_recall_at_5)} / "
        f"{_with_ci(m, 'ndcg_at_10')}"
    )


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
        *(
            _SMALL_GROUPS
            if any(m.intervals for r in ran for m in getattr(r, pick).values())
            else []
        ),
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
    lines.extend(_intervals_note(report))
    lines.extend(_tests_section(report, ran))
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
        f"| {_with_ci(m, 'recall_at_1')} | {_with_ci(m, 'recall_at_5')} "
        f"| {_with_ci(m, 'recall_at_10')} | {_with_ci(m, 'mrr')} | {_with_ci(m, 'ndcg_at_10')} "
        f"| {m.wrong_version_rate:g} "
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


_SMALL_GROUPS: Final[list[str]] = [
    (
        "A kind or a project holds only part of the cases (about 50 per kind in the golden set), "
        "so its intervals, in brackets, are much wider than the whole set's."
    ),
    "",
]
"""Said above a breakdown that has intervals."""
_SMALL_P: Final[float] = 0.001
"""A p-value below this is shown as ``p < 0.001``."""
_LABELS: Final[dict[str, str]] = {
    "recall_at_1": "recall@1",
    "recall_at_5": "recall@5",
    "recall_at_10": "recall@10",
    "mrr": "MRR",
    "ndcg_at_10": "nDCG@10",
}
"""How the tested metrics are named in the summary."""


def _intervals_note(report: RetrievalBenchReport) -> list[str]:
    """Say how the intervals of the table above were computed.

    Args:
        report: The run.

    Returns:
        The lines; none for a report recorded without intervals.
    """
    method = report.statistics
    if method is None:
        return []
    without = [
        f"`{r.configuration}` at `{r.chunking}`"
        for r in report.results
        if r.metrics is not None and not r.metrics.intervals
    ]
    lines = [
        "",
        (
            f"In brackets: the {method.confidence:.0%} interval, a percentile bootstrap over the "
            f"cases ({method.resamples:,} resamples, seed {method.seed})."
        ),
    ]
    if without:
        lines[-1] += (
            " Recorded without their per-case outcomes, so with no interval: "
            + ", ".join(without)
            + "."
        )
    return lines


def _test_cell(test: PairedTest | None, *, points: bool) -> str:
    """One paired test: the difference, its interval and the p-value; bold when significant.

    Args:
        test: The test, or None.
        points: Show a rate's difference in points; otherwise as a score.

    Returns:
        ``+3.0 [-0.9, +6.9], p 0.13``, or ``-``.
    """
    if test is None:
        return "-"
    scale, digits = (100, 1) if points else (1, 3)
    low, high = test.interval.low * scale, test.interval.high * scale
    shown = f"{test.difference * scale:+.{digits}f}"
    shown = f"**{shown}**" if test.significant else shown
    p = f"p < {_SMALL_P:g}" if test.p_value < _SMALL_P else f"p {test.p_value:.2g}"
    return f"{shown} [{low:+.{digits}f}, {high:+.{digits}f}], {p}"


def _tests_section(report: RetrievalBenchReport, ran: Sequence[ConfigResult]) -> list[str]:
    """The paired tests of every result against its budget's default.

    Args:
        report: The run.
        ran: Its results that ran.

    Returns:
        The lines; none when no result was tested.
    """
    tested = [(r, r.versus_default) for r in ran if r.versus_default is not None]
    untested = [f"`{r.configuration}` at `{r.chunking}`" for r in ran if not r.rows]
    if not tested and not untested:
        return []
    alpha = report.statistics.alpha if report.statistics else DEFAULT_STATS.alpha
    metrics = (*BINARY_TESTS, *GRADED_TESTS)
    lines = [
        "",
        "## Against the budget's default",
        "",
        (
            "Each result against its budget's default, on the answerable cases both answered: "
            "the difference (recall@k in points, MRR and nDCG@10 as scores), its paired "
            "bootstrap interval in brackets, and the p-value of McNemar's test (mid-p) for "
            "recall@k or of a sign-flip permutation test for MRR and nDCG@10. "
            f"**Bold**: significant at {alpha:.0%}."
        ),
        "",
        "| configuration | chunking | budget | against | "
        + " | ".join(_LABELS[m] for m in metrics)
        + " |",
        "|---|---|---|---|" + "---|" * len(metrics),
    ]
    for r, versus in tested:
        cells = [_test_cell(versus.tests.get(m), points=m in BINARY_TESTS) for m in metrics]
        lines.append(
            f"| `{r.configuration}` | `{r.chunking}` | {r.budget} "
            f"| `{versus.configuration}` at `{versus.chunking}` | " + " | ".join(cells) + " |"
        )
    if untested:
        lines += ["", f"Not tested, recorded without per-case outcomes: {', '.join(untested)}."]
    return lines
