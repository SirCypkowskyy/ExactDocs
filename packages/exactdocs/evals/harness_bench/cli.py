"""``just harness-bench``: run coding-agent CLIs headless on the coding tasks and golden questions.

- ``list``: the harnesses, their pinned CLI releases, the providers they run against and how their
  web tools are turned off;
- ``parse``: parse a recorded transcript (as the report would) and print it;
- ``run``: every job with every harness, model and arm, each run in its own container
  (``run``), graded or judged, and the report.

See docs/evals/harnesses.md.
"""

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from agent_bench.arms import ARMS, CONTEXT7, DEFAULT_ARMS, EXACTDOCS, GROUNDED_DOCS, parse_arms
from agent_bench.cli import Setup, selected_cases, setups_of
from agent_bench.harness import RetrievalConfig, bench_dataset
from agent_bench.judge import AnswerJudge, judge_agent
from agent_bench.models import DEFAULT_RETRIES, chat_model
from agent_bench.report import BenchReport
from agent_bench.servers import DEFAULT_GROUNDED_DOCS, ArmServers, grounded_docs_config
from coding_tasks.check import prepare_all
from coding_tasks.cli import per_project, selected
from coding_tasks.environments import ENVIRONMENTS_DIR
from coding_tasks.environments import default_cache_dir as environments_cache
from coding_tasks.evaluators import task_dataset
from coding_tasks.report import CodingReport
from coding_tasks.sandbox import DOCKER_IMAGE, sandbox_named
from coding_tasks.tasks import DEFAULT_CUTOFF, TASKS_DIR, load_tasks
from harness_bench.container import DockerRunner, RunLimits
from harness_bench.endpoints import HttpArmServers
from harness_bench.harness import HarnessModel, HarnessRun, McpServer
from harness_bench.jobs import Job, QuestionJob, TaskJob
from harness_bench.releases import HARNESSES, harnesses_home, install, parse_harnesses
from harness_bench.report import HarnessReport, baseline_outcomes, markdown
from harness_bench.run import Installed, Plan, load_rows, run_bench
from retrieval_eval.context7 import API_KEY_VARIABLE
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    default_cache_dir,
    fetch,
    load_cases,
    load_corpus,
)
from retrieval_eval.grounded_docs_cli import home_dir

REPORT: Final[Path] = Path("reports/evals/harness-bench.json")
"""Where ``run`` writes the JSON report (the Markdown and the checkpoint go next to it)."""
ROWS_SUFFIX: Final[str] = ".rows.jsonl"
"""The checkpoint next to the report: one finished run per line, for ``--resume``."""
DEFAULT_RETRIEVAL: Final[tuple[str, ...]] = ("bm25:mode=bm25",)
"""The ``exactdocs`` arm's configuration when none is given (the coding tasks' default)."""
JOB_KINDS: Final[tuple[str, ...]] = ("tasks", "questions")
"""What ``--jobs`` takes."""


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="harness-bench",
        description="Coding-agent CLIs (Claude Code, Codex, Gemini CLI, OpenCode) run headless on "
        "the coding tasks and the golden questions, with each documentation arm "
        "(docs/evals/harnesses.md).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the harnesses and their pinned CLIs")
    parse = commands.add_parser("parse", help="parse a recorded transcript and print it")
    parse.add_argument("--harness", required=True, choices=list(HARNESSES))
    parse.add_argument("--mcp-server", help="the MCP server's name in the run (e.g. exactdocs)")
    parse.add_argument("--model", default="anthropic:unknown", help="for the price")
    parse.add_argument("transcript", type=Path)
    run = commands.add_parser("run", help="run the harnesses and write the report")
    _run_options(run)
    return parser


