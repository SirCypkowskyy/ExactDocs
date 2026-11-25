"""``just coding-tasks``: list, prepare and check the version-pinned coding tasks, and run agents.

- ``list``: the task inventory (project, pinned version, pair, other version, post-cutoff);
- ``prepare``: install every environment the tasks need from its lockfile;
- ``check``: no model; every reference passes and every other-version solution fails (CI);
- ``run``: agents complete the tasks with each documentation arm (``agent.py``).

See docs/evals/coding-tasks.md.
"""

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final

from agent_bench.arms import DEFAULT_ARMS, parse_arms
from agent_bench.harness import RetrievalConfig
from agent_bench.models import DEFAULT_RETRIES, thinking_setting
from coding_tasks.agent import DEFAULT_MAX_REQUESTS
from coding_tasks.check import CheckReport, check_tasks, markdown, prepare_all
from coding_tasks.environments import ENVIRONMENTS_DIR, default_cache_dir
from coding_tasks.offline import OFFLINE_AGENTS, offline_model
from coding_tasks.report import CodingReport
from coding_tasks.report import markdown as report_markdown
from coding_tasks.run import load_rows, run_tasks
from coding_tasks.sandbox import Limits, sandbox_named
from coding_tasks.tasks import DEFAULT_CUTOFF, TASKS_DIR, CodingTask, load_tasks
from retrieval_eval.golden import CORPUS_FILE, Corpus, fetch, load_corpus
from retrieval_eval.golden import default_cache_dir as golden_cache_dir

CHECK_REPORT: Final[Path] = Path("reports/evals/coding-tasks-check.json")
"""Where ``check`` writes its JSON report (the Markdown goes next to it)."""
RUN_REPORT: Final[Path] = Path("reports/evals/coding-tasks.json")
"""Where ``run`` writes its JSON report (the Markdown and the checkpoint go next to it)."""
ROWS_SUFFIX: Final[str] = ".rows.jsonl"
"""The checkpoint next to the run's report: one finished task per line, for ``--resume``."""
DEFAULT_RETRIEVAL: Final[tuple[str, ...]] = ("bm25:mode=bm25",)
"""The ``exactdocs`` arm's retrieval configuration when none is given."""


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="coding-tasks",
        description="Version-pinned coding tasks: an agent's code must run against the version "
        "the project pins (docs/evals/coding-tasks.md).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("list", "list the tasks"),
        ("prepare", "install the environments the tasks need"),
        ("check", "check that every reference passes and every other-version solution fails"),
    ):
        command = commands.add_parser(name, help=text)
        _common(command)
        if name == "check":
            command.add_argument(
                "--sandbox",
                default="process",
                choices=["process", "docker"],
                help="where the tests run (default: process)",
            )
            command.add_argument("--concurrency", type=int, default=min(4, os.cpu_count() or 1))
            command.add_argument("--report", type=Path, default=CHECK_REPORT)
            command.add_argument(
                "--work-dir", type=Path, help="where workspaces are built (default: temporary)"
            )
        if name == "list":
            command.add_argument(
                "--cutoff",
                type=date.fromisoformat,
                default=DEFAULT_CUTOFF,
                help=f"training cutoff the tasks are counted against (default {DEFAULT_CUTOFF})",
            )
    run = commands.add_parser("run", help="agents complete the tasks with each documentation arm")
    _common(run)
    run.add_argument(
        "--agent-model",
        action="append",
        default=[],
        help="pydantic-ai model name, repeat for several (ollama:<model> with OLLAMA_BASE_URL and "
        "OLLAMA_API_KEY)",
    )
    run.add_argument(
        "--offline",
        action="store_true",
        help=f"the scripted models instead ({', '.join(OFFLINE_AGENTS)}); no provider",
    )
    run.add_argument(
        "--arm",
        action="append",
        default=[],
        help=f"documentation arm, repeat or comma-separate (default: {','.join(DEFAULT_ARMS)})",
    )
    run.add_argument(
        "--retrieval",
        action="append",
        default=[],
        help="name[:key=value,...] of the exactdocs arm (default: bm25:mode=bm25)",
    )
    run.add_argument("--thinking", help="the agents' thinking (default: each model's own)")
    run.add_argument("--limit", type=int, help="at most this many tasks per project")
    run.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    run.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES)
    run.add_argument("--concurrency", type=int, default=1, help="tasks asked at once")
    run.add_argument(
        "--sandbox",
        default="docker",
        choices=["docker", "process"],
        help="where the agent's code runs (default: docker; process needs a network namespace)",
    )
    run.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=DEFAULT_CUTOFF,
        help=f"training cutoff the report counts tasks against (default {DEFAULT_CUTOFF})",
    )
    run.add_argument("--resume", action="store_true", help="continue from <report>.rows.jsonl")
    run.add_argument("--golden-cache", type=Path, default=golden_cache_dir())
    run.add_argument(
        "--work-dir", type=Path, help="workspaces and server logs (default: temporary)"
    )
    run.add_argument("--report", type=Path, default=RUN_REPORT)
    return parser


