"""The coding tasks' report: per task, project and arm, with intervals and paired tests (#489).

One row per task asked of one agent model with one arm (and retrieval configuration). A cell (a
model and an arm) gives, over its graded tasks (a provider failure is not graded, counted in
*Errors*):

- the **pass rate** (hidden tests passed against the pinned version), overall, per project and
  over the tasks whose pinned version came after the training cutoff, each with its 95% interval;
- the **forbidden-API rate** (share of tasks whose changed code uses an API the pinned version
  does not have) and the APIs used, with counts;
- the **files changed** per task (mean with its interval);
- the cost per task: wall time, input and output tokens, tool calls (mean, interval, p50, p95);
- against ``none``, on the tasks both graded: the pass rate by McNemar's test (mid-p).

The Markdown also has a table of every task against every cell.
"""

from collections.abc import Callable, Iterable, Sequence
from datetime import date
from statistics import fmean
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import EvaluationReport

from agent_bench.arms import NONE
from agent_bench.harness import AgentRun, ToolCall
from agent_bench.redact import scrub
from agent_bench.report import Spread, spread
from coding_tasks.evaluators import TaskInfo, TaskInput
from coding_tasks.grading import TaskRun
from coding_tasks.sandbox import Isolation
from coding_tasks.tasks import CodingTask
from coding_tasks.workspace import RUN_TESTS, WORKSPACE_TOOLS
from retrieval_eval.stats import DEFAULT, Interval, PairedTest, StatsMethod, interval, paired_binary

ERROR: Final[str] = "error"
"""The outcome of a run the provider failed: not graded."""

type CellKey = tuple[str, str, str]
"""``(agent model, arm, retrieval)``."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class TaskResult(_Model):
    """One task asked of one agent model with one arm."""

    agent_model: str
    """The agent's model."""
    arm: str
    """The documentation arm."""
    retrieval: str = ""
    """The retrieval configuration (for ``exactdocs``)."""
    task: str
    """The task."""
    project: str
    """Its project."""
    version: str
    """The version it pins."""
    pair: str | None = None
    """Its version pair."""
    post_cutoff: bool = False
    """The pinned version was released after the training cutoff."""
    outcome: str
    """``passed``, ``failed`` or ``error`` (the provider failed: not graded)."""
    installed: str | None = None
    """The pinned package's version found in the sandbox."""
    tests: int = 0
    """Hidden tests run."""
    failures: list[str] = Field(default_factory=list)
    """Hidden tests that failed."""
    typecheck: bool | None = None
    """The TypeScript type check passed (``None`` for Python)."""
    forbidden: list[str] = Field(default_factory=list)
    """Forbidden APIs the changed code uses."""
    forbidden_reasons: list[str] = Field(default_factory=list)
    """Why each is forbidden."""
    files_changed: int = 0
    """Files added, changed or deleted."""
    changed: list[str] = Field(default_factory=list)
    """Those files."""
    unexpected: list[str] = Field(default_factory=list)
    """Changed files the task did not name."""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    """Every tool call, documentation and workspace."""
    read: list[str] = Field(default_factory=list)
    """The documentation sections read in full, as ``<chunk or article>@<version>``."""
    input_tokens: int = 0
    """Input tokens over the run."""
    output_tokens: int = 0
    """Output tokens over the run, thinking included."""
    thinking_tokens: int | None = None
    """Thinking tokens, reported or estimated; ``None`` when not returned."""
    usd: float | None = None
    """What it cost; ``None`` when the model is unpriced."""
    seconds: float = 0.0
    """Wall time of the agent's run (grading not included)."""
    provider_retries: int = 0
    """Requests retried after a provider failure."""
    retry_seconds: float = 0.0
    """Of the wall time, the time lost to those retries."""
    answer: str = ""
    """The agent's final summary."""
    error: str | None = None
    """Why the run ended without an answer."""

    @property
    def graded(self) -> bool:
        """The run was graded (it did not fail on the provider's side).

        Returns:
            True unless the outcome is ``error``.
        """
        return self.outcome != ERROR

    @property
    def passed(self) -> bool:
        """The hidden tests passed.

        Returns:
            True for ``passed``.
        """
        return self.outcome == "passed"

    @property
    def docs_calls(self) -> int:
        """Calls to the documentation tools.

        Returns:
            Tool calls that are not workspace tools.
        """
        return sum(c.name not in WORKSPACE_TOOLS for c in self.tool_calls)

    @property
    def test_runs(self) -> int:
        """Times the agent ran the workspace's tests.

        Returns:
            ``run_tests`` calls.
        """
        return sum(c.name == RUN_TESTS for c in self.tool_calls)


