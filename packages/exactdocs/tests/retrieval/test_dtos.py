"""The retrieval DTOs' schema descriptions name the limits the domain enforces."""

from typing import Any

import pytest
from pydantic import BaseModel

from exactdocs.retrieval.adapters.driving.http import LibraryRetrievalIn
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
