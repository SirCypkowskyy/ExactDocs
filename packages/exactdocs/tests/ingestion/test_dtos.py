"""The ingestion DTOs' schema descriptions name the limits the use cases enforce."""

from typing import Any

from pydantic import BaseModel

from exactdocs.ingestion.constants import MAX_LISTED_REFS, MAX_PREVIEW_FILES
from exactdocs.ingestion.dtos import RepositoryPreview, RepositoryRefs


def field_schema(model: type[BaseModel], name: str) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")["properties"][name]


def test_a_ref_listings_truncated_description_names_how_many_refs_it_lists() -> None:
    description = field_schema(RepositoryRefs, "truncated")["description"]

    assert f"at most {MAX_LISTED_REFS} of each are listed" in description


def test_a_previews_files_description_names_how_many_files_it_lists() -> None:
    description = field_schema(RepositoryPreview, "files")["description"]

    assert f"at most {MAX_PREVIEW_FILES}." in description


def test_the_limits_stay_required_fields() -> None:
    assert "truncated" in RepositoryRefs.model_json_schema()["required"]
    assert "files" in RepositoryPreview.model_json_schema()["required"]
