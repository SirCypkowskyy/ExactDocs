"""The harness benchmark's report: per harness, model and arm, with intervals and paired tests.

One row per job (a coding task or a golden question) run once by one harness with one model and
one arm. A cell (harness, model, arm and configuration, job kind) gives, over its counted runs (a
provider's or the CLI's own failure is not counted, but listed in *Errors*), each with its 95%
interval (``retrieval_eval.stats``):

- the **pass rate** (a task's hidden tests passed) or the **accuracy** (the judge's grade);
- the share of runs that **called the documentation server** at least once, and the **docs calls**
  per run;
- the **wall time** (mean, p50, p95), the **input tokens**, the **output tokens with the thinking**,
  the **thinking tokens** where the CLI reports them (else *not reported*), and **USD** (else
  *unpriced*);
- built-in web calls and the hosts the gate refused (a CLI's telemetry, updates, a web tool).

Every arm is compared with the same harness's ``none`` arm on the same jobs (pass rate by McNemar's
test, wall time and output tokens by a paired permutation test, with the ratios of the means), and,
given the no-harness reports of #496 and #495, with the same model and arm without a harness.
"""

import itertools
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agent_bench.arms import NONE
from agent_bench.report import ArmComparison, BenchReport, QuestionResult, Spread, accurate
from agent_bench.report import counted as question_counted
from coding_tasks.report import CodingReport, Rate, TaskResult
from harness_bench.harness import Harness
from harness_bench.jobs import JobKind
from harness_bench.transcript import HarnessCall, ThinkingSource, UsdSource
from retrieval_eval.stats import (
    DEFAULT,
    StatsMethod,
    interval,
    paired_binary,
    paired_mean,
)
from retrieval_eval.suite import percentile

NO_HARNESS: Final[str] = "no harness"
"""How a comparison with the pydantic-ai loop (#495, #496) names its baseline."""
P95: Final[float] = 0.95
"""The high percentile of each cost."""
SHOWN_FAILURES: Final[int] = 30
"""Runs without an answer listed in the Markdown (all are in the JSON)."""

type CellKey = tuple[str, str, str, str, JobKind]
"""``(harness, agent model, arm, retrieval, kind)``."""
type BaselineKey = tuple[str, str, str, str, str]
"""``(agent model, arm, retrieval, kind, job)`` of a run without a harness."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class HarnessResult(_Model):
    """One job run once by one harness with one model and one arm."""

    harness: str
    """The harness."""
    cli_version: str
    """Its CLI's version (as the transcript says it, else the pinned one)."""
    agent_model: str
    """The model, ``<provider>:<model>``."""
    arm: str
    """The documentation arm."""
    retrieval: str = ""
    """The arm's configuration."""
    kind: JobKind
    """A coding task or a golden question."""
    job: str
    """The task's ID or the case's name."""
    project: str
    """The golden project."""
    outcome: str
    """``passed``, ``failed`` or ``error`` (a task); the judge's grade (a question)."""
    passed: bool
    """The task passed, or the answer counts as accurate."""
    counted: bool
    """It counts in the rates: not a failure of the provider's or the CLI's."""
    failure: str | None = None
    """``provider``, ``harness`` (the CLI failed to run), ``no_answer`` (the agent's side), or
    ``None``."""
    error: str | None = None
    """Why the run ended without an answer."""
    seconds: float
    """Wall time of the CLI's run, container start included (grading not included)."""
    reported_seconds: float | None = None
    """The run's duration as the CLI reports it."""
    timed_out: bool = False
    """It was killed at the wall limit."""
    exit_code: int | None = None
    """The CLI's exit status."""
    turns: int | None = None
    """Model requests, where the transcript counts them."""
    input_tokens: int | None = None
    """Input tokens, cached ones included; ``None`` when not reported."""
    cached_input_tokens: int | None = None
    """Of them, read from the provider's cache."""
    output_tokens: int | None = None
    """Output tokens, the thinking included; ``None`` when not reported."""
    thinking_tokens: int | None = None
    """Thinking tokens on their own; ``None`` when not reported."""
    thinking_source: ThinkingSource = "not reported"
    """Where ``thinking_tokens`` comes from."""
    thinking_chars: int = 0
    """Characters of thinking text in the transcript."""
    usd: float | None = None
    """What it cost; ``None`` when unpriced."""
    usd_source: UsdSource = "unpriced"
    """Where ``usd`` comes from."""
    calls: list[HarnessCall] = Field(default_factory=list)
    """Every tool call."""
    docs_calls: int = 0
    """Calls to the arm's documentation server."""
    web_calls: int = 0
    """Calls to a built-in web tool (there must be none)."""
    tools_offered: list[str] = Field(default_factory=list)
    """The tools the CLI said it offered, where its transcript lists them."""
    tunnels: dict[str, int] = Field(default_factory=dict)
    """Tunnels the gate opened, by host."""
    denied: dict[str, int] = Field(default_factory=dict)
    """What the gate refused, by host."""
    answer: str = ""
    """The final message."""
    run_dir: str = ""
    """The run's folder in the work directory (transcript, standard error, workspace)."""
    task: TaskResult | None = None
    """The coding tasks' row (a task)."""
    question: QuestionResult | None = None
    """The agent benchmark's row (a question)."""