class Rate(_Model):
    """A share of tasks, with its interval."""

    count: int
    """Tasks counted."""
    rate: float | None
    """The share; ``None`` for no task."""
    interval: Interval | None = None
    """Its 95% bootstrap interval."""


class CellSummary(_Model):
    """One agent model with one arm (and retrieval configuration) over the tasks."""

    agent_model: str
    """The agent's model."""
    arm: str
    """The arm."""
    retrieval: str = ""
    """The retrieval configuration."""
    tasks: int
    """Tasks asked."""
    errors: int
    """Runs the provider failed (not graded, left out of every rate)."""
    passed: Rate
    """Tasks whose hidden tests passed."""
    by_project: dict[str, Rate] = Field(default_factory=dict)
    """The pass rate per project."""
    post_cutoff: Rate
    """The pass rate over the tasks pinning a version released after the cutoff."""
    forbidden: Rate
    """Tasks whose changed code uses a forbidden API."""
    forbidden_apis: dict[str, int] = Field(default_factory=dict)
    """Each forbidden API used, and in how many tasks."""
    files_changed: Spread | None = None
    """Files changed per task."""
    seconds: Spread | None = None
    """Wall time per task."""
    input_tokens: Spread | None = None
    """Input tokens per task."""
    output_tokens: Spread | None = None
    """Output tokens per task, thinking included."""
    tool_calls: Spread | None = None
    """Tool calls per task."""
    docs_calls: Spread | None = None
    """Documentation tool calls per task."""
    usd: float | None = None
    """What the runs cost; ``None`` when any is unpriced."""
    versus_none: PairedTest | None = None
    """The pass rate against the ``none`` arm's, same model, on the tasks both graded."""


class RunMeta(_Model):
    """What a rerun needs."""

    started_at: str
    """When the run started (UTC)."""
    exactdocs_version: str
    """The ExactDocs version."""
    git_commit: str | None
    """The repository's commit."""
    agent_models: list[str]
    """The agent models."""
    arms: list[str]
    """The arms."""
    retrieval: dict[str, dict[str, str]] = Field(default_factory=dict)
    """Each retrieval configuration's settings (secrets redacted)."""
    tasks: int
    """Tasks asked."""
    selection: str
    """How they were picked."""
    cutoff: date
    """The training cutoff ``post_cutoff`` is counted against."""
    max_requests: int
    """Model requests one task may take."""
    concurrency: int
    """Tasks asked at once."""
    thinking: str
    """The agents' thinking setting."""
    max_retries: int
    """Retries of a failed provider request."""
    providers: dict[str, str] = Field(default_factory=dict)
    """Where the models are served (base URLs only)."""
    instructions: dict[str, str] = Field(default_factory=dict)
    """Each arm's instructions."""
    prompt: str
    """The prompt template."""
    isolation: Isolation
    """How the sandbox enforced its limits."""


class CodingReport(_Model):
    """A run of the coding tasks."""

    meta: RunMeta
    """What a rerun needs."""
    cells: list[CellSummary]
    """One per agent model, arm and retrieval configuration."""
    results: list[TaskResult]
    """Every task asked."""
    statistics: StatsMethod = DEFAULT
    """How the intervals and tests were computed."""


