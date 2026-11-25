"""What a harness is asked and how its run is graded: a coding task (#496) or a question (#495).

- A **coding task** (``TaskJob``) gives the CLI the task's workspace, with the prepared environment
  mounted read-only so its own tests run (``sh .home/run-tests.sh``, the coding tasks' visible
  test script), and the prompt the pydantic-ai agent gets: the sentence about the arm's
  documentation tool, ``My project uses <title> at version <version>.`` and the request. The
  workspace is then graded as the coding tasks grade it (``grading.Runner.grade``: the hidden
  tests in the coding tasks' sandbox, the forbidden APIs, the files changed) and reported by the
  coding tasks' own evaluators.
- A **golden question** (``QuestionJob``) gives the CLI an empty workspace and the agent benchmark's
  instructions and prompt; its final message is judged by the agent benchmark's blind judge.

Either way the CLI's run is first turned into the agent benchmark's ``AgentRun`` (``agent_run``), so
the coding tasks' and the agent benchmark's evaluators and rows are used as they are.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic_evals import Case, Dataset

from agent_bench.arms import Arm
from agent_bench.harness import PROMPT, AgentRun, BenchInfo, Failure, ToolCall
from agent_bench.judge import AnswerJudge
from agent_bench.redact import scrub
from agent_bench.report import QuestionResult, accurate, counted
from agent_bench.report import results_of as question_results
from coding_tasks.agent import DOCS_SOURCE, NO_DOCS_SOURCE
from coding_tasks.environments import PreparedEnvironment
from coding_tasks.evaluators import (
    FilesChanged,
    ForbiddenApi,
    TaskInfo,
    TaskInput,
    TestsPass,
)
from coding_tasks.grading import HOME_DIR, Runner, TaskRun, materialize, test_script
from coding_tasks.report import TaskResult
from coding_tasks.report import results_of as task_results
from coding_tasks.sandbox import Limits, Sandbox
from coding_tasks.tasks import CodingTask
from harness_bench.transcript import Transcript
from retrieval_eval.dataset import Question

type JobKind = Literal["task", "question"]
"""A coding task or a golden question."""

TASK_PROMPT: Final[str] = """\
{source}

{request}

The project's dependencies are pinned in its lockfile and already installed: nothing can be \
installed and the lockfile cannot be changed. Write code for exactly the version of the library \
the project uses. Run the project's tests with `sh {tests}` before you finish, and end with a \
short summary of what you changed."""
"""A coding task's prompt for a CLI: the arm's sentence, the project and the request, as the
pydantic-ai agent gets them (``coding_tasks.agent``), and how to run the project's tests."""
TEST_SCRIPT: Final[str] = f"{HOME_DIR}/run-tests.sh"
"""The workspace's own tests, as the agent runs them (outside what is graded)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Place:
    """Where a job's run happens and what its container sees besides the CLI."""

    workspace: Path
    """The workspace."""
    readable: Sequence[tuple[Path, Path]] = ()
    """``(source, target)`` directories mounted read-only (the prepared environment)."""
    path: Sequence[Path] = ()
    """Directories put first on ``PATH`` (the environment's interpreter)."""
    env: Mapping[str, str] = field(default_factory=dict)
    """Variables the run needs (a stand-in environment's ``PYTHONPATH``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Graded:
    """How a job's run was graded."""

    outcome: str
    """``passed``, ``failed`` or ``error`` for a task; the judge's grade for a question."""
    passed: bool
    """The task passed, or the answer counts as accurate."""
    counted: bool
    """It counts in the rates (not a provider's failure)."""
    task: TaskResult | None = None
    """The coding tasks' row."""
    question: QuestionResult | None = None
    """The agent benchmark's row."""


