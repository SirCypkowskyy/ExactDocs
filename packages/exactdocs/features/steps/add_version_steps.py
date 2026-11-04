"""Steps for adding a version to a library over the REST API."""

from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context

from steps.import_steps import LIBRARY, import_version, wait_for_job


def _add(context: Context, library: str, ref: str) -> None:
    context.response = context.client.post(
        f"/api/v1/libraries{library}/versions", json={"ref": ref}
    )
    if context.response.status_code == HTTPStatus.ACCEPTED:
        wait_for_job(context, context.response.json()["job_id"])


@given('the fixture repository is imported at "{ref}" with paths "{paths}" excluding "{exclusion}"')
def step_given(context: Context, ref: str, paths: str, exclusion: str) -> None:
    import_version(context, ref, include_paths=[paths], exclude_paths=[exclusion])
    assert context.job["state"] == "succeeded", context.job


@when('the user adds the version "{ref}"')
def step_add(context: Context, ref: str) -> None:
    _add(context, LIBRARY, ref)


@when('the user adds "{ref}" to the library "{library}"')
def step_add_to(context: Context, ref: str, library: str) -> None:
    _add(context, library, ref)


@then('both "{first}" and "{second}" are listed')
def step_listed(context: Context, first: str, second: str) -> None:
    assert context.response.status_code == HTTPStatus.ACCEPTED, context.response.text
    assert context.job["state"] == "succeeded", context.job
    detail = context.client.get(f"/api/v1/libraries{LIBRARY}").json()
    assert sorted(v["ref"] for v in detail["versions"]) == sorted([first, second]), detail


@then("the response says the import was accepted and points to its job")
def step_location(context: Context) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    location = response.headers["Location"]
    assert location == f"/api/v1/jobs/{response.json()['job_id']}", location
    assert context.client.get(location).status_code == HTTPStatus.OK


@then('the default version is "{ref}"')
def step_default(context: Context, ref: str) -> None:
    assert context.response.status_code == HTTPStatus.ACCEPTED, context.response.text
    assert context.job["state"] == "succeeded", context.job
    detail = context.client.get(f"/api/v1/libraries{LIBRARY}").json()
    assert detail["default_version"] == ref, detail


@then('adding the version fails with "{code}"')
def step_fails(context: Context, code: str) -> None:
    assert context.response.status_code in {409, 422}, context.response.text
    assert context.response.json()["error"] == code, context.response.text
    jobs = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs").json()
    assert len(jobs["jobs"]) == 1, jobs  # only the first import


@then("the library is not found")
def step_not_found(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.NOT_FOUND, context.response.text
