import time

import pytest

from exactdocs.ingestion.errors import InvalidPathPatternError
from exactdocs.ingestion.models import PathSelection

PATHS = [
    "README.md",
    "docs/index.md",
    "docs/guide/setup.mdx",
    "docs/guide/setup.png",
    "docs/guide/UPPER.MD",
    "docs/archive/old.md",
    "docs/archive/deep/older.md",
    "docs-old/readme.md",
    "src/lib.py",
    "src/NOTES.md",
    "a.md.bak",
]


def selected(include: list[str], exclude: list[str] | None = None) -> list[str]:
    selection = PathSelection.of(include, exclude or [])
    return [path for path in PATHS if selection.selects(path)]


ALL_ARTICLES = [
    "README.md",
    "docs/index.md",
    "docs/guide/setup.mdx",
    "docs/guide/UPPER.MD",
    "docs/archive/old.md",
    "docs/archive/deep/older.md",
    "docs-old/readme.md",
    "src/NOTES.md",
]


@pytest.mark.parametrize(
    ("include", "exclude", "expected"),
    [
        ([], [], ALL_ARTICLES),  # empty means every .md/.mdx file, whatever the case
        (["**/*.{md,mdx}"], [], [p for p in ALL_ARTICLES if p != "docs/guide/UPPER.MD"]),
        (["docs/"], [], ALL_ARTICLES[1:6]),  # a folder, and not its namesake docs-old
        (["docs"], [], ALL_ARTICLES[1:6]),
        (["docs/**"], [], ALL_ARTICLES[1:6]),
        (["docs/*.md"], [], ["docs/index.md"]),  # * stays in one level
        (
            ["docs/**/*.md"],
            [],
            ["docs/index.md", "docs/archive/old.md", "docs/archive/deep/older.md"],
        ),
        (["README.md", "src/NOTES.md"], [], ["README.md", "src/NOTES.md"]),
        (["*.md"], [], ["README.md"]),
        (["docs/index.m?"], [], ["docs/index.md"]),
        (
            ["docs/**"],
            ["docs/archive/**"],
            ["docs/index.md", "docs/guide/setup.mdx", "docs/guide/UPPER.MD"],
        ),
        (
            ["docs/"],
            ["docs/archive/"],
            ["docs/index.md", "docs/guide/setup.mdx", "docs/guide/UPPER.MD"],
        ),
        (
            ["docs/"],
            ["docs/archive"],
            ["docs/index.md", "docs/guide/setup.mdx", "docs/guide/UPPER.MD"],
        ),
        (
            [],
            ["**/archive/**", "docs-old"],
            [
                "README.md",
                "docs/index.md",
                "docs/guide/setup.mdx",
                "docs/guide/UPPER.MD",
                "src/NOTES.md",
            ],
        ),
        (["docs/"], ["**"], []),  # exclusions win, even over everything
        (["./docs/", " ./README.md "], [], ["README.md", *ALL_ARTICLES[1:6]]),
        (["docs/guide/*.{png,mdx}"], [], ["docs/guide/setup.mdx"]),  # a png is no article
    ],
)
def test_the_selection_table(include: list[str], exclude: list[str], expected: list[str]) -> None:
    assert sorted(selected(include, exclude)) == sorted(expected)


def test_patterns_are_normalised_and_deduplicated() -> None:
    selection = PathSelection.of(["./docs/", "docs/", " ./x.md"], [" a "])

    assert selection == PathSelection(include=("docs/", "x.md"), exclude=("a",))


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "  ",
        "/etc/x",
        "/",
        "../etc",
        "a/../b",
        "a//b",
        "a/./b",
        "a\\b",
        "{a,b",
        "x" * 300,
        "a\x00b",
    ],
)
def test_unusable_patterns_are_refused(pattern: str) -> None:
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([pattern])
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([], [pattern])


def test_too_many_patterns_are_refused() -> None:
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([f"d{i}/" for i in range(65)])


def test_patterns_are_case_sensitive_but_the_suffix_is_not() -> None:
    selection = PathSelection.of(["Docs/"])

    assert not selection.selects("docs/a.md")
    assert selection.selects("Docs/a.MD")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("d/{a,b}.md", "d/a.md", True),
        ("d/{a,b}.md", "d/c.md", False),
        ("d/{}.md", "d/.md", True),  # {} is a choice of the empty text
        ("d/{}.md", "d/x.md", False),
        ("d/{a,{b,c}}.md", "d/a}.md", True),  # braces do not nest: it ends at the first }
        ("d/{a,{b,c}}.md", "d/a.md", False),
        ("d/{a,{b,c}}.md", "d/{b}.md", True),
        ("d/a}.md", "d/a}.md", True),  # a lone } is a plain character
        ("d/a**b.md", "d/axxb.md", True),  # ** inside a name is a *
        ("d/a**b.md", "d/x/b.md", False),
        ("**/c.md", "c.md", True),  # ** also matches no folder at all
        ("a/**/c.md", "a/c.md", True),
        ("a/**/c.md", "a/b/b/c.md", True),
    ],
)
def test_braces_and_wildcards_in_detail(pattern: str, path: str, expected: bool) -> None:
    assert PathSelection.of([pattern]).selects(path) is expected


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("/".join(["**"] * 60) + "/zzz.md", "a/" * 200 + "q.md"),  # 120 stacked globstars
        ("/".join(["**/*"] * 30) + "/zzz.md", "a/" * 400 + "q.md"),
        ("*a" * 60 + "*z.md", "a" * 250 + ".md"),  # stacked wildcards inside one name
        ("**" * 100 + "z.md", "a" * 250 + "/" + "a" * 250 + ".md"),
        ("{a,aa,aaa}" * 20 + "z.md", "a" * 250 + ".md"),
        ("?*" * 60 + "z.md", "a" * 250 + ".md"),
    ],
)
def test_hostile_patterns_finish_fast(pattern: str, path: str) -> None:
    selection = PathSelection.of([pattern])
    started = time.perf_counter()

    assert not selection.selects(path)
    assert time.perf_counter() - started < 0.05
