"""Run every job with every harness, model and arm, each run in its own container, and grade it.

As in the agent benchmark and the coding tasks, the jobs are interleaved (each job with every
model, harness and arm before the next job), run ``concurrency`` at a time, and each finished run
is appended to a checkpoint (``<report>.rows.jsonl``); ``--resume`` keeps what an earlier run of
the same command graded and runs only the rest, and what failed on the provider's or the CLI's
side. A harness never runs a model whose provider it does not support.

Each run:

1. builds the job's workspace and a home of its own in ``<work dir>/runs/<run>``;
2. opens a network of its own (``container``): the gate lets through the provider's host, and
   forwards to the arm's MCP server (and to a stand-in provider on this machine);
3. writes the CLI's configuration (``Harness.configure``) and runs it headless in its container;
4. keeps the transcript (scrubbed of secrets) next to the workspace, parses it
   (``Harness.parse``), and removes the home (its configuration holds the arm's credentials);
5. grades the workspace or judges the answer (``jobs``).
"""

import asyncio
import contextlib
import dataclasses
import importlib.metadata
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from agent_bench.arms import Arm
from agent_bench.cli import Setup
from agent_bench.harness import Failure
from agent_bench.redact import scrub
from fixture_repo import git
from harness_bench.container import (
    CliRun,
    HarnessRunner,
    Placement,
    RunLimits,
    RunNetwork,
    node_home,
)
from harness_bench.endpoints import ArmEndpoints, Endpoint
from harness_bench.harness import Harness, HarnessModel, HarnessRun, McpServer
from harness_bench.jobs import Graded, Job, Place, agent_run
from harness_bench.report import (
    BaselineKey,
    HarnessReport,
    HarnessResult,
    RunMeta,
    cells_of,
    harness_meta,
)
from harness_bench.transcript import Transcript
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS

type JobKey = tuple[str, str, str, str, str, str]
"""``(harness, agent model, arm, retrieval, kind, job)``: one job run once."""

LOOPBACK: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost", "::1"})
"""Hosts of a provider on this machine (a stand-in): forwarded, not tunnelled."""


def key_of(row: HarnessResult) -> JobKey:
    """A result's job key.

    Args:
        row: The result.

    Returns:
        ``(harness, model, arm, retrieval, kind, job)``.
    """
    return row.harness, row.agent_model, row.arm, row.retrieval, row.kind, row.job


def load_rows(path: Path) -> dict[JobKey, HarnessResult]:
    """Read a checkpoint: the last result of each job.

    Args:
        path: The ``.rows.jsonl`` file.

    Returns:
        Each job's latest result; nothing when there is no file.
    """
    rows: dict[JobKey, HarnessResult] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = HarnessResult.model_validate_json(line)
            rows[key_of(row)] = row
    return rows


def classify(transcript: Transcript, cli: CliRun) -> tuple[str | None, Failure | None, str | None]:
    """Tell how a run ended.

    Args:
        transcript: The parsed transcript.
        cli: How the CLI ended.

    Returns:
        The harness failure (``provider``, ``harness``, ``no_answer``; ``None`` for an answer), the
        agent benchmark's failure (``provider`` is not graded: the provider's and the CLI's own
        failures; ``no_answer`` is the agent's) and the error.
    """
    if transcript.provider_failure:
        return "provider", "provider", transcript.error
    if cli.timed_out:
        return "no_answer", "no_answer", "killed at the wall limit"
    started = transcript.lines - transcript.unparsed > 0
    if cli.exit_code not in {0, None} and not started:
        return "harness", "provider", f"the CLI exited with status {cli.exit_code}: {cli.stderr}"
    if transcript.error:
        return "no_answer", "no_answer", transcript.error
    return None, None, None


@dataclass(frozen=True, slots=True, kw_only=True)
class Ran:
    """What one run was: the harness, the job, the model, the arm, and what the CLI was given."""

    harness: Harness
    """The harness."""
    job: Job
    """The job."""
    model: HarnessModel
    """The model."""
    setup: Setup
    """The arm and its configuration."""
    run: HarnessRun
    """What the CLI was given."""


