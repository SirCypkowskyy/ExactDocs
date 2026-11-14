"""The ingestion DTOs' and routes' descriptions name the limits the domain enforces."""

from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from exactdocs.ingestion.adapters.driving.http import build_auto_sync_router
from exactdocs.ingestion.constants import (
    MAX_LISTED_REFS,
    MAX_PREVIEW_FILES,
    UNEXPECTED_BACKOFF_CAP,
)
from exactdocs.ingestion.dtos import (
    AutoSyncOut,
    DisableAutoSyncCommand,
    GetAutoSyncQuery,
    RepositoryPreview,
    RepositoryRefs,
    SetAutoSyncCommand,
)


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


async def _get(query: GetAutoSyncQuery) -> AutoSyncOut:
    raise AssertionError(query)


async def _set(command: SetAutoSyncCommand) -> AutoSyncOut:
    raise AssertionError(command)


async def _disable(command: DisableAutoSyncCommand) -> AutoSyncOut:
    raise AssertionError(command)


def test_the_back_off_cap_is_a_whole_number_of_hours_above_one() -> None:
    # The auto-sync description prints the cap as "{n} hours": a cap of 90 minutes or of one
    # hour would print a wrong text without this guard.
    hours, rest = divmod(UNEXPECTED_BACKOFF_CAP, timedelta(hours=1))
    assert rest == timedelta(0)
    assert hours > 1


def test_setting_a_schedule_describes_the_longest_back_off_in_hours() -> None:
    app = FastAPI()
    app.include_router(
        build_auto_sync_router(get_auto_sync=_get, set_auto_sync=_set, disable_auto_sync=_disable)
    )
    operation = app.openapi()["paths"]["/libraries/{owner}/{repo}/auto-sync"]["put"]

    hours = UNEXPECTED_BACKOFF_CAP // timedelta(hours=1)
    assert f"(doubling, at most {hours} hours)" in operation["description"]
