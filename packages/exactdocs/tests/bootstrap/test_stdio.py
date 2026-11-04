"""``exactdocs serve --stdio``: read-only, no token, nothing on stdout but MCP frames."""

import json
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from sqlalchemy.exc import OperationalError

from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import StartupError, open_database
from exactdocs.bootstrap.mcp import build_stdio_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef

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

        await SqliteLibraryRepository(server.engine).save(
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
    for files in (before, after):  # SQLite may create its WAL index files; never the database
        files.pop("exactdocs.db-shm", None)
        files.pop("exactdocs.db-wal", None)
    assert after == before, "the database file must be byte for byte unchanged"


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
