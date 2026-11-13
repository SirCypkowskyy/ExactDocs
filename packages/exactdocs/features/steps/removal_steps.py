"""Steps for removing versions and libraries: driven over REST, checked over REST, MCP and disk."""

import asyncio
import time
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.ingestion.adapters.driven.sqlite import jobs
from steps.mcp_steps import call_tool
from steps.search_steps import git_blob_sha, import_versions, read_version

LIBRARY = "/fixture/docs-repo"
API = "/api/v1/libraries/fixture/docs-repo"


def _remove_version(context: Context, ref: str) -> None:
    context.response = context.client.delete(f"{API}/versions/{ref}")
    if context.response.status_code == HTTPStatus.OK:
        context.removal = context.response.json()


@when('the user removes version "{ref}" of "{library}"')
@given('the user removed version "{ref}" of "{library}"')
def step_remove_version(context: Context, ref: str, library: str) -> None:
    assert library == LIBRARY
    _remove_version(context, ref)


@when('the user removes the library "{library}"')
def step_remove_library(context: Context, library: str) -> None:
    assert library == LIBRARY
    context.response = context.client.delete(API)
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    context.removal = context.response.json()


@given('"{library}" has a long job history and an import of "{ref}" still running')
def step_long_history(context: Context, library: str, ref: str) -> None:
    assert library == LIBRARY
    moment = "2026-01-01T00:00:00.000000+00:00"
    row = {"kind": "import", "library": library, "done": 0, "total": 0, "created_at": moment}
    finished = [
        {
            **row,
            "id": f"0000-history-{n:05}",
            "version": ref,
            "state": "succeeded",
            "problems": '[{"path": "logo.png", "code": "binary", "reason": "binary file"}]',
        }
        for n in range(2000)
    ]
    running = {**row, "id": "0000-running", "version": ref, "state": "running", "problems": "[]"}

    async def insert() -> None:
        container = Container.build(context.settings)
        async with container.running(jobs=False), container.engine.begin() as connection:
            await connection.execute(jobs.insert(), [*finished, running])

    asyncio.run(insert())


@then('the removal is refused because "{ref}" is still being imported')
def step_removal_refused(context: Context, ref: str) -> None:
    assert context.response.status_code == HTTPStatus.CONFLICT, context.response.text
    assert context.response.json()["error"] == "import_in_progress", context.response.json()
    assert context.client.get(f"{API}/versions/{ref}").status_code == HTTPStatus.OK


def _assert_not_served(context: Context, ref: str | None) -> None:
    """The version (or the whole library) is unknown to REST and MCP, never answered otherwise."""
    client = context.client
    if ref is not None:
        assert client.get(f"{API}/versions/{ref}").status_code == HTTPStatus.NOT_FOUND
        assert (
            client.get(f"{API}/articles", params={"ref": ref}).status_code == HTTPStatus.NOT_FOUND
        )
        assert (
            client.get(f"{API}/search", params={"q": "retry_policy", "ref": ref}).status_code
            == HTTPStatus.NOT_FOUND
        )
    else:
        assert client.get(API).status_code == HTTPStatus.NOT_FOUND
    listed = client.get("/api/v1/libraries").json()["libraries"]
    served = {r["ref"] for lib in listed if lib["id"] == LIBRARY for r in lib["refs"]}
    assert (ref not in served) if ref else (served == set()), served
    call_tool(context, "list_libraries", {})
    mcp = {
        r["ref"]
        for lib in context.mcp_data["libraries"]
        if lib["id"] == LIBRARY
        for r in lib["refs"]
    }
    assert (ref not in mcp) if ref else (mcp == set()), mcp
    arguments: dict[str, Any] = {"library": LIBRARY, "query": "retry_policy"}
    call_tool(context, "search_docs", {**arguments, "ref": ref or "v1.3.0"}, raise_on_error=False)
    assert context.mcp_result.is_error, context.mcp_result
    call_tool(
        context, "list_articles", {"library": LIBRARY, "ref": ref or "v1.3.0"}, raise_on_error=False
    )
    assert context.mcp_result.is_error, context.mcp_result


@then("it does not appear in browse, search, list_libraries or search_docs")
def step_not_served(context: Context) -> None:
    ref = context.removal["ref"]
    assert ref, context.removal
    _assert_not_served(context, ref)


