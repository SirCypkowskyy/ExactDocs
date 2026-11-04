"""Steps for checking a git URL over the REST API."""

from http import HTTPStatus
from urllib.parse import urlsplit

from behave import given, then, when
from behave.runner import Context


def _fill(context: Context, url: str) -> str:
    """Point `<fixtures>` and `<port>` at the running fixture servers."""
    fixtures = context.fixture_repo.path.parents[1]
    port = urlsplit(context.fixture_repo.http_url).port
    return url.replace("<fixtures>", fixtures.as_posix()).replace("<port>", str(port))


@given('library "{library_id}" exists from GitHub')
def step_library_exists(context: Context, library_id: str) -> None:
    response = context.client.get(f"/api/v1/libraries{library_id}")
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["host"] == "github"


@when('a user checks the repository URL "{url}"')
@when('a user checks "{url}"')
def step_check(context: Context, url: str) -> None:
    context.response = context.client.post(
        "/api/v1/repositories/check", json={"url": _fill(context, url)}
    )


@then('it is accepted with the proposed library ID "{library_id}"')
def step_accepted(context: Context, library_id: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["library_id"] == library_id, context.response.text


@then('the default branch is "{branch}"')
def step_default_branch(context: Context, branch: str) -> None:
    assert context.response.json()["default_branch"] == branch


@then("the user is asked to choose another library ID")
def step_taken(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.CONFLICT, context.response.text
    body = context.response.json()
    assert body["error"] == "library_id_taken"
    assert "choose another library ID" in body["detail"]


@then('the check fails with "{code}"')
def step_fails(context: Context, code: str) -> None:
    assert context.response.status_code in {409, 422}, context.response.text
    assert context.response.json()["error"] == code, context.response.text


@then('the answer does not repeat "{secret}"')
def step_not_repeated(context: Context, secret: str) -> None:
    assert secret not in context.response.text
