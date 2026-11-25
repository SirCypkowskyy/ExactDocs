"""``just agent-bench``: run the agent benchmark, export a labelling sample, compute agreement.

See docs/evals/agent-bench.md.
"""

import argparse
import asyncio
import contextlib
import functools
import importlib.metadata
import itertools
import json
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import yaml
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_evals import Case, Dataset

from agent_bench.agreement import LABELLING_HEADER, SAMPLE_SIZE, agreement, sample
from agent_bench.arms import ARMS, DEFAULT_ARMS, EXACTDOCS, Arm, parse_arms
from agent_bench.harness import (
    PROMPT,
    AgentRun,
    ArmServers,
    ArmTools,
    BenchInfo,
    Recorder,
    RetrievalConfig,
    asker,
    bench_dataset,
)
from agent_bench.judge import ERROR, AnswerJudge, judge_agent
from agent_bench.models import (
    DEFAULT_RETRIES,
    chat_model,
    model_settings,
    providers_used,
    thinking_setting,
)
from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE
from agent_bench.redact import recorded_settings, scrub
from agent_bench.report import (
    BenchReport,
    CorpusCommit,
    QuestionResult,
    RunMeta,
    against_arms,
    against_reference,
    counted,
    markdown,
    results_of,
    summarize,
)
from fixture_repo import git
from retrieval_eval.dataset import Question
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    GoldenCase,
    default_cache_dir,
    fetch,
    load_cases,
    load_corpus,
)
from retrieval_eval.golden_review import draw_sample
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS

REPORT: Final[Path] = Path("reports/evals/agent-bench.json")
"""Where ``run`` writes the JSON report by default (the Markdown goes next to it)."""
SAMPLE: Final[Path] = Path("reports/evals/agent-bench-labels.yaml")
"""Where ``sample`` writes the labelling sample by default."""
ROWS_SUFFIX: Final[str] = ".rows.jsonl"
"""The checkpoint next to the report: one finished question per line, for ``--resume``."""
DEFAULT_RETRIEVAL: Final[tuple[str, ...]] = ("bm25:mode=bm25", "hybrid:mode=hybrid")
"""The retrieval configurations when none is given. Without an embedding model, ``hybrid``
falls back to BM25 (the report shows ``bm25 (mode_unavailable)``)."""
DEFAULT_MAX_REQUESTS: Final[int] = 20
"""Model requests one question may take by default."""
DEFAULT_SEED: Final[int] = 495
"""The seed of a stratified sample (``--per-stratum``)."""

