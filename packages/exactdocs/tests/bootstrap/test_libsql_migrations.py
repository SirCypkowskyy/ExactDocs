"""#358: ExactDocs' migrations on libSQL give SQLite's schema.

ExactDocs' database runs on a libSQL server through ``turso-serverless`` (#474,
``test_libsql_database.py``). These tests check the schema itself: they run every Alembic
revision on libSQL through the sync ``libsql`` driver, on a local file and on a libSQL server
(``EXACTDOCS_TEST_LIBSQL_URL``),
and compare the result with stdlib SQLite's, so a revision that libSQL's SQLite (3.45) cannot run
shows up. They need the ``libsql`` package (a Python 3.14 wheel for Linux x86_64 only), so they
skip elsewhere; CI's x86_64 runners run them.
"""

import asyncio
import importlib
import importlib.util
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import StaticPool

import integration
import libsql_backends
from exactdocs.bootstrap.constants import MIGRATIONS
from exactdocs.bootstrap.database import _upgrade

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("libsql") is None, reason="needs the libsql package"
)

SCHEMA = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY 1, 2"


class _Sqlite3Hooks:
    """A ``libsql`` connection with the two sqlite3 hooks SQLAlchemy's SQLite dialect calls.

    ``create_function`` (the dialect's REGEXP) does not exist in ``libsql``; no revision uses it.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def create_function(self, *_: object, **__: object) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _migrated(connect: Callable[[], Any]) -> list[tuple[str, str, str | None]]:
    """Run every revision on a fresh database (as ``migrate`` does), then read its schema."""
    raw = connect()
    engine = create_engine("sqlite://", creator=lambda: raw, poolclass=StaticPool)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            with connection.begin():
                _upgrade(connection, MIGRATIONS)
            return _schema(connection)
    finally:
        engine.dispose()
        raw.close()


def _schema(connection: Connection) -> list[tuple[str, str, str | None]]:
    return [(t, n, s) for t, n, s in connection.exec_driver_sql(SCHEMA).all()]


def _sqlite_schema(tmp_path: Path) -> list[tuple[str, str, str | None]]:
    path = tmp_path / "sqlite.db"
    found = _migrated(lambda: sqlite3.connect(path, isolation_level=None))
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT count(*) FROM alembic_version").fetchone() == (1,)
    return found


def test_every_revision_runs_on_a_local_libsql_file(tmp_path: Path) -> None:
    driver: Any = importlib.import_module("libsql")
    path = str(tmp_path / "libsql.db")

    found = _migrated(lambda: _Sqlite3Hooks(driver.connect(path, isolation_level=None)))

    assert found == _sqlite_schema(tmp_path)


OTHERS = ("test_", "behave_", "libsql_")
"""Tables of a shared test server that are not the schema's: the libSQL backend tests' own, and
libSQL's (``libsql_vector_meta_shadow``, made with the first vector index)."""


@integration.LIBSQL
def test_every_revision_runs_on_a_libsql_server(tmp_path: Path) -> None:
    driver: Any = importlib.import_module("libsql")
    assert libsql_backends.LIBSQL_URL is not None
    url, token = libsql_backends.LIBSQL_URL, libsql_backends.LIBSQL_TOKEN or ""
    if any(kind == "table" for kind, _ in _tables(driver, url, token)):
        pytest.skip("the server holds tables of its own: it needs an empty one")

    try:
        found = _migrated(lambda: _Sqlite3Hooks(driver.connect(url, auth_token=token)))
    finally:
        _drop_schema(driver, url, token)

    # The server re-spells a virtual table's CREATE statement (its whitespace): same schema.
    assert _spelled([r for r in found if not r[1].startswith(OTHERS)]) == _spelled(
        _sqlite_schema(tmp_path)
    )


def _spelled(schema: list[tuple[str, str, str | None]]) -> list[tuple[str, str, str | None]]:
    return [(t, n, s if s is None else re.sub(r"\s+", "", s)) for t, n, s in schema]


def _tables(driver: Any, url: str, token: str) -> list[tuple[str, str]]:
    """The server's triggers, views and tables but ``OTHERS``, in the order they can be dropped.

    Triggers and views first (they name tables), then virtual tables (they own shadow tables).
    """
    connection = driver.connect(url, auth_token=token)
    try:
        rows = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view', 'table') "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' "
            "ORDER BY type = 'table', coalesce(sql, '') NOT LIKE 'CREATE VIRTUAL TABLE%', name"
        ).fetchall()
    finally:
        connection.close()
    return [(t, n) for t, n in rows or [] if not n.startswith(OTHERS)]


def _drop_schema(driver: Any, url: str, token: str) -> None:
    """Drop what the revisions made on the server, in one request.

    Over HTTP each request is a stream (a connection) of its own, so ``PRAGMA foreign_keys=OFF``
    only lasts for the statements sent with it.
    """
    dropped = [
        (f'DROP {kind.upper()} IF EXISTS "{name}"', ())
        for kind, name in _tables(driver, url, token)
    ]
    if not dropped:
        return

    async def drop() -> None:
        engine = libsql_backends.admin()
        await engine.open()
        try:
            await engine.run([("PRAGMA foreign_keys=OFF", ()), *dropped], atomic=False)
        finally:
            await engine.close()

    asyncio.run(drop())