class Usage(_Model):
    """A cost per run over the runs that report it."""

    reported: int
    """Runs that report it."""
    of: int
    """Runs counted."""
    spread: Spread | None = None
    """Mean with its interval, p50 and p95 over the runs that report it."""


class CellSummary(_Model):
    """One harness with one model and one arm (and configuration), over one kind of job."""

    harness: str
    """The harness."""
    agent_model: str
    """The model."""
    arm: str
    """The arm."""
    retrieval: str = ""
    """The arm's configuration."""
    kind: JobKind
    """Coding tasks or golden questions."""
    runs: int
    """Runs made."""
    errors: int
    """Runs the provider or the CLI failed: not counted."""
    passed: Rate
    """Tasks passed, or answers accurate."""
    called_docs: Rate | None = None
    """Runs that called the documentation server at least once; ``None`` for ``none``."""
    docs_calls: Spread | None = None
    """Documentation calls per run."""
    tool_calls: Spread | None = None
    """Tool calls per run, every tool."""
    seconds: Spread | None = None
    """Wall time per run."""
    input_tokens: Usage
    """Input tokens per run."""
    output_tokens: Usage
    """Output tokens per run, the thinking included."""
    thinking_tokens: Usage
    """Thinking tokens per run, where reported."""
    thinking: str
    """Where the thinking tokens come from: ``reported``, ``derived``, ``not reported`` or a mix."""
    usd: Usage
    """USD per run, where priced."""
    web_calls: int = 0
    """Built-in web calls over the cell."""
    denied: dict[str, int] = Field(default_factory=dict)
    """Hosts the gate refused over the cell, by host."""
    versus_none: ArmComparison | None = None
    """Against the same harness's ``none`` arm, same model, on the jobs both counted."""
    versus_no_harness: ArmComparison | None = None
    """Against the same model and arm without a harness (#495, #496), on the same jobs."""


class HarnessMeta(_Model):
    """One harness as it ran."""

    name: str
    """The harness."""
    package: str
    """Its CLI's npm package."""
    version: str
    """The pinned release."""
    integrity: str
    """The release's integrity hash."""
    released: date
    """When it was published."""
    providers: list[str]
    """The providers it runs against."""
    web_tools: str
    """How its built-in web tools are turned off (or why they cannot be)."""
    limits: str
    """How the turn limit and the thinking setting reach it."""
    isolation: str
    """How its runs are isolated."""


