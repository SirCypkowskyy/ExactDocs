"""The retrieval grid (#494): the grid file, the eval-only chunkers, searches and baselines.

Everything here is model-free: the dense cells embed with the term-hash stand-in. The command runs
on the retrieval benchmark's tiny corpus.
"""

import itertools
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from exactdocs.ingestion.models import ChunkingConfig, parse_article
from exactdocs.retrieval.adapters.driven.memory import HashEmbeddingModels
from exactdocs.retrieval.models import EmbeddedTexts
from exactdocs.retrieval.ports.driven import Embeddings
from retrieval_bench_stand_ins import tiny_corpus
from retrieval_eval.grid import (
    Cell,
    Grid,
    PassageIndex,
    grep,
    load_grid,
    passages_of,
    window_spans,
)
from retrieval_eval.grid_cli import CACHE_SLICE, REPORT_NAME, CachedEmbeddings, GridReport, main
from retrieval_eval.ingestion import Article, measure
from retrieval_eval.retrieval_bench import Budget

FENCE = "```"
CODE = "\n".join(f"    value_{i} = compute({i})" for i in range(30))
ARTICLE = f"""# Guide

Intro text for the guide.

## Install

Run pip to install the demo package.

### From source

Clone the repository and build the wheel.

## Configure

{FENCE}python
{CODE}
{FENCE}
"""


def _cell(**settings: object) -> Cell:
    return Cell.model_validate({"name": "cell", "search": "bm25", **settings})


def _passages(cell: Cell, chunking: ChunkingConfig | None = None, version: str = "v1") -> list:
    article = parse_article("docs/guide.md", ARTICLE)
    return passages_of(cell, "demo", version, article, chunking or ChunkingConfig())


# ---------------------------------------------------------------- chunkers


def test_windows_are_whole_lines_that_cover_the_body_and_overlap() -> None:
    spans = window_spans(ARTICLE, 32, 8)

    assert spans[0][0] == 0
    assert spans[-1][1] == len(ARTICLE)
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert start <= end  # nothing is left out
        assert end - start <= 8 * 4  # at most the overlap is shared
        assert start == 0 or ARTICLE[start - 1] == "\n"  # a window starts on a line


def test_a_window_cuts_a_code_block_that_heading_chunks_keep_whole() -> None:
    def cuts(cell: Cell) -> int:
        chunks = tuple(p.chunk for p in _passages(cell))
        article = Article(key="demo v1:docs/guide.md", source=ARTICLE, chunks=chunks)
        return measure([article], []).cuts_in_code_fence

    assert cuts(_cell(window=32, overlap=8)) > 0
    assert cuts(_cell()) == 0


def test_a_window_starts_at_the_heading_path_it_begins_in() -> None:
    passages = _passages(_cell(window=16, overlap=0))

    paths = [p.chunk.heading_path for p in passages]
    assert paths[0] == ("Guide",)
    assert ("Guide", "Configure") in paths
    assert all(p.shown == p.chunk.content for p in passages)


def test_the_context_prefix_is_the_title_and_heading_path() -> None:
    install = next(p for p in _passages(_cell()) if p.chunk.heading_path == ("Guide", "Install"))

    assert install.context == "Guide > Install"  # the H1 that is the title is not repeated
    assert install.text(prefixed=True).startswith("Guide > Install\n\n## Install")
    assert install.text(prefixed=False) == install.chunk.content


def test_a_heading_chunk_widens_to_its_parent_section_when_read() -> None:
    passages = _passages(_cell(chunking="h6", expand="parent"), ChunkingConfig(max_chars=None))

    source = next(p for p in passages if p.chunk.heading_path[-1:] == ("From source",))
    assert source.chunk.content.startswith("### From source")
    assert source.shown.startswith("## Install")
    assert "### From source" in source.shown
    assert "## Configure" not in source.shown
    top = next(p for p in passages if p.chunk.heading_path == ("Guide",))
    assert top.shown == ARTICLE  # a top-level heading widens to itself, with its subsections


# ---------------------------------------------------------------- searches


@pytest.mark.parametrize("search", ["bm25", "dense", "hybrid"])
async def test_a_search_returns_nothing_of_another_version(search: str) -> None:
    cell = _cell(search=search, embedding=None if search == "bm25" else "stand-in")
    passages = _passages(cell, version="v1") + _passages(cell, version="v2")
    embeddings = HashEmbeddingModels(size=64, by_terms=True).bind(
        None, name="local:stand-in", dimensions=None, batch_size=16
    )
    index = await PassageIndex.build(cell, passages, embeddings)
    try:
        found = await index.search("demo", "v1", "install the demo package with pip")
    finally:
        index.close()

    assert found.passages
    assert {passages[i].version for i in found.passages} == {"v1"}
    assert "pip" in passages[found.passages[0]].chunk.content
    assert (index.cost.tokens > 0) is (search != "bm25")  # embedding the corpus is counted


