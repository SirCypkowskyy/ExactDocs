"""Steps for ExactDocs on PostgreSQL: real ``exactdocs serve`` processes on one database.

The scenarios are tagged ``@postgres`` and need ``EXACTDOCS_TEST_POSTGRES_URL`` (see
``tests/fixtures/databases.py``; ``environment.py`` skips them without it, CI requires it).
"""

import asyncio
import os
import shutil
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
from collections.abc import Generator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import LiteralString

import httpx
import psycopg
from behave import given, then, when
from behave.runner import Context
from sqlalchemy.engine import make_url

from databases import SECRET_KEY, postgres_database
from exactdocs.bootstrap.settings import Settings
from steps.http_steps import running_with
from steps.search_steps import import_versions, step_search_table

CLI = "from exactdocs.bootstrap.cli import main; main()"
CREDENTIALS = {"username": "admin", "password": "a long enough test password"}
REF = "v1.4.0"
VERSIONS = ("v1.3.0", "v1.4.0")  # as the ranking suite imports them
STARTUP_SECONDS = 90
IMPORT_SECONDS = 120


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def serve(context: Context, url: str, name: str, env: Mapping[str, str] | None = None) -> str:
    """Start ``exactdocs serve`` on the database; return its base URL once it is ready.

    ``env`` adds settings (e.g. ``EXACTDOCS_DBOS_SYSTEM_SCHEMA``) to the process's environment.
    """
    data = Path(tempfile.mkdtemp(prefix=f"exactdocs-{name}-"))
    context.add_cleanup(shutil.rmtree, data, ignore_errors=True)
    port = _free_port()
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(data / "data"),
        "EXACTDOCS_DATABASE_URL": url,
        "EXACTDOCS_SECRET_KEY": SECRET_KEY,
        **(env or {}),
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
def signed_in(base: str) -> Generator[httpx.Client]:
    """Yield a client signed in as the admin, setting the instance up first if it needs it."""
    with httpx.Client(base_url=base, timeout=30) as client:
        client.post("/api/v1/setup", json=CREDENTIALS)  # 409 once another process set it up
        client.post("/api/v1/session", json=CREDENTIALS).raise_for_status()
        yield client


def import_fixture(context: Context, client: httpx.Client) -> None:
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


def query_as(url: str, statement: LiteralString, *params: object) -> list[tuple[object, ...]]:
    """Run one statement on the database as the role in ``url``."""
    plain = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(plain) as connection:
        return connection.execute(statement, params or None).fetchall()


def _database(
    context: Context, *, owner_without_createdb: bool = False, pg_search: bool = False
) -> str:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    database = stack.enter_context(
        postgres_database(owner_without_createdb=owner_without_createdb, pg_search=pg_search)
    )
    context.database_url = database.url
    return database.url


@given("two ExactDocs processes use the same PostgreSQL database")
def step_two_processes(context: Context) -> None:
    url = _database(context)
    context.first = serve(context, url, "first")
    context.second = serve(context, url, "second")


@when("a library is imported through the first")
def step_import_through_first(context: Context) -> None:
    with signed_in(context.first) as client:
        import_fixture(context, client)


@then("the second serves it, and the import ran exactly once")
def step_second_serves(context: Context) -> None:
    with signed_in(context.second) as client:
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
    assert query_as(url, "SELECT count(*) FROM ingestion_jobs WHERE kind = 'import'") == [(1,)]
    assert query_as(url, "SELECT state FROM catalog_manifests") == [("active",)]
    assert query_as(url, "SELECT count(*) FROM retrieval_manifests") == [(1,)]
    # Each process holds an executor slot of its own (two-key advisory locks, slots 0 and 1).
    slots = query_as(
        url,
        "SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND objsubid = 2"
        " AND classid = 1163412547 AND granted ORDER BY objid",
    )
    assert slots == [(0,), (1,)], slots


def _from(address: str) -> dict[str, str]:
    """Headers making the request come from ``address`` (the processes trust 127.0.0.1)."""
    return {"X-Forwarded-For": address}


@when(
    '{count:d} sign-ins for "{username}" fail, each from a different address, '
    "alternating between the processes"
)
def step_fail_alternating(context: Context, count: int, username: str) -> None:
    with httpx.Client(base_url=context.first, timeout=30) as client:
        client.post("/api/v1/setup", json=CREDENTIALS).raise_for_status()
    wrong = {"username": username, "password": "not the admin's password"}
    for n in range(count):
        base = (context.first, context.second)[n % 2]
        # A new address each time: no address count reaches its limit, only the username's.
        response = httpx.post(
            f"{base}/api/v1/session", json=wrong, headers=_from(f"10.0.0.{n + 1}"), timeout=30
        )
        assert response.status_code == httpx.codes.UNAUTHORIZED, response.text


