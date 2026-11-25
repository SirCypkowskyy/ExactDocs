"""``just coding-tasks``: list, prepare and check the version-pinned coding tasks, and run agents.

- ``list``: the task inventory (project, pinned version, pair, other version, post-cutoff);
- ``prepare``: install every environment the tasks need from its lockfile;
- ``check``: no model; every reference passes and every other-version solution fails (CI);
- ``run``: agents complete the tasks with each documentation arm (``agent.py``).

See docs/evals.md#version-pinned-coding-tasks.
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

from coding_tasks.check import CheckReport, check_tasks, markdown, prepare_all
from coding_tasks.environments import ENVIRONMENTS_DIR, default_cache_dir
from coding_tasks.sandbox import Limits, sandbox_named
from coding_tasks.tasks import DEFAULT_CUTOFF, TASKS_DIR, CodingTask, load_tasks
from retrieval_eval.golden import CORPUS_FILE, Corpus, load_corpus

CHECK_REPORT: Final[Path] = Path("reports/evals/coding-tasks-check.json")
"""Where ``check`` writes its JSON report (the Markdown goes next to it)."""


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="coding-tasks",
        description="Version-pinned coding tasks: an agent's code must run against the version "
        "the project pins (docs/evals.md#version-pinned-coding-tasks).",
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
        "| Task | Project | Pinned | Released | Pair | Other version | Change behind the trap |"
        " After the cutoff |",
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
    lines += [
        "",
        f"{len(tasks)} tasks over {len(projects)} projects ({', '.join(projects)}); {paired} in "
        f"version pairs; {sum(t.post_cutoff(cutoff) for t in tasks)} pin a version released after "
        f"{cutoff}, {sum(t.api_post_cutoff(cutoff) for t in tasks)} of them also hinge on a change "
        "released after it.",
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
