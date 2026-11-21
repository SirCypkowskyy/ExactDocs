"""Steps for the title and description a library takes from its root README."""

from http import HTTPStatus
from pathlib import Path

from behave import given, step, then
from behave.runner import Context

from steps.mcp_steps import call_tool

LIBRARY = "/fixture/docs-repo"
README_TITLE = "Acme Payments"
README_DESCRIPTION = (
    "Acme Payments is a small, fictional payments SDK. "
    "It exists only as test content for ExactDocs."
)


READMES = Path(__file__).parents[2] / "tests" / "fixtures" / "readmes"
"""READMEs shaped like those of real projects, kept small."""


def _git(context: Context, *args: str) -> str:
    return context.fixture_git(*args, cwd=context.fixture_repo.path)


@given('a branch "{branch}" has a README shaped like "{readme}"')
def step_branch_readme(context: Context, branch: str, readme: str) -> None:
    """Branch off ``v1.3.0`` (no context7.json) and replace its README; needs a private copy."""
    _git(context, "checkout", "-q", "-b", branch, "v1.3.0")
    (context.fixture_repo.path / "README.md").write_bytes((READMES / readme).read_bytes())
    _git(context, "-c", "user.name=Fixture", "-c", "user.email=f@exactdocs.invalid",
         "commit", "-q", "-am", "docs: a README with a logo")  # fmt: skip
    _git(context, "checkout", "-q", "main")


def _library(context: Context) -> dict:
    response = context.client.get(f"/api/v1/libraries{LIBRARY}")
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@step('the user changes the title to "{title}"')
def step_change_title(context: Context, title: str) -> None:
    response = context.client.patch(f"/api/v1/libraries{LIBRARY}", json={"title": title})
    assert response.status_code == HTTPStatus.OK, response.text


@then("the title of the library is the first heading of the README")
def step_readme_title(context: Context) -> None:
    assert _library(context)["title"] == README_TITLE


@then("the description of the library is the first paragraph of the README")
def step_readme_description(context: Context) -> None:
    assert _library(context)["description"] == README_DESCRIPTION


@then('the description of the library starts with "{start}"')
def step_description_starts(context: Context, start: str) -> None:
    description = _library(context)["description"]
    assert description.startswith(start), description


@then('the title of the library is "{title}"')
def step_title(context: Context, title: str) -> None:
    assert _library(context)["title"] == title


@then('"list_libraries" shows the title "{title}"')
def step_listed_title(context: Context, title: str) -> None:
    call_tool(context, "list_libraries", {})
    (found,) = [lib for lib in context.mcp_data["libraries"] if lib["id"] == LIBRARY]
    assert found["title"] == title
