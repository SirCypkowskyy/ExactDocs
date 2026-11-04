"""Steps for the rename map git gives each imported version."""

from http import HTTPStatus

from behave import given, then
from behave.runner import Context

from steps.import_steps import LIBRARY

GIT_MIN_SIMILARITY, FULL_SIMILARITY = 50, 100  # git reports renames from 50 percent


def _renamed_path(context: Context, ref: str, path: str, direction: str = "forward"):
    return context.client.get(
        f"/api/v1/libraries{LIBRARY}/renamed-path",
        params={"ref": ref, "path": path, "direction": direction},
    )


@given("git cannot compare two commits")
def step_git_cannot(context: Context) -> None:
    context.renames.failing = True


@then('the rename map of "{ref}" maps "{old}" to "{new}"')
def step_maps(context: Context, ref: str, old: str, new: str) -> None:
    response = _renamed_path(context, ref, old)
    assert response.status_code == HTTPStatus.OK, response.text
    found = response.json()["renamed"]
    assert (found["old_path"], found["new_path"], found["ref"]) == (old, new, ref), found
    assert found["from_ref"] == "v1.3.0", found
    assert GIT_MIN_SIMILARITY <= found["similarity"] <= FULL_SIMILARITY, found


@then('the rename map of "{ref}" has nothing for "{old}"')
def step_nothing(context: Context, ref: str, old: str) -> None:
    response = _renamed_path(context, ref, old)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json() == {"renamed": None}, response.text


@then('"{new}" of "{ref}" came from "{old}"')
def step_back(context: Context, new: str, ref: str, old: str) -> None:
    response = _renamed_path(context, ref, new, "back")
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["renamed"]["old_path"] == old, response.text


@then('the rename map of "{ref}" is not found')
def step_unknown(context: Context, ref: str) -> None:
    assert _renamed_path(context, ref, "docs/a.md").status_code == HTTPStatus.NOT_FOUND
