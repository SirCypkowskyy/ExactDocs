"""``just retrieval-grid``: every cell of a grid file on the golden set, resumable per cell (#494).

App cells run through the retrieval benchmark (``retrieval_bench_cli.bench``, one configuration
at one chunking), eval-only cells and baselines through ``grid``; each finished cell is written
to ``<out>/cells/`` at once, and a later run with the same cell, golden set and projects reuses
it. The report is the retrieval benchmark's (intervals, the paired test of every cell against the
default its budget ships with), plus the text scorer's context numbers and the ingestion
metrics (#346) of each eval-only chunker. See docs/evals.md#the-retrieval-grid.
"""

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from array import array
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import starmap
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from exactdocs.bootstrap.constants import DEFAULT_LOCAL_RERANKER, LOCAL_PROFILE
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.local_models import LocalModels, model_folder, read_marker
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.ingestion.models import ChunkingConfig, ParsedArticle, parse_article
from exactdocs.retrieval.adapters.driven.local_models import LocalEmbeddingModels
from exactdocs.retrieval.constants import LOCAL_EMBEDDING_BATCH
from exactdocs.retrieval.models import EmbeddedTexts, ProviderKind, ProviderProfile
from exactdocs.retrieval.ports.driven import AgentReads, Embeddings
from retrieval_eval.dataset import RetrievalDataset, fingerprint
from retrieval_eval.golden import (
    CASES_DIR,
    CORPUS_FILE,
    Project,
    default_cache_dir,
    fetch,
    load_corpus,
    load_golden,
)
from retrieval_eval.golden_cli import selected
from retrieval_eval.grid import (
    GRID_FILE,
    Cell,
    Grid,
    Passage,
    PassageIndex,
    grep,
    load_grid,
    passages_of,
)
from retrieval_eval.ingestion import Article, IngestionMetrics, measure
from retrieval_eval.ingestion_cli import (
    CONFIGURATIONS,
    article_files,
    article_key,
    expected_sections,
)
from retrieval_eval.retrieval_bench import (
    BUDGETS,
    CUT_BUDGETS,
    TOKEN_BUDGETS,
    ConfigResult,
    ModelInfo,
    Recommendation,
    RetrievalBenchReport,
    Versus,
    against_defaults,
    markdown,
    paired_cell,
    paired_tests,
    run_problems,
)
from retrieval_eval.retrieval_bench_cli import (
    LOCAL_EMBEDDINGS,
    Builder,
    bench,
    environment,
    matrix,
)
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.text_bench import TextAnswer, TextMetrics, TextResult, text_row
from retrieval_eval.text_match import SectionIndex

SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed."""
REPORT_DIR: Final[Path] = Path("reports/evals/grid")
"""Where the report and the finished cells go, by default."""
REPORT_NAME: Final[str] = "retrieval-grid"
"""The report's file name, without the extension."""
_SLUG: Final[re.Pattern[str]] = re.compile(r"[^\w.+@-]")
"""What a cell's file name replaces in its name."""

CACHE_SLICE: Final[int] = 256
"""Texts embedded, and kept in the embedding cache, together: an interrupted cell loses at most
one slice."""

type EmbeddingsFor = Callable[[str], Awaitable[Embeddings | str]]
"""Loads an eval-only cell's embedding model by name, or says why it cannot."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class CellRecord(_Model):
    """One finished cell, as ``<out>/cells/`` keeps it."""

    key: str
    """The cell's settings, the golden set and the projects, hashed: a stored cell is reused
    only under the same key."""
    result: ConfigResult
    """Its result (without the paired test, made when the report is put together)."""
    text: TextMetrics | None = None
    """An eval-only cell's text numbers (context tokens, facts found)."""
    ingestion: IngestionMetrics | None = None
    """An eval-only cell's chunks, measured as the ingestion benchmark measures the importer's."""


