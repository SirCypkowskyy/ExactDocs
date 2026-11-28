"""``just bench-pages``: the benchmark pages' tables, generated from the recorded runs (#349).

Each page under ``docs/benchmark/`` holds generated blocks between ``<!-- bench:<name> -->`` and
``<!-- /bench -->``; everything around them is written by hand. This rewrites the blocks from
``evals/results/*.json`` (ingestion, retrieval, agent, coding tasks, harnesses, and other tools'
runs such as ``grounded-docs.json``) and the golden set, with the benchmarks' own Markdown
renderers, adds the reports' new rows to ``results/history.json`` (``bench_history``), and with
``--check`` fails when a page or the history differs from what they give. See
docs/benchmark/method/runs.md.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Final, get_args

from agent_bench.arms import CONTEXT7, GROUNDED_DOCS
from agent_bench.report import BenchReport
from agent_bench.report import markdown as agent_markdown
from coding_tasks.report import CodingReport
from coding_tasks.report import markdown as coding_markdown
from harness_bench.report import HarnessReport
from harness_bench.report import markdown as harness_markdown
from retrieval_eval import bench_history
from retrieval_eval.dataset import GoldenKind
from retrieval_eval.golden import load_cases, load_corpus
from retrieval_eval.golden_review import load_review, review_block
from retrieval_eval.grid_cli import GridReport
from retrieval_eval.grid_cli import page_block as grid_block
from retrieval_eval.grounded_docs import GroundedDocsReport, page_blocks, results_block
from retrieval_eval.ingestion_cli import IngestionReport
from retrieval_eval.ingestion_cli import markdown as ingestion_markdown
from retrieval_eval.retrieval_bench import RetrievalBenchReport
from retrieval_eval.retrieval_bench import markdown as retrieval_markdown

RESULTS: Final[Path] = Path(__file__).parents[1] / "results"
PAGES: Final[Path] = Path(__file__).parents[4] / "docs" / "benchmark"
HISTORY: Final[Path] = RESULTS / "history.json"
"""Every recorded run, one row per result (``bench_history``)."""
GRID_RESULTS: Final[str] = "retrieval-grid-rank1.json"
"""The recorded run of the grid's rank-1 cells (#575), in ``RESULTS``."""
GRID_GROUPED: Final[str] = "retrieval-grid-grouped.json"
"""The recorded run of the grid's app cells grouped by article and not (#575), in ``RESULTS``."""
GRID_VARIANTS: Final[str] = "retrieval-grid-variants.json"
"""The recorded run of the grid's windows, baselines, h6 hybrid cells and bge-base (#494)."""
BLOCK: Final[re.Pattern[str]] = re.compile(
    r"(<!-- bench:(?P<name>[a-z-]+) -->\n)(?:(?!<!-- bench:).)*?(^<!-- /bench -->)",
    re.DOTALL | re.MULTILINE,
)


def _body(summary: str) -> str:
    """Drop a rendered report's title and intro paragraph: the page has its own.

    Returns:
        The rest of the summary.
    """
    return summary.split("\n\n", 2)[2].strip()


