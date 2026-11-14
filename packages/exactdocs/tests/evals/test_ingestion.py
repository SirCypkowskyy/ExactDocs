"""The ingestion benchmark (#346): each metric on tiny inputs, the match rule, the check, a run.

The metrics are pure functions of an article's source and its chunks; the run imports a tiny
local repository standing in for the golden corpus, so nothing needs the network or the cache.
"""

import json
from pathlib import Path

import pytest
import yaml

from fixture_repo import git
from retrieval_eval.dataset import Answer, Hit, Question
from retrieval_eval.golden import Corpus, PinnedVersion, Project
from retrieval_eval.golden_run import GoldenRetriever, nested_match
from retrieval_eval.ingestion import (
    Article,
    Chunk,
    IngestionMetrics,
    coverage,
    cuts,
    lost_chars,
    measure,
    mkdocs_blocks_as_code,
    percentile,
    source_headings,
    tokens,
    wrong_heading_path,
)
from retrieval_eval.ingestion_cli import (
    Bm25Result,
    ConfigurationResult,
    IngestionReport,
    article_sources,
    check,
    main,
)

FENCE = "```"


def _chunk(content: str, *path: str, headings: tuple[tuple[str, ...], ...] | None = None) -> Chunk:
    return Chunk(
        heading_path=path, content=content, headings=(path,) if headings is None else headings
    )


# ---------------------------------------------------------------- the line reader


def test_headings_are_found_outside_fences_only() -> None:
    source = f"# Title\n\nText\n\n## Install\n\n{FENCE}sh\n# a comment\n{FENCE}\n\nSetext\n---\n"

    assert source_headings(source) == [1, 2, 2]


def test_a_fence_closes_only_with_its_own_marker_and_length() -> None:
    source = "~~~~\n```\n# inside\n~~~\n# still inside\n~~~~\n# Out\n"

    assert source_headings(source) == [1]


def test_backticks_in_the_info_string_do_not_open_a_fence() -> None:
    assert source_headings("```not `a` fence\n# Heading\n") == [1]


def test_the_reader_pairs_fences_after_a_jsx_tag_as_mdx_does() -> None:
    # CommonMark reads `</Tab>` as an HTML block that runs to the blank line, so the closing
    # fence opens a new block that swallows the heading.
    source = f"</Tab>\n{FENCE}ts\nconst a = 1;\n\nconst b = 2;\n{FENCE}\n\n## The error param\n"

    assert source_headings(source) == [2]


def test_a_list_item_or_table_row_above_dashes_is_not_a_setext_heading() -> None:
    assert source_headings("- item\n---\n| a |\n---\n") == []


# ---------------------------------------------------------------- integrity


def test_cuts_at_headings_are_clean() -> None:
    chunks = [_chunk("# A\n\n- one\n- two\n", "A"), _chunk("## B\n\n| x |\n", "A", "B")]

    assert cuts(chunks) == (0, 0, 0)


def test_a_cut_inside_a_fence_is_counted() -> None:
    chunks = [_chunk(f"## A\n\n{FENCE}sh\n", "A"), _chunk(f"# not a heading\n{FENCE}\n", "x")]

    assert cuts(chunks) == (1, 0, 0)


def test_a_cut_inside_a_table_or_a_list_is_counted() -> None:
    table = [_chunk("| a | b |\n|---|---|\n| 1 | 2 |\n", "A"), _chunk("| 3 | 4 |\n", "A")]
    listed = [_chunk("- one\n- two\n", "A"), _chunk("- three\n", "A")]
    apart = [_chunk("- one\n\n", "A"), _chunk("Text\n", "A")]

    assert cuts(table) == (0, 1, 0)
    assert cuts(listed) == (0, 0, 1)
    assert cuts(apart) == (0, 0, 0)


def test_lost_characters_are_the_source_in_no_chunk() -> None:
    source = "# A\n\nOne.\n\n## B\n\nTwo.\n"
    whole = [_chunk("# A\n\nOne.\n\n", "A"), _chunk("## B\n\nTwo.\n", "A", "B")]

    assert lost_chars(source, whole) == 0
    assert lost_chars(source, whole[:1]) == len("##BTwo.")
    assert lost_chars(source, [_chunk("rewritten", "A")]) == len("#AOne.##BTwo.")


def test_a_chunk_is_matched_after_the_previous_one() -> None:
    source = "same\n\nsame\n"

    assert lost_chars(source, [_chunk("same\n", "A"), _chunk("same\n", "A")]) == 0


# ---------------------------------------------------------------- shape and headings


def test_tokens_are_estimated_at_four_characters_rounded_up() -> None:
    assert [tokens(""), tokens("abcd"), tokens("abcde")] == [0, 1, 2]