@then('the next sign-in for "{username}", from a new address, is throttled on both processes')
def step_throttled_on_both(context: Context, username: str) -> None:
    right = {**CREDENTIALS, "username": username}
    for n, base in enumerate((context.first, context.second)):
        # Even the right password: the attempt is refused before it is checked, by the shared
        # username count alone (this address has never failed).
        response = httpx.post(
            f"{base}/api/v1/session", json=right, headers=_from(f"10.0.1.{n + 1}"), timeout=30
        )
        assert response.status_code == httpx.codes.TOO_MANY_REQUESTS, response.text
        assert response.json()["error"] == "rate_limited", response.text
        assert int(response.headers["retry-after"]) > 0, response.headers


@given("the database role may not create databases")
def step_role_without_createdb(context: Context) -> None:
    url = _database(context, owner_without_createdb=True)
    assert query_as(url, "SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user") == [
        (False,)
    ]
    context.databases_before = query_as(url, "SELECT datname FROM pg_database ORDER BY datname")


@when("ExactDocs starts on PostgreSQL")
def step_starts_on_postgres(context: Context) -> None:
    context.first = serve(context, context.database_url, "only")


@then('DBOS keeps its tables in schema "{schema}" of the same database and jobs run')
def step_dbos_in_schema(context: Context, schema: str) -> None:
    with signed_in(context.first) as client:
        import_fixture(context, client)
    url = context.database_url
    tables = query_as(
        url,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = %s AND table_name = 'workflow_status'",
        schema,
    )
    assert tables == [("workflow_status",)], tables
    after = query_as(url, "SELECT datname FROM pg_database ORDER BY datname")
    assert after == context.databases_before, "DBOS created a database"


def ranked_on(
    context: Context, settings: Settings, *, keep: bool
) -> list[tuple[str, str, object, list]]:
    """Serve the fixture library at both versions on ``settings``; search the expected queries.

    ``keep`` leaves the app serving (``context.client``) until the scenario ends; otherwise it
    stops here: one process runs one job worker at a time.

    Returns:
        Each query, its version, its expected section and the top 5 (article, heading path).
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    running_with(context, stack, settings)
    asyncio.run(import_versions(context, list(VERSIONS)))
    step_search_table(context)
    if not keep:
        stack.close()
    return [
        (
            query,
            version,
            expected,
            [(r["article_path"], r["heading_path"]) for r in body["results"]],
        )
        for query, version, expected, body in context.ranked
    ]


def rank_both(context: Context, url: str, dbos_system_schema: str = "dbos") -> None:
    """Rank the expected queries on SQLite, then on the PostgreSQL database at ``url``."""
    sqlite_dir = Path(tempfile.mkdtemp(prefix="exactdocs-sqlite-"))
    context.add_cleanup(shutil.rmtree, sqlite_dir, ignore_errors=True)
    context.sqlite_ranked = ranked_on(context, Settings(data_dir=sqlite_dir), keep=False)
    postgres_dir = Path(tempfile.mkdtemp(prefix="exactdocs-postgres-"))
    context.add_cleanup(shutil.rmtree, postgres_dir, ignore_errors=True)
    settings = Settings(
        data_dir=postgres_dir,
        database_url=url,
        secret_key=SECRET_KEY,
        dbos_system_schema=dbos_system_schema,
    )
    context.postgres_ranked = ranked_on(context, settings, keep=True)


@when("the ranking suite runs on ParadeDB")
def step_rank_on_paradedb(context: Context) -> None:
    rank_both(context, _database(context, pg_search=True))


@when('the ranking suite runs on PostgreSQL without "pg_search"')
def step_rank_without_pg_search(context: Context) -> None:
    rank_both(context, _database(context, pg_search=False))


@then("every expected query ranks its section first, as on SQLite")
def step_ranks_as_on_sqlite(context: Context) -> None:
    assert context.postgres_ranked
    wrong = []
    for (query, version, expected, top), (_, _, _, sqlite_top) in zip(
        context.postgres_ranked, context.sqlite_ranked, strict=True
    ):
        want = None if expected is None else (expected["article"], expected["heading_path"])
        first = top[0] if top else None
        if first != want or first != (sqlite_top[0] if sqlite_top else None):
            wrong.append(f"{query!r} in {version}: wanted {want}, top 5 {top[:5]}")
    assert not wrong, "\n".join(wrong)


@then('the health check names the search engine "{engine}"')
def step_health_engine(context: Context, engine: str) -> None:
    health = context.client.get("/api/health").json()
    assert health["search_engine"] == engine, health