def golden_block() -> str:
    """The corpus and the cases per kind and project, from ``golden/``.

    Returns:
        The Markdown.

    Raises:
        ValueError: A case file does not load.
    """
    corpus = load_corpus()
    cases, problems = load_cases()
    if problems:
        raise ValueError("; ".join(problems))
    lines = [
        "| Project | Versions (pinned commit) | Docs paths | Licence | Attribution |",
        "|---|---|---|---|---|",
    ]
    for p in corpus.projects:
        versions = ", ".join(f"{v.name} (`{v.commit[:7]}`)" for v in p.versions)
        paths = ", ".join(f"`{path}`" for path in p.include)
        lines.append(
            f"| [{p.title}]({p.repository}) | {versions} | {paths} | {p.licence} "
            f"| {p.attribution} |"
        )
    count = Counter((project, c.metadata.kind if c.metadata else None) for project, c in cases)
    projects = [p.id for p in corpus.projects]
    lines += [
        "",
        "| Kind | " + " | ".join(projects) + " | All | Example |",
        "|---|" + "---|" * (len(projects) + 2),
    ]
    for i, kind in enumerate(get_args(GoldenKind.__value__)):
        of_kind = [(p, c) for p, c in cases if c.metadata and c.metadata.kind == kind]
        # one example per kind, taken from each project in turn
        example = next((c for p, c in of_kind if p == projects[i % len(projects)]), of_kind[0][1])
        per = " | ".join(str(count[p, kind]) for p in projects)
        total = sum(count[p, kind] for p in projects)
        lines.append(f"| `{kind}` | {per} | {total} | {example.name} |")
    totals = " | ".join(str(sum(n for (p, _), n in count.items() if p == q)) for q in projects)
    lines.append(f"| all | {totals} | {len(cases)} | |")
    return "\n".join(lines)


def ingestion_block(report: IngestionReport) -> str:
    """The ingestion tables; the lists of missing sections stay in ``results/ingestion.md``.

    Returns:
        The Markdown.
    """
    lean = report.model_copy(
        update={
            "configurations": [
                c.model_copy(
                    update={"totals": c.totals.model_copy(update={"missing_sections": []})}
                )
                for c in report.configurations
            ]
        }
    )
    return _body(ingestion_markdown(lean)).split("\n## Examples", 1)[0].strip()


def retrieval_blocks(report: RetrievalBenchReport) -> dict[str, str]:
    """The run, the recommendations and the result tables of the retrieval benchmark.

    Returns:
        The Markdown of the blocks ``retrieval-run``, ``defaults`` and ``retrieval``.
    """
    defaults, rest = _body(retrieval_markdown(report)).split("\n## Every configuration", 1)
    env = report.environment
    run = [
        (
            f"- Golden set: {report.cases} cases, fingerprint `{report.golden}`, "
            f"projects {', '.join(report.projects)}."
        ),
        (
            f"- ExactDocs commit `{env.get('exactdocs_commit', '?')}` "
            f"(`{env.get('exactdocs', '?')}`), Python {env.get('python', '?')}, "
            f"{env.get('platform', '?')}, {env.get('cpus', '?')} CPUs."
        ),
        "- Libraries: "
        + ", ".join(
            f"{name} {env[name]}"
            for name in ("fastembed", "onnxruntime", "pydantic-ai-slim", "pydantic-evals")
            if name in env
        )
        + ".",
        "",
        "| Project | Version | Commit |",
        "|---|---|---|",
        *(f"| {v['project']} | {v['version']} | `{v['commit']}` |" for v in report.corpus),
    ]
    return {
        "retrieval-run": "\n".join(run),
        "defaults": defaults.removeprefix("## Recommended defaults").strip(),
        "retrieval": ("## Every configuration" + rest).strip(),
    }


