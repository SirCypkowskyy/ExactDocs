"""Steps that drive ExactDocs through its public HTTP API, like a real client would."""

import asyncio
import tempfile
from contextlib import ExitStack
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import Library, LibraryName, Version

# The demo catalog exists only as test data: ExactDocs itself starts with an empty catalog.
DEMO_LIBRARIES = [
    Library(name=LibraryName("/fastapi/fastapi"), versions=frozenset({Version("0.115")})),
    Library(name=LibraryName("/reactjs/react.dev"), versions=frozenset({Version("19.1")})),
]


async def store_demo_catalog(settings: Settings) -> None:
    container = Container.build(settings)
    async with container.running():
        repository = SqliteLibraryRepository(container.engine)
        for library in DEMO_LIBRARIES:
            await repository.save(library)


@given("ExactDocs is running with the demo catalog")
def step_running(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)  # runs the app's shutdown after the scenario
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    settings = Settings(data_dir=data_dir)
    asyncio.run(store_demo_catalog(settings))
    context.client = stack.enter_context(
        TestClient(create_app(Container.build(settings)), base_url="http://localhost")
    )


@when("I list the libraries over the REST API")
def step_list(context: Context) -> None:
    context.response = context.client.get("/api/v1/libraries")


@when('I request the library "{name}"')
def step_get(context: Context, name: str) -> None:
    context.response = context.client.get(f"/api/v1/libraries{name}")


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
