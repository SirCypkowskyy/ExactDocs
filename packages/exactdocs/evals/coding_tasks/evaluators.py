"""The coding tasks as a Pydantic Evals dataset, and its three evaluators.

Each task is a case: its inputs are what the agent is told (the project, its version and the
prompt), its metadata what the report groups by (project, environment, pair, release dates). The
task function returns a ``TaskRun`` (``grading``); the evaluators read its grade:

- ``TestsPass``: the hidden tests passed in the sandbox (an assertion);
- ``ForbiddenApi``: no forbidden API in the changed code (an assertion, its reason naming each API
  used and why it does not exist in the pinned version) and how many were used (a score);
- ``FilesChanged``: how many files were added, changed or deleted (a score).

A run that failed on the provider's side has no grade: every evaluator says so and the report
leaves the run out.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from coding_tasks.grading import TaskRun
from coding_tasks.tasks import ApiSince, CodingTask
from retrieval_eval.golden import Corpus

TESTS_PASS: Final[str] = "tests_pass"
"""The assertion that the hidden tests passed."""
NO_FORBIDDEN_API: Final[str] = "no_forbidden_api"
"""The assertion that no forbidden API was used."""
FORBIDDEN_APIS: Final[str] = "forbidden_apis"
"""The score: forbidden APIs used."""
FILES_CHANGED: Final[str] = "files_changed"
"""The score: files added, changed or deleted."""
NOT_GRADED: Final[str] = "not graded: the run failed on the provider's side"
"""The reason every evaluator gives for a run without a grade."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class TaskInput(_Model):
    """What the agent is told about a task."""

    task: str
    """The task's ID (not shown to the agent)."""
    project: str
    """The golden project."""
    title: str
    """The project's display name, as the agent is told it."""
    version: str
    """The version the project pins, as the agent is told it."""
    prompt: str
    """The request."""


class TaskInfo(_Model):
    """What the report groups a task by; nothing of its solution."""

    project: str
    """The golden project."""
    library: str
    """Its ExactDocs library ID."""
    environment: str
    """The environment."""
    package: str
    """The pinned package."""
    pinned: str
    """Its exact version."""
    released: date
    """When that version was released."""
    pair: str | None = None
    """The version pair, if any."""
    other_version: str
    """The version the other-version solution is written for."""
    api_since: ApiSince | None = None
    """The release behind the trap."""
    files: list[str] = Field(default_factory=list)
    """The files the task expects to change."""


type TaskDataset = Dataset[TaskInput, TaskRun, TaskInfo]
"""The coding tasks' dataset."""


def task_dataset(tasks: list[CodingTask], corpus: Corpus) -> TaskDataset:
    """Turn tasks into the dataset, with the three evaluators.

    Args:
        tasks: The tasks.
        corpus: The golden corpus, for each project's title and library ID.

    Returns:
        One case per task.

    Raises:
        ValueError: A task's project is not in the corpus.
    """
    cases = []
    for task in tasks:
        project = corpus.project(task.spec.project)
        if project is None:
            message = f"task {task.id}: project {task.spec.project} is not in the golden corpus"
            raise ValueError(message)
        spec = task.environment.spec
        cases.append(
            Case(
                name=task.id,
                inputs=TaskInput(
                    task=task.id,
                    project=project.id,
                    title=project.title,
                    version=task.spec.version,
                    prompt=task.spec.prompt.strip(),
                ),
                metadata=TaskInfo(
                    project=project.id,
                    library=project.library,
                    environment=task.environment.name,
                    package=spec.package,
                    pinned=spec.version,
                    released=spec.released,
                    pair=task.spec.pair,
                    other_version=task.spec.other_version,
                    api_since=task.spec.api_since,
                    files=task.spec.files,
                ),
            )
        )
    return Dataset[TaskInput, TaskRun, TaskInfo](
        name="coding-tasks",
        cases=cases,
        evaluators=[TestsPass(), ForbiddenApi(), FilesChanged()],
    )


@dataclass(repr=False)
class TestsPass(Evaluator[TaskInput, TaskRun, TaskInfo]):
    """Asserts that the hidden tests passed against the pinned version."""

    def evaluate(
        self, ctx: EvaluatorContext[TaskInput, TaskRun, TaskInfo]
    ) -> dict[str, EvaluationReason]:
        """Read the hidden tests' outcome.

        Args:
            ctx: The task and its run.

        Returns:
            ``tests_pass``, with the failing tests (or the type check) as its reason.
        """
        grade = ctx.output.grade
        if grade is None:
            return {TESTS_PASS: EvaluationReason(value=False, reason=NOT_GRADED)}
        tests = grade.tests
        if tests.passed:
            reason = f"{tests.tests} tests passed on {ctx.metadata and ctx.metadata.package} {tests.installed}"
        elif tests.timed_out:
            reason = "killed at the wall limit"
        elif tests.typecheck is False:
            reason = "the type check failed"
        elif tests.failures:
            reason = f"{tests.failed} of {tests.tests} failed: {', '.join(tests.failures[:5])}"
        else:
            reason = f"the test run ended with status {tests.exit_code} before any test passed"
        return {TESTS_PASS: EvaluationReason(value=tests.passed, reason=reason)}


@dataclass(repr=False)
class ForbiddenApi(Evaluator[TaskInput, TaskRun, TaskInfo]):
    """Asserts that no API absent from (or removed in) the pinned version was used, and counts them."""

    def evaluate(
        self, ctx: EvaluatorContext[TaskInput, TaskRun, TaskInfo]
    ) -> dict[str, EvaluationReason]:
        """Read the forbidden APIs the grade found.

        Args:
            ctx: The task and its run.

        Returns:
            ``no_forbidden_api`` (its reason names each API and why) and ``forbidden_apis``.
        """
        grade = ctx.output.grade
        if grade is None:
            return {
                NO_FORBIDDEN_API: EvaluationReason(value=False, reason=NOT_GRADED),
                FORBIDDEN_APIS: EvaluationReason(value=0, reason=NOT_GRADED),
            }
        first = {}
        for hit in grade.forbidden:
            first.setdefault(hit.api, hit)
        reason = "; ".join(
            f"{api} ({hit.file}:{hit.line}): {hit.reason}" for api, hit in first.items()
        )
        return {
            NO_FORBIDDEN_API: EvaluationReason(value=not first, reason=reason or "none used"),
            FORBIDDEN_APIS: EvaluationReason(value=len(first), reason=reason or "none used"),
        }


@dataclass(repr=False)
class FilesChanged(Evaluator[TaskInput, TaskRun, TaskInfo]):
    """Counts the files the run added, changed or deleted."""

    def evaluate(
        self, ctx: EvaluatorContext[TaskInput, TaskRun, TaskInfo]
    ) -> dict[str, EvaluationReason]:
        """Read the changes the grade found.

        Args:
            ctx: The task and its run.

        Returns:
            ``files_changed``, listing them (and those the task did not name).
        """
        grade = ctx.output.grade
        if grade is None:
            return {FILES_CHANGED: EvaluationReason(value=0, reason=NOT_GRADED)}
        changes = grade.changes
        parts = [
            f"{label} {', '.join(names)}"
            for label, names in (
                ("added", changes.added),
                ("modified", changes.modified),
                ("deleted", changes.deleted),
            )
            if names
        ]
        if grade.unexpected:
            parts.append(f"not named by the task: {', '.join(grade.unexpected)}")
        return {
            FILES_CHANGED: EvaluationReason(value=changes.count, reason="; ".join(parts) or "none")
        }