class RunMeta(_Model):
    """What a rerun needs."""

    started_at: str
    """When the run started (UTC)."""
    exactdocs_version: str
    """The ExactDocs version."""
    git_commit: str | None
    """The repository's commit."""
    harnesses: list[HarnessMeta]
    """The harnesses."""
    agent_models: list[str]
    """The models."""
    thinking: dict[str, str] = Field(default_factory=dict)
    """Each model's thinking setting."""
    arms: list[str]
    """The arms."""
    servers: dict[str, dict[str, str]] = Field(default_factory=dict)
    """What each arm's server was (``agent_bench.servers.ArmServers.described``)."""
    jobs: int
    """Jobs per harness, model and arm."""
    selection: str
    """How the jobs were picked."""
    cutoff: date | None = None
    """The training cutoff the tasks are counted against."""
    judge_model: str | None = None
    """The judge of the golden questions."""
    max_turns: int
    """The turn limit, where a CLI takes one."""
    wall_seconds: float
    """The wall limit of a run."""
    concurrency: int
    """Runs at once."""
    isolation: str
    """How runs are isolated."""
    image: str = ""
    """The container image."""
    resumed: int = 0
    """Runs kept from an earlier run of the same command."""
    baselines: list[str] = Field(default_factory=list)
    """The no-harness reports compared with."""


class HarnessReport(_Model):
    """A run of the harness benchmark."""

    meta: RunMeta
    """What a rerun needs."""
    cells: list[CellSummary]
    """One per harness, model, arm, configuration and kind."""
    results: list[HarnessResult]
    """Every run."""
    statistics: StatsMethod = DEFAULT
    """How the intervals and tests were computed."""


def harness_meta(harness: Harness, isolation: str) -> HarnessMeta:
    """Describe a harness for the report.

    Args:
        harness: The harness.
        isolation: How its runs are isolated.

    Returns:
        Its release, providers, web tools and limits.
    """
    release = harness.release
    return HarnessMeta(
        name=harness.name,
        package=release.package,
        version=release.version,
        integrity=release.integrity,
        released=release.released,
        providers=sorted(harness.providers),
        web_tools=harness.web_tools,
        limits=harness.limits,
        isolation=isolation,
    )


def _rate(values: Sequence[bool], method: StatsMethod) -> Rate:
    """A share with its interval.

    Args:
        values: One outcome per run, in job order.
        method: The bootstrap's settings.

    Returns:
        The rate.
    """
    if not values:
        return Rate(count=0, rate=None)
    floats = [1.0 if v else 0.0 for v in values]
    return Rate(
        count=len(values),
        rate=round(statistics.fmean(floats), 4),
        interval=interval(floats, method),
    )


def _spread(values: Sequence[float], method: StatsMethod, digits: int = 3) -> Spread | None:
    """Mean with its interval, p50 and p95.

    Args:
        values: One value per run, in job order.
        method: The bootstrap's settings.
        digits: Decimals kept.

    Returns:
        The spread; ``None`` for no value.
    """
    if not values:
        return None
    return Spread(
        questions=len(values),
        mean=round(statistics.fmean(values), digits),
        interval=interval(values, method, digits=digits),
        p50=round(percentile(values, 0.5), digits),
        p95=round(percentile(values, P95), digits),
    )


def _usage(
    rows: Sequence[HarnessResult], of: Callable[[HarnessResult], float | None], method: StatsMethod
) -> Usage:
    """A cost over the runs that report it.

    Args:
        rows: The counted runs.
        of: Reads the cost (``None`` when not reported).
        method: The bootstrap's settings.

    Returns:
        How many report it, and its spread over them.
    """
    values = [float(v) for r in rows if (v := of(r)) is not None]
    return Usage(reported=len(values), of=len(rows), spread=_spread(values, method, digits=4))


def _thinking(rows: Sequence[HarnessResult]) -> str:
    """Say where a cell's thinking tokens come from.

    Args:
        rows: The counted runs.

    Returns:
        ``reported``, ``derived``, ``not reported``, or the sources and how many of each.
    """
    sources = Counter(r.thinking_source for r in rows)
    if len(sources) <= 1:
        return next(iter(sources), "not reported")
    return ", ".join(f"{source} ({n})" for source, n in sorted(sources.items()))


def _ordered(rows: Iterable[HarnessResult]) -> list[HarnessResult]:
    """Put runs in job order, so cells of the same jobs share the bootstrap's draws.

    Args:
        rows: Runs.

    Returns:
        Them, by job.
    """
    return sorted(rows, key=lambda r: r.job)


