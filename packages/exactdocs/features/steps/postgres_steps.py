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
    The process's output goes to ``context.serve_log`` (the last one started).

    Returns:
        The server's base URL.

    Raises:
        AssertionError: When the server does not get ready in time.
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
    context.serve_log = data / "serve.log"
    log = context.serve_log.open("w")
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
    """Run one statement on the database as the role in ``url``.

    Returns:
        The rows the statement returned.
    """
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
    """Headers making the request come from ``address`` (the processes trust 127.0.0.1).

    Returns:
        The headers.
    """
    return {"X-Forwarded-For": address}


@when(
    '{count:d} sign-ins for "{username}" fail, each from a different address, '
    "alternating between the processes"
)
def step_fail_alternating(context: Context, count: int, username: str) -> None:
    with httpx.Client(base_url=context.first, timeout=30) as client:
        setup = client.post("/api/v1/setup", json=CREDENTIALS)
        assert setup.status_code in {httpx.codes.CREATED, httpx.codes.CONFLICT}, setup.text
    wrong = {"username": username, "password": "not the admin's password"}
    used = getattr(context, "failed_addresses", 0)
    for n in range(count):
        base = (context.first, context.second)[n % 2]
        # A new address each time: no address count reaches its limit, only the username's.
        address = f"10.0.0.{used + n + 1}"
        response = httpx.post(
            f"{base}/api/v1/session", json=wrong, headers=_from(address), timeout=30
        )
        assert response.status_code == httpx.codes.UNAUTHORIZED, response.text
    context.failed_addresses = used + count


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


RESET = {"username": "admin", "password": "a brand new passphrase for the admin"}
"""The admin's credentials once ``admin reset-password`` has run."""


def _throttle_counts(url: str) -> dict[object, tuple[object, ...]]:
    """The sign-in throttle's counts in the database, by key.

    Returns:
        Each key mapped to its count row.
    """
    rows = query_as(url, "SELECT key, failures, last_at, previous_at FROM identity_failed_sign_ins")
    return {row[0]: row[1:] for row in rows}


def _remembered(url: str) -> dict[object, object]:
    """The sign-in throttle's remembered sign-ins in the database, by key.

    Returns:
        Each key mapped to its remembered sign-ins.
    """
    rows = query_as(url, "SELECT key, signed_in_at FROM identity_known_sign_ins")
    return {row[0]: row[1] for row in rows}


@when('the operator runs "exactdocs admin reset-password" for "{username}" on that database')
def step_reset_on_postgres(context: Context, username: str) -> None:
    context.counts_before = _throttle_counts(context.database_url)
    context.remembered_before = _remembered(context.database_url)
    assert f"username:{username}" in context.counts_before, context.counts_before
    data = Path(tempfile.mkdtemp(prefix="exactdocs-cli-"))
    context.add_cleanup(shutil.rmtree, data, ignore_errors=True)
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(data / "data"),
        "EXACTDOCS_DATABASE_URL": context.database_url,
        "EXACTDOCS_SECRET_KEY": SECRET_KEY,
    }
    tokens = ["admin", "reset-password", "--username", username, "--password-stdin"]
    done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
        [sys.executable, "-c", CLI, *tokens],
        env=env,
        input=RESET["password"] + "\n",
        capture_output=True,
        text=True,
        timeout=STARTUP_SECONDS,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert RESET["password"] not in done.stdout + done.stderr
    assert "warning" not in done.stderr, done.stderr  # the username's count was cleared


@given(
    '"{username}" signed in successfully from {address}, so that address is remembered for "{same}"'
)
def step_signed_in_from(context: Context, username: str, address: str, same: str) -> None:
    assert username == same == CREDENTIALS["username"], (username, same)
    with httpx.Client(base_url=context.first, timeout=30) as client:
        setup = client.post("/api/v1/setup", json=CREDENTIALS)
        assert setup.status_code in {httpx.codes.CREATED, httpx.codes.CONFLICT}, setup.text
        response = client.post("/api/v1/session", json=CREDENTIALS, headers=_from(address))
        assert response.status_code == httpx.codes.CREATED, response.text
    context.remembered_key = f"{username}@address:{address}"
    assert context.remembered_key in _remembered(context.database_url)


OTHER_SIGN_INS = (
    "root@address:203.0.113.7",  # another username, at the same address
    "admin2@address:198.51.100.9",  # a username that starts with the reset one
    "admin@example.com@address:198.51.100.9",  # one that has an @ in it
)
"""Remembered sign-ins of usernames other than the one being reset."""


@given("sign-ins of other usernames are remembered too")
def step_other_sign_ins(context: Context) -> None:
    # Only one account exists (ACL-06), so the other usernames' rows are written directly,
    # stamped like the admin's (a stale stamp would be pruned).
    added = query_as(
        context.database_url,
        "INSERT INTO identity_known_sign_ins (key, signed_in_at)"
        " SELECT k, signed_in_at FROM identity_known_sign_ins, unnest(CAST(%s AS text[])) AS k"
        " WHERE key = %s RETURNING key",
        list(OTHER_SIGN_INS),
        context.remembered_key,
    )
    assert {row[0] for row in added} == set(OTHER_SIGN_INS), added


@then(
    'no sign-in of "{username}" is remembered, '
    "and the other usernames' remembered sign-ins are unchanged"
)
def step_remembered_forgotten(context: Context, username: str) -> None:
    before = context.remembered_before
    assert context.remembered_key in before, before
    expected = {k: v for k, v in before.items() if not str(k).startswith(f"{username}@address:")}
    assert set(OTHER_SIGN_INS) <= set(expected), expected
    remembered = _remembered(context.database_url)
    assert remembered == expected, (remembered, expected)


@then(
    'a failed sign-in for "{username}" from {address} counts against the username "{same}" '
    "again, on both processes"
)
def step_counts_again(context: Context, username: str, address: str, same: str) -> None:
    assert username == same, (username, same)
    wrong = {"username": username, "password": "not the admin's password"}
    for count, base in enumerate((context.first, context.second), start=1):
        response = httpx.post(
            f"{base}/api/v1/session", json=wrong, headers=_from(address), timeout=30
        )
        assert response.status_code == httpx.codes.UNAUTHORIZED, response.text
        record = _throttle_counts(context.database_url).get(f"username:{username}")
        assert record is not None, f"not charged to the username on {base}"
        assert record[0] == count, record


@then(
    'the throttle count of "{username}" is gone, '
    "and the other usernames' and the addresses' counts are unchanged"
)
def step_only_username_count_gone(context: Context, username: str) -> None:
    expected = {k: v for k, v in context.counts_before.items() if k != f"username:{username}"}
    assert any(str(k).startswith("username:") for k in expected), expected
    assert any(str(k).startswith("address:") for k in expected), expected
    counts = _throttle_counts(context.database_url)
    assert counts == expected, (counts, expected)


@then(
    'the next sign-in for "{username}" with the new password, from a new address, '
    "succeeds on both processes"
)
def step_new_password_on_both(context: Context, username: str) -> None:
    right = {**RESET, "username": username}
    for n, base in enumerate((context.second, context.first)):
        response = httpx.post(
            f"{base}/api/v1/session", json=right, headers=_from(f"10.0.2.{n + 1}"), timeout=30
        )
        assert response.status_code == httpx.codes.CREATED, response.text


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