def _run_options(run: argparse.ArgumentParser) -> None:
    """Add the ``run`` command's options.

    Args:
        run: Its parser.
    """
    run.add_argument(
        "--harness",
        action="append",
        default=[],
        help=f"repeat or comma-separate ({', '.join(HARNESSES)})",
    )
    run.add_argument(
        "--model",
        action="append",
        default=[],
        help="<provider>:<model>, repeat for several (anthropic, openai, google, ollama); a "
        "harness runs only the models of providers it supports",
    )
    run.add_argument("--thinking", help="minimal, low, medium, high, xhigh or max (recorded)")
    run.add_argument(
        "--arm",
        action="append",
        default=[],
        help=f"repeat or comma-separate (default {','.join(DEFAULT_ARMS)}; "
        f"known {', '.join(ARMS)})",
    )
    run.add_argument("--retrieval", action="append", default=[], help="the exactdocs arm's")
    run.add_argument("--grounded-docs", action="append", default=[], help="its configuration")
    run.add_argument("--jobs", default="tasks", help="tasks, questions, or tasks,questions")
    run.add_argument("--tasks", default="", help="comma-separated task IDs (default: all)")
    run.add_argument("--projects", default="", help="comma-separated projects (default: all)")
    run.add_argument("--limit", type=int, help="at most this many tasks per project")
    run.add_argument(
        "--post-cutoff",
        action="store_true",
        help="only the tasks pinning a version released after --cutoff",
    )
    run.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF)
    run.add_argument("--kinds", default="", help="golden kinds of the questions (default: all)")
    run.add_argument("--question-limit", type=int, help="at most this many questions per project")
    run.add_argument("--per-stratum", type=int, help="a stratified sample of the questions")
    run.add_argument("--judge-model", help="pydantic-ai model of the questions' judge")
    run.add_argument("--max-turns", type=int, default=40)
    run.add_argument("--wall-seconds", type=float, default=900.0)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES, help="the judge's")
    run.add_argument("--sandbox", default="docker", choices=["docker", "process"])
    run.add_argument("--baseline-tasks", type=Path, help="a coding-tasks report, no harness")
    run.add_argument("--baseline-questions", type=Path, help="an agent-bench report, no harness")
    run.add_argument("--harnesses-home", type=Path, default=harnesses_home())
    run.add_argument("--grounded-docs-home", type=Path, default=home_dir())
    run.add_argument("--models-dir", type=Path)
    run.add_argument("--cache-dir", type=Path, default=environments_cache() / "environments")
    run.add_argument("--golden-cache", type=Path, default=default_cache_dir())
    run.add_argument("--work-dir", type=Path, help="runs and server logs (default: temporary)")
    run.add_argument("--report", type=Path, default=REPORT)
    run.add_argument("--resume", action="store_true", help="continue from <report>.rows.jsonl")
    run.add_argument("--tasks-dir", type=Path, default=TASKS_DIR, help=argparse.SUPPRESS)
    run.add_argument(
        "--environments-dir", type=Path, default=ENVIRONMENTS_DIR, help=argparse.SUPPRESS
    )
    run.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    run.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Asked:
    """What a ``run`` command asks for, checked."""

    harnesses: list[str]
    """The harnesses' names."""
    models: list[HarnessModel]
    """The models."""
    setups: list[Setup]
    """The arms and their configurations."""
    kinds: set[str]
    """``tasks``, ``questions`` or both."""
    corpus: Corpus
    """The corpus manifest."""


def _asked(args: argparse.Namespace) -> _Asked | str:
    """Check a ``run`` command's arguments.

    Args:
        args: The parsed arguments.

    Returns:
        What it asks for, or what is wrong with it.
    """
    try:
        harnesses = [h.name for h in parse_harnesses(args.harness)]
        models = [HarnessModel.parse(m, thinking=args.thinking) for m in args.model]
        setups = _setups(args)
    except ValueError as error:
        return str(error)
    kinds = {k.strip() for k in args.jobs.split(",") if k.strip()}
    problem = _problem(args, harnesses, models, kinds) or _keys(harnesses, models, setups)
    if problem:
        return problem
    return _Asked(
        harnesses=harnesses,
        models=models,
        setups=setups,
        kinds=kinds,
        corpus=load_corpus(args.corpus),
    )


def _setups(args: argparse.Namespace) -> list[Setup]:
    """Read the arms and their configurations.

    Args:
        args: The parsed arguments.

    Returns:
        One setup per arm and configuration.
    """
    arms = parse_arms(args.arm)
    retrieval = [RetrievalConfig.parse(t) for t in args.retrieval or DEFAULT_RETRIEVAL]
    grounded = [grounded_docs_config(n) for n in args.grounded_docs or [DEFAULT_GROUNDED_DOCS]]
    return setups_of(arms, {EXACTDOCS: retrieval, GROUNDED_DOCS: grounded})


