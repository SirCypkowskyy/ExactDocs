"""``just golden-validate`` / ``just golden-import``: fetch the corpus, check the cases, import it.

See docs/evals.md#the-golden-set.
"""

import argparse
import asyncio
import json
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

from exactdocs.bootstrap.container import Container
from exactdocs.catalog.dtos import (
    ChunkingIn,
    CreateLibraryCommand,
    GetLibraryQuery,
    HostKind,
    SetLibrarySettingsCommand,
)
from exactdocs.ingestion.constants import IMPORT_JOB
from exactdocs.ingestion.models import Job, JobId, ProblemCode, RefKind
from exactdocs_kernel import SystemClock
from fixture_import import importer
from retrieval_eval.fixture import model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    Project,
    default_cache_dir,
    fetch,
    load_cases,
    load_corpus,
    schema_problems,
    section_problems,
)
from retrieval_eval.golden_review import REVIEW_FILE, review_file_problems

IMPORT_REPORT: Final[Path] = Path("reports/evals/golden-import.json")
"""Where ``import`` writes what it imported, by default."""


@dataclass(
    slots=True, kw_only=True
)  # conventions: allow-mutable-dataclass -- the job reports into it
class ImportedVersion:
    """What importing one pinned version did; implements ingestion's ``JobProgress``."""

    project: str
    """The project's ID."""
    library: str
    """The library ID it was imported under."""
    version: str
    """The version."""
    pinned_commit: str
    """The commit the manifest pins."""
    imported_commit: str = ""
    """The commit the catalog recorded for the version once imported."""
    files: int = 0
    """Files the import processed."""
    seconds: float = 0.0
    """How long the import took."""
    problems: list[tuple[str, str, str]] = field(default_factory=list)
    """``(path, code, reason)`` of every file skipped or imported with a note."""

    async def report(self, *, done: int, total: int) -> None:
        """Keep the number of files.

        Args:
            done: Files processed so far.
            total: Files to process.
        """
        del done
        self.files = total

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        """Keep a problem.

        Args:
            path: The file.
            code: Its kind.
            reason: What happened.
        """
        self.problems.append((path, code.value, reason))

    async def chunking(self, *, chunked: int, reused: int) -> None:
        """Ignore chunking progress.

        Args:
            chunked: Articles cut.
            reused: Articles whose chunks were reused.
        """

    async def parsing(self, *, parsed: int, taken: int) -> None:
        """Ignore parsing progress.

        Args:
            parsed: Articles parsed.
            taken: Articles taken as stored.
        """


async def import_corpus(
    container: Container,
    projects: Sequence[Project],
    repos: dict[str, Path],
    chunking: ChunkingIn | None = None,
) -> list[ImportedVersion]:
    """Import every pinned version of the projects with the real importer, at its commit.

    Args:
        container: The container, running.
        projects: The projects to import.
        repos: The cached repository of each project (``fetch``).
        chunking: How each library cuts its articles; ``None``: the default settings.

    Returns:
        One record per version, with the commit the catalog recorded for it.
    """
    run = importer(container)
    done = []
    for project in projects:
        await container.catalog.create_library(
            CreateLibraryCommand(
                id=project.library,
                title=project.title,
                source_url=repos[project.id].resolve().as_uri(),
                host=HostKind.GIT,
                include_paths=project.include,
                exclude_paths=project.exclude,
            )
        )
        if chunking is not None:
            await container.catalog.set_library_settings(
                SetLibrarySettingsCommand(
                    id=project.library,
                    include_paths=project.include,
                    exclude_paths=project.exclude,
                    chunking=chunking,
                )
            )
        for version in project.versions:
            record = ImportedVersion(
                project=project.id,
                library=project.library,
                version=version.name,
                pinned_commit=version.commit,
            )
            job = Job.queued(
                job_id=JobId(f"golden-{project.id}-{version.name}"),
                kind=IMPORT_JOB,
                library=project.library,
                version=version.name,
                commit_sha=version.commit,
                ref_kind=RefKind.TAG,
                now=SystemClock().now(),
            )
            started = time.perf_counter()
            await run(job, record)
            record.seconds = round(time.perf_counter() - started, 2)
            done.append(record)
        library = await container.catalog.get_library(GetLibraryQuery(id=project.library))
        imported = {v.ref: v.commit_sha for v in library.versions}
        for record in done:
            if record.project == project.id:
                record.imported_commit = imported.get(record.version, "")
    return done


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="golden", description="The golden set over pinned upstream docs (docs/evals.md)."
    )
    parser.add_argument("command", choices=["fetch", "validate", "import"])
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch nothing; use the cache")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="import: the instance's data directory to import into (default: a temporary one)",
    )
    parser.add_argument(
        "--report", type=Path, default=IMPORT_REPORT, help="import: the JSON record of the run"
    )
    return parser


