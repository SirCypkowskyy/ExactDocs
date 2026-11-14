"""``exactdocs serve --stdio``: read-only, no token, nothing on stdout but MCP frames."""

import json
import os
import sqlite3
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from datetime import date
from pathlib import Path

import aiosqlite
import pytest
from fastmcp import Client
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection

from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import (
    StartupError,
    open_database,
    open_spend_ledger_database,
    spend_ledger_authorizer,
)
from exactdocs.bootstrap.mcp import build_stdio_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.models import SpendEntry, SpendKey, SpendWindow

CLI = "from exactdocs.bootstrap.cli import main; main()"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST_LIBRARIES = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "list_libraries", "arguments": {}},
}


def database() -> Path:
    return Settings().data_dir / "exactdocs.db"


def snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


async def listed() -> list[str]:
    container = ReadOnlyContainer.build(Settings())
    async with container.running(), Client(build_stdio_mcp(container)) as mcp:
        result = await mcp.call_tool("list_libraries", {})
    return [library["id"] for library in result.structured_content["libraries"]]


@pytest.mark.usefixtures("demo_catalog")
async def test_lists_libraries_next_to_a_running_server_that_keeps_writing() -> None:
    server = Container.build(Settings())
    async with server.running():  # the HTTP server: WAL mode, its connections open
        assert await listed() == ["/acme/ledger", "/acme/payments"]

        await SqliteLibraryRepository(engine=server.engine).save(
            Library(
                id=LibraryId("/acme/new"),
                title="New",
                source_url="https://example.com/new.git",
                host=HostKind.GIT,
                default_branch=VersionRef("main"),
                versions=frozenset(),
            )
        )

        assert "/acme/new" in await listed()  # a new transaction sees what the server committed


@pytest.mark.usefixtures("demo_catalog")
async def test_lists_libraries_with_the_server_stopped_and_leaves_the_files_alone() -> None:
    before = snapshot(database().parent)

    assert await listed() == ["/acme/ledger", "/acme/payments"]

    after = snapshot(database().parent)
    created = after.keys() - before.keys()
    assert created <= {"exactdocs.db-shm", "exactdocs.db-wal"}, "only SQLite's WAL index files"
    assert {name: after[name] for name in before} == before, "existing files byte for byte"


@pytest.mark.usefixtures("demo_catalog")
async def test_the_engine_refuses_every_write() -> None:
    engine = open_database(Settings(), read_only=True)
    try:
        async with engine.connect() as connection:
            with pytest.raises(OperationalError, match="readonly"):
                await connection.exec_driver_sql("CREATE TABLE x (a)")
            with pytest.raises(OperationalError, match="readonly"):
                await connection.exec_driver_sql("DELETE FROM catalog_libraries")
    finally:
        await engine.dispose()


TODAY = SpendKey(
    scope_kind="instance", scope_id="", window=SpendWindow.DAY, window_start=date(2026, 11, 12)
)


@pytest.mark.usefixtures("demo_catalog")
async def test_the_spend_ledger_engine_adds_spend_the_server_reads_once_per_replay() -> None:
    server = Container.build(Settings())
    ledger = open_spend_ledger_database(Settings())
    spent = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=SpendWindow.DAY,
        window_start=TODAY.window_start,
        input_tokens=50,
        output_tokens=10,
        requests=1,
        token="response-1",
    )
    try:
        async with server.running():  # the HTTP server, writing beside it
            await SqliteSpendLedger(engine=ledger).add([spent])
            await SqliteSpendLedger(engine=ledger).add([spent])  # a replay: counted once

            row = (await SqliteSpendLedger(engine=server.engine).get([TODAY]))[TODAY]
    finally:
        await ledger.dispose()

    assert (row.input_tokens, row.output_tokens, row.requests) == (50, 10, 1)


DENIED = "not authorized|authorization denied"  # at prepare time, or (VACUUM) when it runs
DELETE_CATALOG = "AFTER INSERT ON retrieval_ai_spend BEGIN DELETE FROM catalog_libraries; END"


@pytest.mark.usefixtures("demo_catalog")
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM catalog_libraries",
        "UPDATE catalog_libraries SET title = 'x'",
        "INSERT INTO retrieval_hyde_answers SELECT * FROM retrieval_hyde_answers",
        "CREATE TABLE x (a)",
        "DROP TABLE retrieval_ai_spend",
        "ALTER TABLE retrieval_ai_spend ADD COLUMN x",
        "CREATE INDEX x ON retrieval_ai_spend (requests)",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA journal_mode=DELETE",
        "PRAGMA writable_schema=ON",
        "PRAGMA incremental_vacuum",
        "PRAGMA wal_checkpoint",
        "PRAGMA wal_checkpoint(TRUNCATE)",
        "PRAGMA optimize",
        "VACUUM",
        "VACUUM INTO 'copy.db'",
        "CREATE TEMP TABLE x (a)",
        "CREATE TEMP VIEW x AS SELECT 1",
        f"CREATE TRIGGER x {DELETE_CATALOG}",
        f"CREATE TEMP TRIGGER x {DELETE_CATALOG}",
    ],
)
async def test_the_spend_ledger_engine_writes_nothing_else(statement: str) -> None:
    ledger = open_spend_ledger_database(Settings())
    try:
        async with ledger.connect() as connection:  # no transaction: VACUUM would refuse one
            driver = await _driver(connection)
            with pytest.raises(sqlite3.DatabaseError, match=DENIED):
                await driver.execute(statement)
    finally:
        await ledger.dispose()


