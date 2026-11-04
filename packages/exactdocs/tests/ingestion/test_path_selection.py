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
        (["/docs/", " ./README.md "], [], ["README.md", *ALL_ARTICLES[1:6]]),
        (["docs/guide/*.{png,mdx}"], [], ["docs/guide/setup.mdx"]),  # a png is no article
    ],
)
def test_the_selection_table(include: list[str], exclude: list[str], expected: list[str]) -> None:
    assert sorted(selected(include, exclude)) == sorted(expected)


def test_patterns_are_normalised_and_deduplicated() -> None:
    selection = PathSelection.of(["/docs/", "docs/", " ./x.md"], [" a "])

    assert selection == PathSelection(include=("docs/", "x.md"), exclude=("a",))


@pytest.mark.parametrize(
    "pattern", ["", "  ", "../etc", "a/../b", "a\\b", "{a,b", "x" * 300, "a\x00b"]
)
def test_unusable_patterns_are_refused(pattern: str) -> None:
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([pattern])
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([], [pattern])


def test_too_many_patterns_are_refused() -> None:
    with pytest.raises(InvalidPathPatternError):
        PathSelection.of([f"d{i}/" for i in range(65)])