def selected(corpus: Corpus, projects: str) -> list[Project]:
    """Pick the projects asked for.

    Args:
        corpus: The corpus.
        projects: Comma-separated IDs; empty for all.

    Returns:
        The projects, in manifest order.

    Raises:
        SystemExit: An ID is not in the corpus.
    """
    wanted = {p for p in projects.split(",") if p}
    if unknown := wanted - {p.id for p in corpus.projects}:
        message = f"not in the corpus: {', '.join(sorted(unknown))}"
        raise SystemExit(message)
    return [p for p in corpus.projects if not wanted or p.id in wanted]


def _validate(corpus: Corpus, cases_dir: Path, repos: dict[str, Path], projects: str) -> int:
    """Check every case and the review's verdicts (``review.yaml`` beside the cases), print problems.

    Args:
        corpus: The corpus.
        cases_dir: The case files.
        repos: The cached repository of each project.
        projects: Comma-separated IDs whose cases are checked; empty for all.

    Returns:
        The exit code: 0 when every case is valid, else 1.
    """
    cases, problems = load_cases(cases_dir)
    problems += schema_problems(cases, corpus)
    problems += review_file_problems(cases, cases_dir.parent / REVIEW_FILE.name)
    wanted = {p.id for p in selected(corpus, projects)}
    checked = [(project, case) for project, case in cases if project in wanted]
    problems += section_problems(checked, corpus, repos)
    if problems:
        sys.stderr.write(f"{len(problems)} problem(s) in the golden set:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        return 1
    files = len({project for project, _ in cases})
    sys.stdout.write(f"golden set: {len(cases)} cases in {files} files, every section exists\n")
    return 0


def _import(projects: list[Project], repos: dict[str, Path], data_dir: Path, report: Path) -> int:
    """Import the projects, print a summary and write the record.

    Args:
        projects: The projects.
        repos: The cached repository of each.
        data_dir: An empty data directory.
        report: Where the JSON record goes.

    Returns:
        The exit code: 1 when a version's recorded commit is not the pinned one.
    """

    async def go() -> list[ImportedVersion]:
        """Run the container and import.

        Returns:
            The records.
        """
        container = model_free_container(data_dir)
        async with container.running(jobs=False):
            return await import_corpus(container, projects, repos)

    records = asyncio.run(go())
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps([asdict(r) for r in records], indent=2) + "\n", encoding="utf-8")
    wrong = 0
    for r in records:
        ok = r.imported_commit == r.pinned_commit
        wrong += not ok
        sys.stdout.write(
            f"{r.project} {r.version} @ {r.imported_commit or '(none)'}: {r.files} files, "
            f"{len(r.problems)} problems, {r.seconds} s{'' if ok else '  NOT THE PINNED COMMIT'}\n"
        )
    sys.stdout.write(f"record: {report}; data: {data_dir}\n")
    return 1 if wrong else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    if args.command == "fetch":
        for project in projects:
            sys.stdout.write(f"{project.id}: {repos[project.id]}\n")
        return 0
    if args.command == "validate":
        return _validate(corpus, args.cases, repos, args.projects)
    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="exactdocs-golden-"))
    return _import(projects, repos, data_dir, args.report)