class GridReport(_Model):
    """The grid's JSON report (``retrieval-grid.json``), documented in docs/evals.md."""

    schema_version: int = SCHEMA_VERSION
    grid: str
    """The grid file's cells and defaults, hashed."""
    bench: RetrievalBenchReport
    """Every cell's result in the retrieval benchmark's report, ``recommendations`` holding the
    default each budget was tested against."""
    text: dict[str, TextMetrics] = {}
    """By cell: the text scorer's context numbers of the cells scored from text."""
    ingestion: dict[str, IngestionMetrics] = {}
    """By chunker: the ingestion metrics of each eval-only chunker (cuts in code and tables)."""
    resumed: list[str] = []
    """Cells taken from an earlier run instead of run again."""
    versus_control: dict[str, Versus] = {}
    """By cell: the paired tests against the cell it is a variant of (``Cell.against``, #575)."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- counts reuse
class CachedEmbeddings:
    """Implements ``Embeddings``: keeps the vectors of every slice of texts on disk (#575).

    Cells that embed the same texts (the same chunks, prefixed alike) embed them once, and a
    cell interrupted while embedding takes up where it stopped. A slice is kept under the hash
    of the model and its texts, with the tokens it cost and the seconds it took; ``reused``
    adds up the seconds of the slices taken from the cache, so a cell's index cost still says
    what embedding took.
    """

    inner: Embeddings
    """The model."""
    folder: Path
    """Where the slices are kept."""
    reused: float = 0.0
    """Seconds the slices taken from the cache took when they were embedded."""

    @property
    def name(self) -> str:
        """The model as the role names it."""
        return self.inner.name

    async def dimensions(self) -> int:
        """Say how many numbers each vector holds.

        Returns:
            The model's dimensions.
        """
        return await self.inner.dimensions()

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        """Embed texts slice by slice, each slice from the cache when it holds it.

        Args:
            texts: The texts.

        Returns:
            One vector per text, in order, and the tokens every slice cost.
        """
        vectors: list[tuple[float, ...]] = []
        tokens = requests = 0
        self.folder.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(texts), CACHE_SLICE):
            part = texts[start : start + CACHE_SLICE]
            digest = hashlib.sha256("\0".join([self.inner.name, *part]).encode()).hexdigest()
            meta, data = self.folder / f"{digest[:32]}.json", self.folder / f"{digest[:32]}.bin"
            if meta.is_file() and data.is_file():
                kept: dict[str, float] = json.loads(meta.read_text(encoding="utf-8"))
                flat = array("d")
                flat.frombytes(data.read_bytes())
                self.reused += kept["seconds"]
            else:
                started = time.perf_counter()
                embedded = await self.inner.embed_documents(part)
                kept = {
                    "tokens": embedded.input_tokens,
                    "requests": embedded.requests,
                    "seconds": round(time.perf_counter() - started, 3),
                    "dimensions": len(embedded.vectors[0]) if embedded.vectors else 0,
                }
                flat = array("d", (x for v in embedded.vectors for x in v))
                data.write_bytes(flat.tobytes())
                meta.write_text(json.dumps(kept), encoding="utf-8")  # last: the slice is whole
            size = int(kept["dimensions"]) or 1
            vectors.extend(tuple(flat[i : i + size]) for i in range(0, len(flat), size))
            tokens += int(kept["tokens"])
            requests += int(kept["requests"])
        return EmbeddedTexts(vectors=tuple(vectors), input_tokens=tokens, requests=requests)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        """Embed a question (never cached: the latency is measured).

        Args:
            text: The question.

        Returns:
            Its vector.
        """
        return await self.inner.embed_query(text)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Corpus:
    """The pinned versions' files, read once for every eval-only cell."""

    articles: Mapping[tuple[str, str], tuple[ParsedArticle, ...]]
    """Each ``(project, version)``'s parsed articles."""
    raw: Mapping[tuple[str, str], Mapping[str, str]]
    """Each ``(project, version)``'s files as they are, by path (the grep baseline's)."""
    sections: Mapping[str, SectionIndex]
    """The text scorer's index of each project."""


def _container(settings: Settings, *, agent_reads: AgentReads | None = None) -> Container:
    """Build an app cell's container as an instance with these settings would.

    Args:
        settings: The settings.
        agent_reads: Records the agentic explorer's reads.

    Returns:
        The container.
    """
    return Container.build(settings, agent_reads=agent_reads)


def _read(projects: Sequence[Project], repos: Mapping[str, Path]) -> _Corpus:
    """Read every selected file of every pinned version.

    Args:
        projects: The projects.
        repos: The cached repository of each.

    Returns:
        The files, parsed and raw, and the text scorer's indexes.
    """
    articles: dict[tuple[str, str], tuple[ParsedArticle, ...]] = {}
    raw: dict[tuple[str, str], dict[str, str]] = {}
    for project in projects:
        for pinned in project.versions:
            files = article_files(repos[project.id], pinned.commit, project)
            texts = {
                path: data.decode("utf-8-sig", errors="replace")
                for path, data in sorted(files.items())
                if data is not None
            }
            raw[project.id, pinned.name] = texts
            articles[project.id, pinned.name] = tuple(starmap(parse_article, texts.items()))
    return _Corpus(
        articles=articles,
        raw=raw,
        sections={p.id: SectionIndex.of_project(p, repos[p.id]) for p in projects},
    )


def _chunking(name: str) -> ChunkingConfig:
    """Map a chunking configuration of the ingestion benchmark to the chunker's settings.

    Args:
        name: Its name.

    Returns:
        The settings the importer cuts with.

    Raises:
        ValueError: No such configuration.
    """
    found = next((c.chunking for c in CONFIGURATIONS if c.name == name), None)
    if found is None:
        message = f"unknown chunking configuration {name!r}"
        raise ValueError(message)
    return ChunkingConfig(
        split_depth=found.split_level,
        min_chars=found.min_chars,
        max_chars=found.max_chars,
        chunker=found.chunker,
    )


def _cut(
    cell: Cell, corpus: _Corpus, dataset: RetrievalDataset
) -> tuple[list[Passage], IngestionMetrics]:
    """Cut every pinned version as an eval-only cell does, and measure the cut (#346).

    Args:
        cell: The cell.
        corpus: The pinned versions' files.
        dataset: The golden set (the sections it expects).

    Returns:
        Every passage, and the ingestion metrics of the chunks.
    """
    chunking = _chunking(cell.chunking)
    passages: list[Passage] = []
    articles = []
    for (project, version), parsed in corpus.articles.items():
        for article in parsed:
            own = passages_of(cell, project, version, article, chunking)
            passages += own
            articles.append(
                Article(
                    key=article_key(project, version, article.path),
                    source=article.body,
                    chunks=tuple(p.chunk for p in own),
                )
            )
    return passages, measure(articles, expected_sections(dataset))


async def run_eval_cell(
    cell: Cell, corpus: _Corpus, dataset: RetrievalDataset, embeddings_for: EmbeddingsFor
) -> CellRecord:
    """Run an eval-only cell or baseline and score it from its text.

    Args:
        cell: The cell.
        corpus: The pinned versions' files.
        dataset: The golden set.
        embeddings_for: Loads its embedding model.

    Returns:
        Its record (``key`` left empty).
    """
    result = ConfigResult(
        configuration=cell.name,
        chunking=cell.chunker,
        budget=cell.budget,
        mode=cell.search or "",
        status="ran",
        settings=cell.model_dump(mode="json", exclude_defaults=True),
        models=[]
        if cell.embedding is None
        else [ModelInfo(role="embedding", model=cell.embedding)],
    )
    answers: dict[str, TextAnswer] = {}
    ingestion = index = None
    if cell.search == "grep":
        for case in dataset.cases:
            q = case.inputs
            started = time.perf_counter()
            texts = grep(corpus.raw[q.project or "", q.version], q.query)
            ms = round((time.perf_counter() - started) * 1000, 3)
            answers[case.name or ""] = TextAnswer(texts=texts, search_ms=ms)
    else:
        embeddings = None
        if cell.embedding is not None:
            loaded = await embeddings_for(cell.embedding)
            if isinstance(loaded, str):
                return CellRecord(
                    key="",
                    result=result.model_copy(update={"status": "unavailable", "reason": loaded}),
                )
            embeddings = loaded
        passages, ingestion = _cut(cell, corpus, dataset)
        before = embeddings.reused if isinstance(embeddings, CachedEmbeddings) else 0.0
        index = await PassageIndex.build(cell, passages, embeddings)
        if isinstance(embeddings, CachedEmbeddings):  # what embedding took, cached or not
            seconds = round(index.cost.seconds + embeddings.reused - before, 1)
            index = replace(index, cost=index.cost.model_copy(update={"seconds": seconds}))
        try:
            for case in dataset.cases:
                q = case.inputs
                answers[case.name or ""] = await index.answer(q.project or "", q.version, q.query)
        finally:
            index.close()
    rows = [
        text_row(case, answers[case.name or ""], corpus.sections[case.inputs.project or ""])
        for case in dataset.cases
    ]
    scored = TextResult.of(cell.name, rows)
    result = result.model_copy(
        update={
            "index": None if index is None else index.cost,
            "misses": sum(1 for r in rows if r.row.answerable and r.row.rank is None),
            # shortcut: searched within the version asked only, so a "wrong version" here is a
            # text the scorer places only in another version (one crossing sections); it shows
            # in the rate and does not fail the run. Upgrade if a cell ever searches several.
        }
    ).with_breakdowns([r.row for r in rows])
    return CellRecord(key="", result=result, text=scored.metrics, ingestion=ingestion)


def _cached(embeddings_for: EmbeddingsFor, folder: Path) -> EmbeddingsFor:
    """Load each model once for the run, with its vectors kept in ``folder`` (``CachedEmbeddings``).

    Args:
        embeddings_for: Loads a model.
        folder: Where the vectors are kept, across runs.

    Returns:
        The loader.
    """
    loaded: dict[str, Embeddings | str] = {}

    async def load(model: str) -> Embeddings | str:
        """Load a model, or reuse the one loaded before.

        Args:
            model: Its name.

        Returns:
            The model, its vectors cached, or why it cannot run.
        """
        if model not in loaded:
            found = await embeddings_for(model)
            loaded[model] = (
                found if isinstance(found, str) else CachedEmbeddings(inner=found, folder=folder)
            )
        return loaded[model]

    return load


def _key(cell: Cell, golden: str, projects: Sequence[Project]) -> str:
    """Hash what a cell's result depends on in the grid.

    Args:
        cell: The cell.
        golden: The golden set's fingerprint.
        projects: The projects (and their pinned commits).

    Returns:
        ``sha256:`` and 16 hex digits.
    """
    pinned = [(p.id, [(v.name, v.commit) for v in p.versions]) for p in projects]
    # what does not change the result is left out, and so are settings added since cells were
    # first kept while they hold their default, so a stored cell keeps its key
    unset = {"neighbours"} if cell.neighbours is None else set()
    text = f"{cell.model_dump_json(exclude={'against', *unset})}|{golden}|{pinned}"
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def _defaults(grid: Grid, results: Mapping[str, ConfigResult]) -> list[Recommendation]:
    """The default each budget is tested against, as the grid declares it.

    Args:
        grid: The grid.
        results: Each cell's result, by cell name.

    Returns:
        One per budget: the declared cell, or why there is none.
    """
    picks = []
    for budget in BUDGETS:
        name = grid.defaults.get(budget)
        found = results.get(name or "")
        if name is None or found is None or found.metrics is None:
            why = "no default declared" if name is None else f"`{name}` did not run"
            picks.append(
                Recommendation(
                    budget=budget,
                    configuration=None,
                    chunking=None,
                    usd_per_1000_questions=None,
                    reasons=[why],
                )
            )
            continue
        picks.append(
            Recommendation(
                budget=budget,
                configuration=found.configuration,
                chunking=found.chunking,
                usd_per_1000_questions=round(found.metrics.usd_per_question * 1000, 4),
                reasons=[f"declared in the grid (`{name}`): what ExactDocs ships for this budget"],
            )
        )
    return picks


async def run_grid(
    grid: Grid,
    projects: Sequence[Project],
    repos: Mapping[str, Path],
    dataset: RetrievalDataset,
    *,
    out: Path,
    hosted: AiSettings,
    models_dir: Path,
    embeddings_for: EmbeddingsFor,
    local_reranker: str = DEFAULT_LOCAL_RERANKER,
    allow_providers: bool = False,
    build: Builder = _container,
    fresh: bool = False,
) -> GridReport:
    """Run every cell of a grid, reusing the cells an earlier run finished.

    Args:
        grid: The grid.
        projects: The projects.
        repos: The cached repository of each.
        dataset: The golden set, restricted to ``projects``.
        out: Where the finished cells are kept (``cells/``).
        hosted: The environment's ``ai`` settings (app cells on hosted models).
        models_dir: Where the local models were pulled.
        embeddings_for: Loads an eval-only cell's embedding model.
        local_reranker: The local cross-encoder of app cells.
        allow_providers: Run app cells on hosted models (by hand only).
        build: Builds an app cell's container.
        fresh: Run every cell again.

    Returns:
        The report.

    Raises:
        ValueError: A cell names no configuration of the retrieval benchmark, or no chunking
            configuration.
    """
    configs = {c.name: c for c in matrix(LOCAL_EMBEDDINGS)}
    if unknown := sorted({c.app for c in grid.cells if c.app and c.app not in configs}):
        message = f"app cells that name no retrieval-benchmark configuration: {', '.join(unknown)}"
        raise ValueError(message)
    for cell in grid.cells:
        _chunking(cell.chunking)
    golden = fingerprint(dataset)
    store = out / "cells"
    store.mkdir(parents=True, exist_ok=True)
    embeddings_for = _cached(embeddings_for, out / "embeddings")
    corpus: _Corpus | None = None
    records: dict[str, CellRecord] = {}
    resumed = []
    for cell in grid.cells:
        key = _key(cell, golden, projects)
        path = store / f"{_SLUG.sub('_', cell.name)}.json"
        if not fresh and path.is_file():
            kept = CellRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if kept.key == key:
                records[cell.name] = kept
                resumed.append(cell.name)
                continue
        started = time.perf_counter()
        if cell.app is not None:
            ran = await bench(
                projects,
                repos,
                dataset,
                [next(c for c in CONFIGURATIONS if c.name == cell.chunking)],
                [configs[cell.app]],
                hosted=hosted,
                models_dir=models_dir,
                local_reranker=local_reranker,
                allow_providers=allow_providers,
                build=build,
            )
            record = CellRecord(
                key=key, result=ran.results[0].model_copy(update={"versus_default": None})
            )
        else:
            corpus = corpus or _read(projects, repos)
            record = (await run_eval_cell(cell, corpus, dataset, embeddings_for)).model_copy(
                update={"key": key}
            )
        path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        records[cell.name] = record
        sys.stderr.write(
            f"{cell.name}: {record.result.status} ({time.perf_counter() - started:.0f} s)\n"
        )
    return _report(grid, records, projects, dataset, resumed)


def _report(
    grid: Grid,
    records: Mapping[str, CellRecord],
    projects: Sequence[Project],
    dataset: RetrievalDataset,
    resumed: Sequence[str],
) -> GridReport:
    """Put the finished cells together and test each against its budget's default.

    Args:
        grid: The grid.
        records: Each cell's record, by name.
        projects: The projects.
        dataset: The golden set.
        resumed: The cells an earlier run finished.

    Returns:
        The report.
    """
    results = {name: r.result for name, r in records.items()}
    picks = _defaults(grid, results)
    chunkers = {}
    for cell in grid.cells:
        about = next((c.about for c in CONFIGURATIONS if c.name == cell.chunker), None)
        chunkers.setdefault(cell.chunker, about or _about(cell))
    report = RetrievalBenchReport(
        golden=fingerprint(dataset),
        cases=len(dataset.cases),
        projects=[p.id for p in projects],
        corpus=[
            {"project": p.id, "version": v.name, "commit": v.commit}
            for p in projects
            for v in p.versions
        ],
        environment=environment(),
        chunkings=[{"name": name, "about": about} for name, about in chunkers.items()],
        results=against_defaults(list(results.values()), picks, DEFAULT_STATS),
        recommendations=picks,
        statistics=DEFAULT_STATS,
    )
    return GridReport(
        grid="sha256:" + hashlib.sha256(grid.model_dump_json().encode()).hexdigest()[:16],
        bench=report,
        text={name: r.text for name, r in records.items() if r.text is not None},
        ingestion={
            cell.chunker: found
            for cell in grid.cells
            if (found := records[cell.name].ingestion) is not None
        },
        resumed=list(resumed),
        versus_control=_versus_controls(grid, results),
    )


def _versus_controls(grid: Grid, results: Mapping[str, ConfigResult]) -> dict[str, Versus]:
    """Test every variant against the cell it is a variant of, on the cases both answered.

    Args:
        grid: The grid.
        results: Each cell's result, by cell name.

    Returns:
        The tests, by variant; a variant whose control did not run (or kept no rows) has none.
    """
    tested = {}
    for cell in grid.cells:
        control, variant = results.get(cell.against or ""), results.get(cell.name)
        if control is None or variant is None or control.metrics is None:
            continue
        if variant.metrics is None or not (tests := paired_tests(control, variant, DEFAULT_STATS)):
            continue
        tested[cell.name] = Versus(
            configuration=cell.against or "", chunking=control.chunking, tests=tests
        )  # the control by its cell name
    return tested


def _about(cell: Cell) -> str:
    """Say what an eval-only chunker does.

    Args:
        cell: A cell that uses it.

    Returns:
        A sentence.
    """
    if cell.window is not None:
        return (
            f"eval-only: windows of whole lines of about {cell.window} estimated tokens, "
            f"{cell.overlap} shared with the window before; headings, code and tables ignored"
        )
    return "the raw files, searched as they are"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def grid_markdown(report: GridReport) -> str:
    """Render the report: the retrieval benchmark's summary, then context and cuts.

    Args:
        report: The run.

    Returns:
        The Markdown.
    """
    summary = markdown(report.bench)
    summary = summary.replace("# Retrieval benchmark", "# Retrieval grid", 1)
    summary = summary.replace("## Recommended defaults", "## Defaults tested against", 1)
    lines = [
        "",
        "## Text and context",
        "",
        "The cells scored from their text (#491): what they return, in estimated tokens.",
        "",
        "| cell | results/q | context tokens/q | tokens to first hit | facts found |",
        "|---|---|---|---|---|",
    ]
    for name, m in report.text.items():
        to_hit = "-" if m.tokens_to_first_hit is None else f"{m.tokens_to_first_hit:.0f}"
        lines.append(
            f"| `{name}` | {m.results_per_question:.1f} | {m.context_tokens_per_question:.0f} "
            f"| {to_hit} | {_pct(m.facts_found_rate)} |"
        )
    lines += [
        "",
        "## Eval-only chunkers",
        "",
        "The ingestion benchmark's metrics (#346) of each chunker the grid cuts with itself.",
        "",
        (
            "Sections held: of the sections the golden set expects, those that start a chunk "
            "or are a heading inside one. (Coverage and lost characters say little of windows: "
            "a window starts mid-section, and overlapping windows are not found in order.)"
        ),
        "",
        "| chunker | chunks | tokens p50 / p95 | cuts in code / table / list | sections held |",
        "|---|---|---|---|---|",
    ]
    for name, m in report.ingestion.items():
        held = m.held_sections / m.expected_sections if m.expected_sections else None
        lines.append(
            f"| `{name}` | {m.chunks} | {m.tokens_p50} / {m.tokens_p95} "
            f"| {m.cuts_in_code_fence} / {m.cuts_in_table} / {m.cuts_in_list} | {_pct(held)} |"
        )
    lines += _controls_section(report)
    if report.resumed:
        lines += ["", f"Taken from an earlier run: {', '.join(f'`{n}`' for n in report.resumed)}."]
    return summary + "\n".join(lines) + "\n"


_CONTROL_TESTS: Final[tuple[tuple[str, str], ...]] = (
    ("recall_at_1", "recall@1"),
    ("recall_at_5", "recall@5"),
    ("recall_at_10", "recall@10"),
    ("mrr", "MRR"),
    ("ndcg_at_10", "nDCG@10"),
    *((name, f"within {budget:,}") for name, budget in TOKEN_BUDGETS.items()),
    *((name, f"cut at {budget:,}") for name, budget in CUT_BUDGETS.items()),
)
"""The metrics a variant is tested on against its control, and their labels."""


def _controls_section(report: GridReport) -> list[str]:
    """The paired tests of every variant against the cell it is a variant of.

    Args:
        report: The run.

    Returns:
        The lines; none when no cell names a control.
    """
    if not report.versus_control:
        return []
    lines = [
        "",
        "## Against each variant's control",
        "",
        (
            "Each variant against the cell it varies (`against` in the grid file), on the "
            "answerable cases both answered: the difference (recall in points, MRR and nDCG@10 "
            "as scores), its paired bootstrap interval and the p-value (McNemar's test, mid-p, "
            "for recall; a sign-flip permutation test for MRR and nDCG@10). **Bold**: "
            "significant at 5%."
        ),
        "",
        "| cell | against | " + " | ".join(label for _, label in _CONTROL_TESTS) + " |",
        "|---|---|" + "---|" * len(_CONTROL_TESTS),
    ]
    for name, versus in report.versus_control.items():
        cells = [
            paired_cell(versus.tests.get(metric), points=metric not in {"mrr", "ndcg_at_10"})
            for metric, _ in _CONTROL_TESTS
        ]
        lines.append(f"| `{name}` | `{versus.configuration}` | " + " | ".join(cells) + " |")
    return lines


def local_embeddings(local: LocalModels) -> EmbeddingsFor:
    """Load eval-only cells' embedding models from ``exactdocs models pull``'s directory.

    Args:
        local: The local models (closed by the caller).

    Returns:
        The loader.
    """

    async def embeddings_for(model: str) -> Embeddings | str:
        """Load a pulled model.

        Args:
            model: Its name.

        Returns:
            The model, or why it cannot run.
        """
        marker = read_marker(model_folder(local.models_dir, model))
        if marker is None or marker.model != model:
            return f"{model} is not in {local.models_dir}: run `exactdocs models pull {model}`"
        profile = ProviderProfile(name=LOCAL_PROFILE, kind=ProviderKind.LOCAL)
        handle = await local.embedder(profile, model)
        return LocalEmbeddingModels().bind(
            handle,
            name=f"{LOCAL_PROFILE}:{model}",
            dimensions=None,
            batch_size=LOCAL_EMBEDDING_BATCH,
        )

    return embeddings_for


def _parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="retrieval-grid",
        description="Every cell of a grid file measured on the golden set (docs/evals.md).",
    )
    parser.add_argument("--grid", type=Path, default=GRID_FILE, help="the grid file")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where the fetched projects are kept (default: %(default)s)",
    )
    parser.add_argument("--offline", action="store_true", help="fetch nothing; use the cache")
    parser.add_argument("--projects", default="", help="comma-separated project IDs (default: all)")
    parser.add_argument(
        "--cells",
        default="*",
        help="comma-separated cell names or shell patterns (default: every one; the defaults, and "
        "the control of each cell picked, always run)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="where `exactdocs models pull` put the local models (default: EXACTDOCS_MODELS_DIR, "
        "else the data directory's models/)",
    )
    parser.add_argument(
        "--allow-providers",
        action="store_true",
        help="run app cells on the hosted models EXACTDOCS_AI__... configures (by hand only)",
    )
    parser.add_argument("--fresh", action="store_true", help="run every cell again")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORT_DIR,
        help="the report and the finished cells (cells/) go here (default: %(default)s)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the grid.

    Args:
        argv: The arguments; ``sys.argv`` by default.

    Returns:
        The exit code: 1 when the corpus cannot be fetched or a cell got a result of another
        version or failed; 2 for a grid that names unknown configurations.
    """
    args = _parser().parse_args(argv)
    grid = load_grid(args.grid)
    patterns = [p.strip() for p in args.cells.split(",") if p.strip()]
    wanted = set(grid.defaults.values())
    picked = [c for c in grid.cells if any(fnmatch.fnmatchcase(c.name, p) for p in patterns)]
    wanted |= {c.against for c in picked if c.against}  # a variant runs with its control
    grid = grid.model_copy(
        update={
            "cells": [
                c
                for c in grid.cells
                if c.name in wanted or any(fnmatch.fnmatchcase(c.name, p) for p in patterns)
            ]
        }
    )
    projects = selected(load_corpus(args.corpus), args.projects)
    try:
        repos = {p.id: fetch(p, args.cache_dir, offline=args.offline) for p in projects}
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    golden = load_golden(args.cases)
    golden.cases = [c for c in golden.cases if c.inputs.project in {p.id for p in projects}]
    environment_settings = Settings()
    models_dir = args.models_dir or environment_settings.effective_models_dir
    local = LocalModels(models_dir=models_dir)
    try:
        report = asyncio.run(
            run_grid(
                grid,
                projects,
                repos,
                golden,
                out=args.out,
                hosted=environment_settings.ai,
                models_dir=models_dir,
                embeddings_for=local_embeddings(local),
                allow_providers=args.allow_providers,
                fresh=args.fresh,
            )
        )
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    finally:
        local.close()
    (args.out / f"{REPORT_NAME}.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    summary = grid_markdown(report)
    (args.out / f"{REPORT_NAME}.md").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(step_summary).open("a", encoding="utf-8") as out:
            out.write(summary)
    problems = run_problems(report.bench)
    for problem in problems:
        sys.stderr.write(f"problem: {problem}\n")
    return 1 if problems else 0
