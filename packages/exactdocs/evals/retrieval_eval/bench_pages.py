"""``just bench-pages``: the benchmark pages' tables, generated from the recorded runs (#349).

Each page under ``docs/benchmark/`` holds generated blocks between ``<!-- bench:<name> -->`` and
``<!-- /bench -->``; everything around them is written by hand. This rewrites the blocks from
``evals/results/*.json`` and the golden set, with the benchmarks' own Markdown renderers, and with
``--check`` fails when a page differs from what they give. See docs/benchmark/method.md.
"""

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Final, get_args

from retrieval_eval.dataset import GoldenKind
from retrieval_eval.golden import load_cases, load_corpus
from retrieval_eval.ingestion_cli import IngestionReport
from retrieval_eval.ingestion_cli import markdown as ingestion_markdown
from retrieval_eval.retrieval_bench import RetrievalBenchReport
from retrieval_eval.retrieval_bench import markdown as retrieval_markdown

RESULTS: Final[Path] = Path(__file__).parents[1] / "results"
PAGES: Final[Path] = Path(__file__).parents[4] / "docs" / "benchmark"
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


def blocks(results: Path = RESULTS) -> dict[str, str]:
    """Every generated block, by name.

    Returns:
        The Markdown of each block.
    """
    ingestion = IngestionReport.model_validate_json((results / "ingestion.json").read_text("utf-8"))
    retrieval = RetrievalBenchReport.model_validate_json(
        (results / "retrieval.json").read_text("utf-8")
    )
    return {
        "golden": golden_block(),
        "ingestion": ingestion_block(ingestion),
        **retrieval_blocks(retrieval),
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
    generated = blocks()
    stale = []
    for path in sorted(args.pages.glob("*.md")):
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