@pytest.mark.usefixtures("demo_catalog")
async def test_the_spend_ledger_engine_writes_no_temp_table_named_like_the_ledger() -> None:
    ledger = open_spend_ledger_database(Settings())
    try:
        async with ledger.connect() as connection:
            driver = await _driver(connection)
            await driver.set_authorizer(None)  # only the test can make the shadowing table
            await driver.execute(
                "CREATE TEMP TABLE retrieval_ai_spend_replays AS "
                "SELECT * FROM main.retrieval_ai_spend_replays WHERE 0"
            )
            await driver.set_authorizer(spend_ledger_authorizer)
            with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                await driver.execute(
                    "INSERT INTO temp.retrieval_ai_spend_replays "
                    "SELECT * FROM main.retrieval_ai_spend_replays"
                )
    finally:
        await ledger.dispose()


async def _driver(connection: AsyncConnection) -> aiosqlite.Connection:
    """Return the aiosqlite connection under one of the spend ledger engine's connections."""
    driver = (await connection.get_raw_connection()).driver_connection
    assert isinstance(driver, aiosqlite.Connection)
    return driver


@pytest.mark.usefixtures("demo_catalog")
@pytest.mark.parametrize("pragma", ["user_version", "journal_mode", "busy_timeout"])
async def test_the_spend_ledger_engine_may_read_a_pragma(pragma: str) -> None:
    ledger = open_spend_ledger_database(Settings())
    try:
        async with ledger.connect() as connection:
            assert (await connection.exec_driver_sql(f"PRAGMA {pragma}")).scalar() is not None
    finally:
        await ledger.dispose()


async def test_the_spend_ledger_engine_never_creates_a_database(tmp_path: Path) -> None:
    with pytest.raises(StartupError, match="No ExactDocs database"):
        open_spend_ledger_database(Settings(data_dir=tmp_path / "missing"))
    assert not (tmp_path / "missing").exists()


async def test_works_before_any_account_exists() -> None:
    server = Container.build(Settings())
    async with server.running():  # migrated, empty: no account, no library
        pass

    assert await listed() == []


async def test_building_it_creates_no_key_known_hosts_or_directory(tmp_path: Path) -> None:
    server = Container.build(Settings())
    async with server.running():
        pass
    data_dir = Settings().data_dir
    for name in ("secret.key", "known_hosts"):
        (data_dir / name).unlink(missing_ok=True)

    await listed()

    assert not (data_dir / "secret.key").exists()
    assert not (data_dir / "known_hosts").exists()
    with pytest.raises(StartupError, match="No ExactDocs database"):
        ReadOnlyContainer.build(Settings(data_dir=tmp_path / "missing"))
    assert not (tmp_path / "missing").exists()


async def test_a_database_that_was_never_migrated_is_refused() -> None:
    database().parent.mkdir(parents=True)
    database().touch()

    container = ReadOnlyContainer.build(Settings())
    with pytest.raises(StartupError, match="empty"):
        async with container.running():
            pass


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, *args],
        capture_output=True,
        text=True,
        env=os.environ,
        timeout=60,
        check=False,
    )


def test_a_missing_database_is_a_clear_error_on_stderr() -> None:
    result = run_cli("serve", "--stdio")

    assert result.returncode != 0
    assert not result.stdout
    assert str(database()) in result.stderr
    assert not database().parent.exists()


@pytest.mark.usefixtures("demo_catalog")
def test_stdout_carries_nothing_but_mcp_frames() -> None:
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, "serve", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    for message in (INITIALIZE, INITIALIZED, LIST_LIBRARIES):
        process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    # Stdin stays open until both answers came: closing it early ends the session.
    lines = [process.stdout.readline(), process.stdout.readline()]
    process.stdin.close()
    rest, stderr = process.communicate(timeout=60)

    assert not rest, "after the two answers nothing else is written"
    assert [json.loads(line)["id"] for line in lines] == [1, 2]  # raises on any non-JSON line
    assert all(json.loads(line)["jsonrpc"] == "2.0" for line in lines)
    assert "/acme/payments" in lines[1]
    assert process.returncode == 0, stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
@pytest.mark.usefixtures("demo_catalog")
def test_a_read_only_directory_without_wal_files_is_a_clear_startup_error() -> None:
    directory = database().parent
    assert not (directory / "exactdocs.db-wal").exists()  # a stopped server leaves none
    directory.chmod(0o555)
    try:
        result = run_cli("serve", "--stdio")
    finally:
        directory.chmod(0o755)

    assert result.returncode != 0
    assert not result.stdout
    assert str(database()) in result.stderr
    assert "writable" in result.stderr
    assert "same user" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("demo_catalog")
async def test_a_database_from_a_newer_exactdocs_says_to_upgrade() -> None:
    engine = open_database(Settings())
    async with engine.begin() as connection:
        await connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'ffffffffffff'")
    await engine.dispose()

    container = ReadOnlyContainer.build(Settings())
    with pytest.raises(StartupError, match="newer ExactDocs") as raised:
        async with container.running():
            pass
    assert "Upgrade" in str(raised.value)
    assert "exactdocs serve" not in str(raised.value)


@pytest.mark.parametrize("option", ["--host=0.0.0.0", "--port=9000", "--reload"])
def test_http_options_are_rejected_with_stdio(option: str) -> None:
    result = run_cli("serve", "--stdio", option)

    assert result.returncode != 0
    assert not result.stdout
    assert "HTTP options" in result.stderr
