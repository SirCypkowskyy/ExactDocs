"""The text matcher (#491): which sections of which pinned versions a text result holds.

Two versions of one small guide: ``Install`` is the same in both, ``Configure`` changed in v2 and
``Lifespan`` exists only in v2.
"""

from pathlib import Path

import pytest

from retrieval_bench_stand_ins import tiny_corpus
from retrieval_eval.golden import fetch, load_corpus
from retrieval_eval.text_match import (
    Section,
    SectionIndex,
    TextMatch,
    Verdict,
    shingles,
    words,
)
from text_corpus import CONFIGURE_V1, CONFIGURE_V2, INSTALL, two_version_corpus, two_version_index

INDEX = two_version_index()
GUIDE = "docs/guide.md"


def _section(version: str, *path: str) -> Section:
    return Section(version=version, article=GUIDE, heading_path=("Guide", *path))


# ---------------------------------------------------------------- normalization


def test_words_drop_markup_and_fold_case() -> None:
    text = (
        "## The `on_startup` *Hook*\n\n"
        "1. See [the docs](https://example.com/docs?a=(b)) or https://example.com/x.\n"
        '<Tabs items={["a"]}>&amp; more</Tabs>\n'
        '```python title="app.py"\nprint(1)\n```'
    )

    assert words(text) == [
        "the", "on", "startup", "hook", "see", "the", "docs", "or", "more", "print", "1",
    ]  # fmt: skip


def test_a_short_text_is_one_shingle_and_an_empty_one_none() -> None:
    assert shingles(["a", "b"]) == frozenset({"a b"})
    assert shingles([]) == frozenset()
    assert len(shingles(list("abcdefg"))) == 3  # 5-word windows over 7 words


# ---------------------------------------------------------------- the cases the issue names


def test_an_exact_copy_answers_its_section_of_its_version_only() -> None:
    match = INDEX.match(CONFIGURE_V1)

    assert match.answers("v1", GUIDE, ["Guide", "Configure"])
    assert not match.answers("v2", GUIDE, ["Guide", "Configure"])
    assert match.verdict("v1") is Verdict.RIGHT


def test_a_partial_copy_answers_the_section_it_is_part_of() -> None:
    half = CONFIGURE_V1.split("\n\n", 2)[2]  # the second paragraph only, without the heading

    match = INDEX.match(half)

    assert match.answers("v1", GUIDE, ["Guide", "Configure"])
    assert match.answers("v1", GUIDE, ["Guide"])  # and the sections it is nested in
    assert match.verdict("v1") is Verdict.RIGHT


def test_reflowed_markdown_rendered_as_plain_text_still_matches() -> None:
    reflowed = " ".join(
        CONFIGURE_V1.replace("## Configure", "CONFIGURE")
        .replace("`timeout`", "timeout")
        .replace("[settings file](settings.md)", "settings file")
        .replace("- ", "* ")
        .split()
    )

    assert INDEX.match(reflowed).answers("v1", GUIDE, ["Guide", "Configure"])


def test_text_shared_by_both_versions_is_version_neutral() -> None:
    match = INDEX.match(INSTALL)

    assert match.answers("v1", GUIDE, ["Guide", "Install"])
    assert match.answers("v2", GUIDE, ["Guide", "Install"])
    assert match.verdict("v2") is Verdict.NEUTRAL
    assert match.verdict("v1") is Verdict.NEUTRAL


def test_text_of_another_version_only_is_wrong_for_the_version_asked() -> None:
    assert INDEX.match(CONFIGURE_V1).verdict("v2") is Verdict.WRONG
    assert INDEX.match(CONFIGURE_V2).verdict("v1") is Verdict.WRONG


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Kubernetes operators reconcile custom resources against the cluster's desired state.",
        "pip install",  # too little text to hold any section
    ],
    ids=["empty", "unrelated", "fragment"],
)
def test_text_that_holds_no_section_is_unmatched(text: str) -> None:
    match = INDEX.match(text)

    assert match.sections == frozenset()
    assert match.verdict("v1") is Verdict.UNMATCHED


# ---------------------------------------------------------------- coarser and finer results


def test_a_coarser_result_answers_every_section_it_holds() -> None:
    article = two_version_corpus()["v2"][GUIDE]

    match = INDEX.match(article)

    assert {
        _section("v2"),
        _section("v2", "Install"),
        _section("v2", "Configure"),
        _section("v2", "Lifespan"),
    } <= match.sections
    assert match.answers("v1", GUIDE, ["Guide", "Install"])  # shared, so neutral
    assert not match.answers("v1", GUIDE, ["Guide", "Configure"])  # changed in v2


def test_a_result_holding_a_section_whole_answers_it_whatever_else_it_holds() -> None:
    other = " ".join(f"unrelated filler sentence number {n} about nothing" for n in range(30))

    match = INDEX.match(f"{other}\n\n{INSTALL}")

    assert match.answers("v1", GUIDE, ["Guide", "Install"])
    assert not match.answers("v1", GUIDE, ["Guide", "Configure"])
    assert INDEX.match(other).sections == frozenset()


def test_the_threshold_decides_how_much_must_agree() -> None:
    own = words(CONFIGURE_V1)
    half = own[: len(own) // 2]
    text = " ".join([*half, *(f"filler{n}" for n in range(len(half)))])  # half the section

    assert not INDEX.match(text).answers("v1", GUIDE, ["Guide", "Configure"])
    assert INDEX.with_threshold(0.4).match(text).answers("v1", GUIDE, ["Guide", "Configure"])


def test_the_section_text_comes_with_its_subsections() -> None:
    text = INDEX.text_of(_section("v1"))

    assert "## Install" in text
    assert "## Configure" in text
    assert not INDEX.text_of(_section("v9"))


def test_a_project_is_indexed_from_its_cached_repository(tmp_path: Path) -> None:
    tiny_corpus(tmp_path)
    (project,) = load_corpus(tmp_path / "corpus.yaml").projects

    index = SectionIndex.of_project(project, fetch(project, tmp_path / "cache"))

    found = index.match("Set the timeout option in the settings file.")
    assert found == TextMatch(
        sections=frozenset({
            Section(version="v1", article="docs/guide.md", heading_path=("Guide", "Configure")),
            Section(version="v1", article="docs/guide.md", heading_path=("Guide",)),
        })
    )  # fmt: skip
