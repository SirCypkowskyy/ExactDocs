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
SEARCH_BACKENDS = [*SQL_BACKENDS, *(["postgres_c"] if ADMIN_URL else [])]
"""The search index's contract also runs on a PostgreSQL database in the ``C`` locale."""

# A fixed, valid key: every process of one test shares it, as a deployment's must.
SECRET_KEY = "contract-tests-secret-key-0123456789abcdef"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresDatabase:
    """A database created for one test, and the URL that reaches it."""

    name: str
    url: str


def _admin() -> psycopg.Connection:
    assert ADMIN_URL is not None, "EXACTDOCS_TEST_POSTGRES_URL is not set"
    url = make_url(ADMIN_URL).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)


@contextmanager
def postgres_database(
    *, owner_without_createdb: bool = False, c_locale: bool = False
) -> Generator[PostgresDatabase]:
    """Create an empty database, yield it, then drop it (and its role) whatever happened.

    ``owner_without_createdb`` creates a login role that owns the database but may not create
    databases (``NOCREATEDB``), as on managed PostgreSQL, and connects as that role.
    ``c_locale`` creates it with ``LC_COLLATE``/``LC_CTYPE`` ``C`` (``initdb --locale=C``), where
    character classes such as ``[[:alnum:]]`` only know ASCII.

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