def summarize(key: CellKey, rows: Sequence[HarnessResult], method: StatsMethod) -> CellSummary:
    """Aggregate one cell.

    Args:
        key: The harness, model, arm, configuration and kind.
        rows: The cell's runs.
        method: The bootstrap's settings.

    Returns:
        The cell's summary, without the comparisons.
    """
    kept = _ordered(r for r in rows if r.counted)
    denied: Counter[str] = Counter()
    for row in rows:
        denied.update(row.denied)
    return CellSummary(
        harness=key[0],
        agent_model=key[1],
        arm=key[2],
        retrieval=key[3],
        kind=key[4],
        runs=len(rows),
        errors=len(rows) - len(kept),
        passed=_rate([r.passed for r in kept], method),
        called_docs=None if key[2] == NONE else _rate([r.docs_calls > 0 for r in kept], method),
        docs_calls=None if key[2] == NONE else _spread([float(r.docs_calls) for r in kept], method),
        tool_calls=_spread([float(len(r.calls)) for r in kept], method),
        seconds=_spread([r.seconds for r in kept], method),
        input_tokens=_usage(kept, lambda r: r.input_tokens, method),
        output_tokens=_usage(kept, lambda r: r.output_tokens, method),
        thinking_tokens=_usage(kept, lambda r: r.thinking_tokens, method),
        thinking=_thinking(kept),
        usd=_usage(kept, lambda r: r.usd, method),
        web_calls=sum(r.web_calls for r in rows),
        denied=dict(denied.most_common()),
    )


def _ratio(mine: Sequence[float], theirs: Sequence[float]) -> float | None:
    """The ratio of two means.

    Args:
        mine: This cell's values.
        theirs: The baseline's, on the same jobs.

    Returns:
        ``mean(mine) / mean(theirs)``, rounded to 2 places; ``None`` when undefined.
    """
    if not mine or not statistics.fmean(theirs):
        return None
    return round(statistics.fmean(mine) / statistics.fmean(theirs), 2)


def compare(
    mine: Mapping[str, tuple[bool, float, float, float]],
    theirs: Mapping[str, tuple[bool, float, float, float]],
    against: str,
    method: StatsMethod,
    against_retrieval: str = "",
) -> ArmComparison | None:
    """Compare a cell with a baseline on the jobs both counted.

    Args:
        mine: This cell's ``(passed, seconds, input tokens, output tokens)`` by job.
        theirs: The baseline's.
        against: The baseline's name (``none``, ``no harness``).
        method: The tests' settings.
        against_retrieval: The baseline's configuration.

    Returns:
        The paired tests of the pass rate, wall time and tokens, and the ratios; ``None`` when
        they share no job.
    """
    common = sorted(mine.keys() & theirs.keys())
    if not common:
        return None
    a, b = [theirs[j] for j in common], [mine[j] for j in common]
    seconds_a, seconds_b = [x[1] for x in a], [x[1] for x in b]
    output_a, output_b = [x[3] for x in a], [x[3] for x in b]
    return ArmComparison(
        against=against,
        against_retrieval=against_retrieval,
        cases=len(common),
        accuracy=paired_binary([x[0] for x in a], [x[0] for x in b], method),
        seconds=paired_mean(seconds_a, seconds_b, method),
        input_tokens=paired_mean([x[2] for x in a], [x[2] for x in b], method),
        output_tokens=paired_mean(output_a, output_b, method),
        seconds_ratio=_ratio(seconds_b, seconds_a),
        output_tokens_ratio=_ratio(output_b, output_a),
    )


def _outcomes(rows: Iterable[HarnessResult]) -> dict[str, tuple[bool, float, float, float]]:
    """Index counted runs by job, for a paired comparison.

    Args:
        rows: Runs of one cell.

    Returns:
        ``(passed, seconds, input tokens, output tokens)`` by job.
    """
    return {
        r.job: (r.passed, r.seconds, float(r.input_tokens or 0), float(r.output_tokens or 0))
        for r in rows
        if r.counted
    }


