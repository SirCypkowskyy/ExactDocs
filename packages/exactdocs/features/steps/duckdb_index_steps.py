"""Steps for DuckDB as the search and vector backend (#357).

The server writes a DuckDB file in the scenario's data folder. The steps read that file in the
same process, with the settings the backend opens it with (DuckDB shares one database per
process and file), as an operator would read it with ExactDocs stopped.
"""

import asyncio
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

import duckdb
from behave import given, step, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.retrieval.constants import DUCKDB_CONFIG
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit, store_demo_catalog
from steps.search_steps import LIBRARY, import_versions

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
EMBEDDING_SECONDS = 60.0
KEYWORDS = "connection_pool"
QUESTION = "how do I retry failed calls"
CLI = "from exactdocs.bootstrap.cli import main; main()"


@given("ExactDocs is configured with a DuckDB database file")
def step_configured(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.duckdb_file = data_dir / "index.duckdb"
    endpoint = stack.enter_context(gateway(by_terms=True))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    context.settings = Settings(
        data_dir=data_dir,
        ai=ai,
        search_backend="duckdb",
        vector_backend="duckdb",
        index_backends={"duckdb": {"path": str(context.duckdb_file)}},
    )
    context.stack = stack
    asyncio.run(store_demo_catalog(context.settings))


def _wait_for_embedding(client: TestClient, refs: list[str]) -> None:
    deadline = time.monotonic() + EMBEDDING_SECONDS
    jobs: list[dict] = []
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/libraries{LIBRARY}/jobs", params={"limit": 100})
        assert response.status_code == HTTPStatus.OK, response.text
        jobs = [j for j in response.json()["jobs"] if j["kind"] == "embed"]
        if {j["version"] for j in jobs} >= set(refs) and all(
            j["state"] in {"succeeded", "failed"} for j in jobs
        ):
            break
        time.sleep(0.05)
    assert sorted((j["version"], j["state"]) for j in jobs) == [
        (ref, "succeeded") for ref in sorted(refs)
    ], jobs


@step('versions "{first}" and "{second}" are imported and embedded')
def step_imported(context: Context, first: str, second: str) -> None:
    context.refs = [first, second]
    asyncio.run(import_versions(context, context.refs))  # its own DuckDB connection, closed
    container = Container.build(context.settings, remote=OfflineGit(GitCli.locate()))
    context.client = context.stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    _wait_for_embedding(context.client, context.refs)


def _duckdb(context: Context) -> duckdb.DuckDBPyConnection:
    """The server's DuckDB file, opened as the backend opens it (shared within the process)."""
    connection = duckdb.connect(str(context.duckdb_file), config=dict(DUCKDB_CONFIG))
    context.add_cleanup(connection.close)
    return connection


def _space_table(connection: duckdb.DuckDBPyConnection) -> str:
    (table,) = [
        name
        for (name,) in connection.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE starts_with(table_name, 'exactdocs_vectors_')"
        ).fetchall()
    ]
    return table


@then("their chunks and vectors are written to DuckDB tables with library and version columns")
def step_written(context: Context) -> None:
    connection = _duckdb(context)
    expected = {f"{LIBRARY}/{ref}" for ref in context.refs}
    for table in ("exactdocs_search", _space_table(connection)):
        rows = dict(
            connection.execute(
                f"SELECT version_id, count(*) FROM {table} "  # ruff: ignore[hardcoded-sql-expression]
                "WHERE library = $library GROUP BY version_id",
                {"library": LIBRARY},
            ).fetchall()
        )
        assert set(rows) == expected, (table, rows)
        assert all(rows.values()), (table, rows)
    (dimensions,) = connection.execute(
        f"SELECT array_length(any_value(vector)) FROM {_space_table(connection)}"  # ruff: ignore[hardcoded-sql-expression]
    ).fetchone() or (0,)
    assert dimensions > 0


def _searched(context: Context, ref: str, query: str, mode: str) -> list[dict]:
    response = context.client.get(
        SEARCH, params={"q": query, "ref": ref, "mode": mode, "limit": 10}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["version"], body["retrieval_mode"]) == (ref, mode), body
    return body["results"]


@then("keyword and vector searches answer from DuckDB, filtered to the asked version")
def step_answered(context: Context) -> None:
    searches = [(KEYWORDS, "bm25"), (QUESTION, "vector")]
    for ref in context.refs:
        for query, mode in searches:
            results = _searched(context, ref, query, mode)
            assert results, (ref, mode)
            assert {r["commit_sha"] for r in results} == {context.commits[ref]}, (ref, results)
    # The answers come from DuckDB: once its copy of a version is gone, that version finds
    # nothing, though the database still holds every chunk and vector; the other still answers.
    gone, kept = context.refs
    connection = _duckdb(context)
    for table in ("exactdocs_search", _space_table(connection)):
        connection.execute(
            f"DELETE FROM {table} WHERE version_id = $version",  # ruff: ignore[hardcoded-sql-expression]
            {"version": f"{LIBRARY}/{gone}"},
        )
    for query, mode in searches:
        assert _searched(context, gone, query, mode) == [], (gone, mode)
        assert _searched(context, kept, query, mode), (kept, mode)


@when('the operator runs "exactdocs index check" while the server runs')
def step_cli_check(context: Context) -> None:
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(context.settings.data_dir),
        "EXACTDOCS_SEARCH_BACKEND": "duckdb",
        "EXACTDOCS_VECTOR_BACKEND": "duckdb",
        "EXACTDOCS_INDEX_BACKENDS__DUCKDB__PATH": str(context.duckdb_file),
    }
    env.pop("EXACTDOCS_DATABASE_URL", None)
    context.ran = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, "index", "check"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


@then("the command fails, saying DuckDB lets one process write the file")
def step_cli_refused(context: Context) -> None:
    ran = context.ran
    assert ran.returncode != 0, (ran.stdout, ran.stderr)
    assert "DuckDB lets one process write a database file" in ran.stderr, ran.stderr
    assert str(context.duckdb_file) in ran.stderr, ran.stderr
    assert f"PID {os.getpid()}" in ran.stderr, ran.stderr
