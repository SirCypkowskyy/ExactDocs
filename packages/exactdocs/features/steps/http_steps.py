"""Steps that drive ExactDocs through its public HTTP API, like a real client would."""

import asyncio
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    RefKind,
    Version,
    VersionRef,
)

IMPORTED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _version(ref: str, kind: RefKind, sha: str) -> Version:
    return Version(
        ref=VersionRef(ref), kind=kind, commit_sha=sha.ljust(40, "0"), imported_at=IMPORTED
    )


# The demo catalog exists only as test data: ExactDocs itself starts with an empty catalog.
# It is shaped like the fixture docs repository: two tags and a branch.
DEMO_LIBRARIES = [
    Library(
        id=LibraryId("/acme/payments"),
        title="Payments",
        source_url="https://github.com/acme/payments",
        host=HostKind.GITHUB,
        default_branch=VersionRef("main"),
        versions=frozenset(
            {
                _version("v1.3.0", RefKind.TAG, "1a"),
                _version("v1.4.0", RefKind.TAG, "1b"),
                _version("main", RefKind.BRANCH, "1c"),
                _version("next", RefKind.BRANCH, "1d"),
            }
        ),
    ),
    Library(
        id=LibraryId("/acme/ledger"),
        title="Ledger",
        source_url="https://git.example.com/acme/ledger.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset({_version("main", RefKind.BRANCH, "2a")}),
    ),
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


@when('I request the library "{library_id}"')
def step_get(context: Context, library_id: str) -> None:
    context.response = context.client.get(f"/api/v1/libraries{library_id}")


@when('I request the version "{target}"')
def step_get_version(context: Context, target: str) -> None:
    owner, repo, ref = target.removeprefix("/").split("/", 2)
    context.response = context.client.get(f"/api/v1/libraries/{owner}/{repo}/versions/{ref}")


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
    expected = [
        (row["id"], row["versions"].split(", "), row["default version"])
        for row in context.table or []
    ]
    actual = [
        (lib["id"], lib["versions"], lib["default_version"])
        for lib in context.response.json()["libraries"]
    ]
    assert actual == expected, actual


@then('the default version of "{library_id}" is "{ref}"')
def step_default_version(context: Context, library_id: str, ref: str) -> None:
    body = context.response.json()
    assert (body["id"], body["default_version"]) == (library_id, ref), body


@then('the version used is "{ref}" of "{library_id}"')
def step_version_used(context: Context, ref: str, library_id: str) -> None:
    body = context.response.json()
    assert (body["library"], body["ref"]) == (library_id, ref), body


@then("I get {count:d} excerpts")
def step_excerpts(context: Context, count: int) -> None:
    assert len(context.response.json()["excerpts"]) == count


@when("I fetch the OpenAPI description")
def step_openapi(context: Context) -> None:
    context.response = context.client.get("/api/v1/openapi.json")


@then("every operation has a stable operation ID and documented error responses")
def step_operations(context: Context) -> None:
    paths = context.response.json()["paths"]
    operations = [op for item in paths.values() for op in item.values()]
    assert operations
    for op in operations:
        tag, _, name = op["operationId"].partition("-")
        assert tag in op["tags"], op["operationId"]
        assert name, op["operationId"]
        assert {"404", "422"} <= set(op["responses"]), op["operationId"]


@then("the error has a message")
def step_error_message(context: Context) -> None:
    assert context.response.json()["detail"]
