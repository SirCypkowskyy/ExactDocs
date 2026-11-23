"""Throwaway PostgreSQL databases for the adapter contract tests and the PostgreSQL scenarios.

``EXACTDOCS_TEST_POSTGRES_URL`` names a server and a role that may create databases and roles
(CI: the ParadeDB service, its superuser; locally e.g. ``postgresql://postgres@127.0.0.1/postgres``).
Without it the PostgreSQL variants are not collected: the SQLite and in-memory ones still run. CI
sets ``EXACTDOCS_REQUIRE_POSTGRES=1``, which makes a missing URL an error instead.
"""

import os
import re
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get("EXACTDOCS_TEST_POSTGRES_URL") or None
if ADMIN_URL is None and os.environ.get("EXACTDOCS_REQUIRE_POSTGRES") == "1":
    message = "EXACTDOCS_REQUIRE_POSTGRES=1 but EXACTDOCS_TEST_POSTGRES_URL is not set"
    raise RuntimeError(message)

TERMINATE_WAIT_MS = 5000
"""How long ``pg_terminate_backend`` waits for a backend to exit (and release its locks)."""

SQL_BACKENDS = ["sqlite", "postgres"] if ADMIN_URL else ["sqlite"]
"""The SQL backends the contract tests run on here."""


# A fixed, valid key: every process of one test shares it, as a deployment's must.
SECRET_KEY = "contract-tests-secret-key-0123456789abcdef"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresDatabase:
    """A database created for one test, and the URL that reaches it."""

    name: str
    url: str


def _admin(database: str | None = None) -> psycopg.Connection:
    assert ADMIN_URL is not None, "EXACTDOCS_TEST_POSTGRES_URL is not set"
    url = make_url(ADMIN_URL).set(drivername="postgresql")
    if database is not None:
        url = url.set(database=database)
    return psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)


PG_SEARCH = ADMIN_URL is not None and os.environ.get("EXACTDOCS_TEST_PG_SEARCH") == "1"
"""The test server has ParadeDB's ``pg_search`` (``EXACTDOCS_TEST_PG_SEARCH=1``; CI's ParadeDB
does): the BM25 variants run. Declared rather than asked, so importing this module never connects
(the no-outbound tests import it inside a namespace without a network)."""
SEARCH_BACKENDS = [
    *SQL_BACKENDS,
    *(["postgres_c"] if ADMIN_URL else []),
    *(["pg_search"] if PG_SEARCH else []),
]
"""The search index's contract also runs on a PostgreSQL database in the ``C`` locale (full-text
search) and, where the server has it, on ``pg_search``."""


@contextmanager
def postgres_database(
    *,
    owner_without_createdb: bool = False,
    c_locale: bool = False,
    without_extensions: tuple[str, ...] = (),
    pg_search: bool = False,
) -> Generator[PostgresDatabase]:
    """Create an empty database, yield it, then drop it (and its role) whatever happened.

    ``owner_without_createdb`` creates a login role that owns the database but may not create
    databases (``NOCREATEDB``), as on managed PostgreSQL, and connects as that role.
    ``c_locale`` creates it with ``LC_COLLATE``/``LC_CTYPE`` ``C`` (``initdb --locale=C``), where
    character classes such as ``[[:alnum:]]`` only know ASCII.
    ``without_extensions`` drops these extensions from the new database (ParadeDB's template
    database already has ``vector``), as on a server where they were never installed in it.
    ``pg_search`` installs ParadeDB's extension in it, so ExactDocs searches with BM25; without it
    the extension is removed even where the template has it (ParadeDB's ``template1``), so
    ExactDocs uses PostgreSQL full-text search.

    Yields:
        The database's name and URL.
    """
    name = f"exactdocs_test_{secrets.token_hex(6)}"
    admin_url = make_url(ADMIN_URL or "")
    role, password = None, None
    with _admin() as admin:
        if owner_without_createdb:
            role, password = name, secrets.token_hex(16)
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier(role)
                )
            )
        elif c_locale:
            admin.execute(
                sql.SQL(
                    "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'"
                    " LC_COLLATE 'C' LC_CTYPE 'C'"
                ).format(sql.Identifier(name))
            )
        else:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    if without_extensions:
        plain = admin_url.set(drivername="postgresql", database=name)
        with psycopg.connect(plain.render_as_string(hide_password=False), autocommit=True) as db:
            for extension in without_extensions:
                db.execute(
                    sql.SQL("DROP EXTENSION IF EXISTS {} CASCADE").format(sql.Identifier(extension))
                )
    with _admin(name) as admin:
        admin.execute(
            "CREATE EXTENSION IF NOT EXISTS pg_search CASCADE"
            if pg_search
            else "DROP EXTENSION IF EXISTS pg_search"
        )
    url = admin_url.set(drivername="postgresql+psycopg", database=name)
    if role is not None:
        url = url.set(username=role, password=password)
    try:
        yield PostgresDatabase(name=name, url=url.render_as_string(hide_password=False))
    finally:
        with _admin() as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            if role is not None:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