class Job(Protocol):
    """One thing a harness is asked."""

    @property
    def name(self) -> str:
        """The task's ID or the case's name."""
        ...

    @property
    def kind(self) -> JobKind:
        """A coding task or a golden question."""
        ...

    @property
    def project(self) -> str:
        """The golden project."""
        ...

    def prompt(self, arm: Arm) -> str:
        """What the CLI is asked with this arm.

        Args:
            arm: The arm.

        Returns:
            The prompt.
        """
        ...

    def place(self, root: Path) -> Place:
        """Build the job's workspace in a run's folder.

        Args:
            root: The run's folder.

        Returns:
            The workspace and what the container needs.
        """
        ...

    async def grade(
        self, place: Place, run: AgentRun, *, model: str, arm: str, retrieval: str
    ) -> Graded:
        """Grade a run.

        Args:
            place: The job's workspace.
            run: The CLI's run as an ``AgentRun``.
            model: The agent model.
            arm: The arm.
            retrieval: The arm's configuration.

        Returns:
            The grade.
        """
        ...


def agent_run(
    transcript: Transcript, *, seconds: float, failure: Failure | None, error: str | None
) -> AgentRun:
    """Turn a CLI's run into the agent benchmark's record.

    Args:
        transcript: The parsed transcript.
        seconds: The run's wall time.
        failure: Whose side the run failed on, if it did.
        error: Why.

    Returns:
        The record; tokens the CLI did not report are 0 there (the harness report keeps them as
        not reported).
    """
    return AgentRun(
        answer=transcript.answer,
        tool_calls=[
            ToolCall(name=c.name, args=c.args, seconds=0.0, error=c.error) for c in transcript.calls
        ],
        input_tokens=transcript.input_tokens or 0,
        output_tokens=transcript.output_tokens or 0,
        thinking_tokens=transcript.thinking_tokens,
        thinking_chars=transcript.thinking_chars,
        requests=transcript.turns or 0,
        usd=transcript.usd,
        seconds=seconds,
        error=scrub(error) if error else None,
        failure=failure,
    )


def task_prompt(arm: Arm, inputs: TaskInput) -> str:
    """A coding task's prompt for a CLI.

    Args:
        arm: The arm.
        inputs: The task.

    Returns:
        ``TASK_PROMPT`` filled in.
    """
    source = NO_DOCS_SOURCE if arm.tool is None else DOCS_SOURCE.format(tool=arm.tool)
    request = PROMPT.format(title=inputs.title, version=inputs.version, query=inputs.prompt)
    return TASK_PROMPT.format(source=source, request=request, tests=TEST_SCRIPT)