async def test_widened_hits_that_repeat_are_returned_once() -> None:
    cell = _cell(chunking="h6", expand="parent")
    passages = _passages(cell, ChunkingConfig(max_chars=None))
    index = await PassageIndex.build(cell, passages, None)
    try:
        answer = await index.answer("demo", "v1", "install pip clone wheel")
    finally:
        index.close()

    assert len(answer.texts) == len(set(answer.texts))


async def test_hits_grouped_by_article_come_back_with_their_neighbours_once_per_article() -> None:
    cell = _cell(chunking="h6", expand="article")
    guide = _passages(cell, ChunkingConfig(max_chars=None))
    other = passages_of(
        cell, "demo", "v1", parse_article("docs/other.md", "# Other\n\nInstall nothing.\n"),
        ChunkingConfig(max_chars=None),
    )  # fmt: skip
    index = await PassageIndex.build(cell, [*guide, *other], None)
    try:
        answer = await index.answer("demo", "v1", "install from source")
    finally:
        index.close()

    # one result per article, ranked by its best hit: the guide's subsection, then the other page
    assert len(answer.texts) == 2
    first = answer.texts[0]
    # its hits with one chunk on either side, in article order, each once
    assert first.index("## Install") < first.index("### From source")
    assert first.count("### From source") == 1
    assert "## Configure" in first  # the neighbour after the subsection
    assert answer.texts[1] == other[0].chunk.content
    with pytest.raises(ValidationError, match="heading chunking"):
        _cell(window=32, expand="article")


async def test_cells_that_embed_the_same_texts_embed_them_once(tmp_path: Path) -> None:
    counted = _Counting(
        HashEmbeddingModels(size=16).bind(None, name="local:m", dimensions=None, batch_size=4)
    )
    cached = CachedEmbeddings(inner=counted, folder=tmp_path)
    texts = [f"text {i}" for i in range(CACHE_SLICE + 3)]

    first = await cached.embed_documents(texts)
    again = await CachedEmbeddings(inner=counted, folder=tmp_path).embed_documents(texts)

    assert counted.texts == len(texts)  # the second run read every slice back
    assert again.vectors == first.vectors
    assert again.input_tokens == first.input_tokens
    assert (await cached.embed_query("q")).vectors == (await counted.embed_query("q")).vectors


class _Counting:
    """Implements ``Embeddings``: counts the texts embedded as documents."""

    def __init__(self, inner: Embeddings) -> None:
        self.inner, self.texts = inner, 0

    @property
    def name(self) -> str:
        return self.inner.name

    async def dimensions(self) -> int:
        return await self.inner.dimensions()

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        self.texts += len(texts)
        return await self.inner.embed_documents(texts)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        return await self.inner.embed_query(text)


def test_grep_matches_whole_words_keeps_context_and_ranks_by_terms() -> None:
    files = {
        "a.md": "one\ntwo\ninstall here\nthree\n",
        "b.md": "pip install demo\n",
        "c.md": "reinstall nothing\n",
    }

    found = grep(files, "How do I install the demo with pip?", context=1)

    assert found[0] == "pip install demo\n"  # three terms before one
    assert found[1] == "two\ninstall here\nthree\n"
    assert len(found) == 2  # "reinstall" is not the word "install"
    assert grep(files, "the of a") == []


# ---------------------------------------------------------------- the grid file


def test_a_cell_is_either_an_app_configuration_or_an_eval_only_search() -> None:
    assert Cell(app="bm25").name == "bm25@default"
    assert Cell(app="bm25", chunking="h2").chunker == "h2"
    assert Cell(name="g", search="grep").chunker == "raw"
    assert _cell(window=256, overlap=64).chunker == "window-256+64"
    assert _cell(search="dense", embedding="m").budget is Budget.LOCAL
    for bad in (
        {"name": "x"},
        {"name": "x", "app": "bm25", "search": "bm25"},
        {"app": "bm25", "window": 256},
        {"name": "x", "search": "dense"},
        {"name": "x", "search": "bm25", "window": 64, "overlap": 64},
        {"search": "bm25"},
    ):
        with pytest.raises(ValidationError):
            Cell.model_validate(bad)
    with pytest.raises(ValidationError, match="twice"):
        Grid.model_validate({"defaults": {}, "cells": [{"app": "bm25"}, {"app": "bm25"}]})
    with pytest.raises(ValidationError, match="name no cell"):
        Grid.model_validate({"defaults": {"none": "nope"}, "cells": [{"app": "bm25"}]})