@then('the library "{library}" does not appear in browse, search, list_libraries or search_docs')
def step_library_not_served(context: Context, library: str) -> None:
    assert library == LIBRARY
    _assert_not_served(context, None)


def _wait_for_collection(context: Context) -> None:
    job_id = context.removal["collection_job_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = context.client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] in {"succeeded", "failed"}:
            assert job["state"] == "succeeded", job
            return
        time.sleep(0.05)
    message = f"the collection job {job_id} did not finish"
    raise AssertionError(message)


def _stored(context: Context, blobs: set[str]) -> dict[str, int]:
    """How many rows keep these blobs on disk: article texts and chunk sets."""

    async def count() -> dict[str, int]:
        container = Container.build(context.settings)
        async with container.running(jobs=False), container.engine.connect() as connection:
            found = {}
            for name, table in (
                ("texts", "catalog_article_contents"),
                ("chunk sets", "retrieval_chunk_sets"),
            ):
                rows = await connection.execute(text(f"SELECT DISTINCT blob_sha FROM {table}"))  # ruff: ignore[hardcoded-sql-expression]
                found[name] = len(blobs & {row[0] for row in rows})
            return found

    return asyncio.run(count())


def _blobs(context: Context, ref: str) -> set[str]:
    _, files = read_version(context, ref)
    return {git_blob_sha(body) for _, body in files}


@then('content used only by "{ref}" is garbage-collected')
def step_collected(context: Context, ref: str) -> None:
    _wait_for_collection(context)
    only = _blobs(context, ref) - _blobs(context, "v1.4.0" if ref == "v1.3.0" else "v1.3.0")
    assert only, "the fixture versions must differ"
    assert _stored(context, only) == {"texts": 0, "chunk sets": 0}, only


@then('content shared with "{ref}" is kept')
def step_shared_kept(context: Context, ref: str) -> None:
    shared = _blobs(context, ref) & _blobs(context, "v1.3.0")
    assert shared, "the fixture versions must share content"
    assert _stored(context, shared) == {"texts": len(shared), "chunk sets": len(shared)}
    response = context.client.get(f"{API}/search", params={"q": "token", "ref": ref})
    assert response.status_code == HTTPStatus.OK, response.text


@then('all content of "{library}" is garbage-collected')
def step_all_collected(context: Context, library: str) -> None:
    assert library == LIBRARY
    _wait_for_collection(context)
    every = _blobs(context, "v1.3.0") | _blobs(context, "v1.4.0")
    assert _stored(context, every) == {"texts": 0, "chunk sets": 0}


@then('"{library}" has no versions')
def step_no_versions(context: Context, library: str) -> None:
    body = context.client.get(f"/api/v1/libraries{library}").json()
    assert body["versions"] == [], body
    assert body["default_version"] is None, body


@then('searching "{library}" without a version finds nothing to search')
def step_nothing_to_search(context: Context, library: str) -> None:
    response = context.client.get(f"/api/v1/libraries{library}/search", params={"q": "token"})
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


@given('the fixture docs repository is also imported as "{library}" at "{ref}"')
def step_also_imported(context: Context, library: str, ref: str) -> None:
    asyncio.run(import_versions(context, [ref], library))


@then('all content of "{ref}" is still kept for "{library}"')
def step_kept_for_other(context: Context, ref: str, library: str) -> None:
    _wait_for_collection(context)
    blobs = _blobs(context, ref)
    assert _stored(context, blobs) == {"texts": len(blobs), "chunk sets": len(blobs)}
    owner, repo = library.removeprefix("/").split("/")
    found = context.client.get(
        f"/api/v1/libraries/{owner}/{repo}/search", params={"q": "token", "ref": ref}
    )
    assert found.status_code == HTTPStatus.OK, found.text
    assert found.json()["results"], found.json()


@then("the search index holds exactly the rows of the stored chunks")
def step_index_matches(context: Context) -> None:
    _wait_for_collection(context)

    async def counts() -> tuple[int, int]:
        container = Container.build(context.settings)
        async with container.running(jobs=False), container.engine.connect() as connection:
            fts = await connection.execute(text("SELECT count(*) FROM retrieval_search"))
            stored = await connection.execute(text("SELECT count(*) FROM retrieval_chunks"))
            return fts.scalar_one(), stored.scalar_one()

    fts, stored = asyncio.run(counts())
    assert fts == stored, (fts, stored)