def baseline_outcomes(
    tasks: CodingReport | None, questions: BenchReport | None
) -> dict[BaselineKey, tuple[bool, float, float, float]]:
    """Read the runs of the same models and arms without a harness (#496's and #495's reports).

    Args:
        tasks: A coding tasks report (``just coding-tasks run``).
        questions: An agent benchmark report (``just agent-bench run``).

    Returns:
        ``(passed, seconds, input tokens, output tokens)`` by ``(model, arm, retrieval, kind,
        job)``, over the runs without a provider failure.
    """
    found: dict[BaselineKey, tuple[bool, float, float, float]] = {}
    for row in tasks.results if tasks else []:
        if row.graded:
            key = (row.agent_model, row.arm, row.retrieval, "task", row.task)
            found[key] = (
                row.passed,
                max(row.seconds - row.retry_seconds, 0.0),
                float(row.input_tokens),
                float(row.output_tokens),
            )
    for q in questions.questions if questions else []:
        if question_counted(q):
            key = (q.agent_model, q.arm, q.retrieval, "question", q.case)
            found[key] = (accurate(q), q.net_seconds, float(q.input_tokens), float(q.output_tokens))
    return found


def cells_of(
    rows: Sequence[HarnessResult],
    method: StatsMethod = DEFAULT,
    baseline: Mapping[BaselineKey, tuple[bool, float, float, float]] | None = None,
) -> list[CellSummary]:
    """Summarize every cell, compared with its harness's ``none`` and with no harness.

    Args:
        rows: Every run.
        method: The bootstrap's and the tests' settings.
        baseline: The runs without a harness (``baseline_outcomes``).

    Returns:
        One summary per cell, in the order the rows first name them.
    """
    by_cell: dict[CellKey, list[HarnessResult]] = {}
    for row in rows:
        by_cell.setdefault(
            (row.harness, row.agent_model, row.arm, row.retrieval, row.kind), []
        ).append(row)
    cells = []
    for key, mine in by_cell.items():
        cell = summarize(key, mine, method)
        versus = None
        nones = [k for k in by_cell if k[0:2] == key[0:2] and k[2] == NONE and k[4] == key[4]]
        if key[2] != NONE and nones:
            versus = compare(_outcomes(mine), _outcomes(by_cell[nones[0]]), NONE, method)
        loop = None
        if baseline:
            theirs = {
                job: value
                for (model, arm, retrieval, kind, job), value in baseline.items()
                if (model, arm, retrieval, kind) == (key[1], key[2], key[3], key[4])
            }
            loop = compare(_outcomes(mine), theirs, NO_HARNESS, method, key[3])
        cells.append(cell.model_copy(update={"versus_none": versus, "versus_no_harness": loop}))
    return cells


# ------------------------------------------------------------------------------------ Markdown


def _pct(rate: Rate | None) -> str:
    """Show a rate with its interval and count.

    Args:
        rate: The rate.

    Returns:
        E.g. ``62.5 % [41.7, 83.3] (n=24)``, or ``n/a``.
    """
    if rate is None or rate.rate is None:
        return "n/a"
    ci = (
        ""
        if rate.interval is None
        else f" [{rate.interval.low * 100:.1f}, {rate.interval.high * 100:.1f}]"
    )
    return f"{rate.rate * 100:.1f} %{ci} (n={rate.count})"


def _mean(value: Spread | None, digits: int = 1, *, spread: bool = True) -> str:
    """Show a cost: mean [interval]; p50; p95.

    Args:
        value: The spread.
        digits: Decimals.
        spread: Also show p50 and p95.

    Returns:
        The text, or ``n/a``.
    """
    if value is None:
        return "n/a"
    ci = (
        ""
        if value.interval is None
        else f" [{value.interval.low:,.{digits}f}, {value.interval.high:,.{digits}f}]"
    )
    text = f"{value.mean:,.{digits}f}{ci}"
    if spread:
        text += f"; p50 {value.p50:,.{digits}f}; p95 {value.p95:,.{digits}f}"
    return text


def _used(usage: Usage, digits: int = 0, *, none: str = "not reported") -> str:
    """Show a cost that some runs may not report.

    Args:
        usage: The cost.
        digits: Decimals.
        none: What to show when no run reports it.

    Returns:
        The mean with its interval, and how many runs report it when not all do.
    """
    if usage.spread is None:
        return none
    text = _mean(usage.spread, digits, spread=False)
    return text if usage.reported == usage.of else f"{text} ({usage.reported} of {usage.of})"