def test_the_recorded_grid_holds_every_variant_and_baseline_the_issue_asks_for() -> None:
    grid = load_grid()

    cells = {c.name: c for c in grid.cells}
    assert grid.defaults[Budget.NONE] == grid.defaults[Budget.LOCAL] == "bm25@default"
    assert {"hybrid:bge-base-en-v1.5@default", "bm25+ce@default"} <= set(cells)
    assert "hybrid:hosted@default" in cells
    assert len({c.window for c in grid.cells if c.window is not None}) >= 2
    assert all(c.overlap > 0 for c in grid.cells if c.window is not None)
    assert any(c.prefix_embedded for c in grid.cells)
    assert any(c.prefix_indexed for c in grid.cells)
    assert any(c.expand == "parent" for c in grid.cells)
    assert any(c.search == "grep" for c in grid.cells)
    # #575: grouping by article, for BM25 and hybrid search, each variant with its control
    grouped = [c for c in grid.cells if c.expand == "article"]
    assert {c.search for c in grouped} == {"bm25", "hybrid"}
    assert all(c.against in cells for c in grouped)
    rag = [c for c in grid.cells if c.window is not None and c.search == "dense"]
    assert rag
    assert all(c.embedding == "BAAI/bge-small-en-v1.5" for c in rag)


# ---------------------------------------------------------------- the command


def test_the_command_runs_the_grid_and_resumes_per_cell(tmp_path: Path) -> None:
    args = tiny_corpus(tmp_path)
    grid = tmp_path / "matrix.yaml"
    grid.write_text(
        yaml.safe_dump({
            "defaults": {"none": "bm25@default"},
            "cells": [
                {"app": "bm25"},
                {"name": "grep", "search": "grep"},
                {"name": "window", "window": 32, "overlap": 8, "search": "bm25"},
                {"name": "rag", "window": 32, "search": "dense", "embedding": "not/pulled"},
            ],
        }),
        encoding="utf-8",
    )  # fmt: skip
    out = tmp_path / "out"
    run = [*args, "--grid", str(grid), "--out", str(out)]

    assert main([*run, "--cells", "grep"]) == 0  # the default runs too
    first = GridReport.model_validate_json((out / f"{REPORT_NAME}.json").read_text("utf-8"))
    assert [r.configuration for r in first.bench.results] == ["bm25", "grep"]

    assert main(run) == 0
    report = GridReport.model_validate_json((out / f"{REPORT_NAME}.json").read_text("utf-8"))
    assert report.resumed == ["bm25@default", "grep"]
    results = {r.configuration: r for r in report.bench.results}
    assert results["window"].status == "ran"
    assert results["rag"].status == "unavailable"
    assert "exactdocs models pull not/pulled" in (results["rag"].reason or "")
    assert results["window"].versus_default is not None
    assert "window-32+8" in report.ingestion
    summary = (out / f"{REPORT_NAME}.md").read_text("utf-8")
    assert summary.startswith("# Retrieval grid")
    assert "## Eval-only chunkers" in summary

    assert main([*run, "--fresh"]) == 0
    fresh = GridReport.model_validate_json((out / f"{REPORT_NAME}.json").read_text("utf-8"))
    assert fresh.resumed == []


def test_a_variant_runs_with_its_control_and_is_tested_against_it(tmp_path: Path) -> None:
    args = tiny_corpus(tmp_path)
    grid = tmp_path / "matrix.yaml"
    grid.write_text(
        yaml.safe_dump({
            "defaults": {"none": "bm25@default"},
            "cells": [
                {"app": "bm25"},
                {"name": "own", "search": "bm25"},
                {"name": "grouped", "search": "bm25", "expand": "article", "against": "own"},
            ],
        }),
        encoding="utf-8",
    )  # fmt: skip
    out = tmp_path / "out"

    assert main([*args, "--grid", str(grid), "--out", str(out), "--cells", "grouped"]) == 0

    report = GridReport.model_validate_json((out / f"{REPORT_NAME}.json").read_text("utf-8"))
    assert [r.configuration for r in report.bench.results] == ["bm25", "own", "grouped"]
    versus = report.versus_control["grouped"]
    assert versus.configuration == "own"
    assert {"recall_at_1", "recall_at_1k_tokens", "recall_at_1k_tokens_cut"} <= set(versus.tests)
    summary = (out / f"{REPORT_NAME}.md").read_text("utf-8")
    assert "## Against each variant's control" in summary
    assert "| `grouped` | `own` |" in summary
    assert "## Within a token budget" in summary
    with pytest.raises(ValidationError, match="controls that name no cell"):
        Grid.model_validate({"defaults": {}, "cells": [{"app": "bm25", "against": "nope"}]})


def test_the_command_refuses_an_unknown_configuration(tmp_path: Path) -> None:
    args = tiny_corpus(tmp_path)
    grid = tmp_path / "matrix.yaml"
    grid.write_text(yaml.safe_dump({"defaults": {}, "cells": [{"app": "nope"}]}), encoding="utf-8")

    assert main([*args, "--grid", str(grid), "--out", str(tmp_path / "out")]) == 2