def _common(command: argparse.ArgumentParser) -> None:
    """Add the options every command takes.

    Args:
        command: A subcommand's parser.
    """
    command.add_argument("--tasks", default="", help="comma-separated task IDs (default: all)")
    command.add_argument("--projects", default="", help="comma-separated projects (default: all)")
    command.add_argument("--cache-dir", type=Path, default=default_cache_dir() / "environments")
    command.add_argument("--tasks-dir", type=Path, default=TASKS_DIR, help=argparse.SUPPRESS)
    command.add_argument(
        "--environments-dir", type=Path, default=ENVIRONMENTS_DIR, help=argparse.SUPPRESS
    )
    command.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)


def selected(tasks: Sequence[CodingTask], ids: str, projects: str) -> list[CodingTask]:
    """Pick tasks by ID and project.

    Args:
        tasks: Every task.
        ids: Comma-separated IDs (all when empty).
        projects: Comma-separated projects (all when empty).

    Returns:
        The tasks asked for, in order.
    """
    wanted = {i for i in ids.split(",") if i}
    wanted_projects = {p for p in projects.split(",") if p}
    return [
        t
        for t in tasks
        if (not wanted or t.id in wanted)
        and (not wanted_projects or t.spec.project in wanted_projects)
    ]


def _load(args: argparse.Namespace) -> tuple[list[CodingTask], Corpus] | None:
    """Read the tasks a command asks for.

    Args:
        args: The parsed arguments.

    Returns:
        The tasks and the corpus; ``None`` after printing the problems (or an empty selection).
    """
    corpus = load_corpus(args.corpus)
    tasks, problems = load_tasks(args.tasks_dir, args.environments_dir, corpus)
    if problems:
        sys.stderr.write("".join(f"coding-tasks: {p}\n" for p in problems))
        return None
    picked = selected(tasks, args.tasks, args.projects)
    if not picked:
        sys.stderr.write("coding-tasks: no task matches\n")
        return None
    return picked, corpus