def question_prompt(arm: Arm, question: Question, title: str) -> str:
    """A golden question's prompt for a CLI: the agent benchmark's instructions, then its prompt.

    Args:
        arm: The arm.
        question: The question.
        title: The project's display name.

    Returns:
        The prompt.
    """
    asked = PROMPT.format(title=title, version=question.version, query=question.query)
    return f"{arm.instructions}\n\n{asked}"


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskJob:
    """A coding task for a harness."""

    case: Case[TaskInput, TaskRun, TaskInfo]
    """The task's case (``coding_tasks.evaluators.task_dataset``)."""
    task: CodingTask
    """The task."""
    prepared: PreparedEnvironment
    """Its environment, installed."""
    sandbox: Sandbox
    """Where the hidden tests run."""
    limits: Limits = field(default_factory=Limits)
    """The hidden tests' limits."""
    cutoff: date
    """The training cutoff the rows count the task against."""
    kind: JobKind = "task"
    """A coding task."""

    @property
    def name(self) -> str:
        """The task's ID.

        Returns:
            The ID.
        """
        return self.task.id

    @property
    def project(self) -> str:
        """The task's project.

        Returns:
            The golden project.
        """
        return self.task.spec.project

    def prompt(self, arm: Arm) -> str:
        """The task's prompt with an arm.

        Args:
            arm: The arm.

        Returns:
            The prompt.
        """
        return task_prompt(arm, self.case.inputs)

    def place(self, root: Path) -> Place:
        """Build the workspace from the task's template and write its test script.

        Args:
            root: The run's folder.

        Returns:
            The workspace, the environment mounted read-only and on ``PATH``.
        """
        workspace = materialize(self.task, root / "workspace", self.prepared)
        script = workspace / TEST_SCRIPT
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(test_script(self.prepared, workspace, hidden=False), encoding="utf-8")
        env = {}
        if self.prepared.pythonpath:
            env["PYTHONPATH"] = ":".join(str(p) for p in self.prepared.pythonpath)
        return Place(
            workspace=workspace,
            readable=self.prepared.mounts,
            path=self.prepared.bin_dirs,
            env=env,
        )

    async def grade(
        self, place: Place, run: AgentRun, *, model: str, arm: str, retrieval: str
    ) -> Graded:
        """Grade the workspace as the coding tasks do; a provider's failure is not graded.

        Args:
            place: The workspace.
            run: The CLI's run.
            model: The agent model.
            arm: The arm.
            retrieval: The arm's configuration.

        Returns:
            The grade, with the coding tasks' row.
        """
        grade = None
        if run.failure != "provider":
            runner = Runner(sandbox=self.sandbox, prepared=self.prepared, limits=self.limits)
            grade = await runner.grade(self.task, place.workspace)

        async def output(_: TaskInput) -> TaskRun:
            """Return the run already made.

            Args:
                _: The task's inputs.

            Returns:
                The run and its grade.
            """
            return TaskRun(agent=run, grade=grade)

        dataset = Dataset[TaskInput, TaskRun, TaskInfo](
            name="harness-coding-tasks",
            cases=[self.case],
            evaluators=[TestsPass(), ForbiddenApi(), FilesChanged()],
        )
        report = await dataset.evaluate(output, name=f"{model} / {arm}", progress=False)
        row = task_results(
            report,
            {self.task.id: self.task},
            agent_model=model,
            arm=arm,
            retrieval=retrieval,
            cutoff=self.cutoff,
        )[0]
        return Graded(outcome=row.outcome, passed=row.passed, counted=row.graded, task=row)


@dataclass(frozen=True, slots=True, kw_only=True)
class QuestionJob:
    """A golden question for a harness."""

    case: Case[Question, AgentRun, BenchInfo]
    """The case (``agent_bench.harness.bench_dataset``)."""
    judge: AnswerJudge
    """The agent benchmark's judge."""
    kind: JobKind = "question"
    """A golden question."""

    @property
    def name(self) -> str:
        """The case's name.

        Returns:
            The name.
        """
        return self.case.name or ""

    @property
    def project(self) -> str:
        """The case's project.

        Returns:
            The golden project.
        """
        return self.case.metadata.project if self.case.metadata else ""

    def prompt(self, arm: Arm) -> str:
        """The question's prompt with an arm.

        Args:
            arm: The arm.

        Returns:
            The prompt.
        """
        title = self.case.metadata.title if self.case.metadata else self.project
        return question_prompt(arm, self.case.inputs, title)

    def place(self, root: Path) -> Place:
        """Make an empty workspace: the question needs no project.

        Args:
            root: The run's folder.

        Returns:
            The workspace.
        """
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return Place(workspace=workspace)

    async def grade(
        self, place: Place, run: AgentRun, *, model: str, arm: str, retrieval: str
    ) -> Graded:
        """Judge the answer as the agent benchmark does (blind to the arm).

        Args:
            place: The workspace (unused).
            run: The CLI's run.
            model: The agent model.
            arm: The arm.
            retrieval: The arm's configuration.

        Returns:
            The grade, with the agent benchmark's row.
        """
        del place

        async def output(_: Question) -> AgentRun:
            """Return the run already made.

            Args:
                _: The question.

            Returns:
                The run.
            """
            return run

        dataset = Dataset[Question, AgentRun, BenchInfo](
            name="harness-golden", cases=[self.case], evaluators=[self.judge]
        )
        report = await dataset.evaluate(output, name=f"{model} / {arm}", progress=False)
        row = question_results(report, model, retrieval, arm=arm)[0]
        return Graded(outcome=row.grade, passed=accurate(row), counted=counted(row), question=row)