def test_percentiles_are_nearest_rank() -> None:
    values = list(range(1, 101))

    assert (percentile(values, 0.5), percentile(values, 0.95), percentile([], 0.5)) == (50, 95, 0)


@pytest.mark.parametrize(
    ("path", "wrong"),
    [
        (("Objects", "z.deepPartial() [#deep-partial]"), True),
        (("Validators {#validators}",), True),
        (("See [the guide][guide]",), True),
        (("A [link](https://example.com)",), True),
        (("Using the [Field()][pydantic.Field] function",), True),
        (("See [the guide][]",), True),
        (("win.setAlwaysOnTop(flag[, level][, relativeLevel])",), False),
        (('webkitdirectory for <input type="file"/>',), False),
        (("{/* note */} Title",), True),
        (("A", " "), True),
        (("z.toZod<T>()",), False),
        (("Install", "On macOS"), False),
        ((), False),
    ],
)
def test_a_wrong_heading_path_holds_markup_or_an_empty_heading(
    path: tuple[str, ...], wrong: bool
) -> None:
    assert wrong_heading_path(path) is wrong


def test_mkdocs_blocks_indented_by_four_spaces_are_counted() -> None:
    text = (
        '!!! note\n\n    Read as code.\n\n=== "Python"\n    ```py\n    x = 1\n    ```\n\n'
        "!!! tip\n\nNot indented.\n\n```md\n!!! note\n\n    inside a fence\n```\n"
    )

    assert mkdocs_blocks_as_code(text) == 2


# ---------------------------------------------------------------- coverage


def test_coverage_counts_sections_that_start_a_chunk_and_lists_the_rest() -> None:
    article = Article(
        key="p v1:a.md",
        source=None,
        chunks=(
            _chunk("# A\n", "A", headings=(("A",), ("A", "B"))),
            _chunk("## C\n", "A", "C"),
        ),
    )
    expected = [
        ("p v1:a.md", ("A",)),
        ("p v1:a.md", ("A", "B")),
        ("p v1:a.md", ("A", "C")),
        ("p v1:a.md", ("A", "D")),
        ("p v1:a.md", ("A",)),
    ]

    assert coverage([article], expected) == (
        4,
        2,
        3,
        ["p v1:a.md [A > B] (held)", "p v1:a.md [A > D]"],
    )


# ---------------------------------------------------------------- the whole measure


def test_measure_combines_every_metric() -> None:
    articles = [
        Article(
            key="p v1:guide.md",
            source="Intro.\n\n## One\n\nText.\n\n## Two\n\nMore {!examples/a.py!}\n",
            chunks=(
                _chunk("Intro.\n\n", headings=()),
                _chunk(
                    "## One\n\nText.\n\n## Two\n\nMore {!examples/a.py!}\n",
                    "One",
                    headings=(("One",), ("Two",)),
                ),
            ),
        ),
        Article(key="p v1:empty.md", source="", chunks=()),
        Article(
            key="p v1:link.md",
            source="# Readme\n\nLong text.\n",
            chunks=(_chunk("../README.md", "Readme"),),
        ),
        Article(
            key="p v1:swallowed.md", source="# A\n\n## B\n", chunks=(_chunk("# A\n\n## B\n", "A"),)
        ),
    ]

    metrics = measure(articles, [("p v1:guide.md", ("Two",)), ("p v1:link.md", ("Readme",))])

    assert metrics.model_dump(
        exclude={"examples", "missing_sections", "wrong_heading_examples"}
    ) == {
        "articles": 4,
        "articles_without_chunks": 1,
        "articles_without_h1": 1,
        "chunks": 4,
        "expected_sections": 2,
        "covered_sections": 1,
        "held_sections": 2,
        "coverage": 0.5,
        "cuts_in_code_fence": 0,
        "cuts_in_table": 0,
        "cuts_in_list": 0,
        "source_chars": len("Intro.##OneText.##TwoMore{!examples/a.py!}#ReadmeLongtext.#A##B"),
        "lost_chars": len("#ReadmeLongtext."),
        "tokens_p50": 3,
        "tokens_p95": 12,
        "tokens_max": 12,
        "small_chunks": 4,
        "small_share": 1.0,
        "multi_top_chunks": 1,
        "multi_top_share": 0.25,
        "empty_heading_paths": 1,
        "wrong_heading_paths": 0,
        "source_headings": 5,
        "headings_missed": 1,
        "headings_extra": 0,
        "unexpanded_includes": 1,
        "mkdocs_blocks_as_code": 0,
    }
    assert metrics.missing_sections == ["p v1:guide.md [Two] (held)"]
    assert metrics.examples == {
        "articles_without_chunks": ["p v1:empty.md"],
        "unexpanded_includes": ["p v1:guide.md"],
        "lost_chars": ["p v1:link.md"],
        "headings_missed": ["p v1:swallowed.md"],
    }