def _problem(
    args: argparse.Namespace, harnesses: list[str], models: list[HarnessModel], kinds: set[str]
) -> str | None:
    """Check the models and the jobs asked for.

    Args:
        args: The parsed arguments.
        harnesses: The harnesses.
        models: The models.
        kinds: The kinds of jobs.

    Returns:
        What is wrong, or ``None``.
    """
    if not models:
        return "give --model <provider>:<model>"
    if not kinds or kinds - set(JOB_KINDS):
        return f"--jobs takes {', '.join(JOB_KINDS)}"
    if "questions" in kinds and not args.judge_model:
        return "the golden questions need --judge-model"
    if not any(m.provider.name in HARNESSES[h].providers for m in models for h in harnesses):
        return "no harness asked supports any model asked"
    return None


def _keys(harnesses: list[str], models: list[HarnessModel], setups: list[Setup]) -> str | None:
    """Check that every key a run needs is set.

    Args:
        harnesses: The harnesses.
        models: The models.
        setups: The arms.

    Returns:
        What is missing, or ``None``.
    """
    supported = [
        m for m in models if any(m.provider.name in HARNESSES[h].providers for h in harnesses)
    ]
    missing = sorted(
        {m.provider.key_variable for m in supported if not os.environ.get(m.provider.key_variable)}
    )
    if missing:
        return f"set {', '.join(missing)}: each harness runs with the provider's API key"
    context7 = any(s.arm == ARMS[CONTEXT7] for s in setups)
    if context7 and not os.environ.get(API_KEY_VARIABLE, "").strip():
        return f"the context7 arm needs a Context7 API key in {API_KEY_VARIABLE}"
    return None


async def _jobs(args: argparse.Namespace, asked: _Asked) -> tuple[list[Job], set[str], str]:
    """Build the jobs: the coding tasks (their environments installed) and the golden questions.

    Args:
        args: The parsed arguments.
        asked: What the command asks for.

    Returns:
        The jobs, their projects and how they were picked.

    Raises:
        ValueError: The tasks or the questions do not load, or none matches.
    """
    jobs: list[Job] = []
    parts = []
    if "tasks" in asked.kinds:
        loaded, problems = load_tasks(args.tasks_dir, args.environments_dir, asked.corpus)
        if problems:
            raise ValueError("\n".join(problems))
        tasks = per_project(selected(loaded, args.tasks, args.projects), args.limit)
        if args.post_cutoff:
            tasks = [t for t in tasks if t.post_cutoff(args.cutoff)]
        prepared = await prepare_all(tasks, args.cache_dir)
        sandbox = sandbox_named(args.sandbox, require_network_isolation=True)
        dataset = task_dataset(tasks, asked.corpus)
        by_id = {t.id: t for t in tasks}
        jobs += [
            TaskJob(
                case=case,
                task=by_id[case.name or ""],
                prepared=prepared[by_id[case.name or ""].environment.name],
                sandbox=sandbox,
                cutoff=args.cutoff,
            )
            for case in dataset.cases
        ]
        parts.append(f"{len(tasks)} tasks" + (" after the cutoff" if args.post_cutoff else ""))
    if "questions" in asked.kinds:
        cases, problems = load_cases(args.cases)
        if problems:
            raise ValueError("\n".join(problems))
        picked = selected_cases(
            cases,
            projects=[p for p in args.projects.split(",") if p],
            kinds=[k for k in args.kinds.split(",") if k],
            limit=args.question_limit,
            per_stratum=args.per_stratum,
        )
        judge = AnswerJudge(
            judge=judge_agent(chat_model(args.judge_model, max_retries=args.max_retries))
        )
        jobs += [
            QuestionJob(case=c, judge=judge) for c in bench_dataset(picked, asked.corpus).cases
        ]
        parts.append(f"{len(picked)} golden questions")
    if not jobs:
        message = "no job matches"
        raise ValueError(message)
    if args.projects:
        parts.append(f"projects {args.projects}")
    if args.tasks:
        parts.append(f"tasks {args.tasks}")
    if args.limit is not None:
        parts.append(f"at most {args.limit} tasks per project")
    return jobs, {j.project for j in jobs}, "; ".join(parts)


def _baseline(args: argparse.Namespace) -> tuple[dict, list[str]]:
    """Read the no-harness reports given.

    Args:
        args: The parsed arguments.

    Returns:
        Their outcomes by job (``report.baseline_outcomes``) and their paths.
    """
    tasks = questions = None
    paths = []
    if args.baseline_tasks:
        tasks = CodingReport.model_validate_json(args.baseline_tasks.read_text(encoding="utf-8"))
        paths.append(str(args.baseline_tasks))
    if args.baseline_questions:
        text = args.baseline_questions.read_text(encoding="utf-8")
        questions = BenchReport.model_validate_json(text)
        paths.append(str(args.baseline_questions))
    return baseline_outcomes(tasks, questions), paths


