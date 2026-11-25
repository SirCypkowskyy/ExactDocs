"""``just text-bench``: calibrate the text scorer on ExactDocs' own results (#491).

For each chunking configuration, the golden corpus is imported into a model-free instance (the
ingestion benchmark's import), every golden question is asked with BM25 in its project's library,
and each result is kept twice: as ExactDocs returns it (its chunk ID, read back with
``read_chunk``) and as text (the chunk's content). Both are scored, and the report records how
often the text scorer takes the hit and miss decisions chunk-ID scoring takes, at every threshold
of the sweep. It needs no model. See docs/evals.md#scoring-text-results.
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from exactdocs.bootstrap.container import Container
from exactdocs.retrieval.dtos import ReadChunkQuery, SearchDocsQuery
from exactdocs.retrieval.models import RetrievalMode
from retrieval_eval.dataset import Answer, Hit, RetrievalDataset, fingerprint
from retrieval_eval.evaluators import RECALL_AT
from retrieval_eval.fixture import model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import import_corpus, selected
from retrieval_eval.golden_run import held_match
from retrieval_eval.ingestion import tokens
from retrieval_eval.ingestion_cli import CONFIGURATIONS, Configuration, held_headings
from retrieval_eval.retrieval_bench_cli import environment
from retrieval_eval.text_bench import (
    Calibration,
    TextScorerReport,
    calibrate,
    markdown,
    problems,
    scorer_settings,
)
from retrieval_eval.text_match import SectionIndex

REPORT_DIR: Final[Path] = Path("reports/evals")
"""Where ``text-scorer.json`` and ``text-scorer.md`` are written, by default."""
RESULTS_DIR: Final[Path] = Path(__file__).parents[1] / "results"
"""The recorded run in the repository."""
REPORT_NAME: Final[str] = "text-scorer"
"""The report's file name, without the extension."""

type Found = dict[str, tuple[Answer, list[str]]]
"""Each case's answer (by its name), with the text of each hit."""


async def bm25_results(
    container: Container, projects: Sequence[Project], dataset: RetrievalDataset
) -> Found:
    """Ask every question with BM25 in its project's library; keep each hit and its text.

    As ``retrievers.SearchDocsRetriever`` does, each chunk ID is read back, so the version of a
    hit is the chunk's own; its content is the hit's text.

    Args:
        container: The container, running, with the corpus imported.
        projects: The projects.
        dataset: The golden set.

    Returns:
        Each case's answer, by its name, with the content of each hit.
    """
    libraries = {p.id: p for p in projects}
    found: Found = {}
    for case in dataset.cases:
        project = libraries[case.inputs.project or ""]
        started = time.perf_counter()
        result = await container.retrieval.search_docs(
            SearchDocsQuery(
                library=project.library,
                ref=case.inputs.version,
                query=case.inputs.query,
                limit=max(RECALL_AT),
                mode=RetrievalMode.BM25,
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        hits, texts = [], []
        for result_hit in result.results:
            chunk = await container.retrieval.read_chunk(
                ReadChunkQuery(chunk_id=result_hit.chunk_id)
            )
            same_library = chunk.library.casefold() == project.library.casefold()
            hits.append(
                Hit(
                    version=chunk.version if same_library else f"{chunk.library}/{chunk.version}",
                    article=chunk.article_path,
                    heading_path=list(chunk.heading_path),
                    commit_sha=chunk.commit_sha,
                    chunk_id=chunk.chunk_id,
                    tokens=tokens(chunk.content),
                )
            )
            texts.append(chunk.content)
        answer = Answer(
            hits=hits, pinned_commit=project.commit(case.inputs.version), search_ms=elapsed_ms
        )
        found[case.name or ""] = (answer, texts)
    return found


async def run_chunking(
    chunking: Configuration,
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    indexes: Mapping[str, SectionIndex],
    data_dir: Path,
) -> Calibration:
    """Import the corpus at one chunking, run BM25 and calibrate the text scorer on it.

    Args:
        chunking: The chunking configuration.
        projects: The projects.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        indexes: Each project's sections (``SectionIndex.of_project``).
        data_dir: An empty data directory.

    Returns:
        The calibration.

    Raises:
        RuntimeError: A version was not imported at its pinned commit.
    """
    container = model_free_container(data_dir)
    async with container.running(jobs=False):
        records = await import_corpus(container, projects, dict(repos), chunking.chunking)
        if wrong := [r for r in records if r.imported_commit != r.pinned_commit]:
            names = ", ".join(f"{r.project} {r.version}" for r in wrong)
            message = f"not imported at the pinned commit: {names}"
            raise RuntimeError(message)
        matches = held_match(await held_headings(container.engine, projects))
        found = await bm25_results(container, projects, dataset)
    return calibrate(chunking.name, dataset.cases, found, indexes, matches=matches)


async def bench(
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    chunkings: Sequence[Configuration],
) -> TextScorerReport:
    """Calibrate the text scorer at every chunking configuration.

    Args:
        projects: The projects.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        chunkings: The chunking configurations.

    Returns:
        The report.
    """
    indexes = {p.id: SectionIndex.of_project(p, repos[p.id]) for p in projects}
    calibrations = []
    for chunking in chunkings:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="exactdocs-text-bench-") as tmp:
            calibrations.append(
                await run_chunking(chunking, projects, repos, dataset, indexes, Path(tmp) / "data")
            )
        sys.stderr.write(f"{chunking.name}: {time.perf_counter() - started:.0f} s\n")
    return TextScorerReport(
        golden=fingerprint(dataset),
        cases=len(dataset.cases),
        projects=[p.id for p in projects],
        corpus=[
            {"project": p.id, "version": v.name, "commit": v.commit}
            for p in projects
            for v in p.versions
        ],
        environment=environment(),
        scorer=scorer_settings(),
        calibrations=calibrations,
    )


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="text-bench",
        description="Calibrate the text scorer against chunk-ID scoring (docs/evals.md).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch nothing; use the cache")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument(
        "--chunkings",
        default="default",
        help=f"comma-separated chunking configurations, of "
        f"{', '.join(c.name for c in CONFIGURATIONS)} (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help=f"the directory {REPORT_NAME}.json and {REPORT_NAME}.md go to (default: %(default)s)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the calibration.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched or the agreement at
        ``GATED_CHUNKING`` is under ``MIN_AGREEMENT``; 2 for an unknown chunking configuration.
    """
    args = _parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    wanted = [name.strip() for name in args.chunkings.split(",") if name.strip()]
    known = {c.name: c for c in CONFIGURATIONS}
    if unknown := sorted(set(wanted) - set(known)):
        sys.stderr.write(f"unknown chunking configurations: {', '.join(unknown)}\n")
        return 2
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in {p.id for p in projects}]
    report = asyncio.run(bench(projects, repos, golden, [known[name] for name in wanted]))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{REPORT_NAME}.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    summary = markdown(report)
    (args.out / f"{REPORT_NAME}.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as out:
            out.write(summary)
    sys.stdout.write(f"report: {args.out / REPORT_NAME}.json, {args.out / REPORT_NAME}.md\n")
    found = problems(report)
    for problem in found:
        sys.stderr.write(f"problem: {problem}\n")
    return 1 if found else 0