def results_of(
    report: EvaluationReport[TaskInput, TaskRun, TaskInfo],
    tasks: dict[str, CodingTask],
    *,
    agent_model: str,
    arm: str,
    retrieval: str,
    cutoff: date,
) -> list[TaskResult]:
    """Flatten an evaluation into task results.

    Args:
        report: The evaluated tasks of one model, arm and configuration.
        tasks: Every task, by ID.
        agent_model: The model.
        arm: The arm.
        retrieval: The configuration's name (empty for none).
        cutoff: The training cutoff.

    Returns:
        One result per task; a task whose run raised is an ``error``.
    """
    rows = []
    for case in report.cases:
        task, run = tasks[case.name], case.output
        agent, grade = run.agent, run.grade
        base = _base(task, agent_model, arm, retrieval, cutoff)
        if grade is None:
            rows.append(TaskResult(**base, outcome=ERROR, error=agent.error if agent else None))
            continue
        rows.append(
            TaskResult(
                **base,
                outcome="passed" if grade.passed else "failed",
                installed=grade.tests.installed,
                tests=grade.tests.tests,
                failures=grade.tests.failures,
                typecheck=grade.tests.typecheck,
                forbidden=grade.apis,
                forbidden_reasons=list(dict.fromkeys(h.reason for h in grade.forbidden)),
                files_changed=grade.changes.count,
                changed=[*grade.changes.added, *grade.changes.modified, *grade.changes.deleted],
                unexpected=grade.unexpected,
                **(_spent(agent) if agent else {}),
            )
        )
    for failure in report.failures:
        task = tasks[failure.name]
        rows.append(
            TaskResult(
                **_base(task, agent_model, arm, retrieval, cutoff),
                outcome=ERROR,
                error=scrub(f"the task raised: {failure.error_message}"),
            )
        )
    return rows


def _base(task: CodingTask, agent_model: str, arm: str, retrieval: str, cutoff: date) -> dict:
    """The fields of a result that come from the task and the cell.

    Args:
        task: The task.
        agent_model: The model.
        arm: The arm.
        retrieval: The configuration.
        cutoff: The training cutoff.

    Returns:
        The fields.
    """
    return {
        "agent_model": agent_model,
        "arm": arm,
        "retrieval": retrieval,
        "task": task.id,
        "project": task.spec.project,
        "version": task.spec.version,
        "pair": task.spec.pair,
        "post_cutoff": task.post_cutoff(cutoff),
    }


def _spent(agent: AgentRun) -> dict:
    """The fields of a result that come from the agent's run.

    Args:
        agent: The run.

    Returns:
        The fields.
    """
    return {
        "tool_calls": agent.tool_calls,
        "read": [
            f"{s.article if s.whole_article else s.chunk_id}@{s.version}"
            for s in agent.read
        ],
        "input_tokens": agent.input_tokens,
        "output_tokens": agent.output_tokens,
        "thinking_tokens": agent.thinking_tokens,
        "usd": agent.usd,
        "seconds": agent.seconds,
        "provider_retries": agent.provider_retries,
        "retry_seconds": agent.retry_seconds,
        "answer": agent.answer,
        "error": agent.error,
    }


def _rate(values: Sequence[bool], method: StatsMethod) -> Rate:
    """A share with its interval.

    Args:
        values: One outcome per task.
        method: The bootstrap's settings.

    Returns:
        The rate.
    """
    if not values:
        return Rate(count=0, rate=None)
    floats = [1.0 if v else 0.0 for v in values]
    return Rate(count=len(values), rate=round(fmean(floats), 4), interval=interval(floats, method))


def _ordered(rows: Iterable[TaskResult]) -> list[TaskResult]:
    """Put results in task order, so cells are resampled with the same draws.

    Args:
        rows: Results.

    Returns:
        Them, by task.
    """
    return sorted(rows, key=lambda r: r.task)


