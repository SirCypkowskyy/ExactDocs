"""Steps for ExactDocs on Supabase: the ``supabase/postgres`` image, set up with its SQL script.

The ``@supabase`` scenarios need ``EXACTDOCS_TEST_SUPABASE_URL`` (``tests/fixtures/databases.py``;
``environment.py`` skips them without it, CI requires it). Each one runs the README's setup with a
role and schemas of its own, then connects as that role, over SSL, with the URL's ``sslmode``.
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

import httpx
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from databases import SECRET_KEY, SUPABASE_SQL, supabase_role
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.models import RetrievalMode
from fake_llm import gateway
from steps.embedding_steps import AnswersHybrid
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, store_demo_catalog
from steps.postgres_steps import CLI, import_fixture, query_as, rank_both, serve, signed_in
from steps.search_steps import LIBRARY, import_versions

ROOT = Path(__file__).parents[4]
EMBEDDING_SECONDS = 60.0
REFUSAL_SECONDS = 60.0


@given('a Supabase database set up with "{script}"')
def step_set_up(context: Context, script: str) -> None:
    assert (ROOT / script) == SUPABASE_SQL, script
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.supabase = stack.enter_context(supabase_role())


@given('ExactDocs serves from it with "{option}", as a role that cannot create databases')
def step_serves(context: Context, option: str) -> None:
    url = context.supabase.url
    assert option in url, make_url(url).render_as_string()  # hides the password
    assert query_as(url, "SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user") == [
        (False,)
    ]
    context.databases_before = query_as(url, "SELECT datname FROM pg_database ORDER BY datname")
    context.database_url = url
    context.first = serve(
        context, url, "supabase", {"EXACTDOCS_DBOS_SYSTEM_SCHEMA": context.supabase.dbos_schema}
    )


@when('the fixture library is imported and an agent searches "{ref}" for "{query}"')
def step_import_and_search(context: Context, ref: str, query: str) -> None:
    with signed_in(context.first) as client:
        import_fixture(context, client)
        response = client.get(
            f"/api/v1/libraries{context.library}/search", params={"ref": ref, "q": query}
        )
    assert response.status_code == HTTPStatus.OK, response.text
    context.hits = response.json()["results"]


@then('the section defining "{identifier}" ranks first')
def step_ranks_first(context: Context, identifier: str) -> None:
    assert context.hits, "no results"
    first = context.hits[0]
    assert first["article_path"] == "docs/guide/resilience.md", context.hits[:3]
    assert first["heading_path"][-1] == identifier, context.hits[:3]


@then('/api/health reports the search engine "{engine}"')
def step_health(context: Context, engine: str) -> None:
    health = httpx.get(f"{context.first}/api/health", timeout=10).json()
    assert health["search_engine"] == engine, health


@then('DBOS keeps its tables in the role\'s schema "dbos" and no database was created')
def step_dbos_schema(context: Context) -> None:
    url = context.database_url
    tables = query_as(
        url,
        "SELECT table_schema, table_name FROM information_schema.tables"
        " WHERE table_name IN ('workflow_status', 'alembic_version') ORDER BY table_name",
    )
    role = context.supabase.role
    assert tables == [(role, "alembic_version"), (context.supabase.dbos_schema, "workflow_status")]
    after = query_as(url, "SELECT datname FROM pg_database ORDER BY datname")
    assert after == context.databases_before, "a database was created"


@then("every connection ExactDocs and DBOS opened uses SSL")
def step_all_ssl(context: Context) -> None:
    rows = query_as(
        context.database_url,
        "SELECT a.application_name, s.ssl FROM pg_stat_activity a"
        " JOIN pg_stat_ssl s ON s.pid = a.pid"
        " WHERE a.usename = current_user AND a.pid <> pg_backend_pid()",
    )
    assert any(name == "dbos_transact" for name, _ in rows), rows  # DBOS's connections too
    assert all(ssl for _, ssl in rows), rows


@when("the ranking suite runs on Supabase")
def step_rank_on_supabase(context: Context) -> None:
    rank_both(context, context.supabase.url, dbos_system_schema=context.supabase.dbos_schema)


@given('ExactDocs runs on it with "{extension}" enabled in schema "{schema}"')
def step_runs_with_extension(context: Context, extension: str, schema: str) -> None:
    found = query_as(
        context.supabase.url,
        "SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = %s",
        extension,
    )
    assert found == [(schema,)], found
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(
        data_dir=data_dir,
        database_url=context.supabase.url,
        secret_key=SECRET_KEY,
        dbos_system_schema=context.supabase.dbos_schema,
    )
    asyncio.run(store_demo_catalog(context.settings))


@given('an embedding model is configured and "{ref}" is embedded')
def step_embedded(context: Context, ref: str) -> None:
    asyncio.run(import_versions(context, [ref]))
    stack = ExitStack()
    context.add_cleanup(stack.close)
    endpoint = stack.enter_context(gateway())
    ai = AiSettings.model_validate(
        {
            "providers": {"corp": {"kind": "openai-compatible", "base_url": endpoint.v1}},
            "embedding": {"model": "corp:embed"},
        }
    )
    container = Container.build(
        context.settings.model_copy(update={"ai": ai}),
        pipelines={RetrievalMode.HYBRID: AnswersHybrid()},
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )
    deadline = time.monotonic() + EMBEDDING_SECONDS
    jobs: list[dict] = []
    while time.monotonic() < deadline:
        listed = context.client.get(f"/api/v1/libraries{LIBRARY}/jobs", params={"limit": 100})
        assert listed.status_code == HTTPStatus.OK, listed.text
        jobs = [job for job in listed.json()["jobs"] if job["kind"] == "embed"]
        if jobs and all(job["state"] in {"succeeded", "failed"} for job in jobs):
            break
        time.sleep(0.05)
    assert jobs, "no embedding job ran"
    assert all(job["state"] == "succeeded" for job in jobs), jobs


@then('the vectors are a column of type "{type_name}"')
def step_vector_type(context: Context, type_name: str) -> None:
    types = query_as(
        context.supabase.url,
        "SELECT DISTINCT n.nspname || '.' || t.typname FROM pg_attribute a"
        " JOIN pg_class c ON c.oid = a.attrelid JOIN pg_type t ON t.oid = a.atttypid"
        " JOIN pg_namespace n ON n.oid = t.typnamespace"
        " WHERE c.relname LIKE 'retrieval\\_vec\\_%' AND a.attname = 'embedding'"
        " AND c.relnamespace = current_schema()::regnamespace",
    )
    assert types == [(type_name,)], types


@when('ExactDocs starts on "{url}"')
def step_starts_on(context: Context, url: str) -> None:
    data = Path(tempfile.mkdtemp(prefix="exactdocs-pooler-"))
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(data),
        "EXACTDOCS_DATABASE_URL": url,
        "EXACTDOCS_SECRET_KEY": SECRET_KEY,
    }
    context.refused = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
        [sys.executable, "-c", CLI, "serve", "--port", "0"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=REFUSAL_SECONDS,
        check=False,
    )


@then("it refuses to start, naming the session pooler on port 5432 and the direct connection")
def step_refused(context: Context) -> None:
    result = context.refused
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "transaction mode" in output, output
    assert "port 5432" in output, output
    assert "direct connection" in output, output
    assert "pw-7c1e9b" not in output, output  # the password is never echoed
