"""Steps for pinning (and unpinning) the default version of a library over the REST API."""

from http import HTTPStatus

from behave import given, step_matcher, then, when
from behave.runner import Context

from steps.import_steps import import_version
from steps.mcp_steps import call_tool


def _default_path(library: str) -> str:
    return f"/api/v1/libraries{library}/default-version"


def _pin(context: Context, library: str, ref: str) -> None:
    context.response = context.client.put(_default_path(library), json={"ref": ref})


@given('the default of "{library}" is pinned to "{ref}"')
def step_pinned(context: Context, library: str, ref: str) -> None:
    _pin(context, library, ref)
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["default_pinned"] is True, context.response.text


@when('the user pins the default of "{library}" to "{ref}"')
def step_pin(context: Context, library: str, ref: str) -> None:
    _pin(context, library, ref)


@when('the user unpins the default of "{library}"')
def step_unpin(context: Context, library: str) -> None:
    context.response = context.client.delete(_default_path(library))
    assert context.response.status_code == HTTPStatus.OK, context.response.text


# A bare quoted ref; the regex keeps it from matching the longer import steps.
step_matcher("re")


@when(r'"(?P<ref>[^"/]+)" is imported')
def step_new_tag(context: Context, ref: str) -> None:
    """A higher tag appears upstream (on `main` of the private copy), then it is imported."""
    context.fixture_git("tag", ref, "main", cwd=context.fixture_repo.path)
    import_version(context, ref)
    assert context.job["state"] == "succeeded", context.job


step_matcher("parse")


def _answers(context: Context, library: str, ref: str) -> None:
    detail = context.client.get(f"/api/v1/libraries{library}").json()
    assert detail["default_version"] == ref, detail
    # Reading without a ref uses the default version, and says which one it used.
    articles = context.client.get(f"/api/v1/libraries{library}/articles")
    assert articles.status_code == HTTPStatus.OK, articles.text
    assert articles.json()["ref"] == ref, articles.json()


@then('"{library}" still answers with "{ref}"')
def step_still(context: Context, library: str, ref: str) -> None:
    _answers(context, library, ref)


@then('"{library}" answers with "{ref}"')
def step_answers(context: Context, library: str, ref: str) -> None:
    _answers(context, library, ref)


def _listed_pinned(context: Context) -> bool:
    call_tool(context, "list_libraries", {})
    (found,) = [lib for lib in context.mcp_data["libraries"] if lib["id"] == "/fixture/docs-repo"]
    return found["default_pinned"]


@then("list_libraries shows the default as pinned")
def step_listed_pinned(context: Context) -> None:
    assert _listed_pinned(context) is True


@then("list_libraries shows the default as not pinned")
def step_listed_unpinned(context: Context) -> None:
    assert _listed_pinned(context) is False
