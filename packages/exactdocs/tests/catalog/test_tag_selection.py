import pytest

from exactdocs.catalog.errors import InvalidTagFilterError
from exactdocs.catalog.models import TagMatch, TagSelection


@pytest.mark.parametrize(
    ("match", "article", "kept"),
    [
        (TagMatch.ANY, ("api",), True),
        (TagMatch.ANY, ("auth",), False),
        (TagMatch.ANY, (), False),
        (TagMatch.ALL, ("api", "adr", "x"), True),
        (TagMatch.ALL, ("api",), False),
    ],
)
def test_any_needs_one_tag_and_all_needs_every_tag(
    match: TagMatch, article: tuple[str, ...], kept: bool
) -> None:
    assert TagSelection.of(["api", "adr"], match).keeps(article) is kept


def test_an_empty_filter_keeps_every_article() -> None:
    assert TagSelection.of([]).keeps(())


def test_values_are_normalized_like_tags() -> None:
    assert TagSelection.of([" API ", "api", "Getting Started"]).tags == {"api", "getting-started"}


@pytest.mark.parametrize("bad", ["not a tag!", "-x", "a" * 41, "", "a,b"])
def test_a_value_that_is_no_tag_is_refused(bad: str) -> None:
    with pytest.raises(InvalidTagFilterError):
        TagSelection.of(["api", bad])


def test_too_many_values_are_refused() -> None:
    with pytest.raises(InvalidTagFilterError):
        TagSelection.of([f"t{i}" for i in range(21)])
