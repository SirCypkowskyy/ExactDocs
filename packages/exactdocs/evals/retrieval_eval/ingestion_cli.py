"""``just ingestion-bench``: import the golden corpus per chunking configuration and measure it.

Each configuration imports every pinned version with the real importer into its own model-free
instance, then the benchmark reads back the chunks it stored, measures them against the source
at the pinned commit (``ingestion.measure``) and runs the golden set through BM25
(``golden_run``). It writes a JSON report and a Markdown summary, and with ``--check`` fails when
a configuration got worse than a recorded report. See docs/evals.md#the-ingestion-benchmark.
"""

import argparse
import asyncio
import json
import posixpath
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.catalog.dtos import ChunkingIn
from exactdocs.ingestion.models import parse_article
from exactdocs.retrieval.adapters.driven.sqlite import chunks, indexed_manifests, manifest_chunks
from exactdocs.retrieval.constants import CHARS_PER_TOKEN
from fixture_repo import git_bytes
from retrieval_eval.dataset import Hit, RetrievalDataset, fingerprint
from retrieval_eval.fixture import model_free_container
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Corpus,
    PinnedVersion,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import import_corpus, selected
from retrieval_eval.golden_run import golden_retriever, nested_match, run_golden
from retrieval_eval.ingestion import (
    MIN_USEFUL_TOKENS,
    Article,
    Chunk,
    IngestionMetrics,
    Section,
    measure,
)
from retrieval_eval.suite import MAX_RECALL_DROP_POINTS, ModeOutcome

