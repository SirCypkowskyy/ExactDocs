"""pg_search's field boosts follow FTS5's column weights, saturated as FTS5's `bm25()` does."""

import pytest

from exactdocs.retrieval.constants import (
    HEADING_WEIGHT,
    IDENTIFIERS_WEIGHT,
    PATH_WEIGHT,
    PG_SEARCH_BOOSTS,
    TEXT_WEIGHT,
)

K1 = 1.2  # SQLite's bm25(): fixed


WEIGHTS = [HEADING_WEIGHT, PATH_WEIGHT, TEXT_WEIGHT, IDENTIFIERS_WEIGHT]


@pytest.mark.parametrize(("boost", "weight"), list(zip(PG_SEARCH_BOOSTS, WEIGHTS, strict=True)))
def test_a_boost_is_what_one_occurrence_in_its_fts5_column_scores_against_the_text(
    boost: float, weight: float
) -> None:
    assert boost == pytest.approx(weight * (K1 + 1) / (weight + K1), abs=0.001)


def test_the_boosts_order_the_fields_as_fts5_does() -> None:
    heading, path, text, identifiers = PG_SEARCH_BOOSTS

    assert heading > path > text == 1 > identifiers
    assert heading < 2.2  # saturated: never FTS5's raw 20, which lets any heading word win