def result_of(
    ran: Ran,
    transcript: Transcript,
    cli: CliRun,
    graded: Graded,
    *,
    failure: str | None,
    error: str | None,
    run_dir: str,
) -> HarnessResult:
    """Record one run.

    Args:
        ran: What ran.
        transcript: Its parsed transcript.
        cli: How the CLI ended.
        graded: Its grade.
        failure: Whose side it failed on (``classify``).
        error: Why.
        run_dir: Its folder in the work directory.

    Returns:
        The result.
    """
    server = ran.run.mcp.name if ran.run.mcp else None
    return HarnessResult(
        harness=ran.harness.name,
        cli_version=transcript.cli_version or ran.harness.release.version,
        agent_model=ran.model.name,
        arm=ran.setup.arm.name,
        retrieval=ran.setup.retrieval,
        kind=ran.job.kind,
        job=ran.job.name,
        project=ran.job.project,
        outcome=graded.outcome,
        passed=graded.passed,
        counted=graded.counted and failure not in {"provider", "harness"},
        failure=failure,
        error=scrub(error) if error else None,
        seconds=cli.seconds,
        reported_seconds=transcript.reported_seconds,
        timed_out=cli.timed_out,
        exit_code=cli.exit_code,
        turns=transcript.turns,
        input_tokens=transcript.input_tokens,
        cached_input_tokens=transcript.cached_input_tokens,
        output_tokens=transcript.output_tokens,
        thinking_tokens=transcript.thinking_tokens,
        thinking_source=transcript.thinking,
        thinking_chars=transcript.thinking_chars,
        usd=transcript.usd,
        usd_source=transcript.usd_source,
        calls=transcript.calls,
        docs_calls=transcript.docs_calls(server),
        web_calls=sum(c.web for c in transcript.calls),
        tools_offered=transcript.tools_offered,
        tunnels=cli.tunnels,
        denied=cli.denied,
        answer=scrub(transcript.answer),
        run_dir=run_dir,
        task=graded.task,
        question=graded.question,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Installed:
    """A harness and its installed CLI."""

    harness: Harness
    """The harness."""
    executable: Path
    """Its CLI's command."""
    tools: tuple[Path, ...] = ()
    """Folders of commands every run gets besides the CLI (the pinned ripgrep)."""

    @property
    def readable(self) -> list[tuple[Path, Path]]:
        """What its container mounts read-only: the CLI's install, Node.js and the tools.

        Returns:
            ``(source, target)`` pairs, each at its own path.
        """
        prefix = self.executable.parents[2]  # <prefix>/node_modules/.bin/<cli>
        node = node_home()
        found = [prefix, *([node] if node else []), *self.tools]
        return [(p, p) for p in found]

    @property
    def path(self) -> list[Path]:
        """What its container puts first on ``PATH``: the CLI's, Node.js' and the tools' commands.

        Returns:
            The directories.
        """
        node = node_home()
        return [self.executable.parent, *([node / "bin"] if node else []), *self.tools]


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- it collects rows
class Running:
    """Runs the jobs, ``gate`` at a time, and keeps (and checkpoints) each finished one."""

    runner: HarnessRunner
    """Gives each run its container."""
    work_dir: Path
    """Where each run's folder goes."""
    limits: RunLimits
    """Each run's limits."""
    max_turns: int
    """The turn limit, where a CLI takes one."""
    gate: asyncio.Semaphore
    """How many runs at once."""
    checkpoint: Path | None
    """Where each finished run is appended."""
    done: dict[JobKey, HarnessResult]
    """Runs an earlier run graded: not run again."""
    endpoints: dict[tuple[str, str], Endpoint | None] = field(default_factory=dict)
    """Each setup's MCP server, by ``(arm, retrieval)``."""
    rows: dict[JobKey, HarnessResult] = field(default_factory=dict)
    """The runs this run made."""
    todo: int = 0
    """Runs to make."""

    async def run_all(
        self, jobs: Sequence[tuple[Job, Installed, HarnessModel, Setup]]
    ) -> list[HarnessResult]:
        """Run every job not done yet.

        Args:
            jobs: Each job with its harness, model and setup, in the order they run.

        Returns:
            Every job's result, in order: the earlier run's or this one's.
        """
        keyed = [
            (job, key_for(job, installed, model, setup)) for job, installed, model, setup in jobs
        ]
        todo = [
            (spec, key) for spec, (_, key) in zip(jobs, keyed, strict=True) if key not in self.done
        ]
        self.todo = len(todo)
        sys.stderr.write(f"harness-bench: {len(todo)} runs to make, {len(jobs) - len(todo)} done\n")
        await asyncio.gather(*(self.run_one(*spec) for spec, _ in todo))
        found = {**self.done, **self.rows}
        return [found[key] for _, key in keyed if key in found]

    async def run_one(
        self, job: Job, installed: Installed, model: HarnessModel, setup: Setup
    ) -> None:
        """Run one job and record it.

        Args:
            job: The job.
            installed: The harness and its CLI.
            model: The model.
            setup: The arm and its configuration.
        """
        async with self.gate:
            row = await self._run(job, installed, model, setup)
        self.rows[key_of(row)] = row
        if self.checkpoint is not None:
            with self.checkpoint.open("a", encoding="utf-8") as out:
                out.write(row.model_dump_json() + "\n")
        sys.stderr.write(
            f"harness-bench: [{len(self.rows)}/{self.todo}] {row.harness} {row.agent_model} "
            f"{row.arm} {row.job}: {row.outcome} ({row.seconds:.1f} s, "
            f"{row.docs_calls} docs calls)\n"
        )

    async def _run(
        self, job: Job, installed: Installed, model: HarnessModel, setup: Setup
    ) -> HarnessResult:
        """Run one job in its own container, then grade it.

        Args:
            job: The job.
            installed: The harness and its CLI.
            model: The model.
            setup: The arm and its configuration.

        Returns:
            The result.
        """
        root = self._folder(f"{installed.harness.name}-{setup.arm.name}-{job.name}-")
        place = job.place(root)
        run, cli = await self._execute(job, installed, model, setup, place, root / "home")
        (root / "transcript.jsonl").write_text(scrub(cli.output), encoding="utf-8")
        (root / "stderr.txt").write_text(scrub(cli.stderr), encoding="utf-8")
        transcript = installed.harness.parse(cli.output, run)
        failure, agent_failure, error = classify(transcript, cli)
        agent = agent_run(transcript, seconds=cli.seconds, failure=agent_failure, error=error)
        graded = await job.grade(
            place, agent, model=model.name, arm=setup.arm.name, retrieval=setup.retrieval
        )
        return result_of(
            Ran(harness=installed.harness, job=job, model=model, setup=setup, run=run),
            transcript,
            cli,
            graded,
            failure=failure,
            error=error,
            run_dir=str(root.relative_to(self.work_dir)),
        )

    def _folder(self, prefix: str) -> Path:
        """Make a run's folder, with its home.

        Args:
            prefix: Its name's start (harness, arm, job).

        Returns:
            The folder, ``home`` in it.
        """
        runs = self.work_dir / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix=prefix, dir=runs))
        (root / "home").mkdir()
        return root

    async def _execute(
        self,
        job: Job,
        installed: Installed,
        model: HarnessModel,
        setup: Setup,
        place: Place,
        home: Path,
    ) -> tuple[HarnessRun, CliRun]:
        """Configure the CLI and run it in its own network; remove its home afterwards.

        Args:
            job: The job.
            installed: The harness and its CLI.
            model: The model.
            setup: The arm and its configuration.
            place: The job's workspace.
            home: The run's home, removed after the run: its configuration holds the arm's
                credentials.

        Returns:
            What the CLI was given and how it ended.
        """
        endpoint = self.endpoints[setup.arm.name, setup.retrieval]
        forwards: dict[str, tuple[str, int]] = {}
        if endpoint is not None:
            forwards["mcp"] = endpoint.address
        local = model.address[0] in LOOPBACK
        if local:
            forwards["provider"] = model.address
        try:
            async with self.runner.network(
                allowed=[] if local else [model.address], forwards=forwards
            ) as network:
                run = self._harness_run(
                    job, place.workspace, home, model, setup.arm, endpoint, network
                )
                invocation = installed.harness.configure(run, installed.executable)
                invocation = dataclasses.replace(invocation, env={**place.env, **invocation.env})
                placement = Placement(
                    workspace=place.workspace,
                    home=home,
                    readable=[*installed.readable, *place.readable],
                    path=[*installed.path, *place.path],
                )
                cli = await network.run(invocation, placement, self.limits)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        return run, cli

    def _harness_run(
        self,
        job: Job,
        workspace: Path,
        home: Path,
        model: HarnessModel,
        arm: Arm,
        endpoint: Endpoint | None,
        network: RunNetwork,
    ) -> HarnessRun:
        """What the CLI is given, with the addresses its network reaches.

        Args:
            job: The job.
            workspace: Its workspace.
            home: The run's home.
            model: The model.
            arm: The arm.
            endpoint: The arm's MCP server on this machine.
            network: The run's network.

        Returns:
            The run.
        """
        if model.address[0] in LOOPBACK:
            model = dataclasses.replace(
                model, base_url=network.url("provider", urlsplit(model.base_url).path)
            )
        mcp = None
        if endpoint is not None:
            mcp = McpServer(
                name=endpoint.name,
                url=network.url("mcp", endpoint.path),
                tools=endpoint.tools,
                excluded=endpoint.excluded,
                headers=endpoint.headers,
            )
        return HarnessRun(
            workspace=workspace,
            home=home,
            prompt=job.prompt(arm),
            model=model,
            mcp=mcp,
            max_turns=self.max_turns,
        )