def _run(args: argparse.Namespace) -> int:
    """Run the benchmark, write the reports and print the Markdown.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        2 for a usage error, 1 when an install, a fetch or a server failed, else 0 (no gate).
    """
    asked = _asked(args)
    if isinstance(asked, str):
        sys.stderr.write(f"harness-bench: {asked}\n")
        return 2
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="exactdocs-harness-bench-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        installed = [
            Installed(harness=HARNESSES[h], executable=install(HARNESSES[h], args.harnesses_home))
            for h in asked.harnesses
        ]
        jobs, projects, selection = asyncio.run(_jobs(args, asked))
        wanted = projects if any(s.arm.configured for s in asked.setups) else set()
        repos = {p.id: fetch(p, args.golden_cache) for p in asked.corpus.projects if p.id in wanted}
        baseline, baselines = _baseline(args)
    except (RuntimeError, ValueError, OSError) as error:
        sys.stderr.write(f"harness-bench: {error}\n")
        return 1
    servers = ArmServers(
        projects=[p for p in asked.corpus.projects if p.id in projects],
        repos=repos,
        work_dir=work_dir,
        grounded_home=args.grounded_docs_home,
        models_dir=args.models_dir,
    )
    checkpoint = args.report.with_suffix(ROWS_SUFFIX)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    done = load_rows(checkpoint) if args.resume else {}
    if not args.resume:
        checkpoint.write_text("", encoding="utf-8")
    plan = Plan(
        jobs=jobs,
        harnesses=installed,
        models=asked.models,
        setups=asked.setups,
        selection=selection,
        cutoff=args.cutoff if "tasks" in asked.kinds else None,
        judge_model=args.judge_model if "questions" in asked.kinds else None,
    )
    try:
        report = asyncio.run(
            run_bench(
                plan,
                endpoints=HttpArmServers(servers=servers),
                runner=DockerRunner(),
                work_dir=work_dir,
                limits=RunLimits(wall_seconds=args.wall_seconds),
                max_turns=args.max_turns,
                concurrency=args.concurrency,
                checkpoint=checkpoint,
                done=done,
                image=DOCKER_IMAGE,
                baseline=baseline,
                baselines=baselines,
            )
        )
    except RuntimeError as error:
        sys.stderr.write(f"harness-bench: {error}\n")
        return 1
    write(report, args.report)
    sys.stdout.write(f"\nreport: {args.report}; work dir: {work_dir}\n")
    return 0


def write(report: HarnessReport, path: Path) -> None:
    """Write the JSON report and the Markdown next to it, and print the Markdown.

    Args:
        report: The run.
        path: The JSON report.
    """
    text = markdown(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(text)
    if failed := sum(r.failure in {"provider", "harness"} for r in report.results):
        sys.stdout.write(
            f"\n{failed} runs failed on the provider's or the CLI's side; "
            "--resume runs them again\n"
        )


def _list() -> int:
    """Print the harnesses.

    Returns:
        0.
    """
    lines = [
        "| Harness | CLI | Released | Providers | Web tools | Turn limit, thinking |",
        "|---|---|---|---|---|---|",
    ]
    for harness in HARNESSES.values():
        release = harness.release
        lines.append(
            f"| {harness.name} | `{release.package}@{release.version}` | {release.released} | "
            f"{', '.join(sorted(harness.providers))} | {harness.web_tools} | {harness.limits} |"
        )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _parse(args: argparse.Namespace) -> int:
    """Parse a recorded transcript and print it.

    Args:
        args: The parsed ``parse`` arguments.

    Returns:
        0.
    """
    model = HarnessModel.parse(args.model, env={})
    mcp = McpServer(name=args.mcp_server, url="") if args.mcp_server else None
    run = HarnessRun(workspace=Path(), home=Path(), prompt="", model=model, mcp=mcp)
    transcript = HARNESSES[args.harness].parse(args.transcript.read_text(encoding="utf-8"), run)
    sys.stdout.write(transcript.model_dump_json(indent=2) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    if args.command == "list":
        return _list()
    if args.command == "parse":
        return _parse(args)
    return _run(args)
