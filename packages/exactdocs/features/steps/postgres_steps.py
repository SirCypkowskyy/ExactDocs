"""Steps for ExactDocs on PostgreSQL: real ``exactdocs serve`` processes on one database.

The scenarios are tagged ``@postgres`` and need ``EXACTDOCS_TEST_POSTGRES_URL`` (see
``tests/fixtures/databases.py``; ``environment.py`` skips them without it, CI requires it).
"""

import os
import shutil
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import LiteralString

import httpx
import psycopg
from behave import given, then, when
from behave.runner import Context
from sqlalchemy.engine import make_url

from databases import SECRET_KEY, postgres_database

CLI = "from exactdocs.bootstrap.cli import main; main()"
CREDENTIALS = {"username": "admin", "password": "a long enough test password"}
REF = "v1.4.0"
STARTUP_SECONDS = 90
IMPORT_SECONDS = 120


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve(context: Context, url: str, name: str) -> str:
    """Start ``exactdocs serve`` on the database; return its base URL once it is ready."""
    data = Path(tempfile.mkdtemp(prefix=f"exactdocs-{name}-"))
    context.add_cleanup(shutil.rmtree, data, ignore_errors=True)
    port = _free_port()
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(data / "data"),
        "EXACTDOCS_DATABASE_URL": url,
        "EXACTDOCS_SECRET_KEY": SECRET_KEY,
    }
    log = (data / "serve.log").open("w")
    context.add_cleanup(log.close)
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
        [sys.executable, "-c", CLI, "serve", "--port", str(port)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    def stop() -> None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    context.add_cleanup(stop)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        assert process.poll() is None, (data / "serve.log").read_text()
        try:
            if httpx.get(f"{base}/readyz", timeout=2).status_code == httpx.codes.OK:
                return base
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    message = f"{name} did not get ready:\n{(data / 'serve.log').read_text()}"
    raise AssertionError(message)


@contextmanager
def _signed_in(base: str) -> Generator[httpx.Client]:
    """Yield a client signed in as the admin, setting the instance up first if it needs it."""
    with httpx.Client(base_url=base, timeout=30) as client:
        client.post("/api/v1/setup", json=CREDENTIALS)  # 409 once another process set it up
        client.post("/api/v1/session", json=CREDENTIALS).raise_for_status()
        yield client


def _import(context: Context, client: httpx.Client) -> None:
    """Add the fixture library at ``REF`` and wait for its import to succeed."""
    added = client.post(
        "/api/v1/libraries",
        json={"url": context.fixture_repo.http_url, "ref": REF, "include_paths": ["docs/"]},
    )
    added.raise_for_status()
    context.library, job_id = added.json()["library_id"], added.json()["job_id"]
    deadline = time.monotonic() + IMPORT_SECONDS
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    while job["state"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.2)
        job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "succeeded", job
    context.job = job


def _query(url: str, statement: LiteralString, *params: object) -> list[tuple[object, ...]]:
    """Run one statement on the database as the role in ``url``."""
    plain = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(plain) as connection:
        return connection.execute(statement, params or None).fetchall()


def _database(context: Context, *, owner_without_createdb: bool = False) -> str:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    database = stack.enter_context(postgres_database(owner_without_createdb=owner_without_createdb))
    context.database_url = database.url
    return database.url


@given("two ExactDocs processes use the same PostgreSQL database")
def step_two_processes(context: Context) -> None:
    url = _database(context)
    context.first = _serve(context, url, "first")
    context.second = _serve(context, url, "second")


@when("a library is imported through the first")
def step_import_through_first(context: Context) -> None:
    with _signed_in(context.first) as client:
        _import(context, client)


@then("the second serves it, and the import ran exactly once")
def step_second_serves(context: Context) -> None:
    with _signed_in(context.second) as client:
        articles = client.get(
            f"/api/v1/libraries{context.library}/articles", params={"ref": REF}
        ).json()
        assert any(a["path"] == "docs/reference/naming.md" for a in articles["articles"]), articles
        hits = client.get(
            f"/api/v1/libraries{context.library}/search", params={"ref": REF, "q": "token"}
        ).json()
        assert hits["results"], hits
    # Once: one job, and one manifest stored and indexed (a second run would store another).
    url = context.database_url
    assert _query(url, "SELECT count(*) FROM ingestion_jobs WHERE kind = 'import'") == [(1,)]
    assert _query(url, "SELECT state FROM catalog_manifests") == [("active",)]
    assert _query(url, "SELECT count(*) FROM retrieval_manifests") == [(1,)]
    # Each process holds an executor slot of its own (two-key advisory locks, slots 0 and 1).
    slots = _query(
        url,
        "SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND objsubid = 2"
        " AND classid = 1163412547 AND granted ORDER BY objid",
    )
    assert slots == [(0,), (1,)], slots


@given("the database role may not create databases")
def step_role_without_createdb(context: Context) -> None:
    url = _database(context, owner_without_createdb=True)
    assert _query(url, "SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user") == [
        (False,)
    ]
    context.databases_before = _query(url, "SELECT datname FROM pg_database ORDER BY datname")


@when("ExactDocs starts on PostgreSQL")
def step_starts_on_postgres(context: Context) -> None:
    context.first = _serve(context, context.database_url, "only")


@then('DBOS keeps its tables in schema "{schema}" of the same database and jobs run')
def step_dbos_in_schema(context: Context, schema: str) -> None:
    with _signed_in(context.first) as client:
        _import(context, client)
    url = context.database_url
    tables = _query(
        url,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = %s AND table_name = 'workflow_status'",
        schema,
    )
    assert tables == [("workflow_status",)], tables
    after = _query(url, "SELECT datname FROM pg_database ORDER BY datname")
    assert after == context.databases_before, "DBOS created a database"
