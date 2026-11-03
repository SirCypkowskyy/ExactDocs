"""Steps that drive ExactDocs through its public HTTP API, like a real client would."""

from contextlib import ExitStack

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings


@given("ExactDocs is running with the demo catalog")
def step_running(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)  # runs the app's shutdown after the scenario
    context.client = stack.enter_context(TestClient(create_app(Container.build(Settings()))))


@when("I list the libraries over the REST API")
def step_list(context: Context) -> None:
    context.response = context.client.get("/api/v1/libraries")


@when('I request the library "{name}"')
def step_get(context: Context, name: str) -> None:
    context.response = context.client.get(f"/api/v1/libraries/{name}")


@when('I search "{library}" version "{version}" for "{query}"')
def step_search(context: Context, library: str, version: str, query: str) -> None:
    params = {"library": library, "version": version, "query": query}
    context.response = context.client.get("/api/v1/search", params=params)


@then("the response status is {status:d}")
def step_status(context: Context, status: int) -> None:
    assert context.response.status_code == status, context.response.text


@then('the error code is "{code}"')
def step_error(context: Context, code: str) -> None:
    assert context.response.json()["error"] == code


@then("the libraries are:")
def step_libraries(context: Context) -> None:
    expected = [(row["name"], row["versions"].split(", ")) for row in context.table or []]
    actual = [(lib["name"], lib["versions"]) for lib in context.response.json()["libraries"]]
    assert actual == expected, actual


@then("I get {count:d} excerpts")
def step_excerpts(context: Context, count: int) -> None:
    assert len(context.response.json()["excerpts"]) == count
