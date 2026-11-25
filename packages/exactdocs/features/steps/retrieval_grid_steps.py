"""Steps for the retrieval grid (packages/exactdocs/evals): run in-process on a tiny corpus.

The corpus is the retrieval benchmark's (``retrieval_bench_steps``); the eval-only cells embed with
the term-hash stand-in, so no model is downloaded. No local model is pulled, so the app cell that
reranks with the cross-encoder is reported as unavailable.
"""

import asyncio

import yaml
from behave import given, then, when
from behave.runner import Context

from exactdocs.retrieval.adapters.driven.memory import HashEmbeddingModels
from exactdocs.retrieval.ports.driven import Embeddings
from retrieval_bench_stand_ins import HOSTED
from retrieval_eval.golden import fetch, load_corpus, load_golden
from retrieval_eval.grid import load_grid
from retrieval_eval.grid_cli import grid_markdown, run_grid

GRID = {
    "defaults": {"none": "bm25@default", "local": "bm25@default"},
    "cells": [
        {"app": "bm25"},
        {"app": "bm25+ce"},
        {"name": "grep", "search": "grep"},
        {
            "name": "rag",
            "window": 32,
            "overlap": 8,
            "search": "dense",
            "embedding": "stand-in",
        },
        {"name": "window/bm25", "window": 32, "overlap": 8, "search": "bm25"},
        {"name": "indexed", "search": "bm25", "prefix_indexed": True},
        {"name": "embedded", "search": "hybrid", "embedding": "stand-in", "prefix_embedded": True},
        {"name": "parent", "chunking": "h6", "search": "bm25", "expand": "parent"},
    ],
}
"""A grid with an app cell of each budget, both baselines and every eval-only variant."""


async def _stand_in(model: str) -> Embeddings:
    """Embed by hashing terms (no model).

    Args:
        model: The model's name.

    Returns:
        The stand-in.
    """
    return HashEmbeddingModels(size=64, by_terms=True).bind(
        None, name=f"local:{model}", dimensions=None, batch_size=16
    )


def _run(context: Context, cells: int | None = None) -> None:
    """Run the grid (its first ``cells`` only, when given) on the tiny corpus.

    Args:
        context: The scenario.
        cells: How many cells run.
    """
    tmp = context.bench_dir
    grid = load_grid(tmp / "matrix.yaml")
    if cells is not None:
        grid = grid.model_copy(update={"cells": grid.cells[:cells]})
    corpus = load_corpus(tmp / "corpus.yaml")
    repos = {p.id: fetch(p, tmp / "cache", offline=False) for p in corpus.projects}
    context.grid_report = asyncio.run(
        run_grid(
            grid,
            corpus.projects,
            repos,
            load_golden(tmp / "cases"),
            out=tmp / "out",
            hosted=HOSTED,
            models_dir=tmp / "models",
            embeddings_for=_stand_in,
        )
    )


@given("a grid of ingestion, index, retrieval and rerank settings in a file")
def step_grid(context: Context) -> None:
    (context.bench_dir / "matrix.yaml").write_text(yaml.safe_dump(GRID), encoding="utf-8")


@given("a grid run that stopped after its first cell")
def step_stopped(context: Context) -> None:
    _run(context, cells=1)


@when("the grid runs on the golden set")
@when("the run includes the keyword-grep and fixed-window RAG baselines")
def step_run(context: Context) -> None:
    _run(context)


def _ran(context: Context) -> dict:
    return {r.configuration: r for r in context.grid_report.bench.results if r.status == "ran"}


@then("every cell reports the retrieval metrics with intervals and its index cost")
def step_metrics(context: Context) -> None:
    results = {r.configuration: r for r in context.grid_report.bench.results}
    assert len(results) == len(GRID["cells"]), sorted(results)
    assert results["bm25+ce"].status == "unavailable", results["bm25+ce"].reason
    for name, result in _ran(context).items():
        metrics = result.metrics
        assert metrics is not None, name
        assert {"recall_at_1", "recall_at_5", "mrr", "ndcg_at_10"} <= set(metrics.intervals), name
        assert result.rows, name
        assert result.settings or name == "bm25", name
        if name not in {"bm25", "grep"}:  # what had to be indexed records what it took
            assert result.index is not None, name
    assert _ran(context)["embedded"].index.tokens > 0


@then("each cell is compared with the budget's default by the paired test")
def step_paired(context: Context) -> None:
    for name, result in _ran(context).items():
        if name == "bm25":
            assert result.versus_default is None
            continue
        versus = result.versus_default
        assert versus is not None, name
        assert (versus.configuration, versus.chunking) == ("bm25", "default"), name
        assert "recall_at_5" in versus.tests, name


@then("each eval-only chunker reports where it cut code blocks or tables")
def step_cuts(context: Context) -> None:
    ingestion = context.grid_report.ingestion
    assert set(ingestion) == {"window-32+8", "default", "h6"}, sorted(ingestion)
    for name, metrics in ingestion.items():
        assert metrics.chunks > 0, name
        assert metrics.cuts_in_code_fence + metrics.cuts_in_table >= 0, name
    assert "cuts in code / table / list" in grid_markdown(context.grid_report)


@then("they are scored with the text scorer like any other tool")
def step_baselines(context: Context) -> None:
    ran = _ran(context)
    text = context.grid_report.text
    for name in ("grep", "rag"):
        assert name in text, sorted(text)
        assert text[name].context_tokens_per_question > 0, name
        assert ran[name].metrics is not None, name
    assert ran["grep"].chunking == "raw"
    assert ran["rag"].chunking == "window-32+8"
    assert ran["grep"].metrics.recall_at_5 == 1  # the install lines hold the answer
    assert ran["grep"].metrics.wrong_version_rate == 0


@then("the first cell is not run again and every other cell is")
def step_resumed(context: Context) -> None:
    report = context.grid_report
    assert report.resumed == ["bm25@default"], report.resumed
    assert len(report.bench.results) == len(GRID["cells"])
