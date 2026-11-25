"""Grounded Docs on the golden set: its responses, the report and the comparison (#492).

Grounded Docs ([arabold/docs-mcp-server](https://github.com/arabold/docs-mcp-server), MIT) is a
self-hosted documentation server that indexes each library version separately and searches it
with full-text search, and vector search too when an embedding model is configured. The run
(``grounded_docs_cli``, ``just grounded-bench``) indexes every pinned version of the golden corpus
into a pinned release of it, asks every golden question through its ``search_docs`` MCP tool with
the case's library and version, and scores the text it returns with the text scorer (#491). This
module holds what needs no process: reading ``search_docs``' response into results, the report,
the paired tests against ExactDocs (#489) and the Markdown. See docs/evals/grounded-docs.md.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from exactdocs.bootstrap.constants import DEFAULT_LOCAL_EMBEDDING
from retrieval_eval.retrieval_bench import (
    CUT_BUDGETS,
    NDCG_AT,
    TOKEN_BUDGETS,
    BenchMetrics,
    Budget,
    ConfigResult,
    PairedTest,
    Row,
    paired_tests,
)
from retrieval_eval.stats import DEFAULT as DEFAULT_STATS
from retrieval_eval.stats import Interval, StatsMethod, interval
from retrieval_eval.text_bench import TextMetrics, TextResult, TextRow, results_table

SCHEMA_VERSION: Final[int] = 1
"""The JSON report's layout; bumped when a field is renamed or removed."""
PACKAGE: Final[str] = "@arabold/docs-mcp-server"
"""Grounded Docs' npm package."""
VERSION: Final[str] = "3.4.1"
"""The release measured: pinned, never ``latest``."""
INTEGRITY: Final[str] = (
    "sha512-IZQKYKs3p939Tt7N14JDLdukWzDmjOyp1QLARdpFZljh25eAT7cfY0Krtajg0UPpzJOIsHWpp0UBslioskmNzA=="
)
"""The npm registry's integrity hash of ``VERSION``'s tarball: the install is refused without it."""
SEARCH_TOOL: Final[str] = "search_docs"
"""The MCP tool a question goes through."""
TOP_K: Final[int] = NDCG_AT
"""Results asked for per question: the cut-off ExactDocs is measured at (recall@10, nDCG@10)."""
EMBEDDING_MODEL: Final[str] = DEFAULT_LOCAL_EMBEDDING
"""The embedding model of the vector configuration: ExactDocs' best local configuration's."""
NO_RESULTS: Final[str] = "No results found for "
"""How ``search_docs`` starts a response with no result."""
_RESULT: Final[re.Pattern[str]] = re.compile(r"\n-{60}\nResult (\d+): ([^\n]*)\n\n")
"""The line ``search_docs`` puts before each result: a rule of 60 dashes, then its rank and URL."""
TEXT_BASELINE: Final[str] = "ExactDocs bm25 @ default"
"""The ExactDocs result every configuration is tested against, scored from its text in the run."""
RECORDED: Final[tuple[str, ...]] = ("bm25", f"hybrid:{EMBEDDING_MODEL.split('/')[-1]}")
"""ExactDocs configurations at ``default`` taken from the recorded retrieval benchmark run
(``results/retrieval.json``, scored by chunk ID) for the comparison."""
RECORDED_CHUNKING: Final[str] = "default"
"""The chunking those recorded configurations are taken at: what ExactDocs ships."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class Configuration(_Model):
    """One way of running Grounded Docs."""

    name: str
    """Its name in the report."""
    embedding_model: str | None
    """``DOCS_MCP_EMBEDDING_MODEL``, served by the local endpoint; None: full-text search only."""
    about: str
    """What it is."""


CONFIGURATIONS: Final[tuple[Configuration, ...]] = (
    Configuration(
        name="full-text",
        embedding_model=None,
        about=(
            "no embedding model: full-text search only, what it does when no provider "
            "credentials are set"
        ),
    ),
    Configuration(
        name=EMBEDDING_MODEL.split("/")[-1],
        embedding_model=EMBEDDING_MODEL,
        about=(
            f"full-text and vector search, {EMBEDDING_MODEL} served locally through an "
            "OpenAI-compatible endpoint (OPENAI_API_BASE)"
        ),
    ),
)
"""The configurations measured: as its documentation sets them up, nothing tuned."""


class Found(_Model):
    """One result of ``search_docs``."""

    url: str
    """The page it comes from (a ``file://`` URL for a local folder)."""
    content: str
    """Its text: the matching passage with the context Grounded Docs assembles around it."""


def split_results(text: str) -> list[Found]:
    """Read ``search_docs``' response into its results, in its order.

    The tool returns one text: each result is a rule of 60 dashes, ``Result <n>: <url>``, a blank
    line and the result's content. A rule inside a result's content is told apart by its number,
    which must be the next one.

    Args:
        text: The tool's response.

    Returns:
        The results; none for "No results found".
    """
    if text.startswith(NO_RESULTS):
        return []
    marks = []
    for match in _RESULT.finditer(text):
        if int(match[1]) == len(marks) + 1:
            marks.append(match)
    found = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        found.append(Found(url=mark[2], content=text[mark.end() : end].removesuffix("\n")))
    return found


class Embedded(_Model):
    """What the embedding endpoint did during one step of the run."""

    requests: int
    """Requests answered."""
    texts: int
    """Texts embedded."""
    tokens: int
    """Their tokens, before the model truncates a text to its 512."""
    seconds: float
    """Time spent embedding."""
    abandoned: int
    """Requests whose client gave up before the answer (and may have sent them again)."""


class VersionIndex(_Model):
    """One pinned version as Grounded Docs indexed it."""

    project: str
    """The golden project."""
    version: str
    """The pinned version (also Grounded Docs' version name)."""
    commit: str
    """Its commit."""
    library: str
    """Grounded Docs' library name."""
    seconds: float
    """Wall time of the ``scrape`` command (the process start, reading, splitting, embedding)."""
    offered: int
    """Articles offered: the files the ExactDocs importer takes at that commit."""
    indexed: int
    """Pages Grounded Docs stored."""
    chunks: int
    """Chunks it stored."""
    embedded: int
    """Of those, chunks with a vector."""
    max_depth: int
    """The crawl depth passed (its default, or the depth of the deepest article when deeper)."""
    max_pages: int
    """The page limit passed (its default, or the files and folders offered when more)."""
    not_indexed: list[str]
    """Offered articles it stored no page for (its default exclusions, unreadable files)."""
    embedding: Embedded | None = None
    """What the embedding endpoint embedded while this version was indexed; None without one."""


class EmbeddingInfo(_Model):
    """The embedding model behind the vector configuration."""

    model: str
    """Its name."""
    revision: str | None
    """The Hub commit it was pulled at."""
    dimensions: int | None
    """Its vector size."""
    stored_dimensions: int | None
    """The size Grounded Docs stores its vectors at (its table of known models; a shorter vector
    is padded with zeros, which changes no distance between two vectors)."""
    served_by: str
    """What served it."""
    indexing: Embedded
    """Embedding the corpus: every version's ``VersionIndex.embedding``, summed."""
    questions: Embedded
    """Embedding the questions."""


class Paired(_Model):
    """A configuration tested against an ExactDocs result on the answerable cases both answered."""

    against: str
    """The ExactDocs result."""
    scored_by: str
    """How the ExactDocs result was scored: ``text`` (this run) or ``chunk ID`` (recorded run)."""
    tests: dict[str, PairedTest]
    """By metric: McNemar for recall@1, @5 and @10, a permutation test for MRR and nDCG@10."""


class RunResult(_Model):
    """One configuration of Grounded Docs on the golden set."""

    configuration: str
    """Its name."""
    about: str
    """What it is."""
    settings: dict[str, Any]
    """Grounded Docs' configuration in effect (``docs-mcp-server config``), machine paths
    replaced by ``<store>`` and ``<corpus>``."""
    variables: dict[str, str]
    """The environment variables the run set for it (the endpoint's dummy key named, no secret)."""
    embedding: EmbeddingInfo | None
    """The embedding model; None for full-text search only."""
    indexing: list[VersionIndex]
    """Every pinned version, as it was indexed."""
    index_seconds: float
    """Indexing every version, in all."""
    index_bytes: int
    """The size of its data directory (the SQLite database) once every version was indexed."""
    result: TextResult
    """Its metrics, overall, by question kind and by project, scored from the text."""
    context_tokens_interval: Interval | None
    """The 95% interval of the context tokens per question."""
    rows: list[TextRow]
    """Every case's row, by case name: the intervals and paired tests come from them."""
    versus: list[Paired]
    """Paired tests against ExactDocs."""
    errors: list[str]
    """Questions whose search failed (scored as an empty answer)."""
    cases_not_indexed: list[str]
    """Answerable cases none of whose listed articles it indexed: out of its reach, since recall
    counts a hit on any section a case lists (#501)."""


class Baseline(_Model):
    """ExactDocs' BM25 at ``default``, asked and scored from its text in the same run."""

    name: str
    """``TEXT_BASELINE``."""
    result: TextResult
    """Its metrics, scored from the text, as Grounded Docs' are."""
    context_tokens_interval: Interval | None
    """The 95% interval of the context tokens per question."""
    rows: list[TextRow]
    """Every case's row, by case name."""


class Recorded(_Model):
    """An ExactDocs configuration from the recorded retrieval benchmark run (scored by chunk ID)."""

    configuration: str
    """Its name."""
    chunking: str
    """Its chunking."""
    metrics: BenchMetrics
    """Its metrics, with their intervals, as recorded."""
    environment: dict[str, str]
    """That run's commit and machine."""


class GroundedDocsReport(_Model):
    """The run's JSON report (``grounded-docs.json``), documented in docs/evals/grounded-docs.md."""

    schema_version: int = SCHEMA_VERSION
    golden: str
    """The golden set's fingerprint."""
    cases: int
    projects: list[str]
    corpus: list[dict[str, str]]
    """Every pinned version: ``project``, ``version``, ``commit``."""
    date: str
    """When the run ended (UTC, ISO 8601)."""
    tool: dict[str, str]
    """Grounded Docs: ``name``, ``package``, ``version``, ``integrity``, ``node``, ``search``
    (the MCP tool), ``top_k``."""
    environment: dict[str, str]
    """The ExactDocs commit, Python, platform and CPUs (as the retrieval benchmark records them)."""
    scorer: dict[str, Any]
    """The text scorer's settings."""
    statistics: StatsMethod
    """How the intervals and paired tests were computed."""
    baseline: Baseline
    """ExactDocs' BM25 at ``default``, scored the same way."""
    recorded: list[Recorded]
    """ExactDocs configurations of the recorded retrieval benchmark run, for comparison."""
    runs: list[RunResult]
    """One per Grounded Docs configuration."""


def tokens_interval(
    rows: Sequence[TextRow], method: StatsMethod = DEFAULT_STATS
) -> Interval | None:
    """The 95% interval of the context tokens per question.

    Args:
        rows: Every case's row.
        method: The seed, resamples and confidence.

    Returns:
        The interval; None for no case.
    """
    ordered = sorted(rows, key=lambda r: r.case)  # the same draws as the other metrics
    return interval([float(r.context_tokens) for r in ordered], method, digits=1)


def _as_result(name: str, rows: Sequence[Row]) -> ConfigResult:
    """Wrap rows as a benchmark result, to pair them with ``retrieval_bench.paired_tests``.

    Args:
        name: The result's name.
        rows: Its rows.

    Returns:
        A result holding only the rows.
    """
    return ConfigResult(
        configuration=name,
        chunking="",
        budget=Budget.NONE,
        mode="",
        status="ran",
        rows=list(rows),
    )


def paired(
    against: str,
    scored_by: str,
    theirs: Sequence[Row],
    mine: Sequence[Row],
    method: StatsMethod = DEFAULT_STATS,
) -> Paired:
    """Test a configuration's rows against an ExactDocs result's, case by case.

    Args:
        against: The ExactDocs result's name.
        scored_by: How it was scored.
        theirs: Its rows.
        mine: The configuration's rows.
        method: The seed, resamples, confidence and significance level.

    Returns:
        The tests (``retrieval_bench.paired_tests``).
    """
    tests = paired_tests(_as_result(against, theirs), _as_result("mine", mine), method)
    return Paired(against=against, scored_by=scored_by, tests=tests)


def cases_not_indexed(
    rows: Sequence[TextRow],
    articles: Mapping[str, Collection[tuple[str, str]]],
    indexing: Sequence[VersionIndex],
) -> list[str]:
    """Name the answerable cases none of whose listed articles was indexed.

    Recall counts the first hit on any section a case lists, each part and its alternatives
    alike (#501, ``evaluators.first_rank``), so a case is out of reach only when every article
    it lists was left out.

    Args:
        rows: Every case's row.
        articles: The ``(version, article)`` of every section each answerable case lists, by name.
        indexing: Every version as it was indexed.

    Returns:
        The cases' names, in row order.
    """
    missing = {(v.version, path) for v in indexing for path in v.not_indexed}
    return [r.case for r in rows if (listed := articles.get(r.case)) and set(listed) <= missing]


# ---------------------------------------------------------------- the summary


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _with(value: float | None, spread: Interval | None) -> str:
    """A rate with its interval, in percent.

    Args:
        value: The rate.
        spread: Its interval.

    Returns:
        ``81.7% (77.2-85.8)``, or the rate alone.
    """
    if value is None:
        return "-"
    if spread is None or spread.low == spread.high:
        return _pct(value)
    return f"{_pct(value)} ({spread.low * 100:.1f}-{spread.high * 100:.1f})"


def _ratio(value: float, spread: Interval | None) -> str:
    """A mean in [0, 1] with its interval, to three decimals.

    Args:
        value: The mean.
        spread: Its interval.

    Returns:
        ``0.734 (0.69-0.77)``, or the mean alone.
    """
    if spread is None or spread.low == spread.high:
        return f"{value:.3f}"
    return f"{value:.3f} ({spread.low:.3f}-{spread.high:.3f})"


def _count(value: float, spread: Interval | None) -> str:
    if spread is None or spread.low == spread.high:
        return f"{value:,.0f}"
    return f"{value:,.0f} ({spread.low:,.0f}-{spread.high:,.0f})"


def _line(
    name: str,
    scored_by: str,
    metrics: BenchMetrics,
    text: TextMetrics | None,
    tokens: Interval | None,
) -> str:
    """One line of the comparison table.

    Args:
        name: The tool and configuration.
        scored_by: ``text`` or ``chunk ID``.
        metrics: Its benchmark metrics, with their intervals.
        text: What only the text tells; None for a result scored by chunk ID.
        tokens: The interval of the context tokens per question.

    Returns:
        The table's line.
    """
    spread = metrics.intervals
    neutral = _pct(text.version_neutral_share) if text else "-"
    context_tokens = (
        text.context_tokens_per_question if text else metrics.context_tokens_per_question
    )
    context = (
        "-"
        if context_tokens is None
        else _count(context_tokens, tokens or spread.get("context_tokens_per_question"))
    )
    to_hit = text.tokens_to_first_hit if text else metrics.tokens_to_first_hit
    return (
        f"| {name} | {scored_by} | {_with(metrics.recall_at_1, spread.get('recall_at_1'))} "
        f"| {_with(metrics.recall_at_5, spread.get('recall_at_5'))} "
        f"| {_with(metrics.recall_at_10, spread.get('recall_at_10'))} "
        f"| {_ratio(metrics.mrr, spread.get('mrr'))} "
        f"| {_ratio(metrics.ndcg_at_10, spread.get('ndcg_at_10'))} "
        f"| {_with(metrics.wrong_version_rate, spread.get('wrong_version_rate'))} "
        f"| {neutral} | {context} | {'-' if to_hit is None else f'{to_hit:,.0f}'} |"
    )


def _results(report: GroundedDocsReport) -> list[tuple[str, str, BenchMetrics]]:
    """Every result of the report: the baseline, the recorded ExactDocs runs, Grounded Docs.

    Args:
        report: The run.

    Returns:
        ``(name, scored by, metrics)`` of each, in the order of the comparison table.
    """
    return [
        (report.baseline.name, "text", report.baseline.result.metrics.metrics),
        *(
            (f"ExactDocs {r.configuration} @ {r.chunking}", "chunk ID", r.metrics)
            for r in report.recorded
        ),
        *(
            (f"Grounded Docs {run.configuration}", "text", run.result.metrics.metrics)
            for run in report.runs
        ),
    ]


def budget_table(report: GroundedDocsReport) -> list[str]:
    """Recall within each token budget, read whole and cut at the budget, of every result (#575).

    Args:
        report: The run.

    Returns:
        The lines; none for a report recorded before the budgets.
    """
    results = _results(report)
    if all(m.recall_at_1k_tokens is None for _, _, m in results):
        return []
    budgets = [f"{b:,}" for b in TOKEN_BUDGETS.values()]
    lines = [
        (
            "| Tool and configuration | Scored by | context tokens / question "
            "| tokens to first hit | "
            + " | ".join(f"within {b}, whole results" for b in budgets)
            + " | "
            + " | ".join(f"within {b}, text cut" for b in budgets)
            + " |"
        ),
        "|---|---|---|---|" + "---|" * 2 * len(budgets),
    ]
    for name, scored_by, m in results:
        spread = m.intervals
        context = (
            "-"
            if m.context_tokens_per_question is None
            else _count(m.context_tokens_per_question, spread.get("context_tokens_per_question"))
        )
        to_hit = "-" if m.tokens_to_first_hit is None else f"{m.tokens_to_first_hit:,.0f}"
        cells = [_with(getattr(m, b), spread.get(b)) for b in (*TOKEN_BUDGETS, *CUT_BUDGETS)]
        lines.append(f"| {name} | {scored_by} | {context} | {to_hit} | " + " | ".join(cells) + " |")
    return lines


def comparison(report: GroundedDocsReport) -> list[str]:
    """The table of every result: ExactDocs' and Grounded Docs' configurations.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    lines = [
        (
            "| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR "
            "| nDCG@10 | wrong version | version-neutral | context tokens / question "
            "| tokens to first hit |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    base = report.baseline
    lines.append(
        _line(
            base.name,
            "text",
            base.result.metrics.metrics,
            base.result.metrics,
            base.context_tokens_interval,
        )
    )
    lines.extend(
        _line(f"ExactDocs {r.configuration} @ {r.chunking}", "chunk ID", r.metrics, None, None)
        for r in report.recorded
    )
    lines.extend(
        _line(
            f"Grounded Docs {run.configuration}",
            "text",
            run.result.metrics.metrics,
            run.result.metrics,
            run.context_tokens_interval,
        )
        for run in report.runs
    )
    return lines


_METRICS: Final[tuple[tuple[str, str], ...]] = (
    ("recall_at_1", "recall@1"),
    ("recall_at_5", "recall@5"),
    ("recall_at_10", "recall@10"),
    ("mrr", "MRR"),
    ("ndcg_at_10", "nDCG@10"),
)
"""The metrics the paired tests cover, and their labels."""
_BUDGET_METRICS: Final[tuple[tuple[str, str], ...]] = (
    *((name, f"within {budget:,}, whole results") for name, budget in TOKEN_BUDGETS.items()),
    *((name, f"within {budget:,}, text cut") for name, budget in CUT_BUDGETS.items()),
)
"""The recall within a token budget the paired tests cover (#575), and their labels."""


def _difference(name: str, test: PairedTest) -> str:
    """A paired test's difference, interval, p-value and verdict.

    Args:
        name: The metric's field.
        test: The test.

    Returns:
        ``-12.4 points (-17.6 to -7.1), p 0.0001, significant``.
    """
    rate = name.startswith("recall")
    scale, unit = (100, " points") if rate else (1, "")
    digits = 1 if rate else 3
    low, high = test.interval.low * scale, test.interval.high * scale
    verdict = "significant" if test.significant else "not significant"
    return (
        f"{test.difference * scale:+.{digits}f}{unit} ({low:+.{digits}f} to {high:+.{digits}f}), "
        f"p {test.p_value:.3g}, {verdict}"
    )


def tests_table(report: GroundedDocsReport, metrics: Sequence[tuple[str, str]]) -> list[str]:
    """The paired tests of every configuration against ExactDocs.

    Args:
        report: The run.
        metrics: The metrics shown, with their labels.

    Returns:
        The lines: one per configuration and ExactDocs result, one column per metric; none when
        no test covers any of the metrics.
    """
    if not any(name in v.tests for run in report.runs for v in run.versus for name, _ in metrics):
        return []
    lines = [
        "| Grounded Docs | against | " + " | ".join(label for _, label in metrics) + " |",
        "|---|---|" + "---|" * len(metrics),
    ]
    for run in report.runs:
        for versus in run.versus:
            cells = " | ".join(
                _difference(name, versus.tests[name]) if name in versus.tests else "-"
                for name, _ in metrics
            )
            lines.append(
                f"| {run.configuration} | {versus.against} ({versus.scored_by}) | {cells} |"
            )
    return lines


def by_kind(report: GroundedDocsReport) -> list[str]:
    """recall@5 per question kind, ExactDocs' baseline and every configuration.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    results = [(report.baseline.name, report.baseline.result)] + [
        (f"Grounded Docs {run.configuration}", run.result) for run in report.runs
    ]
    kinds = sorted({k for _, r in results for k in r.by_kind})
    lines = [
        "| Kind | " + " | ".join(name for name, _ in results) + " |",
        "|---|" + "---|" * len(results),
    ]
    for kind in kinds:
        cells = []
        for _, r in results:
            m = r.by_kind.get(kind)
            cells.append(
                "-" if m is None or not m.metrics.answerable else _pct(m.metrics.recall_at_5)
            )
        lines.append(f"| `{kind}` | " + " | ".join(cells) + " |")
    return lines


def by_project(report: GroundedDocsReport) -> list[str]:
    """recall@5 and context tokens per project, ExactDocs' baseline and every configuration.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    results = [(report.baseline.name, report.baseline.result)] + [
        (f"Grounded Docs {run.configuration}", run.result) for run in report.runs
    ]
    lines = [
        "| Project | " + " | ".join(name for name, _ in results) + " |",
        "|---|" + "---|" * len(results),
    ]
    for project in report.projects:
        cells = []
        for _, r in results:
            m = r.by_project.get(project)
            cells.append(
                "-"
                if m is None
                else f"{_pct(m.metrics.recall_at_5)}, {m.context_tokens_per_question:,.0f} tokens"
            )
        lines.append(f"| {project} | " + " | ".join(cells) + " |")
    return lines


def _mb(size: int) -> str:
    return f"{size / 1_000_000:,.1f} MB"


def indexing(report: GroundedDocsReport) -> list[str]:
    """What indexing took, per configuration and per pinned version.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    lines = [
        (
            "| Configuration | Indexing time | Index size | Articles offered | Pages indexed "
            "| Chunks | Chunks with a vector |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for run in report.runs:
        offered = sum(v.offered for v in run.indexing)
        pages = sum(v.indexed for v in run.indexing)
        chunks = sum(v.chunks for v in run.indexing)
        embedded = sum(v.embedded for v in run.indexing)
        lines.append(
            f"| {run.configuration} | {run.index_seconds:,.0f} s | {_mb(run.index_bytes)} "
            f"| {offered:,} | {pages:,} | {chunks:,} | {embedded:,} |"
        )
    names = [run.configuration for run in report.runs]
    lines += [
        "",
        "| Project | Version | Articles offered | Pages indexed | Chunks | Depth / pages passed | "
        + " | ".join(f"Seconds, {n}" for n in names)
        + " |",
        "|---|---|---|---|---|---|" + "---|" * len(names),
    ]
    if report.runs:
        first = report.runs[0]
        seconds = {
            (v.project, v.version): [
                next(
                    (
                        w.seconds
                        for w in run.indexing
                        if w.version == v.version and w.project == v.project
                    ),
                    None,
                )
                for run in report.runs
            ]
            for v in first.indexing
        }
        for v in first.indexing:
            cells = " | ".join(
                "-" if s is None else f"{s:,.1f}" for s in seconds[v.project, v.version]
            )
            lines.append(
                f"| {v.project} | {v.version} | {v.offered} | {v.indexed} | {v.chunks:,} "
                f"| {v.max_depth} / {v.max_pages} | {cells} |"
            )
    return lines


def not_indexed(report: GroundedDocsReport) -> list[str]:
    """The articles Grounded Docs did not index, and the cases they put out of its reach.

    Args:
        report: The run.

    Returns:
        The lines.
    """
    if not report.runs:
        return []
    first = report.runs[0]
    lines = []
    for v in first.indexing:
        if v.not_indexed:
            shown = ", ".join(f"`{p}`" for p in v.not_indexed)
            lines.append(f"- {v.project} {v.version}: {shown}")
    if not lines:
        lines = ["- none: every article the importer takes was indexed"]
    cases = first.cases_not_indexed
    lines.append(
        f"- answerable cases that list no other article: {len(cases)}"
        + (f" ({', '.join(cases)})" if cases else "")
    )
    return lines


def run_block(report: GroundedDocsReport) -> str:
    """The run: Grounded Docs' version and settings, the date, the machine and the corpus.

    Args:
        report: The run.

    Returns:
        The Markdown.
    """
    tool, env = report.tool, report.environment
    lines = [
        (
            f"- Grounded Docs {tool.get('version', '?')} (npm `{tool.get('package', '?')}`, "
            f"integrity `{tool.get('integrity', '?')[:23]}...`), Node.js "
            f"{tool.get('node', '?')}; questions through its `{tool.get('search', '?')}` MCP tool "
            f"with the case's library and version, {tool.get('top_k', '?')} results."
        ),
        (
            f"- Run {report.date}: golden set {report.cases} cases, fingerprint "
            f"`{report.golden}`, projects {', '.join(report.projects)}; ExactDocs commit "
            f"`{env.get('exactdocs_commit', '?')}`, Python {env.get('python', '?')}, "
            f"{env.get('platform', '?')}, {env.get('cpus', '?')} CPUs."
        ),
    ]
    for run in report.runs:
        changed = ", ".join(f"`{k}={v}`" for k, v in sorted(run.variables.items()))
        lines.append(f"- `{run.configuration}`: {run.about}. Environment: {changed or 'none'}.")
        if run.embedding:
            e, i, q = run.embedding, run.embedding.indexing, run.embedding.questions
            lines.append(
                f"  Embedding model {e.model} (revision `{(e.revision or '?')[:12]}`, "
                f"{e.dimensions} dimensions, stored at {e.stored_dimensions}), served by "
                f"{e.served_by}: indexing {i.texts:,} texts, {i.tokens:,} tokens, "
                f"{i.seconds:,.0f} s of embedding ({i.abandoned} requests abandoned by the "
                f"client); questions {q.texts:,} texts, {q.seconds:,.0f} s."
            )
    return "\n".join(lines)


def _budget_block(report: GroundedDocsReport) -> list[str]:
    """Recall within a token budget and its paired tests, when the report has them (#575).

    Args:
        report: The run.

    Returns:
        The lines, ending with a blank one; none for a report recorded before the budgets.
    """
    table = budget_table(report)
    if not table:
        return []
    budgets = [f"{b:,}" for b in TOKEN_BUDGETS.values()]
    return [
        "### Within a token budget",
        "",
        (
            f"Recall within the first {', '.join(budgets[:-1])} and {budgets[-1]} estimated tokens "
            "(characters / 4) of the text each tool returned. Whole results: the result that "
            "first answers the case ends within the budget. Text cut: the text is cut at the "
            "budget, and the result the budget cuts counts when its part within the budget "
            "answers (scored from text only)."
        ),
        "",
        *table,
        "",
        "### Paired tests within a token budget",
        "",
        *tests_table(report, _BUDGET_METRICS),
        "",
    ]


def results_block(report: GroundedDocsReport) -> str:
    """The results: the comparison, the paired tests, the breakdowns and the indexing.

    Args:
        report: The run.

    Returns:
        The Markdown.
    """
    lines = [
        "### Every result",
        "",
        *comparison(report),
        "",
        "### Paired tests against ExactDocs",
        "",
        *tests_table(report, _METRICS),
        "",
        *_budget_block(report),
        "### Every metric scored from the text",
        "",
        *results_table([report.baseline.result, *(run.result for run in report.runs)]),
        "",
        "### recall@5 by question kind",
        "",
        *by_kind(report),
        "",
        "### recall@5 and context by project",
        "",
        *by_project(report),
        "",
        "### Indexing",
        "",
        *indexing(report),
        "",
        "Articles not indexed:",
        "",
        *not_indexed(report),
    ]
    errors = [f"- `{run.configuration}`: {e}" for run in report.runs for e in run.errors]
    if errors:
        lines += ["", "Questions whose search failed (scored as empty):", "", *errors]
    return "\n".join(lines)


def markdown(report: GroundedDocsReport) -> str:
    """Render the run as a Markdown summary.

    Args:
        report: The run.

    Returns:
        The summary.
    """
    return "\n".join(
        [
            "# Grounded Docs on the golden set",
            "",
            (
                "Grounded Docs indexed every pinned version of the golden corpus from the same "
                "files the ExactDocs importer takes; every golden question went through its "
                "search with the case's library and version, and the text it returned was scored "
                "with the text scorer, next to ExactDocs' BM25 asked and scored the same way. "
                "Definitions: docs/evals/grounded-docs.md."
            ),
            "",
            "## The run",
            "",
            run_block(report),
            "",
            "## Results",
            "",
            results_block(report),
            "",
        ]
    )


def page_blocks(report: GroundedDocsReport) -> dict[str, str]:
    """The generated blocks of the comparison page (``just bench-pages``).

    Args:
        report: The recorded run.

    Returns:
        ``grounded-docs-run`` and ``grounded-docs``.
    """
    return {"grounded-docs-run": run_block(report), "grounded-docs": results_block(report)}


def problems(report: GroundedDocsReport) -> list[str]:
    """Say what makes a run unfit to record: a failed search, a version left unindexed.

    Args:
        report: The run.

    Returns:
        One problem per configuration and kind of failure.
    """
    found = []
    for run in report.runs:
        if run.errors:
            found.append(f"{run.configuration}: {len(run.errors)} question(s) failed")
        if empty := [f"{v.project} {v.version}" for v in run.indexing if not v.indexed]:
            found.append(f"{run.configuration}: nothing indexed for {', '.join(empty)}")
        if run.embedding and (
            short := [f"{v.project} {v.version}" for v in run.indexing if v.embedded < v.chunks]
        ):
            found.append(f"{run.configuration}: chunks without a vector in {', '.join(short)}")
    return found
