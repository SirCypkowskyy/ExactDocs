"""Run agents on the coding tasks: every task with every agent model and every arm.

As in the agent benchmark, the jobs are interleaved (each task with every model and arm before
the next task), asked ``concurrency`` at a time, and each finished task is appended to a
checkpoint (``<report>.rows.jsonl``); ``--resume`` keeps what an earlier run of the same command
graded and asks only the rest and what failed on the provider's side.
"""

import asyncio
import contextlib
import functools
import importlib.metadata
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_evals import Case, Dataset

from agent_bench.arms import Arm
from agent_bench.cli import Setup, setups_of
from agent_bench.harness import PROMPT, ArmServers, ArmTools, RetrievalConfig
from agent_bench.models import (
    DEFAULT_RETRIES,
    chat_model,
    model_settings,
    providers_used,
    thinking_setting,
)
from agent_bench.redact import recorded_settings
from coding_tasks.agent import DEFAULT_MAX_REQUESTS, ModelFor, TaskAgent, instructions
from coding_tasks.environments import PreparedEnvironment
from coding_tasks.evaluators import TaskInfo, TaskInput, task_dataset
from coding_tasks.grading import TaskRun
from coding_tasks.report import (
    ERROR,
    CellKey,
    CodingReport,
    RunMeta,
    TaskResult,
    cells_of,
    results_of,
)
from coding_tasks.sandbox import Limits, Sandbox
from coding_tasks.tasks import DEFAULT_CUTOFF, CodingTask
from fixture_repo import git
from retrieval_eval.golden import Corpus
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS

type JobKey = tuple[str, str, str, str]
"""``(agent model, arm, retrieval, task)``: one task asked once."""


def load_rows(path: Path) -> dict[JobKey, TaskResult]:
    """Read a checkpoint: the last result of each job.

    Args:
        path: The ``.rows.jsonl`` file.

    Returns:
        Each job's latest result; nothing when there is no file.
    """
    rows: dict[JobKey, TaskResult] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = TaskResult.model_validate_json(line)
            rows[row.agent_model, row.arm, row.retrieval, row.task] = row
    return rows


def _model(name: str, task: CodingTask, *, max_retries: int) -> Model | str:
    """Resolve a real model's name; the task does not matter to it.

    Args:
        name: The pydantic-ai model name.
        task: The task (unused).
        max_retries: Retries of a failed Ollama request.

    Returns:
        The model.
    """
    del task
    return chat_model(name, max_retries=max_retries)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- it collects rows
class Asking:
    """Asks the jobs, ``gate`` at a time, and keeps (and checkpoints) each finished one."""

    tasks: dict[str, CodingTask]
    """Every task, by ID."""
    gate: asyncio.Semaphore
    """How many tasks are asked at once."""
    cutoff: date
    """The training cutoff."""
    checkpoint: Path | None
    """Where each finished job is appended."""
    done: dict[JobKey, TaskResult]
    """Jobs an earlier run graded: not asked again."""
    agents: dict[tuple[str, str, str], TaskAgent] = field(default_factory=dict)
    """The task function of each model, arm and configuration."""
    rows: dict[JobKey, TaskResult] = field(default_factory=dict)
    """The jobs this run asked."""

    async def run(
        self, jobs: Sequence[tuple[Case[TaskInput, TaskRun, TaskInfo], JobKey]]
    ) -> list[TaskResult]:
        """Ask every job not done yet.

        Args:
            jobs: Each task with its key, in the order they are asked.

        Returns:
            Every job's result, in the jobs' order: the earlier run's or this one's.
        """
        todo = [(case, key) for case, key in jobs if key not in self.done]
        sys.stderr.write(f"coding-tasks: {len(todo)} tasks to ask, {len(jobs) - len(todo)} done\n")
        await asyncio.gather(*(self.ask(case, key, len(todo)) for case, key in todo))
        found = {**self.done, **self.rows}
        return [found[key] for _, key in jobs if key in found]

    async def ask(self, case: Case[TaskInput, TaskRun, TaskInfo], key: JobKey, total: int) -> None:
        """Ask one task and record its result.

        Args:
            case: The task's case.
            key: The model, arm, configuration and task.
            total: Jobs this run asks, for the progress line.
        """
        name, arm, config, _ = key
        async with self.gate:
            one = Dataset[TaskInput, TaskRun, TaskInfo](
                name="coding-tasks", cases=[case], evaluators=[]
            )
            evaluated = await one.evaluate(
                self.agents[name, arm, config], name=f"{name} / {arm}", progress=False
            )
        for row in results_of(
            evaluated, self.tasks, agent_model=name, arm=arm, retrieval=config, cutoff=self.cutoff
        ):
            self.rows[key] = row
            if self.checkpoint is not None:
                with self.checkpoint.open("a", encoding="utf-8") as out:
                    out.write(row.model_dump_json() + "\n")
            sys.stderr.write(
                f"coding-tasks: [{len(self.rows)}/{total}] {name} {arm} {key[3]}: {row.outcome}"
                f"{' (' + ', '.join(row.forbidden) + ')' if row.forbidden else ''}"
                f" ({row.seconds:.1f} s)\n"
            )


