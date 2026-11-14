"""The retrieval DTOs' schema descriptions name the limits the domain enforces."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from exactdocs.retrieval.adapters.driving.http import C7Library, LibraryRetrievalIn
from exactdocs.retrieval.constants import (
    AGENT_STEP_ARGUMENT_CHARS,
    CHARS_PER_TOKEN,
    DEFAULT_RERANK_TOP_N,
    ESTIMATE_NOTE,
    MAX_EXPLORED_STEPS,
    MAX_JUSTIFICATION_CHARS,
    MAX_RERANK_TOP_N,
    MAX_RESOLVED,
    QUERY_HITS_CAP,
)
from exactdocs.retrieval.dtos import (
    ChunkHeadingIn,
    ChunkIn,
    ChunkOut,
    EmbeddingEstimateOut,
    LibraryMatchOut,
    ResolveLibraryIdResult,
    SearchResultOut,
    SetLibraryRetrievalCommand,
)


def field_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")["properties"][name]


def test_a_justifications_description_names_its_length_limit() -> None:
    description = field_schema(SearchResultOut, "justification")["description"]

    assert f"at most {MAX_JUSTIFICATION_CHARS} characters" in description


def test_an_explored_paths_description_names_its_limits() -> None:
    description = field_schema(SearchResultOut, "explored_path")["description"]

    assert f"at most {MAX_EXPLORED_STEPS};" in description
    assert f"at most {AGENT_STEP_ARGUMENT_CHARS} characters" in description


def test_resolved_matches_and_query_hits_name_their_caps() -> None:
    matches = field_schema(ResolveLibraryIdResult, "matches")["description"]
    hits = field_schema(LibraryMatchOut, "query_hits")["description"]

    assert f"at most {MAX_RESOLVED}" in matches
    assert f"counted up to {QUERY_HITS_CAP}" in hits


@pytest.mark.parametrize("model", [LibraryRetrievalIn, SetLibraryRetrievalCommand])
def test_a_libraries_rerank_top_n_description_agrees_with_its_schema(
    model: type[BaseModel],
) -> None:
    schema = model.model_json_schema()["properties"]["rerank_top_n"]

    assert f"(1 to {MAX_RERANK_TOP_N})" in schema["description"]
    assert f"{DEFAULT_RERANK_TOP_N} by default" in schema["description"]
    assert schema["anyOf"][0]["maximum"] == MAX_RERANK_TOP_N


def test_an_embedding_estimate_names_the_characters_per_token() -> None:
    description = field_schema(EmbeddingEstimateOut, "estimated_tokens")["description"]

    assert f"`characters` / {CHARS_PER_TOKEN}" in description
    assert f"{CHARS_PER_TOKEN} characters per token" in ESTIMATE_NOTE


@pytest.mark.parametrize("model", [LibraryMatchOut, C7Library])
def test_a_libraries_versions_description_says_which_refs_are_listed(
    model: type[BaseModel],
) -> None:
    description = field_schema(model, "versions")["description"]

    assert "the default version and the most recently imported ones" in description
    assert "possibly not all" in description


@pytest.mark.parametrize("model", [SearchResultOut, ChunkOut])
def test_a_heading_path_description_reads_as_one_line(model: type[BaseModel]) -> None:
    description = field_schema(model, "heading_path")["description"]

    assert "\n" not in description
    assert description.endswith("empty before the first heading.")


def _chunk(
    heading_path: list[str], headings: list[tuple[list[str], str, bool]], part: int = 1
) -> ChunkIn:
    return ChunkIn(
        heading_path=heading_path,
        occurrence_index=0,
        part=part,
        content="more text\n",
        content_hash="h",
        anchor="guide" if heading_path else "",
        headings=[ChunkHeadingIn(heading_path=p, anchor=a, starts_chunk=s) for p, a, s in headings],
    )


@pytest.mark.parametrize(
    ("heading_path", "headings"),
    [
        (["Guide"], []),
        (["Guide"], [(["Guide", "Install"], "install", False)]),
        ([], []),
    ],
    ids=["holding-none", "holding-a-merged-heading", "text-before-the-first-heading"],
)
def test_a_part_after_the_first_of_a_split_section_needs_no_heading_record_of_its_own(
    heading_path: list[str], headings: list[tuple[list[str], str, bool]]
) -> None:
    assert _chunk(heading_path, headings).part == 1


def test_a_part_after_the_first_that_starts_with_its_own_heading_is_refused() -> None:
    with pytest.raises(ValidationError, match="holds no heading of its own"):
        _chunk(["Guide"], [(["Guide"], "guide", True)])


@pytest.mark.parametrize(
    ("heading_path", "headings"),
    [
        (["Guide"], [(["Other"], "other", True)]),
        (["Guide"], [(["Guide", "Install"], "install", False), (["Guide"], "guide", True)]),
        ([], [(["Guide"], "guide", True)]),
        (["Guide"], []),
        (["Guide"], [(["Guide", "Install"], "install", False)]),
    ],
    ids=[
        "another-heading-starts-it",
        "not-the-first-record",
        "text-before-the-first-heading",
        "own-heading-missing",
        "only-a-merged-heading",
    ],
)
def test_a_heading_record_that_contradicts_a_first_part_is_refused(
    heading_path: list[str], headings: list[tuple[list[str], str, bool]]
) -> None:
    with pytest.raises(ValidationError, match="the chunk's own heading"):
        _chunk(heading_path, headings, part=0)


def test_a_part_index_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        _chunk(["Guide"], [], part=-1)