REPORT_DIR: Final[Path] = Path("reports/evals")
"""Where ``ingestion.json`` and ``ingestion.md`` are written, by default."""
RESULTS_DIR: Final[Path] = Path(__file__).parents[1] / "results"
"""The recorded run in the repository, which ``--check`` compares with by default."""
SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed (#349 reads it)."""
_LINK_MODE: Final[str] = "120000"
"""A symlink's tree mode."""
_EPSILON: Final[float] = 1e-9
"""Float noise tolerated when comparing shares."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Configuration:
    """A chunking configuration the benchmark compares."""

    name: str
    """Its short name in the report."""
    about: str
    """What it does, in a sentence."""
    chunking: ChunkingIn
    """The library settings it imports with."""


CONFIGURATIONS: Final[tuple[Configuration, ...]] = (
    Configuration(
        name="default",
        about=(
            "today's default (#381): # to ### start a chunk; one over 4,000 characters is cut "
            "again at deeper headings"
        ),
        chunking=ChunkingIn(),
    ),
    Configuration(
        name="h6",
        about=(
            "every heading starts a chunk; nothing is merged or bounded (the default before #381)"
        ),
        chunking=ChunkingIn(split_level=6, max_chars=None),
    ),
    Configuration(
        name="h2",
        about="only # and ## start a chunk; deeper sections stay inside their parent",
        chunking=ChunkingIn(split_level=2, max_chars=None),
    ),
    Configuration(
        name="merge-400",
        about=(
            "every heading starts a chunk, then one under 400 characters is merged with the "
            "next while the result stays within 4,000"
        ),
        chunking=ChunkingIn(split_level=6, min_chars=400, max_chars=4000),
    ),
)
"""The configurations compared, today's default first. All but ``default`` name every setting,
so a change of the default changes only what ``default`` measures (#381: it measured ``h6``)."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Bm25Result(_Model):
    """BM25 over the golden set, on the chunks a configuration made."""

    answerable: int
    """Cases whose version has an answer (recall and MRR are over these)."""
    recall_at_1: float
    recall_at_5: float
    """The share of answerable cases whose expected section is in the top 5, by the nested rule
    (``golden_run.nested_match``)."""
    recall_at_10: float
    mrr: float
    recall_at_5_exact: float
    """recall@5 when only the exact heading path counts."""
    wrong_version_rate: float
    """Share of cases with a result of another version; must be 0."""
    misses: int
    """Answerable cases whose section is not in the top 10 (nested rule)."""
    errors: list[str]
    """Cases whose search raised."""


class VersionResult(_Model):
    """One pinned version's metrics under a configuration."""

    project: str
    version: str
    library: str
    commit: str
    """The commit it was imported at."""
    metrics: IngestionMetrics


class ConfigurationResult(_Model):
    """One configuration's run."""

    name: str
    about: str
    chunking: dict[str, int | str | None]
    """The library settings (``split_level``, ``min_chars``, ``max_chars``, ``chunker``)."""
    totals: IngestionMetrics
    """The metrics over every version of every project."""
    bm25: Bm25Result
    versions: list[VersionResult]
    """Per project and version, in corpus order."""


class IngestionReport(_Model):
    """The benchmark's JSON report (``ingestion.json``), documented in docs/evals.md."""

    schema_version: int = SCHEMA_VERSION
    golden: str
    """The golden set's fingerprint (``dataset.fingerprint``)."""
    cases: int
    """Cases run through BM25."""
    projects: list[str]
    """The projects measured."""
    min_useful_tokens: int = MIN_USEFUL_TOKENS
    chars_per_token: int = CHARS_PER_TOKEN
    configurations: list[ConfigurationResult]


def article_sources(repo: Path, commit: str, project: Project) -> dict[str, str | None]:
    """Read the body of every file a project selects at a commit, as the repository has it.

    A symlink is followed one hop to a file of the same commit (what a reader of the repository
    sees); one that leads anywhere else is unreadable. The front matter is left out the way
    ``parse_article`` leaves it out, so a body is what the chunks of the article should add up to.

    Args:
        repo: The cached repository.
        commit: The pinned commit.
        project: The project (its docs paths).

    Returns:
        Each selected path's body, or ``None`` when it cannot be read.
    """
    listing = git_bytes("ls-tree", "-r", "-z", commit, cwd=repo).split(b"\0")
    entries: dict[str, tuple[str, str]] = {}
    for line in filter(None, listing):
        meta, _, path = line.partition(b"\t")
        mode, _, sha = meta.decode().split(" ")
        entries[path.decode(errors="replace")] = (mode, sha)
    selection = project.selection
    bodies: dict[str, str | None] = {}
    for path, (mode, blob) in entries.items():
        if not selection.selects(path):
            continue
        sha = blob
        if mode == _LINK_MODE:
            target = git_bytes("cat-file", "blob", blob, cwd=repo).decode(errors="replace")
            found = entries.get(posixpath.normpath(posixpath.join(posixpath.dirname(path), target)))
            if found is None or found[0] == _LINK_MODE:
                bodies[path] = None
                continue
            sha = found[1]
        text = git_bytes("cat-file", "blob", sha, cwd=repo).decode("utf-8-sig", errors="replace")
        bodies[path] = parse_article(path, text).body
    return bodies


async def stored_chunks(engine: AsyncEngine, library: str, version: str) -> dict[str, list[Chunk]]:
    """Read the chunks the importer stored for a version, by article, in order.

    Args:
        engine: The instance's database.
        library: The library ID.
        version: The version.

    Returns:
        Each article's chunks; an article with none is absent.
    """
    newest = (
        select(indexed_manifests.c.manifest_id)
        .where(  # library IDs are stored lowercased
            func.lower(indexed_manifests.c.version_id) == f"{library}/{version}".lower()
        )
        .order_by(indexed_manifests.c.indexed_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    statement = (
        select(
            manifest_chunks.c.article_path,
            chunks.c.heading_path,
            chunks.c.content,
            chunks.c.headings,
        )
        .join(
            chunks,
            and_(
                chunks.c.blob_sha == manifest_chunks.c.blob_sha,
                chunks.c.config_hash == manifest_chunks.c.config_hash,
                chunks.c.position == manifest_chunks.c.position,
            ),
        )
        .where(manifest_chunks.c.manifest_id == newest)
        .order_by(manifest_chunks.c.article_path, manifest_chunks.c.position)
    )
    found: dict[str, list[Chunk]] = {}
    async with engine.connect() as connection:
        for path, heading_path, content, headings in await connection.execute(statement):
            found.setdefault(path, []).append(
                Chunk(
                    heading_path=tuple(json.loads(heading_path)),
                    content=content,
                    headings=tuple(tuple(h[0]) for h in json.loads(headings or "[]")),
                )
            )
    return found


def article_key(project: str, version: str, path: str) -> str:
    """Name an article in a report.

    Args:
        project: The project's ID.
        version: The version.
        path: The article's path.

    Returns:
        ``<project> <version>:<path>``.
    """
    return f"{project} {version}:{path}"


def expected_sections(dataset: RetrievalDataset) -> list[Section]:
    """Every section the golden set expects, keyed like the benchmark's articles.

    Args:
        dataset: The golden set.

    Returns:
        ``(article key, heading path)`` for each expected hit.
    """
    return [
        (article_key(case.inputs.project or "", hit.version, hit.article), tuple(hit.heading_path))
        for case in dataset.cases
        for hit in (case.expected_output.hits if case.expected_output else [])
    ]


def bm25_result(nested: ModeOutcome, exact: ModeOutcome) -> Bm25Result:
    """Keep what the report shows of two BM25 runs.

    Args:
        nested: The run scored by the nested rule.
        exact: The run scored by the exact heading path.

    Returns:
        The result.

    Raises:
        ValueError: A run has no metrics (it did not run).
    """
    m, e = nested.metrics, exact.metrics
    if m is None or e is None:
        message = "a golden run that ran has metrics"
        raise ValueError(message)
    return Bm25Result(
        answerable=m.answerable,
        recall_at_1=m.recall_at_1,
        recall_at_5=m.recall_at_5,
        recall_at_10=m.recall_at_10,
        mrr=m.mrr,
        recall_at_5_exact=e.recall_at_5,
        wrong_version_rate=m.wrong_version_rate,
        misses=len(nested.misses),
        errors=nested.errors,
    )


type _Held = dict[tuple[str, str, tuple[str, ...]], set[tuple[str, ...]]]
"""The heading paths each ``(commit, article, heading path)``'s chunks hold."""


async def _measure_version(
    engine: AsyncEngine,
    project: Project,
    pinned: PinnedVersion,
    bodies: Mapping[str, str | None],
    expected: Sequence[Section],
    held: _Held,
) -> tuple[VersionResult, list[Article]]:
    """Read a version's stored chunks and measure them.

    Args:
        engine: The instance's database.
        project: The project.
        pinned: The version.
        bodies: Its articles' bodies (``article_sources``).
        expected: Every expected section (those of other versions are left out).
        held: Gets the heading paths each of its chunks holds, for ``nested_match``.

    Returns:
        The version's result, and its articles.
    """
    stored = await stored_chunks(engine, project.library, pinned.name)
    articles = [
        Article(
            key=article_key(project.id, pinned.name, path),
            source=bodies.get(path),
            chunks=tuple(stored.get(path, ())),
        )
        for path in sorted(set(bodies) | set(stored))
    ]
    for path, cut in stored.items():
        for chunk in cut:
            key = (pinned.commit, path, chunk.heading_path)
            held.setdefault(key, set()).update((chunk.heading_path, *chunk.headings))
    keys = {a.key for a in articles}
    result = VersionResult(
        project=project.id,
        version=pinned.name,
        library=project.library,
        commit=pinned.commit,
        metrics=measure(articles, [s for s in expected if s[0] in keys]),
    )
    return result, articles


async def run_configuration(
    configuration: Configuration,
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    sources: Mapping[tuple[str, str], Mapping[str, str | None]],
    dataset: RetrievalDataset,
    data_dir: Path,
) -> ConfigurationResult:
    """Import the corpus with one configuration, measure the chunks and run BM25 over them.

    Args:
        configuration: The chunking configuration.
        projects: The projects.
        repos: The cached repository of each project.
        sources: Each ``(project, version)``'s article bodies (``article_sources``).
        dataset: The golden set, restricted to ``projects``.
        data_dir: An empty data directory.

    Returns:
        The configuration's result.

    Raises:
        RuntimeError: A version was not imported at its pinned commit.
    """
    expected = expected_sections(dataset)
    container = model_free_container(data_dir)
    async with container.running(jobs=False):
        records = await import_corpus(container, projects, dict(repos), configuration.chunking)
        if wrong := [r for r in records if r.imported_commit != r.pinned_commit]:
            message = ", ".join(f"{r.project} {r.version}" for r in wrong)
            msg = f"not imported at the pinned commit: {message}"
            raise RuntimeError(msg)
        versions: list[VersionResult] = []
        everything: list[Article] = []
        held: _Held = {}
        for project in projects:
            for pinned in project.versions:
                result, articles = await _measure_version(
                    container.engine,
                    project,
                    pinned,
                    sources[project.id, pinned.name],
                    expected,
                    held,
                )
                versions.append(result)
                everything.extend(articles)

        def holds(hit: Hit) -> frozenset[tuple[str, ...]]:
            """The heading paths a hit's chunk holds.

            Args:
                hit: A returned hit.

            Returns:
                Every heading path of the chunks with its commit, article and heading path.
            """
            return frozenset(
                held.get((hit.commit_sha or "", hit.article, tuple(hit.heading_path)), ())
            )

        retriever = golden_retriever(container.retrieval, Corpus(projects=list(projects)), "bm25")
        nested = await run_golden(dataset, retriever, matches=nested_match(holds))
        exact = await run_golden(dataset, retriever)
    return ConfigurationResult(
        name=configuration.name,
        about=configuration.about,
        chunking=configuration.chunking.model_dump(),
        totals=measure(everything, expected),
        bm25=bm25_result(nested, exact),
        versions=versions,
    )


_GATED_UP: Final[tuple[str, ...]] = (
    "articles_without_chunks",
    "cuts_in_code_fence",
    "cuts_in_table",
    "cuts_in_list",
    "lost_chars",
    "empty_heading_paths",
    "wrong_heading_paths",
    "headings_missed",
    "headings_extra",
)
"""Totals that may not rise against the recorded report."""


def check(report: IngestionReport, recorded: IngestionReport) -> list[str]:
    """Compare a run with a recorded one: what got worse in a configuration both measured.

    Coverage may not drop, the integrity and heading counts in ``_GATED_UP`` may not rise, and
    BM25's recall@5 may not drop more than ``MAX_RECALL_DROP_POINTS``. The two must have run the
    same golden set on the same projects, or nothing is comparable.

    Args:
        report: This run.
        recorded: The recorded run (``results/ingestion.json``).

    Returns:
        One problem per regression; empty when none.
    """
    if (report.golden, report.projects) != (recorded.golden, recorded.projects):
        return [
            (
                f"the recorded report measured golden set {recorded.golden} on "
                f"{', '.join(recorded.projects)}, this run {report.golden} on "
                f"{', '.join(report.projects)}: record this run (docs/evals.md)"
            )
        ]
    before = {c.name: c for c in recorded.configurations}
    problems = []
    for now in report.configurations:
        then = before.get(now.name)
        if then is None:
            continue
        name, a, b = now.name, now.totals, then.totals
        if a.coverage < b.coverage - _EPSILON:
            problems.append(f"{name}: coverage {a.coverage} is below the recorded {b.coverage}")
        for field in _GATED_UP:
            mine, theirs = getattr(a, field), getattr(b, field)
            if mine > theirs:
                problems.append(f"{name}: {field} rose from {theirs} to {mine}")
        drop = round((then.bm25.recall_at_5 - now.bm25.recall_at_5) * 100, 2)
        if drop > MAX_RECALL_DROP_POINTS + _EPSILON:
            problems.append(
                f"{name}: BM25 recall@5 dropped {drop} points (at most {MAX_RECALL_DROP_POINTS})"
            )
    return problems


def _pct(value: float) -> str:
    """A share as a percentage.

    Returns:
        ``12.3%``.
    """
    return f"{value * 100:.1f}%"


def markdown(report: IngestionReport) -> str:
    """Render the report as a Markdown summary.

    Args:
        report: The run.

    Returns:
        The comparison table, then per-version tables and the missing sections.
    """
    lines = [
        "# Ingestion benchmark",
        "",
        (
            f"The golden corpus ({', '.join(report.projects)}; every pinned version) imported with "
            f"each chunking configuration; BM25 over the golden set's {report.cases} cases "
            f"(`{report.golden}`). Tokens are estimated at {report.chars_per_token} characters; "
            f"a small chunk is under {report.min_useful_tokens} tokens. Definitions: "
            "docs/evals.md#the-ingestion-benchmark."
        ),
        "",
        (
            "| configuration | coverage | held | cut fence / table / list | lost chars "
            "| tokens p50 / p95 / max | small | multi-top | empty / wrong path "
            "| headings missed / extra | BM25 recall@5 (exact) | MRR |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report.configurations:
        t, b = c.totals, c.bm25
        held = f"{t.held_sections}/{t.expected_sections}"
        lines.append(
            f"| `{c.name}` | {_pct(t.coverage)} | {held} "
            f"| {t.cuts_in_code_fence} / {t.cuts_in_table} / {t.cuts_in_list} "
            f"| {t.lost_chars} of {t.source_chars} "
            f"| {t.tokens_p50} / {t.tokens_p95} / {t.tokens_max} | {_pct(t.small_share)} "
            f"| {_pct(t.multi_top_share)} | {t.empty_heading_paths} / {t.wrong_heading_paths} "
            f"| {t.headings_missed} / {t.headings_extra} "
            f"| {_pct(b.recall_at_5)} ({_pct(b.recall_at_5_exact)}) | {b.mrr:.3f} |"
        )
    lines.append("")
    lines.extend(f"- `{c.name}`: {c.about}." for c in report.configurations)
    for c in report.configurations:
        lines.extend(
            [
                "",
                f"## `{c.name}` per version",
                "",
                (
                    "| project | version | articles (no chunk) | chunks | coverage | cut fence "
                    "| lost chars | tokens p50 / p95 / max | small | empty / wrong path "
                    "| headings missed / extra | no H1 | includes | MkDocs blocks as code |"
                ),
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for v in c.versions:
            m = v.metrics
            lines.append(
                f"| {v.project} | {v.version} | {m.articles} ({m.articles_without_chunks}) "
                f"| {m.chunks} | {_pct(m.coverage)} | {m.cuts_in_code_fence} | {m.lost_chars} "
                f"| {m.tokens_p50} / {m.tokens_p95} / {m.tokens_max} | {_pct(m.small_share)} "
                f"| {m.empty_heading_paths} / {m.wrong_heading_paths} "
                f"| {m.headings_missed} / {m.headings_extra} | {m.articles_without_h1} "
                f"| {m.unexpanded_includes} | {m.mkdocs_blocks_as_code} |"
            )
        if c.totals.missing_sections:
            lines.extend(["", f"Sections that start no chunk under `{c.name}`:", ""])
            lines.extend(f"- {s}" for s in c.totals.missing_sections)
    default = report.configurations[0].totals if report.configurations else None
    if default is not None:
        lines.extend(["", f"## Examples (`{report.configurations[0].name}`)", ""])
        lines.extend(f"- wrong heading path: {e}" for e in default.wrong_heading_examples)
        for metric, keys in default.examples.items():
            lines.append(f"- {metric}: " + ", ".join(keys))
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="ingestion-bench",
        description="Chunking configurations measured on the golden corpus (docs/evals.md).",
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
        "--configs",
        default="",
        help=f"comma-separated configurations (default: all: "
        f"{', '.join(c.name for c in CONFIGURATIONS)})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help="the directory ingestion.json and ingestion.md go to (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        nargs="?",
        type=Path,
        const=RESULTS_DIR / "ingestion.json",
        help="fail when a configuration got worse than this recorded report "
        "(default: the one in the repository)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    return parser


def _configurations(names: str) -> list[Configuration]:
    """Pick the configurations asked for.

    Args:
        names: Comma-separated names; empty for all.

    Returns:
        The configurations, in ``CONFIGURATIONS`` order.

    Raises:
        SystemExit: A name is unknown.
    """
    wanted = {n for n in names.split(",") if n}
    if unknown := wanted - {c.name for c in CONFIGURATIONS}:
        message = f"unknown configurations: {', '.join(sorted(unknown))}"
        raise SystemExit(message)
    return [c for c in CONFIGURATIONS if not wanted or c.name in wanted]


async def bench(
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    configurations: Sequence[Configuration],
) -> IngestionReport:
    """Run every configuration on the projects.

    Args:
        projects: The projects to measure.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        configurations: The configurations.

    Returns:
        The report.
    """
    sources = {
        (p.id, v.name): article_sources(repos[p.id], v.commit, p)
        for p in projects
        for v in p.versions
    }
    results = []
    for configuration in configurations:
        with tempfile.TemporaryDirectory(prefix="exactdocs-ingestion-") as tmp:
            results.append(
                await run_configuration(
                    configuration, projects, repos, sources, dataset, Path(tmp) / "data"
                )
            )
    return IngestionReport(
        golden=fingerprint(dataset),
        cases=len(dataset.cases),
        projects=[p.id for p in projects],
        configurations=results,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched or ``--check`` finds a regression.
    """
    args = _parser().parse_args(argv)
    corpus = load_corpus(args.corpus)
    projects = selected(corpus, args.projects)
    configurations = _configurations(args.configs)
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    wanted = {p.id for p in projects}
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in wanted]
    report = asyncio.run(bench(projects, repos, golden, configurations))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ingestion.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    summary = markdown(report)
    (args.out / "ingestion.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    sys.stdout.write(f"report: {args.out / 'ingestion.json'}, {args.out / 'ingestion.md'}\n")
    if args.check is None:
        return 0
    recorded = IngestionReport.model_validate_json(args.check.read_text(encoding="utf-8"))
    problems = check(report, recorded)
    for problem in problems:
        sys.stderr.write(f"regression: {problem}\n")
    return 1 if problems else 0