def _label(cell: CellSummary) -> str:
    """Name a cell.

    Args:
        cell: The cell.

    Returns:
        ``harness / model / arm`` (``/ configuration`` for one).
    """
    parts = [
        cell.harness,
        cell.agent_model,
        cell.arm,
        *([cell.retrieval] if cell.retrieval else []),
    ]
    return " / ".join(parts)


def _versus(cell: CellSummary, comparison: ArmComparison) -> str:
    """Show one paired comparison as a table row.

    Args:
        cell: The cell.
        comparison: Its comparison.

    Returns:
        The row.
    """
    passed, seconds, output = comparison.accuracy, comparison.seconds, comparison.output_tokens
    rate_text = "n/a"
    if passed is not None:
        rate_text = (
            f"{passed.difference * 100:+.1f} pts [{passed.interval.low * 100:+.1f}, "
            f"{passed.interval.high * 100:+.1f}]; {passed.gained}/{passed.lost}; p {passed.p_value}"
        )

    def paired(test: object, ratio: float | None) -> str:
        """Show a paired mean difference.

        Args:
            test: The test (a ``PairedTest``, or ``None``).
            ratio: The ratio of the means.

        Returns:
            The difference with its interval, p and the ratio.
        """
        if test is None:
            return "n/a"
        difference = getattr(test, "difference", 0.0)
        found = getattr(test, "interval", None)
        ci = "" if found is None else f" [{found.low:+,.1f}, {found.high:+,.1f}]"
        times = "" if ratio is None else f"; x{ratio}"
        return f"{difference:+,.1f}{ci}; p {getattr(test, 'p_value', '')}{times}"

    return (
        f"| {_label(cell)} | {comparison.cases} | {rate_text} | "
        f"{paired(seconds, comparison.seconds_ratio)} | "
        f"{paired(output, comparison.output_tokens_ratio)} |"
    )


def markdown(report: HarnessReport) -> str:
    """Show the report as Markdown.

    Args:
        report: The run.

    Returns:
        The harnesses, the quality and cost tables, the paired comparisons, the hosts refused,
        the runs without an answer and every job against every cell.
    """
    meta = report.meta
    lines = [
        "## Harnesses",
        "",
        (
            f"{meta.jobs} jobs ({meta.selection}); models {', '.join(meta.agent_models)}; arms "
            f"{', '.join(meta.arms)}; up to {meta.max_turns} turns and {meta.wall_seconds:.0f} s "
            f"a run. Isolation: {meta.isolation}."
        ),
        "",
        "| Harness | CLI | Released | Web tools | Turn limit, thinking |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {h.name} | `{h.package}@{h.version}` | {h.released} | {h.web_tools} | {h.limits} |"
        for h in meta.harnesses
    ]
    if meta.thinking:
        lines += [
            "",
            "Thinking: " + "; ".join(f"`{m}` {t}" for m, t in meta.thinking.items()) + ".",
        ]
    for kind, title, measure in (
        ("task", "Coding tasks", "Passed"),
        ("question", "Golden questions", "Accurate"),
    ):
        cells = [c for c in report.cells if c.kind == kind]
        if cells:
            lines += _kind_tables(cells, title, measure)
    lines += _hosts(report)
    lines += _failures(report)
    lines += _every_job(report)
    return "\n".join(lines) + "\n"


