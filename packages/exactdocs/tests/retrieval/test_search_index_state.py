import pytest

from exactdocs.retrieval.models import SearchIndexState


@pytest.mark.parametrize(
    ("stored", "needs_rebuild"),
    [
        pytest.param(1, True, id="older: built the old way"),
        pytest.param(2, False, id="current"),
        pytest.param(3, False, id="newer: a later release built it, this one was downgraded to"),
        pytest.param(None, True, id="unrecorded: rebuilding records it"),
    ],
)
def test_a_reindex_is_needed_only_for_an_older_or_unrecorded_format(
    stored: int | None, needs_rebuild: bool
) -> None:
    state = SearchIndexState(stored_format=stored, current_format=2, engine="fts5")

    assert state.needs_rebuild is needs_rebuild