def agent_blocks(report: BenchReport) -> dict[str, str]:
    """The run and the result tables of the agent benchmark (#495).

    Returns:
        The Markdown of the blocks ``agent-run`` and ``agent``.

    Raises:
        ValueError: The run has a ``context7`` arm: no Context7 number is published until Upstash
            permits it (docs/evals/context7.md#terms-of-service).
    """
    meta = report.meta
    if CONTEXT7 in meta.arms:
        message = "agent.json has a context7 arm: Context7's terms forbid publishing it"
        raise ValueError(message)
    served = ", ".join(f"{name} at `{url}`" for name, url in meta.providers.items())
    agents = ", ".join(f"`{m}`" for m in meta.agent_models)
    arms = ", ".join(f"`{a}`" for a in meta.arms)
    retrieval = ", ".join(f"`{name}`" for name in meta.retrieval) or "none"
    grounded = sorted({c.retrieval for c in report.cells if c.arm == GROUNDED_DOCS})
    others = "".join(f"; of `grounded-docs`: `{name}`" for name in grounded)
    resumed = (
        f" {meta.resumed} of the answers were kept from an earlier run of the same command "
        "(`--resume`), at its commit and time."
        if meta.resumed
        else ""
    )
    run = [
        (
            f"- Started {meta.started_at}; ExactDocs `{meta.exactdocs_version}` at "
            f"`{meta.git_commit[:12]}`.{resumed}"
        ),
        f"- Agents: {agents}; judge `{meta.judge_model}`"
        + (f"; served by {served}." if served else "."),
        f"- Arms: {arms}; configurations of `exactdocs`: {retrieval}{others}.",
        *(f"- `{name}`: {about.get('server', '?')}." for name, about in meta.servers.items()),
        (
            f"- Cases: {meta.cases} ({meta.selection}); at most {meta.max_requests} model "
            f"requests per question; thinking: {meta.thinking}; {meta.concurrency} questions at "
            f"a time; {meta.max_retries} retries of a failed request."
        ),
    ]
    return {"agent-run": "\n".join(run), "agent": _body(agent_markdown(report))}


def _section(summary: str, heading: str) -> str:
    """The text under a heading of a rendered report, up to the next heading of any level.

    Returns:
        The text; a heading the report lacks raises ``IndexError``.
    """
    after = re.split(rf"^{re.escape(heading)}\n", summary, maxsplit=1, flags=re.MULTILINE)[1]
    return re.split(r"^#+ ", after, maxsplit=1, flags=re.MULTILINE)[0].strip()


def _started(started_at: str, version: str, commit: str | None) -> str:
    """A run's start, ExactDocs version and commit, as a list item.

    Returns:
        The Markdown line.
    """
    return f"- Started {started_at}; ExactDocs `{version}` at `{(commit or '?')[:12]}`."


def comparison_blocks(
    agent: BenchReport, grounded: GroundedDocsReport, harness: HarnessReport, coding: CodingReport
) -> dict[str, str]:
    """The comparison page's tables (#498): retrieval, agent and coding tasks per arm.

    Returns:
        The Markdown of the blocks ``comparison-retrieval``, ``comparison-agent``,
        ``comparison-harnesses`` and ``comparison-coding``.

    Raises:
        ValueError: A coding run has a ``context7`` arm (see ``agent_blocks``).
    """
    if CONTEXT7 in harness.meta.arms or CONTEXT7 in coding.meta.arms:
        message = "a coding run has a context7 arm: Context7's terms forbid publishing it"
        raise ValueError(message)
    am, hm, cm = agent_markdown(agent), harness_markdown(harness), coding_markdown(coding)
    h, c = harness.meta, coding.meta
    resumed = f" {h.resumed} runs were kept from an earlier run (`--resume`)." if h.resumed else ""
    harnesses = [
        _started(h.started_at, h.exactdocs_version, h.git_commit) + resumed,
        "",
        _section(hm, "## Harnesses"),
        "",
        _section(hm, "### Coding tasks"),
        "",
        "Against the harness's own `none` arm, on the same jobs:",
        "",
        _section(hm, "#### Coding tasks: against the harness's own `none` arm, on the same jobs"),
        "",
        "Built-in web calls, and the hosts the gate refused:",
        "",
        _section(hm, "### Network"),
    ]
    loop = [
        _started(c.started_at, c.exactdocs_version, c.git_commit),
        "",
        _section(cm, "## Coding tasks"),
        "",
        "Against `none`, on the same tasks (McNemar, mid-p):",
        "",
        _section(cm, "### Against `none`, on the same tasks (McNemar, mid-p)"),
    ]
    return {
        "comparison-retrieval": _section(results_block(grounded), "### Every result"),
        "comparison-agent": "\n\n".join(
            (
                _section(am, "## Quality"),
                _section(am, "## Against the other arms, on the same cases"),
            )
        ),
        "comparison-harnesses": "\n".join(harnesses),
        "comparison-coding": "\n".join(loop),
    }


