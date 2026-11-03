from pathlib import Path

import pytest

from exactdocs.ingestion.models import PARSER_VERSION, parse_article, strip_invisible

FIXTURES = Path(__file__).parent / "fixtures"


def parse_fixture(name: str):
    return parse_article(name, (FIXTURES / name).read_text(encoding="utf-8", newline=""))


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("guide/install.md", "Install ExactDocs"),  # front matter beats the H1
        ("guide/auth.md", "Authentication"),  # H1
        ("notes.md", "notes"),  # file name
        ("setext.md", "Setext Title"),  # setext H1; "# not a heading" in a fence is skipped
        ("code-first.md", "exactdocs CLI"),  # a fenced comment is not an H1; code span is text
        ("blank-title.md", "Blank Title Falls Through"),
        ("empty-front-matter.md", "After empty front matter"),
        ("mdx-page.mdx", "Tabs example"),
        ("malformed.md", "Real Title"),
        ("not-a-mapping.md", "Heading"),
    ],
)
def test_title_follows_front_matter_then_h1_then_file_name(name: str, title: str) -> None:
    assert parse_fixture(name).title == title


def test_front_matter_is_metadata_and_not_part_of_the_body() -> None:
    article = parse_fixture("guide/install.md")

    assert article.tags == ("setup", "getting started")
    assert article.description == "How to install."
    # dates stay text and unknown keys are kept, so the metadata is JSON-serialisable
    assert article.front_matter["date"] == "2026-01-02"
    assert article.front_matter["weight"] == 3
    assert article.body == "# Not the title\n\nRun `uvx exactdocs`.\n"
    assert article.problems == ()


def test_crlf_front_matter_is_split_off_without_touching_the_body() -> None:
    article = parse_article("a.md", "---\r\ntitle: CRLF Title\r\n---\r\nBody\r\n")

    assert (article.title, article.body) == ("CRLF Title", "Body\r\n")


@pytest.mark.parametrize("name", ["malformed.md", "not-a-mapping.md"])
def test_malformed_front_matter_still_imports_the_article_and_lists_a_problem(name: str) -> None:
    article = parse_fixture(name)

    assert [p.startswith("malformed front matter") for p in article.problems] == [True]
    assert article.front_matter == {}
    assert article.body == (FIXTURES / name).read_text(encoding="utf-8")  # nothing is lost


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ("api, auth", ("api", "auth")),
        ("[api, auth, api]", ("api", "auth")),
        ("[1, 2]", ("1", "2")),
        ("[]", ()),
    ],
)
def test_tags_accept_a_list_or_a_comma_separated_string(
    tags: str, expected: tuple[str, ...]
) -> None:
    assert parse_article("a.md", f"---\ntags: {tags}\n---\n").tags == expected


def test_tags_of_a_wrong_type_are_ignored_with_a_problem() -> None:
    article = parse_article("a.md", "---\ntags: {a: 1}\n---\n")

    assert article.tags == ()
    assert article.problems == ("front matter tags must be a list or a string",)


def test_yaml_is_never_constructed_into_python_objects() -> None:
    article = parse_article("a.md", "---\ntitle: !!python/object/apply:os.system ['exit 1']\n---\n")

    assert article.front_matter == {}
    assert article.problems  # rejected by the safe loader
    assert article.title == "a"


def test_mdx_imports_exports_and_jsx_stay_as_text() -> None:
    source = (FIXTURES / "mdx-page.mdx").read_text(encoding="utf-8")

    article = parse_article("mdx-page.mdx", source)

    assert article.body == source.split("---\n", 2)[2]
    assert "import { Tabs, Tab }" in article.body
    assert "<Tabs>" in article.body
    assert "{1 + 1}" in article.body


ZWSP = "\N{ZERO WIDTH SPACE}"
BIDI_OVERRIDE = "\N{RIGHT-TO-LEFT OVERRIDE}"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
TAG_A = "\N{TAG LATIN SMALL LETTER A}"
ZWJ = "\N{ZERO WIDTH JOINER}"
ZWNJ = "\N{ZERO WIDTH NON-JOINER}"


@pytest.mark.parametrize(
    ("hidden", "clean"),
    [
        (f"Ign{ZWSP}ore", "Ignore"),
        (f"{BIDI_OVERRIDE}drow{BIDI_OVERRIDE}", "drow"),
        (f"{BOM}# Title", "# Title"),
        (f"hi{TAG_A}{TAG_A}", "hi"),
        (f"a{ZWJ}b{ZWNJ}c{ZWNJ}", "abc"),  # next to ASCII
        (f"\N{GRINNING FACE}{ZWJ}{ZWJ}{ZWJ}\N{GRINNING FACE}", "\N{GRINNING FACE}" * 2),  # a run
        (f"\N{WOMAN}{ZWJ}\N{ROCKET}", f"\N{WOMAN}{ZWJ}\N{ROCKET}"),  # emoji sequence is kept
        ("می‌خواهم", "می‌خواهم"),  # Persian
    ],
)
def test_invisible_characters_are_removed(hidden: str, clean: str) -> None:
    assert strip_invisible(hidden) == clean


def test_everything_else_is_verbatim() -> None:
    source = (
        "---\ntitle: T\n---\n"
        "# H\r\n\ttabs, trailing spaces  \n\n"
        "café \N{NO-BREAK SPACE} \N{SOFT HYPHEN} \N{EM SPACE} 中文 \N{GRINNING FACE}\n"
        "```py\nx = 1  # keep\n```\n"
    )
    noisy = source.replace("# H", f"# H{ZWSP}").replace("keep", f"ke{BIDI_OVERRIDE}ep")

    article = parse_article("a.md", noisy)

    assert article.body == source.split("---\n", 2)[2]
    assert article.title == "T"


def test_hidden_characters_cannot_hide_the_front_matter() -> None:
    article = parse_article("a.md", f"{BOM}---\ntitle: Visible\n---\nbody")

    assert (article.title, article.body) == ("Visible", "body")


def test_parser_version_is_an_integer_that_feeds_the_chunking_hash() -> None:
    assert isinstance(PARSER_VERSION, int)
