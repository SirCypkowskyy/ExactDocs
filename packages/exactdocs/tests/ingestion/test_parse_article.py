import json
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

    assert article.tags == ("setup", "getting-started")
    assert article.description == "How to install."
    # dates stay text and unknown keys are kept, so the metadata is JSON-serialisable
    assert article.front_matter["date"] == "2026-01-02"
    assert article.front_matter["weight"] == 3
    assert article.body == "# Not the title\n\nRun `uvx exactdocs`.\n"
    assert article.problems == ()


def test_crlf_front_matter_is_split_off_without_touching_the_body() -> None:
    article = parse_article("a.md", "---\r\ntitle: CRLF Title\r\n---\r\nBody\r\n")

    assert (article.title, article.body) == ("CRLF Title", "Body\r\n")


def test_malformed_front_matter_still_imports_the_article_and_lists_a_problem() -> None:
    article = parse_fixture("malformed.md")

    assert article.problems == ("malformed front matter: invalid YAML at line 2",)
    assert article.front_matter == {}
    assert article.body == (FIXTURES / "malformed.md").read_text(encoding="utf-8")  # nothing lost


def test_a_thematic_break_around_prose_is_body_text_without_a_problem() -> None:
    source = (FIXTURES / "not-a-mapping.md").read_text(encoding="utf-8")

    article = parse_fixture("not-a-mapping.md")

    assert (article.body, article.problems, article.front_matter) == (source, (), {})


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ("api, Auth", ("api", "auth")),
        ("[api, auth, API, ' Auth ']", ("api", "auth")),
        ("[]", ()),
    ],
)
def test_tags_are_trimmed_lower_cased_and_deduplicated(
    tags: str, expected: tuple[str, ...]
) -> None:
    article = parse_article("a.md", f"---\ntags: {tags}\n---\n")

    assert (article.tags, article.problems) == (expected, ())


@pytest.mark.parametrize("tags", ["[api, no, 2024, ~, [x, y]]", "[api, true, 1.5, {a: b}]"])
def test_tags_that_are_not_text_are_dropped_with_a_problem(tags: str) -> None:
    article = parse_article("a.md", f"---\ntags: {tags}\n---\n")

    assert article.tags == ("api",)
    assert article.problems == ("front matter tags must be text; other items were ignored",)


def test_tags_of_a_wrong_type_are_ignored_with_a_problem() -> None:
    article = parse_article("a.md", "---\ntags: {a: 1}\n---\n")

    assert article.tags == ()
    assert article.problems == ("front matter tags must be a list or a string",)


@pytest.mark.parametrize("title", ["404", "No", "[a, b]"])
def test_a_title_that_is_not_text_falls_back_with_a_problem(title: str) -> None:
    article = parse_article("a.md", f"---\ntitle: {title}\n---\n# Heading\n")

    assert article.title == "Heading"
    assert article.problems == ("front matter title must be text",)


UNSAFE_FRONT_MATTER = {
    "python object": "title: !!python/object/apply:os.system ['exit 1']",
    "billion laughs": (
        "a: &a [x, x, x, x, x, x, x, x, x, x]\n"
        "b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]\n"
        "c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]\n"
        "d: [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]"
    ),
    "recursive alias": "a: &a [*a]",
    "alias of a scalar": "a: &x 1\nb: *x",
    "anchor alone": "a: &x 1",
    "binary": "title: !!binary aGk=",
    "set": "tags: !!set {a, b}",
    "explicit timestamp": "date: !!timestamp 2026-01-01",
    "omap": "x: !!omap [a: 1]",
    "infinity": "x: .inf",
    "not a number": "x: .nan",
    "non-text key": "1: a",
    "boolean key": "yes: a",
    "nested bytes": "x: [{y: !!binary aGk=}]",
}


@pytest.mark.parametrize("front_matter", UNSAFE_FRONT_MATTER.values(), ids=UNSAFE_FRONT_MATTER)
def test_unsafe_front_matter_is_a_problem_and_never_reaches_the_metadata(
    front_matter: str,
) -> None:
    source = f"---\n{front_matter}\n---\n# Heading\n"

    article = parse_article("a.md", source)

    assert [p.startswith("malformed front matter: ") for p in article.problems] == [True]
    assert article.front_matter == {}
    assert article.tags == ()
    assert article.body == source  # nothing is lost
    assert article.title == "Heading"


def test_aliases_are_reported_with_their_line() -> None:
    article = parse_article("a.md", "---\na: &x 1\nb: *x\n---\n")

    assert article.problems == (
        "malformed front matter: anchors and aliases are not allowed at line 2",
    )


@pytest.mark.parametrize(
    "name",
    [p.relative_to(FIXTURES).as_posix() for p in sorted(FIXTURES.rglob("*.md*"))],
)
def test_front_matter_of_every_fixture_is_json_serialisable(name: str) -> None:
    json.dumps(parse_fixture(name).front_matter, allow_nan=False)


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
ENGLAND = (
    "\N{WAVING BLACK FLAG}" + "".join(chr(0xE0000 + ord(c)) for c in "gbeng") + "\N{CANCEL TAG}"
)


@pytest.mark.parametrize(
    ("hidden", "clean"),
    [
        (f"Ign{ZWSP}ore", "Ignore"),
        (f"{BIDI_OVERRIDE}drow{BIDI_OVERRIDE}", "drow"),
        (f"{BOM}# Title", "# Title"),
        (f"hi{TAG_A}{TAG_A}", "hi"),
        (f"{ENGLAND} and {ENGLAND}", f"{ENGLAND} and {ENGLAND}"),  # subdivision flags are visible
        (f"hi{TAG_A}{ENGLAND}{TAG_A}", f"hi{ENGLAND}"),  # only tags outside a flag go
        (f"\N{WAVING BLACK FLAG}{TAG_A}", "\N{WAVING BLACK FLAG}"),  # incomplete flag
        ("a\N{VARIATION SELECTOR-17}\N{VARIATION SELECTOR-256}b", "ab"),
        (
            "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}",
            "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}",
        ),
        ("1\N{INVISIBLE TIMES}2\N{INVISIBLE SEPARATOR}3\N{FUNCTION APPLICATION}", "123"),
        ("a\N{COMBINING GRAPHEME JOINER}b\N{BRAILLE PATTERN BLANK}c", "abc"),
        ("a\N{HANGUL FILLER}\N{HANGUL CHOSEONG FILLER}\N{KHMER VOWEL INHERENT AQ}b", "ab"),
        ("\x1b[31mred\x1b[0m\x00\x7f\x85", "[31mred[0m"),  # ANSI escapes, NUL, DEL, NEL
        ("tab\there\nnew\r\nline", "tab\there\nnew\r\nline"),  # \t \n \r survive
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