def summarize(
    key: CellKey, rows: Sequence[TaskResult], method: StatsMethod = DEFAULT
) -> CellSummary:
    """Aggregate one cell.

    Args:
        key: The model, arm and configuration.
        rows: The cell's results.
        method: The bootstrap's settings.

    Returns:
        The cell's summary (without the paired test).
    """
    graded = _ordered(r for r in rows if r.graded)
    apis: dict[str, int] = {}
    for row in graded:
        for api in row.forbidden:
            apis[api] = apis.get(api, 0) + 1

    def costs(of: Callable[[TaskResult], float]) -> Spread | None:
        """Spread one cost over the graded tasks.

        Args:
            of: Reads the cost.

        Returns:
            Its spread.
        """
        return spread([float(of(r)) for r in graded])

    prices = [r.usd for r in graded]
    return CellSummary(
        agent_model=key[0],
        arm=key[1],
        retrieval=key[2],
        tasks=len(rows),
        errors=len(rows) - len(graded),
        passed=_rate([r.passed for r in graded], method),
        by_project={
            project: _rate([r.passed for r in graded if r.project == project], method)
            for project in sorted({r.project for r in graded})
        },
        post_cutoff=_rate([r.passed for r in graded if r.post_cutoff], method),
        forbidden=_rate([bool(r.forbidden) for r in graded], method),
        forbidden_apis=dict(sorted(apis.items(), key=lambda kv: (-kv[1], kv[0]))),
        files_changed=costs(lambda r: r.files_changed),
        seconds=costs(lambda r: r.seconds),
        input_tokens=costs(lambda r: r.input_tokens),
        output_tokens=costs(lambda r: r.output_tokens),
        tool_calls=costs(lambda r: len(r.tool_calls)),
        docs_calls=costs(lambda r: r.docs_calls),
        usd=None if any(p is None for p in prices) else round(sum(p or 0.0 for p in prices), 6),
    )


def cells_of(
    rows: Sequence[TaskResult], keys: Sequence[CellKey], method: StatsMethod = DEFAULT
) -> list[CellSummary]:
    """Summarize every cell and compare each with ``none``, same model, same tasks.

    Args:
        rows: Every result.
        keys: The cells, in report order.
        method: The bootstrap's and the tests' settings.

    Returns:
        One summary per cell.
    """
    by_cell: dict[CellKey, dict[str, TaskResult]] = {}
    for row in rows:
        by_cell.setdefault((row.agent_model, row.arm, row.retrieval), {})[row.task] = row
    cells = []
    for key in keys:
        mine = by_cell.get(key, {})
        cell = summarize(key, list(mine.values()), method)
        baseline = by_cell.get((key[0], NONE, ""))
        if key[1] != NONE and baseline is not None:
            shared = sorted(t for t in mine if t in baseline and mine[t].graded and baseline[t].graded)
            test = paired_binary(
                [baseline[t].passed for t in shared], [mine[t].passed for t in shared], method
            )
            cell = cell.model_copy(update={"versus_none": test})
        cells.append(cell)
    return cells


# ------------------------------------------------------------------------------------ Markdown


def _pct(rate: Rate) -> str:
    """Show a rate as a percentage with its interval and count.

    Args:
        rate: The rate.

    Returns:
        E.g. ``62.5 % [41.7, 83.3] (n=24)``, or ``n/a``.
    """
    if rate.rate is None:
        return "n/a"
    ci = "" if rate.interval is None else f" [{rate.interval.low * 100:.1f}, {rate.interval.high * 100:.1f}]"
    return f"{rate.rate * 100:.1f} %{ci} (n={rate.count})"


def _mean(value: Spread | None, digits: int = 1) -> str:
    """Show a cost: mean [interval]; p50, p95.

    Args:
        value: The spread.
        digits: Decimals.

    Returns:
        The text, or ``n/a``.
    """
    if value is None:
        return "n/a"
    ci = "" if value.interval is None else f" [{value.interval.low:,.{digits}f}, {value.interval.high:,.{digits}f}]"
    return f"{value.mean:,.{digits}f}{ci}; p50 {value.p50:,.{digits}f}; p95 {value.p95:,.{digits}f}"