def test_nothing_measured_is_all_zero_and_fully_covered() -> None:
    metrics = measure([], [])

    assert (metrics.chunks, metrics.coverage, metrics.tokens_max, metrics.small_share) == (
        0,
        1.0,
        0,
        0,
    )


# ---------------------------------------------------------------- the match rule


def _hit(path: list[str], *, article: str = "a.md", commit: str = "c1") -> Hit:
    return Hit(version="v1", article=article, heading_path=path, commit_sha=commit)


@pytest.mark.parametrize(
    ("expected", "hit", "matches"),
    [
        (["A", "B"], ["A", "B"], True),  # the same section
        (["A"], ["A", "B"], True),  # a finer cut: part of the expected section
        (["A", "B", "C"], ["A", "B"], True),  # a coarser cut that holds it (below)
        (["A", "X"], ["A"], False),  # a coarser chunk that does not hold it
        (["A", "B"], ["A", "C"], False),
        ([], ["A"], False),  # text before the first heading is not a prefix of everything
        ([], [], True),
    ],
)
def test_the_nested_rule_holds_across_chunking_depths(
    expected: list[str], hit: list[str], matches: bool
) -> None:
    held = {("A", "B"): frozenset({("A", "B"), ("A", "B", "C")})}
    rule = nested_match(lambda h: held.get(tuple(h.heading_path), frozenset()))

    assert rule(_hit(expected), _hit(hit)) is matches


def test_the_nested_rule_needs_the_same_version_and_article() -> None:
    rule = nested_match(lambda _: frozenset())

    assert not rule(_hit(["A"]), _hit(["A"], article="b.md"))
    assert not rule(_hit(["A"]), Hit(version="v2", article="a.md", heading_path=["A"]))


async def test_the_golden_retriever_asks_the_question_s_project() -> None:
    class Fixed:
        def __init__(self, article: str) -> None:
            self.article = article

        async def answer(self, question: Question) -> Answer:
            return Answer(
                hits=[Hit(version=question.version, article=self.article, heading_path=[])]
            )

    retriever = GoldenRetriever(projects={"a": Fixed("a.md"), "b": Fixed("b.md")})

    answer = await retriever.answer(Question(query="q", version="v1", project="b"))

    assert answer.hits[0].article == "b.md"
    with pytest.raises(ValueError, match="no library for project 'c'"):
        await retriever.answer(Question(query="q", version="v1", project="c"))


# ---------------------------------------------------------------- the regression check


def _report(*, golden: str = "sha256:a", recall: float = 0.8, **totals: float) -> IngestionReport:
    metrics = measure([], []).model_copy(update=totals)
    bm25 = Bm25Result(
        answerable=10,
        recall_at_1=0.5,
        recall_at_5=recall,
        recall_at_10=0.9,
        mrr=0.6,
        recall_at_5_exact=recall,
        wrong_version_rate=0.0,
        misses=1,
        errors=[],
    )
    configuration = ConfigurationResult(
        name="default", about="", chunking={}, totals=metrics, bm25=bm25, versions=[]
    )
    return IngestionReport(golden=golden, cases=10, projects=["p"], configurations=[configuration])


def test_the_check_passes_an_equal_or_better_run() -> None:
    recorded = _report(coverage=0.9, cuts_in_code_fence=2)

    assert check(_report(coverage=0.9, cuts_in_code_fence=2), recorded) == []
    assert check(_report(coverage=1.0, cuts_in_code_fence=0, recall=0.9), recorded) == []


def test_the_check_reports_each_regression() -> None:
    recorded = _report(coverage=0.9, lost_chars=10, recall=0.8)

    problems = check(_report(coverage=0.8, lost_chars=11, recall=0.77), recorded)

    assert problems == [
        "default: coverage 0.8 is below the recorded 0.9",
        "default: lost_chars rose from 10 to 11",
        "default: BM25 recall@5 dropped 3.0 points (at most 2.0)",
    ]
    assert check(_report(recall=0.79), _report(recall=0.8)) == []


def test_the_check_refuses_a_report_of_another_golden_set() -> None:
    (problem,) = check(_report(golden="sha256:b"), _report(golden="sha256:a"))

    assert "golden set sha256:a" in problem
    assert "record this run" in problem


# ---------------------------------------------------------------- a run on a tiny corpus