def inventory(tasks: Sequence[CodingTask], cutoff: date) -> str:
    """Show the tasks as a Markdown table, with counts.

    Args:
        tasks: The tasks.
        cutoff: The training cutoff.

    Returns:
        The table: task, project, pinned version (and its release), pair, other version, whether
        the version and the change it hinges on came after the cutoff.
    """
    lines = [
        (
            "| Task | Project | Pinned | Released | Pair | Other version | Change behind the trap |"
            " After the cutoff |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in tasks:
        since = t.spec.api_since
        after = "version and change" if t.api_post_cutoff(cutoff) else ""
        after = after or ("version" if t.post_cutoff(cutoff) else "")
        lines.append(
            f"| {t.id} | {t.spec.project} | {t.spec.version} | {t.released} | "
            f"{t.spec.pair or ''} | {t.spec.other_version} | "
            f"{f'{since.version} ({since.released})' if since else ''} | {after} |"
        )
    projects = sorted({t.spec.project for t in tasks})
    paired = sum(t.spec.pair is not None for t in tasks)
    both = sum(t.post_cutoff(cutoff) and t.api_post_cutoff(cutoff) for t in tasks)
    lines += [
        "",
        (
            f"{len(tasks)} tasks over {len(projects)} projects ({', '.join(projects)}); "
            f"{paired} in version pairs; {sum(t.post_cutoff(cutoff) for t in tasks)} pin a "
            f"version released after {cutoff}, {both} of them also hinge on a change released "
            f"after it; {sum(t.api_post_cutoff(cutoff) for t in tasks)} in all hinge on such a "
            "change."
        ),
    ]
    return "\n".join(lines) + "\n"


def _check(args: argparse.Namespace) -> int:
    """Check the tasks and write the report.

    Args:
        args: The parsed ``check`` arguments.

    Returns:
        0 when every task is sound, 1 when one is not or an install failed, 2 for a usage error.
    """
    loaded = _load(args)
    if loaded is None:
        return 2
    tasks, corpus = loaded
    try:
        prepared = asyncio.run(prepare_all(tasks, args.cache_dir, concurrency=args.concurrency))
    except RuntimeError as error:
        sys.stderr.write(f"coding-tasks: {error}\n")
        return 1
    sandbox = sandbox_named(args.sandbox, require_network_isolation=False)
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="exactdocs-coding-check-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(
        check_tasks(
            tasks,
            corpus,
            prepared,
            sandbox,
            work_dir=work_dir,
            limits=Limits(),
            concurrency=args.concurrency,
        )
    )
    _write(report, args.report)
    return 0 if report.ok else 1


def _write(report: CheckReport, path: Path) -> None:
    """Write the check's JSON and Markdown, and print the Markdown.

    Args:
        report: The check.
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


def _run(args: argparse.Namespace) -> int:
    """Let agents complete the tasks, then write the report.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        2 for a usage error, 1 when an install or a fetch failed, else 0 (no gate).
    """
    agent_models = list(OFFLINE_AGENTS) if args.offline else args.agent_model
    if not agent_models:
        sys.stderr.write("coding-tasks: give --agent-model, or --offline\n")
        return 2
    try:
        arms = parse_arms(args.arm)
        retrieval = [RetrievalConfig.parse(t) for t in args.retrieval or DEFAULT_RETRIEVAL]
        thinking_setting(args.thinking)
    except ValueError as error:
        sys.stderr.write(f"coding-tasks: {error}\n")
        return 2
    loaded = _load(args)
    if loaded is None:
        return 2
    tasks, corpus = loaded
    tasks = per_project(tasks, args.limit)
    try:
        prepared = asyncio.run(prepare_all(tasks, args.cache_dir))
        wanted = {t.spec.project for t in tasks} if any(a.retrieval for a in arms) else set()
        repos = {p.id: fetch(p, args.golden_cache) for p in corpus.projects if p.id in wanted}
    except RuntimeError as error:
        sys.stderr.write(f"coding-tasks: {error}\n")
        return 1
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="exactdocs-coding-tasks-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.report.with_suffix(ROWS_SUFFIX)
    done = load_rows(checkpoint) if args.resume else {}
    if not args.resume:
        checkpoint.write_text("", encoding="utf-8")
    report = asyncio.run(
        run_tasks(
            tasks,
            corpus,
            prepared,
            sandbox_named(args.sandbox, require_network_isolation=True),
            agent_models=agent_models,
            arms=arms,
            retrieval=retrieval,
            work_dir=work_dir,
            repos=repos,
            models=offline_model if args.offline else None,
            max_requests=args.max_requests,
            concurrency=args.concurrency,
            thinking=args.thinking,
            max_retries=args.max_retries,
            cutoff=args.cutoff,
            selection=_selection(args),
            checkpoint=checkpoint,
            done=done,
        )
    )
    _write_run(report, args.report)
    sys.stdout.write(f"\nreport: {args.report}; work dir: {work_dir}\n")
    return 0


def per_project(tasks: Sequence[CodingTask], limit: int | None) -> list[CodingTask]:
    """Keep at most `limit` tasks per project, in order.

    Args:
        tasks: The tasks.
        limit: The most per project; all when ``None``.

    Returns:
        The tasks kept.
    """
    taken: dict[str, int] = {}
    kept = []
    for task in tasks:
        if limit is None or taken.get(task.spec.project, 0) < limit:
            taken[task.spec.project] = taken.get(task.spec.project, 0) + 1
            kept.append(task)
    return kept


def _write_run(report: CodingReport, path: Path) -> None:
    """Write a run's JSON and Markdown, and print the Markdown.

    Args:
        report: The run.
        path: The JSON report.
    """
    text = report_markdown(report)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(text)
    if errors := sum(r.outcome == "error" for r in report.results):
        sys.stdout.write(
            f"\n{errors} tasks failed on the provider's side; --resume asks them again\n"
        )


def _selection(args: argparse.Namespace) -> str:
    """Describe how the tasks were picked, for the report.

    Args:
        args: The parsed ``run`` arguments.

    Returns:
        E.g. ``projects zod; at most 3 per project``, or ``all``.
    """
    parts = []
    if args.tasks:
        parts.append(f"tasks {args.tasks}")
    if args.projects:
        parts.append(f"projects {args.projects}")
    if args.limit is not None:
        parts.append(f"at most {args.limit} per project")
    return "; ".join(parts) or "all"


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command == "run":
        return _run(args)
    loaded = _load(args)
    if loaded is None:
        return 2
    tasks, _ = loaded
    if args.command == "list":
        sys.stdout.write(inventory(tasks, args.cutoff))
        return 0
    try:
        prepared = asyncio.run(prepare_all(tasks, args.cache_dir))
    except RuntimeError as error:
        sys.stderr.write(f"coding-tasks: {error}\n")
        return 1
    for name, env in sorted(prepared.items()):
        sys.stdout.write(f"{name}: {env.root}\n")
    return 0
