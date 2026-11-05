"""Steps for the import preview (dry run) over the REST API."""

from http import HTTPStatus

from behave import then, when
from behave.runner import Context


def _preview(context: Context, ref: str, include: str, exclude: list[str]) -> None:
    context.response = context.client.post(
        "/api/v1/repositories/preview",
        json={
            "url": context.fixture_repo.file_url,
            "ref": ref,
            "include_paths": [include],
            "exclude_paths": exclude,
        },
    )


@when('a user previews the fixture repository at "{ref}" with paths "{paths}"')
def step_preview(context: Context, ref: str, paths: str) -> None:
    _preview(context, ref, paths, [])


@when('a user dry-runs "{paths}" excluding "{exclusion}" at "{ref}" of the fixture repository')
def step_preview_excluding(context: Context, ref: str, paths: str, exclusion: str) -> None:
    _preview(context, ref, paths, [exclusion])


@then("the matching files are listed with their count")
def step_listed(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert body["files"], body
    assert body["total"] == len(body["files"]), body
    assert not body["truncated"], body


@then('none of the listed files is under "{folder}"')
def step_none_under(context: Context, folder: str) -> None:
    assert not any(f.startswith(folder) for f in context.response.json()["files"])


@then("no library, version or job exists afterwards")
def step_nothing_stored(context: Context) -> None:
    assert (
        context.client.get("/api/v1/libraries/fixture/docs-repo").status_code
        == HTTPStatus.NOT_FOUND
    )
    assert context.client.get("/api/v1/jobs/latest").json()["jobs"] == []
