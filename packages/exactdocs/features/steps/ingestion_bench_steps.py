"""Steps for the ingestion benchmark (packages/exactdocs/evals): run in-process, as
`just ingestion-bench` runs it, on a tiny local repository standing in for the golden corpus.
"""

import shutil
import tempfile
from pathlib import Path

import yaml
from behave import given, then, when
from behave.runner import Context

from fixture_repo import git
from retrieval_eval.ingestion_cli import IngestionReport, main

FENCE = "```"
GUIDE = f"""# Guide

Intro.

### Install

Run it.

{FENCE}sh
pip install demo
{FENCE}

## Use [#use]

Use it.
"""
TABS = f"""</Tab>
{FENCE}ts
const a = 1;

const b = 2;
{FENCE}

## Hidden

Text.
"""


@given("a golden corpus whose docs hide a heading in MDX code and keep a heading id in its text")
def step_tiny_corpus(context: Context) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="exactdocs-ingestion-bench-"))
    context.add_cleanup(shutil.rmtree, tmp, ignore_errors=True)
    repo = tmp / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
    (repo / "docs" / "tabs.mdx").write_text(TABS, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", "v1", cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    project = {
        "id": "demo",
        "title": "Demo",
        "repository": str(repo),
        "include": ["docs/"],
        "licence": "MIT",
        "attribution": "Copyright (c) A",
        "versions": [{"name": "v1", "commit": git("rev-parse", "HEAD", cwd=repo)}],
    }
    (tmp / "corpus.yaml").write_text(yaml.safe_dump({"projects": [project]}), encoding="utf-8")
    hit = {"version": "v1", "article": "docs/guide.md", "heading_path": ["Guide", "Install"]}
    case = {
        "name": "demo v1: How do I install it?",
        "inputs": {"query": "How do I install it?", "version": "v1", "project": "demo"},
        "metadata": {"kind": "how-to"},
        "expected_output": {"hits": [hit], "reference": "Run it.", "facts": ["run it"]},
    }
    (tmp / "cases").mkdir()
    dataset = yaml.safe_dump({"name": "demo", "cases": [case]})
    (tmp / "cases" / "demo.yaml").write_text(dataset, encoding="utf-8")
    context.bench_dir = tmp
    context.bench_args = [
        "--corpus", str(tmp / "corpus.yaml"), "--cases", str(tmp / "cases"),
        "--cache-dir", str(tmp / "cache"), "--out", str(tmp / "out"),
    ]  # fmt: skip


def _run(context: Context, configs: str) -> None:
    assert main([*context.bench_args, "--configs", configs]) == 0
    out = context.bench_dir / "out"
    context.bench_report = IngestionReport.model_validate_json(
        (out / "ingestion.json").read_text(encoding="utf-8")
    )
    context.bench_summary = (out / "ingestion.md").read_text(encoding="utf-8")


@when("the ingestion benchmark runs with today's default chunking")
def step_run_default(context: Context) -> None:
    _run(context, "default")
    (configuration,) = context.bench_report.configurations
    (context.bench_version,) = configuration.versions


@then("it reports, for the project's version, the coverage of the expected sections")
def step_coverage(context: Context) -> None:
    version = context.bench_version
    assert (version.project, version.version) == ("demo", "v1")
    metrics = version.metrics
    assert (metrics.expected_sections, metrics.covered_sections, metrics.coverage) == (1, 1, 1)
    assert metrics.missing_sections == []


@then("the chunks that cut a code block, table or list in two")
def step_integrity(context: Context) -> None:
    metrics = context.bench_version.metrics
    assert (metrics.cuts_in_code_fence, metrics.cuts_in_table, metrics.cuts_in_list) == (0, 0, 0)
    assert metrics.lost_chars == 0
    assert metrics.headings_missed == 1  # "## Hidden" is code to CommonMark after `</Tab>`
    assert metrics.examples["headings_missed"] == ["demo v1:docs/tabs.mdx"]


@then("the distribution of chunk sizes in tokens")
def step_sizes(context: Context) -> None:
    metrics = context.bench_version.metrics
    assert 0 < metrics.tokens_p50 <= metrics.tokens_p95 <= metrics.tokens_max
    assert metrics.small_chunks == metrics.chunks  # every chunk of this tiny corpus is small


@then("how many chunks have an empty or wrong heading path")
def step_paths(context: Context) -> None:
    metrics = context.bench_version.metrics
    assert metrics.empty_heading_paths == 1  # tabs.mdx: its only heading is hidden
    assert metrics.wrong_heading_paths == 1
    assert metrics.wrong_heading_examples == ["Guide > Use [#use]"]


@when('the ingestion benchmark runs the "{first}" and "{second}" chunking configurations')
def step_run_two(context: Context, first: str, second: str) -> None:
    _run(context, f"{first},{second}")


@then("one table compares them on every metric and on BM25 recall@5")
def step_table(context: Context) -> None:
    default, h2 = context.bench_report.configurations
    assert (default.name, h2.name) == ("default", "h2")
    assert (default.totals.coverage, h2.totals.coverage) == (1, 0)  # h2 merges "### Install"
    assert (default.bm25.recall_at_5, h2.bm25.recall_at_5) == (1, 1)
    header, _, first, second = [
        line for line in context.bench_summary.splitlines() if line.startswith("|")
    ][:4]
    for metric in (
        "coverage", "cut fence / table / list", "lost chars", "tokens p50 / p95 / max", "small",
        "multi-top", "empty / wrong path", "headings missed / extra", "BM25 recall@5",
    ):  # fmt: skip
        assert metric in header, metric
    assert first.startswith("| `default` | 100.0% |")
    assert second.startswith("| `h2` | 0.0% |")