type JobKey = tuple[str, str, str, str]
"""``(agent model, arm, retrieval, case)``: one question asked once."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Setup:
    """One arm under one retrieval configuration (none for an arm that takes none)."""

    arm: Arm
    """The arm."""
    config: RetrievalConfig | None
    """Its retrieval configuration."""

    @property
    def retrieval(self) -> str:
        """The configuration's name, empty for none.

        Returns:
            The name.
        """
        return self.config.name if self.config else ""


def setups_of(arms: Sequence[Arm], retrieval: Sequence[RetrievalConfig]) -> list[Setup]:
    """Pair each arm with its retrieval configurations.

    Args:
        arms: The arms.
        retrieval: The retrieval configurations, for an arm that takes them.

    Returns:
        One setup per arm and configuration, in order.
    """
    return [
        Setup(arm=arm, config=config)
        for arm in arms
        for config in (retrieval if arm.retrieval else [None])
    ]


def selected_cases(
    cases: Sequence[tuple[str, GoldenCase]],
    *,
    projects: Sequence[str] = (),
    kinds: Sequence[str] = (),
    limit: int | None = None,
    per_stratum: int | None = None,
    seed: int = DEFAULT_SEED,
) -> list[tuple[str, GoldenCase]]:
    """Pick the cases to ask.

    Args:
        cases: ``(project, case)`` pairs.
        projects: Only these projects (all when empty).
        kinds: Only these kinds (all when empty).
        limit: At most this many per project, in file order.
        per_stratum: A stratified random sample of this many cases per kind and project
            (``golden_review.draw_sample``), taken before ``limit``.
        seed: The sample's seed.

    Returns:
        The cases, in file order (in sample order with ``per_stratum``).
    """
    kept = [
        (project, case)
        for project, case in cases
        if (not projects or project in projects)
        and (not kinds or (case.metadata.kind if case.metadata else "") in kinds)
    ]
    if per_stratum is not None:
        kept = draw_sample(kept, seed=seed, per_stratum=per_stratum)
    taken: dict[str, int] = {}
    picked = []
    for project, case in kept:
        if limit is not None and taken.get(project, 0) >= limit:
            continue
        taken[project] = taken.get(project, 0) + 1
        picked.append((project, case))
    return picked


def selection_of(args: argparse.Namespace) -> str:
    """Describe how the cases were picked, for the report.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        E.g. ``3 per kind and project, seed 495``, or ``all``.
    """
    parts = []
    if args.per_stratum is not None:
        parts.append(f"{args.per_stratum} per kind and project, seed {args.seed}")
    if args.projects:
        parts.append(f"projects {args.projects}")
    if args.kinds:
        parts.append(f"kinds {args.kinds}")
    if args.limit is not None:
        parts.append(f"at most {args.limit} per project")
    return "; ".join(parts) or "all"


def load_rows(path: Path) -> dict[JobKey, QuestionResult]:
    """Read a checkpoint: the last record of each question.

    Args:
        path: The ``.rows.jsonl`` file.

    Returns:
        Each question's latest record, its reason scrubbed again (``redact.scrub``); nothing when
        there is no file.
    """
    rows: dict[JobKey, QuestionResult] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = QuestionResult.model_validate_json(line)
            row = row.model_copy(update={"judge_reason": scrub(row.judge_reason)})
            rows[row.agent_model, row.arm, row.retrieval, row.case] = row
    return rows


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- it collects rows
class Asking:
    """Asks a run's questions, ``gate`` at a time, and keeps (and checkpoints) each finished one."""

    judge: AnswerJudge
    """The judge's evaluator."""
    gate: asyncio.Semaphore
    """How many questions are asked at once."""
    checkpoint: Path | None
    """Where each finished question is appended."""
    done: dict[JobKey, QuestionResult]
    """Questions an earlier run answered: not asked again."""
    tasks: dict[tuple[str, str, str], Callable[[Question], Awaitable[AgentRun]]] = field(
        default_factory=dict
    )
    """The task of each agent model, arm and retrieval configuration."""
    rows: dict[JobKey, QuestionResult] = field(default_factory=dict)
    """The questions asked by this run."""
    todo: int = 0
    """Questions this run asks."""

    async def run(
        self, jobs: Sequence[tuple[Case[Question, AgentRun, BenchInfo], JobKey]]
    ) -> list[QuestionResult]:
        """Ask every job not done yet.

        Args:
            jobs: Each question with its key, in the order they are asked.

        Returns:
            Every job's record, in the jobs' order: the earlier run's or this one's.
        """
        todo = [(case, key) for case, key in jobs if key not in self.done]
        self.todo = len(todo)
        sys.stderr.write(
            f"agent-bench: {len(todo)} questions to ask, {len(jobs) - len(todo)} done\n"
        )
        await asyncio.gather(*itertools.starmap(self.ask, todo))
        found = {**self.done, **self.rows}
        return [found[key] for _, key in jobs if key in found]

    async def ask(self, case: Case[Question, AgentRun, BenchInfo], key: JobKey) -> None:
        """Ask and judge one question, and record it.

        Args:
            case: The golden case.
            key: The model, arm, retrieval configuration and case.
        """
        name, arm, config, _ = key
        async with self.gate:
            one = Dataset[Question, AgentRun, BenchInfo](
                name="golden-agent", cases=[case], evaluators=[self.judge]
            )
            evaluated = await one.evaluate(
                self.tasks[name, arm, config], name=f"{name} / {arm}", progress=False
            )
        for row in results_of(evaluated, name, config, arm=arm):
            self.rows[key] = row
            if self.checkpoint is not None:
                with self.checkpoint.open("a", encoding="utf-8") as out:
                    out.write(row.model_dump_json() + "\n")
            sys.stderr.write(
                f"agent-bench: [{len(self.rows)}/{self.todo}] {name} {arm} {key[3]}: "
                f"{row.grade} ({row.seconds:.1f} s)\n"
            )


