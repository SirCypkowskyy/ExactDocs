"""An agent completes a coding task with the workspace tools and one documentation arm.

The arms are the agent benchmark's (``agent_bench.arms``): ``none`` has no documentation tool,
``exactdocs`` has ExactDocs as shipped (``agent_bench.harness.ArmServers``), and the arms
#492/#493 add come the same way. Every arm also gets the workspace tools (``workspace``). The
agent is told what a coding agent knows from the project (the library and the version it pins)
and the task; the instructions differ between arms only in the sentence about the documentation
tool. A run records its tool calls (documentation and workspace), tokens, thinking, wall time
and provider retries as the agent benchmark does (``agent_bench.harness.run_record``); the
workspace is then graded in the sandbox (``grading``), unless the run failed on the provider's
side, which is not graded and asked again with ``--resume``.
"""

import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from agent_bench.arms import Arm
from agent_bench.harness import PROMPT, Recorder, failure_of, run_record
from agent_bench.redact import scrub
from agent_bench.retries import RETRIES, RetryLog
from coding_tasks.environments import PreparedEnvironment
from coding_tasks.evaluators import TaskInput
from coding_tasks.grading import Runner, TaskRun, materialize
from coding_tasks.sandbox import Limits, Sandbox
from coding_tasks.tasks import CodingTask
from coding_tasks.workspace import Workspace

INSTRUCTIONS: Final[str] = """\
You are a coding agent working in a project's workspace. {source}

Complete the task by changing the workspace's files with the workspace tools: list_files, \
read_file, write_file (a whole file at a time) and run_tests (the project's own tests, in a \
sandbox). The project's dependencies are pinned in its lockfile and already installed: nothing \
can be installed and the lockfile cannot be changed. Write code for exactly the version of the \
library the project uses, run the tests before you finish, and end with a short summary of what \
you changed."""
"""The coding agent's instructions, the same for every arm apart from ``{source}``."""
DOCS_SOURCE: Final[str] = """\
To look up the library's API, your only source of documentation is the {tool} tools: find the \
library, search the documentation of exactly the version the project uses, and read the sections \
you need. Do not rely on what you remember of other versions."""
"""The source sentence of an arm with a documentation tool: only the tool's name differs."""
NO_DOCS_SOURCE: Final[str] = """\
You have no documentation tools: rely on what you know about the version of the library the \
project uses."""
"""The source sentence of the ``none`` arm."""
DEFAULT_MAX_REQUESTS: Final[int] = 30
"""Model requests one task may take by default (reading, writing and testing take several)."""

type ModelFor = Callable[[str, CodingTask], Model | str]
"""Resolves an agent model's name for a task (a scripted model knows the task's solution)."""


def instructions(arm: Arm) -> str:
    """The coding agent's instructions for an arm.

    Args:
        arm: The documentation arm.

    Returns:
        ``INSTRUCTIONS`` with the arm's source sentence.
    """
    source = NO_DOCS_SOURCE if arm.tool is None else DOCS_SOURCE.format(tool=arm.tool)
    return INSTRUCTIONS.format(source=source)


def prompt(inputs: TaskInput) -> str:
    """The user prompt of a task: the project's library and version, then the request.

    Args:
        inputs: The task.

    Returns:
        The agent benchmark's ``PROMPT`` with the task's request as the question.
    """
    return PROMPT.format(title=inputs.title, version=inputs.version, query=inputs.prompt)


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskAgent:
    """The task function of a run: one agent model with one arm completes a task, then grading."""

    model_name: str
    """The agent model's name (for the price and the report)."""
    models: ModelFor
    """Resolves the model for a task."""
    arm: Arm
    """The documentation arm."""
    toolsets: Sequence[AbstractToolset[Recorder]]
    """The arm's documentation toolsets (none for ``none``)."""
    tasks: Mapping[str, CodingTask]
    """The tasks, by ID."""
    prepared: Mapping[str, PreparedEnvironment]
    """Each environment, installed, by name."""
    sandbox: Sandbox
    """Where the tests run."""
    work_dir: Path
    """Where the workspaces are built (each run its own)."""
    limits: Limits = Limits()
    """The limits of each test run."""
    max_requests: int = DEFAULT_MAX_REQUESTS
    """The most model requests one task may take, the same for every arm."""
    settings: ModelSettings | None = None
    """The agent's model settings (the thinking setting)."""

    async def __call__(self, inputs: TaskInput) -> TaskRun:
        """Let the agent complete one task, then grade its workspace.

        Args:
            inputs: The task.

        Returns:
            The agent's run and the grade; no grade when the provider failed.
        """
        task = self.tasks[inputs.task]
        prepared = self.prepared[task.environment.name]
        self.work_dir.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix=f"{task.id}-", dir=self.work_dir))
        workspace_dir = materialize(task, root / "workspace", prepared)
        runner = Runner(sandbox=self.sandbox, prepared=prepared, limits=self.limits)
        workspace = Workspace(root=workspace_dir, task=task, runner=runner)
        agent = Agent[Recorder, str](
            self.models(self.model_name, task),
            deps_type=Recorder,
            instructions=instructions(self.arm),
            toolsets=[*self.toolsets, workspace.toolset()],
        )
        recorder = Recorder()
        answer, error, failure = "", None, None
        retries = RetryLog()
        token = RETRIES.set(retries)
        started = time.perf_counter()
        try:
            with capture_run_messages() as messages:
                try:
                    result = await agent.run(
                        prompt(inputs),
                        deps=recorder,
                        model_settings=self.settings,
                        usage_limits=UsageLimits(request_limit=self.max_requests),
                    )
                    answer = result.output
                except AgentRunError as raised:
                    error, failure = scrub(f"{type(raised).__name__}: {raised}"), failure_of(raised)
        finally:
            RETRIES.reset(token)
        seconds = round(time.perf_counter() - started, 3)
        spent = run_record(messages, recorder, retries, model=self.model_name, seconds=seconds)
        run = spent.model_copy(update={"answer": answer, "error": error, "failure": failure})
        grade = None if failure == "provider" else await runner.grade(task, workspace_dir)
        return TaskRun(agent=run, grade=grade)