def history(results: Path = RESULTS) -> list[bench_history.Row]:
    """The recorded history with the current reports' new rows (dated today).

    Returns:
        The rows.
    """
    path = results / HISTORY.name
    recorded = json.loads(path.read_text("utf-8")) if path.exists() else []
    return bench_history.merge(recorded, bench_history.rows_of(results), bench_history.today())


def blocks(results: Path = RESULTS, rows: list[bench_history.Row] | None = None) -> dict[str, str]:
    """Every generated block, by name.

    Returns:
        The Markdown of each block.
    """
    ingestion = IngestionReport.model_validate_json((results / "ingestion.json").read_text("utf-8"))
    retrieval = RetrievalBenchReport.model_validate_json(
        (results / "retrieval.json").read_text("utf-8")
    )
    agent = BenchReport.model_validate_json((results / "agent.json").read_text("utf-8"))
    path = results / "grounded-docs.json"
    competitors: dict[str, str] = {}
    if path.exists():
        grounded = GroundedDocsReport.model_validate_json(path.read_text("utf-8"))
        harness = HarnessReport.model_validate_json(
            (results / "harness-bench.json").read_text("utf-8")
        )
        coding = CodingReport.model_validate_json(
            (results / "coding-tasks.json").read_text("utf-8")
        )
        competitors = page_blocks(grounded) | comparison_blocks(agent, grounded, harness, coding)
    grids = {
        "retrieval-grid": GRID_RESULTS,
        "retrieval-grouping": GRID_GROUPED,
        "retrieval-grid-variants": GRID_VARIANTS,
    }
    rank_one = {
        name: grid_block(GridReport.model_validate_json((results / file).read_text("utf-8")))
        for name, file in grids.items()
        if (results / file).exists()
    }
    rows = history(results) if rows is None else rows
    return {
        "golden": golden_block(),
        "golden-review": review_block(load_review()),
        "ingestion": ingestion_block(ingestion),
        **retrieval_blocks(retrieval),
        **agent_blocks(agent),
        **competitors,
        **rank_one,
        **{
            f"history-{family}": bench_history.table(rows, family)
            for family in bench_history.COLUMNS
        },
    }


def render(page: str, generated: dict[str, str]) -> str:
    """Fill a page's blocks.

    Args:
        page: The page's Markdown.
        generated: The blocks by name.

    Returns:
        The page with every block replaced; a block that is not generated raises ``KeyError``.
    """
    return BLOCK.sub(lambda m: m[1] + generated[m["name"]] + "\n" + m[3], page)


def main(argv: Sequence[str] | None = None) -> int:
    """Rewrite the pages, or check them.

    Returns:
        1 when ``--check`` finds a page that differs from the reports.
    """
    parser = argparse.ArgumentParser(prog="just bench-pages", description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a page is out of date")
    parser.add_argument("--pages", type=Path, default=PAGES, help="the benchmark pages")
    args = parser.parse_args(argv)
    rows = history()
    generated = blocks(rows=rows)
    stale = []
    recorded = bench_history.dumps(rows)
    if not HISTORY.exists() or HISTORY.read_text("utf-8") != recorded:
        stale.append(HISTORY)
        if not args.check:
            HISTORY.write_text(recorded, "utf-8")
    for path in sorted(args.pages.rglob("*.md")):
        page = path.read_text("utf-8")
        new = render(page, generated)
        if new == page:
            continue
        stale.append(path)
        if not args.check:
            path.write_text(new, "utf-8")
    for path in stale:
        verb = "is out of date (run `just bench-pages`)" if args.check else "updated"
        sys.stdout.write(f"{path}: {verb}\n")
    return 1 if args.check and stale else 0