async def run_bench(
    cases: Sequence[tuple[str, GoldenCase]],
    corpus: Corpus,
    repos: dict[str, Path],
    *,
    agent_models: Sequence[str],
    judge_model: str,
    retrieval: Sequence[RetrievalConfig],
    work_dir: Path,
    arms: Sequence[Arm] = (ARMS[EXACTDOCS],),
    max_requests: int = DEFAULT_MAX_REQUESTS,
    concurrency: int = 1,
    thinking: str | None = None,
    max_retries: int = DEFAULT_RETRIES,
    selection: str = "all",
    tools: ArmTools | None = None,
    models: Callable[[str], Model | str] | None = None,
    checkpoint: Path | None = None,
    done: dict[JobKey, QuestionResult] | None = None,
) -> BenchReport:
    """Ask every case of every agent model with every arm, and judge the answers.

    For the ``exactdocs`` arm, the corpus is imported once per embedding model and ExactDocs is
    started as shipped, ``exactdocs serve --stdio``, per retrieval configuration; ``none`` has no
    tools. The questions are interleaved (each case with every model and arm, then the next case)
    so that a provider's slow hour weighs on every arm alike, and asked ``concurrency`` at a time.
    Each finished question is appended to ``checkpoint``; questions in ``done`` that did not fail
    on the provider's side are not asked again.

    Args:
        cases: ``(project, case)`` pairs.
        corpus: The corpus manifest.
        repos: Each asked project's cached repository.
        agent_models: The agent models (pydantic-ai names, ``ollama:<model>``, or stand-ins).
        judge_model: The judge's model.
        retrieval: The retrieval configurations of the ``exactdocs`` arm.
        work_dir: Where the data directories and the server logs go.
        arms: The arms.
        max_requests: Model requests one question may take, the same for every arm.
        concurrency: Questions asked at once.
        thinking: The agents' thinking setting (``models.thinking_setting``); the model's default
            when ``None``.
        max_retries: Retries of a failed Ollama request.
        selection: How the cases were picked, for the report.
        tools: Gives each arm its toolsets; ``ArmServers`` (the real servers) by default.
        models: Resolves a model name; ``models.chat_model`` with ``max_retries`` by default.
        checkpoint: Where each finished question is appended (JSON lines).
        done: Questions answered by an earlier run of the same command (``--resume``).

    Returns:
        The report.
    """
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    dataset = bench_dataset(cases, corpus)
    projects = [p for p in corpus.projects if p.id in {project for project, _ in cases}]
    servers = ArmServers(projects=projects, repos=repos, work_dir=work_dir)
    setups = setups_of(arms, retrieval)
    resolve = models or functools.partial(chat_model, max_retries=max_retries)
    asking = Asking(
        judge=AnswerJudge(judge=judge_agent(resolve(judge_model))),
        gate=asyncio.Semaphore(concurrency),
        checkpoint=checkpoint,
        done={k: r for k, r in (done or {}).items() if counted(r)},
    )
    async with contextlib.AsyncExitStack() as stack:
        for setup in setups:
            toolsets = await stack.enter_async_context(
                (tools or servers.tools)(setup.arm, setup.config)
            )
            for name in agent_models:
                asking.tasks[name, *_key(setup)] = asker(
                    Agent[Recorder, str](
                        resolve(name),
                        deps_type=Recorder,
                        instructions=setup.arm.instructions,
                        toolsets=list(toolsets),
                    ),
                    name,
                    {p.id: p.title for p in projects},
                    max_requests=max_requests,
                    settings=model_settings(thinking_setting(thinking)),
                )
        jobs = [
            (case, (name, *_key(setup), case.name or ""))
            for case in dataset.cases
            for name in agent_models
            for setup in setups
        ]
        every = await asking.run(jobs)
    cells = [
        summarize(
            name,
            setup.retrieval,
            [r for r in every if (r.agent_model, r.arm, r.retrieval) == (name, *_key(setup))],
            arm=setup.arm.name,
        )
        for name in agent_models
        for setup in setups
    ]
    meta = RunMeta(
        started_at=started_at,
        exactdocs_version=importlib.metadata.version("exactdocs"),
        git_commit=git("rev-parse", "HEAD", cwd=Path(__file__).parent, check=False),
        agent_models=list(agent_models),
        judge_model=judge_model,
        arms=[arm.name for arm in arms],
        retrieval={
            s.config.name: recorded_settings(s.config.env) for s in setups if s.config is not None
        },
        max_requests=max_requests,
        concurrency=concurrency,
        cases=len(dataset.cases),
        selection=selection,
        thinking=thinking or "model default",
        max_retries=max_retries,
        providers=providers_used([*agent_models, judge_model]),
        agent_instructions={arm.name: arm.instructions for arm in arms},
        prompt=PROMPT,
        corpus=[
            CorpusCommit(
                project=r.project,
                version=r.version,
                pinned_commit=r.pinned_commit,
                imported_commit=r.imported_commit,
            )
            for r in servers.records
        ],
    )
    return BenchReport(
        meta=meta,
        cells=against_arms(against_reference(cells, every, DEFAULT_STATS), every, DEFAULT_STATS),
        questions=every,
        statistics=DEFAULT_STATS,
    )


