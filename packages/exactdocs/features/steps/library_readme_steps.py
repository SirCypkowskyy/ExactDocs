"""Steps for the title and description a library takes from its root README."""

from http import HTTPStatus

from behave import step, then
from behave.runner import Context

from steps.mcp_steps import call_tool

LIBRARY = "/fixture/docs-repo"
README_TITLE = "Acme Payments"
README_DESCRIPTION = (
    "Acme Payments is a small, fictional payments SDK. "
    "It exists only as test content for ExactDocs."
)


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


@then('the title of the library is "{title}"')
def step_title(context: Context, title: str) -> None:
    assert _library(context)["title"] == title


@then('"list_libraries" shows the title "{title}"')
def step_listed_title(context: Context, title: str) -> None:
    call_tool(context, "list_libraries", {})
    (found,) = [lib for lib in context.mcp_data["libraries"] if lib["id"] == LIBRARY]
    assert found["title"] == title