def _label(cell: CellSummary) -> str:
    """Name a cell.

    Args:
        cell: The cell.

    Returns:
        ``model / arm`` (``/ retrieval`` for a configuration).
    """
    parts = [cell.agent_model, cell.arm, *([cell.retrieval] if cell.retrieval else [])]
    return " / ".join(parts)


def markdown(report: CodingReport) -> str:
    """Show the report as Markdown.

    Args:
        report: The run.

    Returns:
        The quality and cost tables, the paired tests, the forbidden APIs used and every task
        against every cell.
    """
    meta = report.meta
    lines = [
        "## Coding tasks",
        "",
        f"{meta.tasks} tasks ({meta.selection}); arms {', '.join(meta.arms)}; agent models "
        f"{', '.join(meta.agent_models)}; up to {meta.max_requests} requests a task; thinking "
        f"{meta.thinking}; cutoff {meta.cutoff}. Sandbox: {meta.isolation.sandbox}, network "
        f"{meta.isolation.network}.",
        "",
        "| Model / arm | Passed | After the cutoff | Forbidden API used | Files changed | Errors |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {_label(c)} | {_pct(c.passed)} | {_pct(c.post_cutoff)} | {_pct(c.forbidden)} | "
        f"{_mean(c.files_changed)} | {c.errors} |"
        for c in report.cells
    ]
    projects = sorted({p for c in report.cells for p in c.by_project})
    lines += ["", "### Passed, per project", "", "| Model / arm | " + " | ".join(projects) + " |"]
    lines.append("|---|" + "---|" * len(projects))
    lines += [
        f"| {_label(c)} | "
        + " | ".join(_pct(c.by_project.get(p, Rate(count=0, rate=None))) for p in projects)
        + " |"
        for c in report.cells
    ]
    lines += [
        "",
        "### Cost per task",
        "",
        "| Model / arm | Wall time (s) | Input tokens | Output tokens | Tool calls | Docs calls | USD |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {_label(c)} | {_mean(c.seconds)} | {_mean(c.input_tokens, 0)} | "
        f"{_mean(c.output_tokens, 0)} | {_mean(c.tool_calls)} | {_mean(c.docs_calls)} | "
        f"{'unpriced' if c.usd is None else f'{c.usd:.4f}'} |"
        for c in report.cells
    ]
    compared = [c for c in report.cells if c.versus_none is not None]
    if compared:
        lines += [
            "",
            "### Against `none`, on the same tasks (McNemar, mid-p)",
            "",
            "| Model / arm | Tasks | Difference [95% CI] | Gained / lost | p | Significant |",
            "|---|---|---|---|---|---|",
        ]
        for c in compared:
            t = c.versus_none
            assert t is not None  # noqa: S101 -- filtered above
            lines.append(
                f"| {_label(c)} | {t.cases} | {t.difference * 100:+.1f} pts "
                f"[{t.interval.low * 100:+.1f}, {t.interval.high * 100:+.1f}] | "
                f"{t.gained} / {t.lost} | {t.p_value} | {'yes' if t.significant else 'no'} |"
            )
    used = [c for c in report.cells if c.forbidden_apis]
    if used:
        lines += ["", "### Forbidden APIs used", ""]
        lines += [
            f"- {_label(c)}: " + ", ".join(f"{api} ({n})" for api, n in c.forbidden_apis.items())
            for c in used
        ]
    keys = [(c.agent_model, c.arm, c.retrieval) for c in report.cells]
    outcome = {(r.agent_model, r.arm, r.retrieval, r.task): r for r in report.results}
    tasks = sorted({r.task for r in report.results})
    lines += [
        "",
        "### Every task",
        "",
        "| Task | " + " | ".join(_label(c) for c in report.cells) + " |",
        "|---|" + "---|" * len(report.cells),
    ]
    for task in tasks:
        cells = []
        for key in keys:
            row = outcome.get((*key, task))
            mark = "" if row is None else {"passed": "pass", "failed": "fail"}.get(row.outcome, "error")
            if row is not None and row.forbidden:
                mark += f" ({', '.join(row.forbidden)})"
            cells.append(mark)
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