def _key(setup: Setup) -> tuple[str, str]:
    """A setup's arm and retrieval names.

    Args:
        setup: The setup.

    Returns:
        ``(arm, retrieval)``.
    """
    return setup.arm.name, setup.retrieval


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="agent-bench",
        description="An agent answers the golden set with each documentation arm: no docs, "
        "ExactDocs' MCP tools (docs/evals/agent-bench.md).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the benchmark and write the report")
    run.add_argument(
        "--agent-model",
        action="append",
        default=[],
        help="pydantic-ai model name, repeat for several (e.g. openai:gpt-5-mini, "
        "ollama:gpt-oss:120b with OLLAMA_BASE_URL and OLLAMA_API_KEY)",
    )
    run.add_argument("--judge-model", help="pydantic-ai model name of the judge")
    run.add_argument(
        "--arm",
        action="append",
        default=[],
        help=f"documentation arm, repeat or comma-separate (default: {','.join(DEFAULT_ARMS)}; "
        f"known: {', '.join(ARMS)})",
    )
    run.add_argument(
        "--retrieval",
        action="append",
        default=[],
        help="name[:key=value,...] of EXACTDOCS_AI__ settings for the exactdocs arm, repeat for "
        f"several (default: {' and '.join(DEFAULT_RETRIEVAL)})",
    )
    run.add_argument(
        "--thinking",
        help="the agents' thinking: on, off, minimal, low, medium, high, xhigh or max "
        "(default: each model's own)",
    )
    run.add_argument(
        "--offline",
        action="store_true",
        help=f"stand-in models, no provider: {', '.join(OFFLINE_AGENTS)}, judge {OFFLINE_JUDGE}",
    )
    run.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    run.add_argument("--kinds", default="", help="comma-separated kinds (default: all)")
    run.add_argument("--limit", type=int, help="at most this many cases per project")
    run.add_argument(
        "--per-stratum", type=int, help="a stratified sample: this many cases per kind and project"
    )
    run.add_argument("--seed", type=int, default=DEFAULT_SEED, help="the stratified sample's seed")
    run.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    run.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="retries of a failed provider request (429, 5xx), with backoff",
    )
    run.add_argument("--concurrency", type=int, default=1, help="questions asked at once")
    run.add_argument(
        "--resume",
        action="store_true",
        help="keep the questions the last run of this command answered (its .rows.jsonl) and ask "
        "only the others and those the provider failed on",
    )
    run.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    run.add_argument(
        "--work-dir", type=Path, help="data directories and server logs (default: temporary)"
    )
    run.add_argument(
        "--report", type=Path, default=REPORT, help="the JSON report (Markdown next to it)"
    )
    run.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    run.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    labels = commands.add_parser("sample", help="export answers of a report for hand labelling")
    labels.add_argument("--report", type=Path, default=REPORT)
    labels.add_argument("--out", type=Path, default=SAMPLE)
    labels.add_argument("--size", type=int, default=SAMPLE_SIZE)
    labels.add_argument("--seed", type=int, default=0)
    agree = commands.add_parser("agreement", help="compare hand labels with the judge")
    agree.add_argument("--report", type=Path, default=REPORT)
    agree.add_argument("--labels", type=Path, default=SAMPLE)
    return parser


