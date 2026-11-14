import pytest

from exactdocs.ingestion import models
from exactdocs.ingestion.constants import MAX_TAG_RULES, PARSER_VERSION
from exactdocs.ingestion.errors import InvalidPathPatternError, InvalidTagError
from exactdocs.ingestion.models import (
    MAX_TAGS,
    ChunkingConfig,
    ImportedTags,
    TagRule,
    article_tags,
    chunking_config_hash,
    imported_tags,
    parse_article,
)

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


def test_imported_tags_keep_where_each_comes_from_also_when_both_give_one() -> None:
    found = imported_tags("docs/api/auth.md", ("api", "auth", "auth"), RULES)

    assert found == ImportedTags(tags=("api", "auth"), front_matter=("api", "auth"), rules=("api",))
    assert found.tags == article_tags("docs/api/auth.md", ("api", "auth"), RULES)


def test_sources_are_kept_whole_when_the_combined_tags_are_capped() -> None:
    declared = tuple(f"t{i}" for i in range(MAX_TAGS))

    found = imported_tags("docs/api/a.md", declared, RULES)

    assert found.tags == ("api", *declared[: MAX_TAGS - 1])
    assert (found.rules, found.front_matter) == (("api",), declared)


def test_rules_are_deduplicated_and_normalized() -> None:
    assert [(r.pattern, r.tag) for r in RULES] == [("docs/api/**", "api"), ("docs/adr/", "adr")]


def test_the_tags_of_an_article_are_capped_rule_tags_first() -> None:
    declared = tuple(f"t{i}" for i in range(MAX_TAGS))

    tags = article_tags("docs/api/a.md", declared, RULES)

    assert len(tags) == MAX_TAGS
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
    names = ", ".join(f"t{i}" for i in range(MAX_TAGS + 5))

    article = parse_article("a.md", f"---\ntags: [{names}]\n---\n")

    assert len(article.tags) == MAX_TAGS
    assert article.tags[-1] == f"t{MAX_TAGS - 1}"
    assert article.problems


def test_the_parser_bump_changes_the_chunk_set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ChunkingConfig()
    current = chunking_config_hash(config)
    monkeypatch.setattr(models, "PARSER_VERSION", 2)

    assert models.PARSER_VERSION != PARSER_VERSION == 3
    assert chunking_config_hash(config) != current
