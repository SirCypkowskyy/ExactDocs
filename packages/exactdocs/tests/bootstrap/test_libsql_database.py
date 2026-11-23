"""#474: ExactDocs' own database on a libSQL server, SQLite's dialect over ``turso-serverless``.

The URL, the engine and the driver's adaption are checked everywhere (a fake stands for the
driver's connection). The cases marked ``server`` need ``EXACTDOCS_TEST_LIBSQL_DATABASE_URL``, an
empty libSQL server they wipe (CI starts one and runs them in its *Persistence suite on libSQL*
step, with the persistence contract tests' SQLite cases on the same server).
"""

import asyncio
import os
import sqlite3
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest
import turso_serverless
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

import databases
from exactdocs.bootstrap.backup import BackupError, database_path
from exactdocs.bootstrap.container import Container, vector_index
from exactdocs.bootstrap.database import (
    StartupError,
    is_libsql,
    is_postgres,
    open_database,
    shown_url,
)
from exactdocs.bootstrap.libsql_database import _Connection, auth_token, server_url
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository

SERVER_URL = "libsql://db.example.com:8443?authToken=not-a-real-token"
EXPIRED = "HTTP status 400: The stream has expired due to inactivity"
PROCESSES = 3

server = pytest.mark.skipif(
    databases.LIBSQL_DATABASE_URL is None, reason="needs EXACTDOCS_TEST_LIBSQL_DATABASE_URL"
)


def test_a_libsql_url_runs_on_sqlites_dialect_over_turso() -> None:
    settings = Settings(database_url=SERVER_URL)
    url = make_url(settings.effective_database_url)

    assert url.drivername == "sqlite+libsql"
    assert not settings.uses_postgres
    assert server_url(url) == "https://db.example.com:8443"
    assert auth_token(url) == "not-a-real-token"


def test_tls_0_reaches_a_server_over_plain_http() -> None:
    url = make_url(Settings(database_url="libsql://127.0.0.1:8080?tls=0").effective_database_url)

    assert server_url(url) == "http://127.0.0.1:8080"
    assert auth_token(url) is None


def test_the_token_never_shows_in_a_message() -> None:
    url = make_url(Settings(database_url=SERVER_URL).effective_database_url)

    assert "not-a-real-token" not in shown_url(url)


async def test_the_engine_is_sqlites_dialect_on_libsql_with_its_own_vectors() -> None:
    engine = open_database(Settings(database_url=SERVER_URL))
    try:
        assert engine.dialect.name == "sqlite"
        assert is_libsql(engine)
        assert not is_postgres(engine)
        vectors = vector_index(engine)
        assert vectors.requirement() == "libSQL vectors"  # never sqlite-vec: nothing to load
    finally:
        await engine.dispose()


async def test_a_sqlite_file_is_not_libsql() -> None:
    engine = open_database(Settings())
    try:
        assert not is_libsql(engine)
        assert vector_index(engine).requirement() == "sqlite-vec"
    finally:
        await engine.dispose()


def test_a_libsql_server_is_never_opened_read_only() -> None:
    with pytest.raises(StartupError, match="read-only"):
        open_database(Settings(database_url=SERVER_URL), read_only=True)


def test_the_url_names_the_server_only() -> None:
    with pytest.raises(StartupError, match="server only"):
        open_database(Settings(database_url="libsql://db.example.com/exactdocs"))


def test_backup_points_to_the_servers_own_backups() -> None:
    with pytest.raises(BackupError, match="libSQL"):
        database_path(Settings(database_url=SERVER_URL))


