import pytest

from exactdocs.ingestion.errors import InvalidPathPatternError, InvalidTagError
from exactdocs.ingestion.models import (
    MAX_ARTICLE_TAGS,
    MAX_TAG_RULES,
    TagRule,
    article_tags,
    normalize_tag,
    parse_article,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" API ", "api"),
        ("Getting  Started", "getting-started"),
        ("v1.2+beta", "v1.2+beta"),
        ("\uff21\uff30\uff29", "api"),  # full-width letters, NFKC
        ("zażółć", "zażółć"),
        ("c++", "c++"),
        ("a" * 40, "a" * 40),
        ("a" * 41, None),
        ("", None),
        ("-lead", None),
        ("_lead", None),
        ("a,b", None),
        ("a/b", None),
        ("<script>", None),
        ("emoji\U0001f600", None),
    ],
)
def test_a_tag_has_one_form_or_is_refused(raw: str, expected: str | None) -> None:
    assert normalize_tag(raw) == expected


RULES = TagRule.many([("docs/api/**", "API"), ("docs/adr/", "adr"), ("docs/api/**", "api")])


@pytest.mark.parametrize(
    ("path", "declared", "expected"),
    [
        ("docs/api/auth.md", ("auth",), ("api", "auth")),  # the scenario of the issue
        ("docs/api/auth.md", ("api", "auth"), ("api", "auth")),  # no duplicates
        ("docs/adr/0001.md", (), ("adr",)),
        ("docs/guide/a.md", ("x",), ("x",)),
        ("docs/api/auth.png", ("x",), ("x",)),  # a rule never makes a non-article one
        ("docs/api/a/b/c.md", (), ("api",)),
    ],
)
def test_front_matter_and_path_rule_tags_combine(
    path: str, declared: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert article_tags(path, declared, RULES) == expected


def test_rules_are_deduplicated_and_normalized() -> None:
    assert [(r.pattern, r.tag) for r in RULES] == [("docs/api/**", "api"), ("docs/adr/", "adr")]


def test_the_tags_of_an_article_are_capped_rule_tags_first() -> None:
    declared = tuple(f"t{i}" for i in range(MAX_ARTICLE_TAGS))

    tags = article_tags("docs/api/a.md", declared, RULES)

    assert len(tags) == MAX_ARTICLE_TAGS
    assert tags[0] == "api"


def test_a_rule_with_a_bad_tag_or_glob_is_refused() -> None:
    with pytest.raises(InvalidTagError):
        TagRule.of("docs/**", "not a tag!")
    with pytest.raises(InvalidPathPatternError):
        TagRule.of("../x", "api")


def test_too_many_rules_are_refused() -> None:
    with pytest.raises(InvalidTagError):
        TagRule.many([(f"d{i}/**", "t") for i in range(MAX_TAG_RULES + 1)])


def test_front_matter_tags_that_are_no_tags_are_dropped_with_a_problem() -> None:
    article = parse_article("a.md", "---\ntags: [api, 'not a tag!', '<b>', Auth]\n---\n")

    assert article.tags == ("api", "auth")
    assert article.problems == ("front matter tags: 2 invalid ignored, at most 20 kept",)


def test_front_matter_tags_are_capped() -> None:
    names = ", ".join(f"t{i}" for i in range(MAX_ARTICLE_TAGS + 5))

    article = parse_article("a.md", f"---\ntags: [{names}]\n---\n")

    assert len(article.tags) == MAX_ARTICLE_TAGS
    assert article.tags[-1] == f"t{MAX_ARTICLE_TAGS - 1}"
    assert article.problems