def _kind_tables(cells: Sequence[CellSummary], title: str, measure: str) -> list[str]:
    """The tables of one kind of job.

    Args:
        cells: Its cells.
        title: Its title.
        measure: What its quality is called.

    Returns:
        The quality, cost and comparison tables.
    """
    lines = [
        "",
        f"### {title}",
        "",
        (
            f"| Harness / model / arm | {measure} | Called the docs | Docs calls | Tool calls "
            "| Errors |"
        ),
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {_label(c)} | {_pct(c.passed)} | {_pct(c.called_docs)} | "
        f"{_mean(c.docs_calls, spread=False)} | {_mean(c.tool_calls, spread=False)} | {c.errors} |"
        for c in cells
    ]
    lines += [
        "",
        f"#### {title}: cost per run",
        "",
        (
            "| Harness / model / arm | Wall time (s) | Input tokens "
            "| Output tokens (with thinking) | Thinking tokens | USD |"
        ),
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {_label(c)} | {_mean(c.seconds)} | {_used(c.input_tokens)} | "
        f"{_used(c.output_tokens)} | {_used(c.thinking_tokens)} ({c.thinking}) | "
        f"{_used(c.usd, 4, none='unpriced')} |"
        for c in cells
    ]
    for attribute, heading in (
        ("versus_none", "against the harness's own `none` arm"),
        ("versus_no_harness", "against the same model and arm without a harness"),
    ):
        compared = [(c, getattr(c, attribute)) for c in cells if getattr(c, attribute)]
        if compared:
            lines += [
                "",
                f"#### {title}: {heading}, on the same jobs",
                "",
                (
                    f"| Harness / model / arm | Jobs "
                    f"| {measure} (pts [CI]; gained/lost; McNemar p) "
                    "| Wall time (s [CI]; p; ratio) | Output tokens ([CI]; p; ratio) |"
                ),
                "|---|---|---|---|---|",
            ]
            lines += list(itertools.starmap(_versus, compared))
    return lines


def _hosts(report: HarnessReport) -> list[str]:
    """The web calls and the hosts the gate refused, per harness.

    Args:
        report: The run.

    Returns:
        The section's lines.
    """
    by_harness: dict[str, Counter[str]] = {}
    web: Counter[str] = Counter()
    for row in report.results:
        by_harness.setdefault(row.harness, Counter()).update(row.denied)
        web[row.harness] += row.web_calls
    lines = ["", "### Network", "", "| Harness | Built-in web calls | Hosts the gate refused |"]
    lines.append("|---|---|---|")
    for harness, denied in by_harness.items():
        refused = ", ".join(f"`{h}` ({n})" for h, n in denied.most_common()) or "none"
        lines.append(f"| {harness} | {web[harness]} | {refused} |")
    return lines


def _failures(report: HarnessReport) -> list[str]:
    """The runs without an answer, and why.

    Args:
        report: The run.

    Returns:
        The section's lines (none when every run answered).
    """
    failed = [r for r in report.results if r.failure]
    if not failed:
        return []
    lines = ["", "### Runs without an answer", ""]
    for row in failed[:SHOWN_FAILURES]:
        why = (row.error or "").replace("\n", " ")[:200]
        lines.append(
            f"- {row.harness} / {row.agent_model} / {row.arm} / {row.job}: {row.failure}: {why}"
        )
    if len(failed) > SHOWN_FAILURES:
        lines.append(f"- ... {len(failed) - SHOWN_FAILURES} more in the JSON")
    return lines


def _every_job(report: HarnessReport) -> list[str]:
    """Every job against every cell.

    Args:
        report: The run.

    Returns:
        The table's lines.
    """
    keys = [(c.harness, c.agent_model, c.arm, c.retrieval, c.kind) for c in report.cells]
    found = {
        (r.harness, r.agent_model, r.arm, r.retrieval, r.kind, r.job): r for r in report.results
    }
    jobs = sorted({(r.kind, r.job) for r in report.results})
    lines = [
        "",
        "### Every job",
        "",
        "| Job | " + " | ".join(_label(c) for c in report.cells) + " |",
        "|---|" + "---|" * len(report.cells),
    ]
    for kind, job in jobs:
        marks = []
        for key in keys:
            row = found.get((*key, job)) if key[4] == kind else None
            if row is None:
                marks.append("")
                continue
            mark = "error" if not row.counted else ("pass" if row.passed else row.outcome)
            if row.task and row.task.forbidden:
                mark += f" ({', '.join(row.task.forbidden)})"
            marks.append(f"{mark}, {row.docs_calls} docs" if row.arm != NONE else mark)
        lines.append(f"| {job} | " + " | ".join(marks) + " |")
    return lines