def key_for(job: Job, installed: Installed, model: HarnessModel, setup: Setup) -> JobKey:
    """The key of a job with a harness, model and setup.

    Args:
        job: The job.
        installed: The harness.
        model: The model.
        setup: The arm and its configuration.

    Returns:
        ``(harness, model, arm, retrieval, kind, job)``.
    """
    return (
        installed.harness.name,
        model.name,
        setup.arm.name,
        setup.retrieval,
        job.kind,
        job.name,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """What a benchmark run asks for."""

    jobs: Sequence[Job]
    """The jobs (coding tasks, golden questions)."""
    harnesses: Sequence[Installed]
    """The harnesses with their CLIs."""
    models: Sequence[HarnessModel]
    """The models."""
    setups: Sequence[Setup]
    """The arms and their configurations."""
    selection: str = "all"
    """How the jobs were picked, for the report."""
    cutoff: date | None = None
    """The training cutoff the tasks are counted against."""
    judge_model: str | None = None
    """The judge of the golden questions."""


async def run_bench(
    plan: Plan,
    *,
    endpoints: ArmEndpoints,
    runner: HarnessRunner,
    work_dir: Path,
    limits: RunLimits | None = None,
    max_turns: int = 40,
    concurrency: int = 1,
    checkpoint: Path | None = None,
    done: Mapping[JobKey, HarnessResult] | None = None,
    image: str = "",
    baseline: Mapping[BaselineKey, tuple[bool, float, float, float]] | None = None,
    baselines: Sequence[str] = (),
) -> HarnessReport:
    """Run every job with every harness, model and arm, and report.

    Args:
        plan: The jobs, harnesses, models and setups.
        endpoints: Serves each arm's MCP server.
        runner: Gives each run its container (``DockerRunner``).
        work_dir: Where the runs' folders and the servers' logs go.
        limits: Each run's limits.
        max_turns: The turn limit, where a CLI takes one.
        concurrency: Runs at once.
        checkpoint: Where each finished run is appended (JSON lines).
        done: Results of an earlier run of the same command (``--resume``).
        image: The container image, for the report.
        baseline: The same models' runs without a harness (``report.baseline_outcomes``).
        baselines: The reports they come from, for the report.

    Returns:
        The report.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    running = Running(
        runner=runner,
        work_dir=work_dir,
        limits=limits or RunLimits(),
        max_turns=max_turns,
        gate=asyncio.Semaphore(concurrency),
        checkpoint=checkpoint,
        done={k: r for k, r in (done or {}).items() if r.failure not in {"provider", "harness"}},
    )
    specs = [
        (job, installed, model, setup)
        for job in plan.jobs
        for model in plan.models
        for installed in plan.harnesses
        if model.provider.name in installed.harness.providers
        for setup in plan.setups
    ]
    async with contextlib.AsyncExitStack() as stack:
        for setup in plan.setups:
            running.endpoints[setup.arm.name, setup.retrieval] = await stack.enter_async_context(
                endpoints.endpoint(setup.arm, setup.config)
            )
        every = await running.run_all(specs)
    meta = RunMeta(
        started_at=started_at,
        exactdocs_version=importlib.metadata.version("exactdocs"),
        git_commit=git("rev-parse", "HEAD", cwd=Path(__file__).parent, check=False),
        harnesses=[harness_meta(i.harness, runner.isolation) for i in plan.harnesses],
        agent_models=[m.name for m in plan.models],
        thinking={m.name: m.thinking or "model default" for m in plan.models},
        arms=list(dict.fromkeys(s.arm.name for s in plan.setups)),
        servers=endpoints.described,
        jobs=len(plan.jobs),
        selection=plan.selection,
        cutoff=plan.cutoff,
        judge_model=plan.judge_model,
        max_turns=max_turns,
        wall_seconds=running.limits.wall_seconds,
        concurrency=concurrency,
        isolation=runner.isolation,
        image=image,
        resumed=len(specs) - running.todo,
        baselines=list(baselines),
    )
    return HarnessReport(meta=meta, cells=cells_of(every, DEFAULT_STATS, baseline), results=every)