def _run(args: argparse.Namespace) -> int:
    """Run the benchmark, write the reports and print the Markdown.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        The exit code: 2 for a usage error, else 0 (the benchmark has no gate).
    """
    agent_models = list(OFFLINE_AGENTS) if args.offline else args.agent_model
    judge_model = OFFLINE_JUDGE if args.offline else args.judge_model
    if not agent_models or not judge_model:
        sys.stderr.write("agent-bench: give --agent-model and --judge-model, or --offline\n")
        return 2
    try:
        arms = parse_arms(args.arm)
        retrieval = [RetrievalConfig.parse(t) for t in args.retrieval or DEFAULT_RETRIEVAL]
        thinking_setting(args.thinking)
    except ValueError as error:
        sys.stderr.write(f"agent-bench: {error}\n")
        return 2
    corpus = load_corpus(args.corpus)
    loaded, problems = load_cases(args.cases)
    if problems:
        sys.stderr.write("".join(f"agent-bench: {p}\n" for p in problems))
        return 2
    cases = selected_cases(
        loaded,
        projects=[p for p in args.projects.split(",") if p],
        kinds=[k for k in args.kinds.split(",") if k],
        limit=args.limit,
        per_stratum=args.per_stratum,
        seed=args.seed,
    )
    if not cases:
        sys.stderr.write("agent-bench: no case matches\n")
        return 2
    asked = {project for project, _ in cases}
    try:
        repos = {p.id: fetch(p, args.cache_dir) for p in corpus.projects if p.id in asked}
    except RuntimeError as error:
        sys.stderr.write(f"agent-bench: {error}\n")
        return 1
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="exactdocs-agent-bench-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.report.with_suffix(ROWS_SUFFIX)
    done = load_rows(checkpoint) if args.resume else {}
    if not args.resume:
        checkpoint.write_text("", encoding="utf-8")
    report = asyncio.run(
        run_bench(
            cases,
            corpus,
            repos,
            agent_models=agent_models,
            judge_model=judge_model,
            arms=arms,
            retrieval=retrieval,
            work_dir=work_dir,
            max_requests=args.max_requests,
            concurrency=args.concurrency,
            thinking=args.thinking,
            max_retries=args.max_retries,
            selection=selection_of(args),
            checkpoint=checkpoint,
            done=done,
        )
    )
    _write(report, args.report)
    sys.stdout.write(f"\nreport: {args.report}; work dir: {work_dir}\n")
    return 0


def _write(report: BenchReport, path: Path) -> None:
    """Write the JSON report and the Markdown next to it, and print the Markdown.

    Args:
        report: The run.
        path: The JSON report.
    """
    text = markdown(report)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(text)
    if failed := sum(q.grade == ERROR for q in report.questions):
        sys.stdout.write(
            f"\n{failed} questions failed on the provider's side; `--resume` asks them again\n"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    report = BenchReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    if args.command == "sample":
        entries = sample(report, args.size, args.seed)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=100)
        args.out.write_text(LABELLING_HEADER + text, encoding="utf-8")
        sys.stdout.write(f"{len(entries)} answers to label in {args.out}\n")
        return 0
    labels = yaml.safe_load(args.labels.read_text(encoding="utf-8")) or []
    result = agreement(report, labels)
    sys.stdout.write(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    return 0
