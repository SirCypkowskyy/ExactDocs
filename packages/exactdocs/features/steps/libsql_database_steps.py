"""Steps for ExactDocs' own database on a libSQL server (#474): real ``exactdocs serve`` processes.

The scenario is tagged ``@libsql_database`` and needs ``EXACTDOCS_TEST_LIBSQL_DATABASE_URL`` (see
``tests/fixtures/databases.py``; ``environment.py`` skips it without one). The server is emptied
first: never point it at one that holds anything else.
"""

import tempfile
from pathlib import Path

import turso_serverless
from behave import given, then
from behave.runner import Context

import databases
from steps.postgres_steps import REF, import_fixture, serve, signed_in

QUERIES = ("token", "naming conventions", "how do I retry failed calls")


def _query(statement: str) -> list[tuple[object, ...]]:
    """Run one statement on the test server, as a look from outside ExactDocs."""
    assert databases.LIBSQL_DATABASE_URL is not None
    connection = turso_serverless.connect(
        databases.LIBSQL_DATABASE_URL, auth_token=databases.LIBSQL_DATABASE_TOKEN
    )
    try:
        return [tuple(row) for row in connection.execute(statement).fetchall()]
    finally:
        connection.close()


def _hits(base: str, library: str) -> dict[str, list[tuple[str, str]]]:
    """The search hits of each query (each hit's article and heading), on one process."""
    found = {}
    with signed_in(base) as client:
        for query in QUERIES:
            body = client.get(
                f"/api/v1/libraries{library}/search", params={"ref": REF, "q": query}
            ).json()
            found[query] = [(hit["path"], hit["heading"]) for hit in body["results"]]
    return found


@given("two ExactDocs processes use the same libSQL server as their database")
def step_two_libsql_processes(context: Context) -> None:
    databases.empty_libsql_database()
    url = databases.libsql_database_url()
    context.first = serve(context, url, "first")
    context.second = serve(context, url, "second")


@then("the second serves it from the libSQL server, and the import ran exactly once")
def step_second_serves_from_libsql(context: Context) -> None:
    with signed_in(context.second) as client:
        articles = client.get(
            f"/api/v1/libraries{context.library}/articles", params={"ref": REF}
        ).json()
        assert any(a["path"] == "docs/reference/naming.md" for a in articles["articles"]), articles
    # On the server: one job, one manifest stored and indexed (a second run would add another).
    assert _query("SELECT count(*) FROM ingestion_jobs WHERE kind = 'import'") == [(1,)]
    assert _query("SELECT state FROM catalog_manifests") == [("active",)]
    assert _query("SELECT count(*) FROM retrieval_manifests") == [(1,)]
    assert _query("SELECT count(*) > 0 FROM retrieval_chunks") == [(1,)]


@then("its searches rank as on a SQLite file")
def step_ranks_as_on_sqlite(context: Context) -> None:
    on_libsql = _hits(context.second, context.library)
    assert all(on_libsql.values()), on_libsql
    folder = Path(tempfile.mkdtemp(prefix="exactdocs-sqlite-"))
    sqlite = serve(context, f"sqlite:///{folder / 'exactdocs.db'}", "sqlite")
    with signed_in(sqlite) as client:
        import_fixture(context, client)
    assert on_libsql == _hits(sqlite, context.library)