GUIDE = f"""---
title: Guide
---
# Guide

Intro.

### Install

Run it.

{FENCE}sh
# not a heading
{FENCE}

## Use {{#use}}

Use it.
"""
TABS = f"""</Tab>
{FENCE}ts
const a = 1;

const b = 2;
{FENCE}

## Swallowed

Text.
"""


def _commit(repo: Path, tag: str, files: dict[str, str]) -> str:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git(
        "commit", "-q", "--no-verify", "-m", tag, cwd=repo,
        GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com",
        GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@example.com",
    )  # fmt: skip
    git("tag", tag, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def tiny(tmp_path: Path) -> list[str]:
    """A one-project corpus and golden set on disk; returns the CLI's corpus arguments."""
    repo = tmp_path / "upstream"
    git("init", "-q", "-b", "main", "--template=", str(repo))
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "README.md").symlink_to("../README.md")
    sha = _commit(
        repo,
        "v1",
        {"docs/guide.md": GUIDE, "docs/tabs.mdx": TABS, "README.md": "# Readme\n\nHi.\n"},
    )
    corpus = Corpus(
        projects=[
            Project(
                id="demo",
                title="Demo",
                repository=str(repo),
                include=["docs/"],
                licence="MIT",
                attribution="Copyright (c) A",
                versions=[PinnedVersion(name="v1", commit=sha)],
            )
        ]
    )
    (tmp_path / "corpus.yaml").write_text(yaml.safe_dump(corpus.model_dump(mode="json")), "utf-8")
    cases = tmp_path / "cases"
    cases.mkdir()
    case = {
        "name": "demo v1: How do I install it?",
        "inputs": {"query": "How do I install it?", "version": "v1", "project": "demo"},
        "metadata": {"kind": "how-to"},
        "expected_output": {
            "hits": [
                {"version": "v1", "article": "docs/guide.md", "heading_path": ["Guide", "Install"]}
            ],
            "reference": "Run it.",
            "facts": ["run it"],
        },
    }
    (cases / "demo.yaml").write_text(yaml.safe_dump({"name": "demo", "cases": [case]}), "utf-8")
    return [
        "--corpus", str(tmp_path / "corpus.yaml"), "--cases", str(cases),
        "--cache-dir", str(tmp_path / "cache"),
    ]  # fmt: skip


def test_article_sources_follow_a_symlink_and_leave_the_front_matter_out(
    tiny: list[str], tmp_path: Path
) -> None:
    main([*tiny, "--configs", "default", "--out", str(tmp_path / "out")])  # fetches the cache
    corpus = Corpus.model_validate(yaml.safe_load((tmp_path / "corpus.yaml").read_text("utf-8")))
    project = corpus.projects[0]

    bodies = article_sources(tmp_path / "cache" / "demo.git", project.versions[0].commit, project)

    assert bodies["docs/README.md"] == "# Readme\n\nHi.\n"
    assert bodies["docs/guide.md"] is not None
    assert bodies["docs/guide.md"].startswith("# Guide\n")


def test_a_run_compares_configurations_and_writes_the_report(
    tiny: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"

    assert main([*tiny, "--configs", "default,h2", "--out", str(out)]) == 0

    report = IngestionReport.model_validate_json((out / "ingestion.json").read_text("utf-8"))
    assert [c.name for c in report.configurations] == ["default", "h2"]
    default, h2 = report.configurations
    (version,) = default.versions
    assert (version.project, version.version) == ("demo", "v1")
    totals: IngestionMetrics = default.totals
    assert (totals.articles, totals.coverage, totals.wrong_heading_paths) == (3, 1.0, 1)
    # "## Swallowed" is code to CommonMark; the symlink came in as its target's path
    assert totals.headings_missed == 2
    assert totals.lost_chars == len("#ReadmeHi.")
    # "Install" is inside the "Guide" chunk: no chunk starts it, the nested rule still finds it
    assert (h2.totals.coverage, h2.totals.held_sections) == (0, 1)
    assert (default.bm25.recall_at_5, h2.bm25.recall_at_5, h2.bm25.recall_at_5_exact) == (1, 1, 0)
    assert json.loads((out / "ingestion.json").read_text("utf-8"))["schema_version"] == 1
    summary = (out / "ingestion.md").read_text("utf-8")
    assert "| `default` | 100.0% |" in summary
    assert "demo v1:docs/guide.md [Guide > Install] (held)" in summary
    assert summary in capsys.readouterr().out

    assert (
        main(
            [
                *tiny,
                "--configs",
                "default,h2",
                "--out",
                str(out),
                "--check",
                str(out / "ingestion.json"),
            ]
        )
        == 0
    )
