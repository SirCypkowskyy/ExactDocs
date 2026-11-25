"""Check every task without a model: its reference passes, its other-version solution fails.

For each task, the reference solution and the solution written for the other version are laid over
the workspace template and evaluated like an agent's work (the same dataset, sandbox and
evaluators). A task is sound when:

- the reference passes its hidden tests, with exactly the pinned version installed in the
  sandbox, and uses no forbidden API;
- the other-version solution fails its hidden tests, and uses at least one forbidden API, so the
  report names the API that does not exist in (or was removed from) the pinned version.

CI runs this on every pull request (``just coding-tasks check``).
"""

import asyncio
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.reporting import EvaluationReport

from coding_tasks.environments import PreparedEnvironment, prepare
from coding_tasks.evaluators import HIDDEN_TESTS, TaskInfo, TaskInput, task_dataset
from coding_tasks.grading import Runner, TaskRun, materialize
from coding_tasks.sandbox import Isolation, Limits, Sandbox
from coding_tasks.tasks import CodingTask
from retrieval_eval.golden import Corpus

type Solution = Literal["reference", "other"]
"""Which fixed solution is checked."""
SOLUTIONS: Final[tuple[Solution, ...]] = ("reference", "other")
"""Both, in the order they are checked."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class SolutionCheck(_Model):
    """How one fixed solution fared."""

    passed: bool
    """Its hidden tests passed."""
    reason: str
    """Why (the evaluator's reason)."""
    installed: str | None = None
    """The pinned package's version found in the sandbox."""
    tests: int = 0
    """Hidden tests run."""
    failures: list[str] = Field(default_factory=list)
    """Hidden tests that failed."""
    forbidden: list[str] = Field(default_factory=list)
    """Forbidden APIs it uses."""
    forbidden_reasons: list[str] = Field(default_factory=list)
    """Why each is forbidden."""
    seconds: float = 0.0
    """How long its tests took."""
    output: str = ""
    """The end of the test output, kept when the outcome is not the expected one."""


class TaskCheck(_Model):
    """One task's check."""

    task: str
    """The task."""
    project: str
    """Its project."""
    version: str
    """The pinned version."""
    pair: str | None
    """Its version pair."""
    other_version: str
    """The other-version solution's version."""
    reference: SolutionCheck
    """The reference solution."""
    other: SolutionCheck
    """The other-version solution."""
    other_on_its_version: SolutionCheck | None = None
    """The other-version solution on the environment of its own version (``other_environment``),
    where it must pass; ``None`` when the task names none."""
    problems: list[str] = Field(default_factory=list)
    """What makes the task unsound; empty when it is sound."""

    @property
    def ok(self) -> bool:
        """The task is sound.

        Returns:
            No problem.
        """
        return not self.problems


class CheckReport(_Model):
    """Every task's check."""

    tasks: list[TaskCheck]
    """One per task."""
    isolation: Isolation
    """How the sandbox enforced its limits."""

    @property
    def ok(self) -> bool:
        """Every task is sound.

        Returns:
            True when no task has a problem.
        """
        return all(t.ok for t in self.tasks)


@dataclass(frozen=True, slots=True, kw_only=True)
class Solve:
    """The task function of a check: lay a fixed solution over the template and grade it."""

    tasks: Mapping[str, CodingTask]
    """The tasks, by ID."""
    prepared: Mapping[str, PreparedEnvironment]
    """Each environment, installed, by name."""
    sandbox: Sandbox
    """The sandbox."""
    limits: Limits
    """The limits of each test run."""
    solution: Solution
    """``reference`` or ``other``."""
    work_dir: Path
    """Where the workspaces are built."""
    on_other_environment: bool = False
    """Run on the task's ``other_environment`` instead of its own."""

    async def __call__(self, inputs: TaskInput) -> TaskRun:
        """Grade one task's fixed solution.

        Args:
            inputs: The task.

        Returns:
            Its run: no agent, the grade.
        """
        task = self.tasks[inputs.task]
        environment = task.other_environment if self.on_other_environment else task.environment
        prepared = self.prepared[(environment or task.environment).name]
        files = task.reference if self.solution == "reference" else task.other_directory
        root = Path(tempfile.mkdtemp(prefix=f"{task.id}-{self.solution}-", dir=self.work_dir))
        workspace = materialize(task, root / "workspace", prepared, solution=files)
        runner = Runner(sandbox=self.sandbox, prepared=prepared, limits=self.limits)
        grade = await runner.grade(task, workspace)
        return TaskRun(grade=grade, solution=self.solution)


def _solution_check(case_run: TaskRun | None, reason: str, *, keep_output: bool) -> SolutionCheck:
    """Summarize one fixed solution's evaluation.

    Args:
        case_run: Its run (``None`` when the task function raised).
        reason: The ``tests_pass`` evaluator's reason (or the error).
        keep_output: Keep the end of the test output (the outcome was not the expected one).

    Returns:
        The summary.
    """
    grade = case_run.grade if case_run else None
    if grade is None:
        return SolutionCheck(passed=False, reason=reason)
    return SolutionCheck(
        passed=grade.passed,
        reason=reason,
        installed=grade.tests.installed,
        tests=grade.tests.tests,
        failures=grade.tests.failures,
        forbidden=grade.apis,
        forbidden_reasons=list(dict.fromkeys(h.reason for h in grade.forbidden)),
        seconds=grade.tests.seconds,
        output=grade.tests.output[-4000:] if keep_output else "",
    )


def _by_case(
    report: EvaluationReport[TaskInput, TaskRun, TaskInfo],
) -> dict[str, tuple[TaskRun | None, str]]:
    """Each case's run and the ``tests_pass`` reason.

    Args:
        report: An evaluation of the dataset.

    Returns:
        ``task -> (run, reason)``; a case whose task function raised has no run and the error.
    """
    found: dict[str, tuple[TaskRun | None, str]] = {}
    for case in report.cases:
        assertion = case.assertions.get(HIDDEN_TESTS)
        found[case.name] = (case.output, (assertion.reason or "") if assertion else "")
    for failure in report.failures:
        found[failure.name] = (None, f"the task function raised: {failure.error_message}")
    return found


def problems_of(
    task: CodingTask,
    reference: SolutionCheck,
    other: SolutionCheck,
    other_on_its_version: SolutionCheck | None = None,
) -> list[str]:
    """What makes a task unsound.

    Args:
        task: The task.
        reference: Its reference solution's check.
        other: Its other-version solution's check.
        other_on_its_version: The other-version solution on its own version's environment.

    Returns:
        The problems; empty for a sound task.
    """
    pinned = task.environment.spec.version
    problems = []
    if not reference.passed:
        problems.append(f"the reference fails: {reference.reason}")
    if reference.installed not in {pinned, None} or (
        reference.passed and reference.installed is None
    ):
        problems.append(f"the sandbox had {reference.installed}, not {pinned}")
    if reference.forbidden:
        problems.append(f"the reference uses forbidden APIs: {', '.join(reference.forbidden)}")
    if other.passed:
        problems.append("the other-version solution passes")
    if not other.forbidden:
        problems.append("the other-version solution uses no forbidden API: nothing names it")
    if other_on_its_version is not None and not other_on_its_version.passed:
        problems.append(
            f"the other-version solution fails on {task.spec.other_version} too: "
            f"{other_on_its_version.reason}"
        )
    return problems


async def check_tasks(
    tasks: Sequence[CodingTask],
    corpus: Corpus,
    prepared: Mapping[str, PreparedEnvironment],
    sandbox: Sandbox,
    *,
    work_dir: Path,
    limits: Limits | None = None,
    concurrency: int = 4,
) -> CheckReport:
    """Check that every task's reference passes and its other-version solution fails.

    Args:
        tasks: The tasks.
        corpus: The golden corpus.
        prepared: Each task's environment, installed, by name.
        sandbox: The sandbox.
        work_dir: Where the workspaces are built.
        limits: The limits of each test run.
        concurrency: Tasks graded at once.

    Returns:
        The report.
    """
    by_id = {t.id: t for t in tasks}
    passes: list[tuple[Solution, list[CodingTask], bool]] = [
        *((solution, list(tasks), False) for solution in SOLUTIONS),
        ("other", [t for t in tasks if t.other_environment is not None], True),
    ]
    runs: list[dict[str, tuple[TaskRun | None, str]]] = []
    for solution, picked, crossing in passes:
        solve = Solve(
            tasks=by_id,
            prepared=prepared,
            sandbox=sandbox,
            limits=limits or Limits(),
            solution=solution,
            work_dir=work_dir,
            on_other_environment=crossing,
        )
        report = (
            await task_dataset(picked, corpus).evaluate(
                solve, name=f"check {solution}", max_concurrency=concurrency, progress=False
            )
            if picked
            else None
        )
        runs.append(_by_case(report) if report is not None else {})
    checks = [
        _task_check(task, *(run.get(task.id, (None, "not run")) for run in runs)) for task in tasks
    ]
    return CheckReport(tasks=checks, isolation=sandbox.isolation)


def _task_check(
    task: CodingTask,
    reference_run: tuple[TaskRun | None, str],
    other_run: tuple[TaskRun | None, str],
    crossed_run: tuple[TaskRun | None, str],
) -> TaskCheck:
    """Put one task's three runs together.

    Args:
        task: The task.
        reference_run: The reference's run and reason.
        other_run: The other-version solution's run and reason.
        crossed_run: The other-version solution's run on its own version (``other_environment``).

    Returns:
        The task's check, with its problems.
    """
    reference = _solution_check(*reference_run, keep_output=not _passed(reference_run[0]))
    other = _solution_check(*other_run, keep_output=True)
    crossed = (
        _solution_check(*crossed_run, keep_output=not _passed(crossed_run[0]))
        if task.other_environment is not None
        else None
    )
    return TaskCheck(
        task=task.id,
        project=task.spec.project,
        version=task.spec.version,
        pair=task.spec.pair,
        other_version=task.spec.other_version,
        reference=reference,
        other=other,
        other_on_its_version=crossed,
        problems=problems_of(task, reference, other, crossed),
    )


def _passed(run: TaskRun | None) -> bool:
    """Tell whether a fixed solution's hidden tests passed.

    Args:
        run: Its run, if it ran.

    Returns:
        True when graded and passed.
    """
    return bool(run and run.grade and run.grade.passed)


def markdown(report: CheckReport) -> str:
    """Show a check as a Markdown table.

    Args:
        report: The check.

    Returns:
        A heading, the sandbox's isolation, one row per task and the problems.
    """
    sound = sum(t.ok for t in report.tasks)
    lines = [
        "## Coding tasks: reference and other-version solutions",
        "",
        (
            f"{sound} of {len(report.tasks)} tasks sound: the reference passes on the pinned "
            "version, the other-version solution fails and names a forbidden API."
        ),
        "",
        (
            f"Sandbox: {report.isolation.sandbox}; network {report.isolation.network}; "
            f"CPU {report.isolation.cpu}; memory {report.isolation.memory}; "
            f"time {report.isolation.time}."
        ),
        "",
        "| Task | Pinned | Installed | Reference | Other version | Other fails, naming |",
        "|---|---|---|---|---|---|",
    ]
    for t in report.tasks:
        ref = f"pass ({t.reference.tests})" if t.reference.passed else "**FAIL**"
        other = "**passes**" if t.other.passed else "fails"
        if t.other_on_its_version is not None:
            own = "passes" if t.other_on_its_version.passed else "**fails**"
            other += f" (on {t.other_version}: {own})"
        lines.append(
            f"| {t.task} | {t.project} {t.version} | {t.reference.installed or 'n/a'} | {ref} | "
            f"{t.other_version}: {other} | {', '.join(t.other.forbidden) or '**none**'} |"
        )
    bad = [t for t in report.tasks if not t.ok]
    if bad:
        lines += ["", "### Problems", ""]
        lines += [f"- {t.task}: {'; '.join(t.problems)}" for t in bad]
    return "\n".join(lines) + "\n"


async def prepare_all(
    tasks: Sequence[CodingTask], cache_dir: Path, *, concurrency: int = 4
) -> dict[str, PreparedEnvironment]:
    """Install every environment the tasks need.

    Args:
        tasks: The tasks.
        cache_dir: Where installs are kept.
        concurrency: Installs at once.

    Returns:
        Each environment, installed, by name.
    """
    environments = {t.environment.name: t.environment for t in tasks}
    environments |= {
        t.other_environment.name: t.other_environment for t in tasks if t.other_environment
    }
    gate = asyncio.Semaphore(concurrency)

    async def one(name: str) -> tuple[str, PreparedEnvironment]:
        """Install one environment.

        Args:
            name: Its name.

        Returns:
            ``(name, prepared)``.
        """
        async with gate:
            return name, await prepare(environments[name], cache_dir)

    return dict(await asyncio.gather(*(one(n) for n in sorted(environments))))