class _FakeCursor:
    """The driver's cursor: records statements, fails as the fake connection says."""

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self.arraysize = 1

    def execute(self, sql: str, parameters: object = ()) -> None:
        self.connection.sent.append((sql, parameters))
        if self.connection.failures:
            raise self.connection.failures.pop(0)

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _FakeConnection:
    """The driver's connection, in or out of a transaction."""

    def __init__(self, *failures: Exception, in_transaction: bool = False) -> None:
        self.failures = list(failures)
        self.in_transaction = in_transaction
        self.isolation_level = None
        self.sent: list[tuple[str, object]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def test_a_statement_outside_a_transaction_is_sent_again_once_its_stream_expired() -> None:
    inner = _FakeConnection(turso_serverless.OperationalError(EXPIRED))

    _Connection(inner).execute("SELECT 1")

    assert [sql for sql, _ in inner.sent] == ["SELECT 1", "SELECT 1"]


def test_inside_a_transaction_an_expired_stream_is_an_error() -> None:
    inner = _FakeConnection(turso_serverless.OperationalError(EXPIRED), in_transaction=True)

    with pytest.raises(sqlite3.OperationalError, match="expired"):
        _Connection(inner).execute("INSERT INTO t VALUES (1)")

    assert len(inner.sent) == 1  # the server rolled the transaction back: never sent again


def test_the_drivers_errors_are_sqlite3s() -> None:
    inner = _FakeConnection(turso_serverless.IntegrityError("UNIQUE constraint failed: t.id"))

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _Connection(inner).execute("INSERT INTO t VALUES (1)")


def test_blobs_are_sent_as_bytes() -> None:
    inner = _FakeConnection()

    _Connection(inner).execute("INSERT INTO t VALUES (?, :named)", [memoryview(b"\x00\x01")])
    _Connection(inner).execute("INSERT INTO t VALUES (:blob)", {"blob": memoryview(b"\x02")})

    assert [values for _, values in inner.sent] == [[b"\x00\x01"], {"blob": b"\x02"}]


def test_sqlalchemys_functions_are_accepted_and_others_refused() -> None:
    connection = _Connection(_FakeConnection())

    connection.create_function("regexp", 2, lambda *_: True, deterministic=True)
    connection.create_function("floor", 1, round, deterministic=True)
    with pytest.raises(sqlite3.NotSupportedError, match="libSQL"):
        connection.create_function("my_udf", 1, round)


@server
async def test_a_constraint_error_on_the_server_is_sqlites(monkeypatch: pytest.MonkeyPatch) -> None:
    databases.empty_libsql_database()
    monkeypatch.setenv("EXACTDOCS_DATABASE_URL", databases.libsql_database_url())
    engine = open_database(Settings())
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE test_unique (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO test_unique VALUES (1)"))
        with pytest.raises(IntegrityError) as raised:
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO test_unique VALUES (1)"))
        assert isinstance(raised.value.orig, sqlite3.IntegrityError)
        # sqld sends the primary code only (SQLITE_CONSTRAINT), no extended one.
        assert raised.value.orig.sqlite_errorcode & 0xFF == sqlite3.SQLITE_CONSTRAINT
    finally:
        await engine.dispose()


SAVE_ONE_LIBRARY = """
import asyncio, sys
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId

async def main(n: str) -> None:
    container = Container.build(Settings())
    async with container.running(jobs=False):  # each process migrates, as a server's start does
        await SqliteLibraryRepository(engine=container.engine).save(
            Library(id=LibraryId(f"/acme/lib{n}"), title=f"Lib {n}",
                    source_url=f"https://github.com/acme/lib{n}", host=HostKind.GITHUB)
        )

asyncio.run(main(sys.argv[1]))
"""


@server
async def test_several_processes_migrate_and_write_one_database_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    databases.empty_libsql_database()
    url = databases.libsql_database_url()

    def start(n: int) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "EXACTDOCS_DATABASE_URL": url,
            "EXACTDOCS_DATA_DIR": str(tmp_path / f"data-{n}"),
        }
        return subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
            [sys.executable, "-c", SAVE_ONE_LIBRARY, str(n)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    processes = [start(n) for n in range(PROCESSES)]
    outputs = await asyncio.gather(*(asyncio.to_thread(p.communicate) for p in processes))
    for process, (output, _) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, output.decode()

    monkeypatch.setenv("EXACTDOCS_DATABASE_URL", url)
    container = Container.build(Settings())
    async with container.running(jobs=False):
        saved = await SqliteLibraryRepository(engine=container.engine).list_all()
    assert sorted(str(library.id) for library in saved) == [
        f"/acme/lib{n}" for n in range(PROCESSES)
    ]