SUPABASE_URL = os.environ.get("EXACTDOCS_TEST_SUPABASE_URL") or None
"""The ``postgres`` role of a ``supabase/postgres`` server, with ``sslmode=require`` (CI starts
one with SSL on). Without it the Supabase scenarios are skipped; ``EXACTDOCS_REQUIRE_SUPABASE=1``
(CI) makes a missing URL an error instead."""
if SUPABASE_URL is None and os.environ.get("EXACTDOCS_REQUIRE_SUPABASE") == "1":
    message = "EXACTDOCS_REQUIRE_SUPABASE=1 but EXACTDOCS_TEST_SUPABASE_URL is not set"
    raise RuntimeError(message)

SUPABASE_SQL = Path(__file__).parents[4] / "deploy" / "supabase.sql"
"""The setup the README tells operators to run on Supabase."""
SUPABASE_SQL_ROLE_NAMES = 6
"""How often the script names the role or its schema (``exactdocs``), at least."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SupabaseRole:
    """A role and its schemas, set up on the Supabase server for one test."""

    role: str
    dbos_schema: str
    url: str
    """The role's URL (``postgresql+psycopg://``), with the admin URL's query (``sslmode``)."""


def _supabase_admin() -> psycopg.Connection:
    assert SUPABASE_URL is not None, "EXACTDOCS_TEST_SUPABASE_URL is not set"
    url = make_url(SUPABASE_URL).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)


@contextmanager
def supabase_role() -> Generator[SupabaseRole]:
    """Run ``deploy/supabase.sql`` with names of this test's own; drop it all afterwards.

    Supabase has one database (``postgres``), so tests share it and each gets a role and schemas
    named ``exactdocs_<hex>`` and ``dbos_<hex>`` instead of ``exactdocs`` and ``dbos``.

    Yields:
        The role, its DBOS schema and its URL.
    """
    suffix = secrets.token_hex(6)
    role, dbos_schema, password = f"exactdocs_{suffix}", f"dbos_{suffix}", secrets.token_hex(16)
    script = SUPABASE_SQL.read_text(encoding="utf-8")
    # The README's script, checked: it names the role and its schema in every statement but the
    # extension's, DBOS's schema once, and sets no password (the README's next step does).
    assert not re.search(r"\bPASSWORD\s+'", script, re.IGNORECASE), "it must set no password"
    script, roles = re.subn(r"\bexactdocs\b", role, script)
    script, dbos = re.subn(r"\bdbos\b", dbos_schema, script)
    assert roles >= SUPABASE_SQL_ROLE_NAMES, f"{roles} mentions of the role in {SUPABASE_SQL}"
    assert dbos == 1, f"{dbos} mentions of schema dbos in {SUPABASE_SQL}"
    with _supabase_admin() as admin:
        admin.execute(script.encode())  # no parameters: several statements in one call
        admin.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password))
        )
    url = make_url(SUPABASE_URL or "").set(
        drivername="postgresql+psycopg", username=role, password=password
    )
    try:
        yield SupabaseRole(
            role=role, dbos_schema=dbos_schema, url=url.render_as_string(hide_password=False)
        )
    finally:
        with _supabase_admin() as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s",
                (role,),
            )
            admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(role)))
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(dbos_schema))
            )
            admin.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


PGBOUNCER_URL = os.environ.get("EXACTDOCS_TEST_PGBOUNCER_URL") or None
"""PgBouncer in ``pool_mode = transaction`` in front of ``EXACTDOCS_TEST_POSTGRES_URL``'s server,
for every database (``*``), as that URL's role (#279). It runs ``server_reset_query = DISCARD
ALL`` after every transaction (``server_reset_query_always = 1``), so session state never
survives from one transaction to the next, whichever server connection the next one gets. Without
it the pooler tests are skipped; ``EXACTDOCS_REQUIRE_PGBOUNCER=1`` (CI) makes a missing URL an
error instead."""
if PGBOUNCER_URL is None and os.environ.get("EXACTDOCS_REQUIRE_PGBOUNCER") == "1":
    message = "EXACTDOCS_REQUIRE_PGBOUNCER=1 but EXACTDOCS_TEST_PGBOUNCER_URL is not set"
    raise RuntimeError(message)


def through_pgbouncer(database: PostgresDatabase) -> str:
    """Return the URL that reaches ``database`` through PgBouncer (``PGBOUNCER_URL``).

    Args:
        database: A database created by ``postgres_database``, as the admin role.

    Returns:
        The same database and role, on PgBouncer's host and port.
    """
    assert PGBOUNCER_URL is not None, "EXACTDOCS_TEST_PGBOUNCER_URL is not set"
    pooler = make_url(PGBOUNCER_URL)
    return (
        make_url(database.url)
        .set(host=pooler.host, port=pooler.port)
        .render_as_string(hide_password=False)
    )


LIBSQL_DATABASE_URL = os.environ.get("EXACTDOCS_TEST_LIBSQL_DATABASE_URL") or None
"""A libSQL server the SQLite persistence tests run on instead of a file (#474). CI starts one of
its own (``deploy/libsql-test-server.sh``) and runs the persistence suite again with it: every
SQLite case of a test parametrized on the database then starts on an empty server. Never point it
at a server that holds anything else."""
LIBSQL_DATABASE_TOKEN = os.environ.get("EXACTDOCS_TEST_LIBSQL_DATABASE_AUTH_TOKEN") or None
"""That server's token, if it needs one."""


def libsql_database_url() -> str:
    """``EXACTDOCS_DATABASE_URL`` for the test server: ``libsql://host:port?tls=...&authToken=...``.

    Returns:
        The URL.
    """
    assert LIBSQL_DATABASE_URL is not None, "EXACTDOCS_TEST_LIBSQL_DATABASE_URL is not set"
    parts = urlsplit(LIBSQL_DATABASE_URL)
    query = {"tls": "0" if parts.scheme == "http" else "1"}
    if LIBSQL_DATABASE_TOKEN:
        query["authToken"] = LIBSQL_DATABASE_TOKEN
    return f"libsql://{parts.netloc}?{urlencode(query)}"


def empty_libsql_database() -> None:
    """Drop every trigger, view and table of the test server (libSQL's and SQLite's own excepted)."""
    import turso_serverless  # noqa: PLC0415 -- the libsql-database extra, only for these tests

    assert LIBSQL_DATABASE_URL is not None, "EXACTDOCS_TEST_LIBSQL_DATABASE_URL is not set"
    connection = turso_serverless.connect(
        LIBSQL_DATABASE_URL, auth_token=LIBSQL_DATABASE_TOKEN, isolation_level=None
    )
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        found = connection.execute(
            "SELECT type, name, upper(coalesce(sql, '')) LIKE 'CREATE VIRTUAL%' FROM sqlite_master"
            " WHERE type IN ('trigger', 'view', 'table') AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
            " AND name NOT LIKE 'libsql\\_%' ESCAPE '\\'"
        ).fetchall()
        # Triggers and views, then virtual tables (which drop their shadow tables), then tables.
        for kind, name, _ in sorted(found, key=lambda row: (row[0] == "table", not row[2])):
            connection.execute(f'DROP {kind.upper()} IF EXISTS "{name}"')
    finally:
        connection.close()
