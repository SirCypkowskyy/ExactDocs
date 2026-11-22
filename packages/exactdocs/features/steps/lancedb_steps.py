"""Steps for LanceDB as the search and vector backend (#356), embedded in a temporary directory.

The instance is built from the settings an operator writes (``EXACTDOCS_SEARCH_BACKEND`` and
``EXACTDOCS_VECTOR_BACKEND`` set to ``lancedb``, ``[index_backends.lancedb]``), through the
registry and the adapter's factories, so the import, the embedding job and the searches all go
through LanceDB. The steps look into the directory with LanceDB's own client.
"""

import asyncio
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

import lancedb
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit, store_demo_catalog
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
WORDS = "retry_policy"  # only v1.4.0 documents it
QUERY = "how do I retry failed calls"
REF, OLD = "v1.4.0", "v1.3.0"


@given("ExactDocs is configured with a LanceDB URI (a local directory)")
def step_lancedb_instance(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.lancedb_uri = str(data_dir / "lancedb")
    context.settings = Settings(
        data_dir=data_dir,
        search_backend="lancedb",
        vector_backend="lancedb",
        index_backends={"lancedb": {"uri": context.lancedb_uri}},
    )
    context.stack = stack
    asyncio.run(store_demo_catalog(context.settings))


@when('versions "{old}" and "{new}" are imported and embedded')
def step_imported_and_embedded(context: Context, old: str, new: str) -> None:
    asyncio.run(import_versions(context, [old, new]))
    stack = context.stack
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    container = Container.build(
        context.settings.model_copy(update={"ai": ai}), remote=OfflineGit(GitCli.locate())
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    step_embedded(context, old)
    step_embedded(context, new)


async def _rows(uri: str) -> dict[str, list[dict]]:
    """Every table of the directory with its rows' identifying columns."""
    db = await lancedb.connect_async(uri)
    try:
        found = {}
        async for name in db.list_tables():
            table = await db.open_table(name)
            columns = ["manifest_id", "library", "version_id", "chunk_id", "article_path"]
            found[name] = await table.query().select(columns).to_list()
            table.close()
        return found
    finally:
        db.close()


async def _forget(uri: str, version_id: str) -> None:
    """Delete a version's rows from LanceDB only (the database keeps its chunks and vectors)."""
    db = await lancedb.connect_async(uri)
    try:
        async for name in db.list_tables():
            table = await db.open_table(name)
            await table.delete(f"version_id = '{version_id}'")
            table.close()
    finally:
        db.close()


@then("their chunks and vectors are written to LanceDB tables with library and version columns")
def step_written(context: Context) -> None:
    tables = asyncio.run(_rows(context.lancedb_uri))
    search = tables.pop("exactdocs_chunks")
    (space,) = tables.values()  # one space: the embedding model's
    for ref in (OLD, REF):
        rows = [r for r in search if r["version_id"] == f"{LIBRARY}/{ref}"]
        assert rows, f"no chunk of {ref} in LanceDB"
        assert {r["library"] for r in rows} == {LIBRARY}, rows[:3]
        assert len({r["manifest_id"] for r in rows}) == 1, rows[:3]
    for ref in (OLD, REF):
        chunks = {r["chunk_id"] for r in search if r["version_id"] == f"{LIBRARY}/{ref}"}
        vectors = [r for r in space if r["version_id"] == f"{LIBRARY}/{ref}"]
        assert {r["chunk_id"] for r in vectors} == chunks, ref  # a vector for every chunk
        assert {r["library"] for r in vectors} == {LIBRARY}, vectors[:3]


def _search(context: Context, ref: str, query: str, mode: str) -> list[dict]:
    response = context.client.get(SEARCH, params={"q": query, "ref": ref, "mode": mode})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    for result in body["results"]:
        assert result["commit_sha"] == context.commits[ref], result
    return body["results"]


@then("keyword, vector and hybrid searches answer from LanceDB, filtered to the asked version")
def step_answered(context: Context) -> None:
    assert _search(context, REF, WORDS, "bm25")
    assert _search(context, OLD, WORDS, "bm25") == []  # only v1.4.0 documents it
    assert _search(context, REF, QUERY, "vector")
    assert _search(context, REF, QUERY, "hybrid")
    # LanceDB answers, not the database: without its rows there, nothing is found.
    asyncio.run(_forget(context.lancedb_uri, f"{LIBRARY}/{REF}"))
    assert _search(context, REF, WORDS, "bm25") == []
    assert _search(context, REF, QUERY, "vector") == []
    assert _search(context, REF, QUERY, "hybrid") == []
