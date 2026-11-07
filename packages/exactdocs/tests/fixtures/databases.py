"""Throwaway PostgreSQL databases for the adapter contract tests and the PostgreSQL scenarios.

``EXACTDOCS_TEST_POSTGRES_URL`` names a server and a role that may create databases and roles
(CI: the ParadeDB service, its superuser; locally e.g. ``postgresql://postgres@127.0.0.1/postgres``).
Without it the PostgreSQL variants are not collected: the SQLite and in-memory ones still run. CI
sets ``EXACTDOCS_REQUIRE_POSTGRES=1``, which makes a missing URL an error instead.
"""

import os
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get("EXACTDOCS_TEST_POSTGRES_URL") or None
if ADMIN_URL is None and os.environ.get("EXACTDOCS_REQUIRE_POSTGRES") == "1":
    message = "EXACTDOCS_REQUIRE_POSTGRES=1 but EXACTDOCS_TEST_POSTGRES_URL is not set"
    raise RuntimeError(message)

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
    *, owner_without_createdb: bool = False, c_locale: bool = False, pg_search: bool = False
) -> Generator[PostgresDatabase]:
    """Create an empty database, yield it, then drop it (and its role) whatever happened.

    ``owner_without_createdb`` creates a login role that owns the database but may not create
    databases (``NOCREATEDB``), as on managed PostgreSQL, and connects as that role.
    ``c_locale`` creates it with ``LC_COLLATE``/``LC_CTYPE`` ``C`` (``initdb --locale=C``), where
    character classes such as ``[[:alnum:]]`` only know ASCII.
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