def _key(setup: Setup) -> tuple[str, str]:
    """A setup's arm and retrieval names.

    Args:
        setup: The setup.

    Returns:
        ``(arm, retrieval)``.
    """
    return setup.arm.name, setup.retrieval


async def run_tasks(
    tasks: Sequence[CodingTask],
    corpus: Corpus,
    prepared: Mapping[str, PreparedEnvironment],
    sandbox: Sandbox,
    *,
    agent_models: Sequence[str],
    arms: Sequence[Arm],
    retrieval: Sequence[RetrievalConfig],
    work_dir: Path,
    repos: Mapping[str, Path] | None = None,
    tools: ArmTools | None = None,
    models: ModelFor | None = None,
    limits: Limits | None = None,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    concurrency: int = 1,
    thinking: str | None = None,
    max_retries: int = DEFAULT_RETRIES,
    cutoff: date = DEFAULT_CUTOFF,
    selection: str = "all",
    checkpoint: Path | None = None,
    done: dict[JobKey, TaskResult] | None = None,
) -> CodingReport:
    """Ask every task of every agent model with every arm, and grade the workspaces.

    Args:
        tasks: The tasks.
        corpus: The golden corpus (titles, libraries, the ``exactdocs`` arm's import).
        prepared: Each environment, installed, by name.
        sandbox: Where the tests run.
        agent_models: The agent models (pydantic-ai names, ``ollama:<model>``, scripted ones).
        arms: The documentation arms.
        retrieval: The ``exactdocs`` arm's retrieval configurations.
        work_dir: Where the workspaces, data directories and server logs go.
        repos: Each project's cached repository, for the ``exactdocs`` arm's import.
        tools: Gives each arm its documentation toolsets; ``ArmServers`` by default.
        models: Resolves a model for a task; real models by default.
        limits: The limits of each test run.
        max_requests: Model requests one task may take.
        concurrency: Tasks asked at once.
        thinking: The agents' thinking setting.
        max_retries: Retries of a failed Ollama request.
        cutoff: The training cutoff the report counts tasks against.
        selection: How the tasks were picked, for the report.
        checkpoint: Where each finished task is appended (JSON lines).
        done: Results of an earlier run of the same command (``--resume``).

    Returns:
        The report.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    dataset = task_dataset(list(tasks), corpus)
    projects = [p for p in corpus.projects if p.id in {t.spec.project for t in tasks}]
    servers = ArmServers(projects=projects, repos=repos or {}, work_dir=work_dir)
    setups = setups_of(arms, retrieval)
    resolve = models or functools.partial(_model, max_retries=max_retries)
    settings = model_settings(thinking_setting(thinking))
    asking = Asking(
        tasks={t.id: t for t in tasks},
        gate=asyncio.Semaphore(concurrency),
        cutoff=cutoff,
        checkpoint=checkpoint,
        done={k: r for k, r in (done or {}).items() if r.outcome != ERROR},
    )
    async with contextlib.AsyncExitStack() as stack:
        for setup in setups:
            toolsets = await stack.enter_async_context(
                (tools or servers.tools)(setup.arm, setup.config)
            )
            for name in agent_models:
                asking.agents[name, *_key(setup)] = TaskAgent(
                    model_name=name,
                    models=resolve,
                    arm=setup.arm,
                    toolsets=list(toolsets),
                    tasks=asking.tasks,
                    prepared=prepared,
                    sandbox=sandbox,
                    work_dir=work_dir / "workspaces",
                    limits=limits or Limits(),
                    max_requests=max_requests,
                    settings=settings,
                )
        jobs = [
            (case, (name, *_key(setup), case.name or ""))
            for case in dataset.cases
            for name in agent_models
            for setup in setups
        ]
        every = await asking.run(jobs)
    keys: list[CellKey] = [(name, *_key(setup)) for name in agent_models for setup in setups]
    meta = RunMeta(
        started_at=started_at,
        exactdocs_version=importlib.metadata.version("exactdocs"),
        git_commit=git("rev-parse", "HEAD", cwd=Path(__file__).parent, check=False),
        agent_models=list(agent_models),
        arms=[arm.name for arm in arms],
        retrieval={
            s.config.name: recorded_settings(s.config.env) for s in setups if s.config is not None
        },
        tasks=len(dataset.cases),
        selection=selection,
        cutoff=cutoff,
        max_requests=max_requests,
        concurrency=concurrency,
        thinking=thinking or "model default",
        max_retries=max_retries,
        providers=providers_used(list(agent_models)),
        instructions={arm.name: instructions(arm) for arm in arms},
        prompt=PROMPT,
        isolation=sandbox.isolation,
    )
    return CodingReport(
        meta=meta,
        cells=cells_of(every, keys, DEFAULT_STATS),
        results=every,
        statistics=DEFAULT_STATS,
    )
