"""``exactdocs backup`` / ``restore``: consistent while serving, complete, and refusing harm."""

import asyncio
import io
import json
import os
import sqlite3
import stat
import tarfile
import threading
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from sqlalchemy import Connection

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.backup import BackupError, create_backup, restore_backup
from exactdocs.bootstrap.constants import (
    DATABASE_MEMBER,
    JOBS_FILE,
    KNOWN_HOSTS_FILE,
    MANIFEST_MEMBER,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import alembic_config, open_database, schema_head
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.secret_box import FernetSecretBox
from exactdocs.ingestion.adapters.driven.sqlite import SqliteCredentialVault
from exactdocs.ingestion.constants import KEY_FILE
from exactdocs.ingestion.errors import CredentialsRequiredError
from exactdocs.ingestion.models import AccessToken

LIBRARY = "/acme/private"
"""A library with a stored credential."""
SCOPE = "github.com"
"""The host the credential is for."""
TOKEN = "ghp_backup_round_trip"
"""The stored credential's token."""
OLDER_REVISION = "a1c9e4d7b352"
"""The schema revision of release v0.2.0."""
WRITES = 200
"""Rows a concurrent writer adds while a backup runs."""


@pytest.fixture
def source(tmp_path: Path) -> Settings:
    """Settings of an instance that has been started once (database, key, known_hosts).

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The settings.
    """
    return Settings(data_dir=tmp_path / "source")


@pytest.fixture
def target(tmp_path: Path) -> Settings:
    """Settings of an empty data directory to restore into.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The settings.
    """
    return Settings(data_dir=tmp_path / "target")


@pytest.fixture
async def started(source: Settings) -> Settings:
    """Start the source instance once and store a repository credential in it.

    Args:
        source: The instance's settings.

    Returns:
        The same settings.
    """
    container = Container.build(source)
    async with container.running(jobs=False):
        vault = SqliteCredentialVault(
            engine=container.engine, box=FernetSecretBox.from_file(source.data_dir / KEY_FILE)
        )
        await vault.save(LIBRARY, SCOPE, AccessToken(token=TOKEN))
    return source


async def _load_credential(settings: Settings) -> AccessToken | None:
    """Open the stored credential with the data directory's own key file.

    Args:
        settings: The instance's settings.

    Returns:
        The credential.
    """
    engine = open_database(settings)
    try:
        vault = SqliteCredentialVault(
            engine=engine, box=FernetSecretBox.from_file(settings.data_dir / KEY_FILE)
        )
        credential = await vault.load(LIBRARY, SCOPE)
    finally:
        await engine.dispose()
    assert credential is None or isinstance(credential, AccessToken)
    return credential


def _members(archive: Path) -> dict[str, tarfile.TarInfo]:
    """List an archive's members.

    Args:
        archive: The archive.

    Returns:
        Its members by name.
    """
    with tarfile.open(archive, "r:gz") as tar:
        return {member.name: member for member in tar.getmembers()}


def _revision(database: Path) -> str:
    """Read a database file's schema revision.

    Args:
        database: The file.

    Returns:
        The revision.
    """
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _files(folder: Path) -> list[str]:
    """List what a folder holds, recursively (an absent folder holds nothing).

    Args:
        folder: The folder.

    Returns:
        The relative paths, sorted.
    """
    if not folder.exists():
        return []
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))


def _read(tar: tarfile.TarFile, name: str) -> bytes:
    """Read a regular-file member.

    Args:
        tar: The open archive.
        name: The member.

    Returns:
        Its content.
    """
    file = tar.extractfile(name)
    assert file is not None
    return file.read()


def _rewrite(archive: Path, change: str, content: bytes) -> None:
    """Replace one member of an archive, leaving the manifest as it was.

    Args:
        archive: The archive, rewritten in place.
        change: The member to replace.
        content: Its new content.
    """
    with tarfile.open(archive, "r:gz") as tar:
        members = [(m, _read(tar, m.name)) for m in tar.getmembers()]
    with tarfile.open(archive, "w:gz") as tar:
        for member, data in members:
            body = content if member.name == change else data
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))


async def test_a_round_trip_keeps_the_credentials_with_the_key(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    archive = tmp_path / "backup.tar.gz"

    summary = create_backup(started, archive, include_secret_key=True)
    restored = await restore_backup(target, archive)

    assert set(summary.members) == {DATABASE_MEMBER, KNOWN_HOSTS_FILE, KEY_FILE}
    assert set(_members(archive)) == {MANIFEST_MEMBER, *summary.members}
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert set(restored.members) == set(summary.members)
    assert restored.schema_from == restored.schema_to == schema_head()
    assert await _load_credential(target) == AccessToken(token=TOKEN)
    for name in (KEY_FILE, KNOWN_HOSTS_FILE, "exactdocs.db"):
        assert stat.S_IMODE((target.data_dir / name).stat().st_mode) == 0o600, name


async def test_the_key_stays_out_unless_asked_for(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    archive = tmp_path / "backup.tar.gz"

    summary = create_backup(started, archive)
    await restore_backup(target, archive)

    assert KEY_FILE not in summary.members
    assert not (target.data_dir / KEY_FILE).exists()
    # A fresh key cannot read it: the libraries ask for their credential again.
    with pytest.raises(CredentialsRequiredError):
        await _load_credential(target)


async def test_the_original_key_copied_in_first_opens_the_credentials(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    archive = tmp_path / "backup.tar.gz"
    create_backup(started, archive)
    target.data_dir.mkdir()
    (target.data_dir / KEY_FILE).write_bytes((started.data_dir / KEY_FILE).read_bytes())
    (target.data_dir / KEY_FILE).chmod(0o600)

    await restore_backup(target, archive)

    assert await _load_credential(target) == AccessToken(token=TOKEN)


async def test_the_durable_job_steps_are_backed_up(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    with closing(sqlite3.connect(started.data_dir / JOBS_FILE)) as jobs:
        jobs.execute("CREATE TABLE workflow_status (id TEXT)")
        jobs.execute("INSERT INTO workflow_status VALUES ('import-1')")
        jobs.commit()
    archive = tmp_path / "backup.tar.gz"

    summary = create_backup(started, archive)
    await restore_backup(target, archive)

    assert JOBS_FILE in summary.members
    with closing(sqlite3.connect(target.data_dir / JOBS_FILE)) as jobs:
        assert jobs.execute("SELECT id FROM workflow_status").fetchall() == [("import-1",)]


async def test_a_backup_is_consistent_while_another_connection_writes(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    database = started.data_dir / "exactdocs.db"
    with closing(sqlite3.connect(database)) as setup:
        setup.execute("CREATE TABLE pressure (n INTEGER)")
        setup.commit()
    done = threading.Event()

    def write() -> None:
        """Insert rows one transaction at a time until told to stop."""
        with closing(sqlite3.connect(database, timeout=10)) as writer:
            for n in range(WRITES):
                writer.execute("INSERT INTO pressure VALUES (?)", (n,))
                writer.commit()
                if done.is_set():
                    return

    thread = threading.Thread(target=write)
    thread.start()
    try:
        archive = tmp_path / "backup.tar.gz"
        create_backup(started, archive)
    finally:
        done.set()
        thread.join()
    await restore_backup(target, archive)

    with closing(sqlite3.connect(target.data_dir / "exactdocs.db")) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = [n for (n,) in restored.execute("SELECT n FROM pressure ORDER BY n")]
    assert rows == list(range(len(rows)))  # a prefix of the writes: one moment's view


def _downgrade(connection: Connection, revision: str) -> None:
    """Take the schema back to an older revision.

    Args:
        connection: A connection to the database.
        revision: The revision to go back to.
    """
    config = alembic_config()
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


async def test_an_older_backup_is_migrated(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    engine = open_database(started)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, OLDER_REVISION)
    finally:
        await engine.dispose()
    archive = tmp_path / "backup.tar.gz"

    summary = create_backup(started, archive)
    restored = await restore_backup(target, archive)

    assert summary.schema_revision == restored.schema_from == OLDER_REVISION
    assert restored.schema_to == schema_head()
    assert _revision(target.data_dir / "exactdocs.db") == schema_head()


async def test_a_newer_backup_is_refused_and_nothing_is_written(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    with closing(sqlite3.connect(started.data_dir / "exactdocs.db")) as database:
        database.execute("UPDATE alembic_version SET version_num = 'f00dfeedf00d'")
        database.commit()
    archive = tmp_path / "backup.tar.gz"
    create_backup(started, archive)

    with pytest.raises(BackupError, match=r"f00dfeedf00d.*newer"):
        await restore_backup(target, archive)

    assert _files(target.data_dir) == []


async def test_a_damaged_archive_is_refused_and_nothing_is_left(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    archive = tmp_path / "backup.tar.gz"
    create_backup(started, archive)
    _rewrite(archive, KNOWN_HOSTS_FILE, b"evil.example ssh-ed25519 AAAA\n")

    with pytest.raises(BackupError, match="checksum"):
        await restore_backup(target, archive)

    assert _files(target.data_dir) == []  # no database, no half-written file


async def test_a_manifest_naming_other_files_is_refused(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    archive = tmp_path / "backup.tar.gz"
    create_backup(started, archive)
    with tarfile.open(archive, "r:gz") as tar:
        manifest = json.loads(_read(tar, MANIFEST_MEMBER))
    manifest["files"]["../../escape"] = "0" * 64
    _rewrite(archive, MANIFEST_MEMBER, json.dumps(manifest).encode())

    with pytest.raises(BackupError, match="damaged manifest"):
        await restore_backup(target, archive)

    assert _files(target.data_dir) == []


@pytest.mark.parametrize("content", [b"", b"not a tar at all", b"\x1f\x8b\x08\x00broken"])
async def test_something_else_is_not_a_backup(
    target: Settings, tmp_path: Path, content: bytes
) -> None:
    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(content)

    with pytest.raises(BackupError, match="ExactDocs backup"):
        await restore_backup(target, archive)


async def test_restore_never_overwrites_an_instance(started: Settings, tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.gz"
    create_backup(started, archive)
    before = (started.data_dir / "exactdocs.db").read_bytes()

    with pytest.raises(BackupError, match="already"):
        await restore_backup(started, archive)

    assert (started.data_dir / "exactdocs.db").read_bytes() == before


async def test_an_existing_archive_is_not_overwritten(started: Settings, tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.gz"
    archive.write_bytes(b"keep me")

    with pytest.raises(BackupError, match="already exists"):
        create_backup(started, archive)

    assert archive.read_bytes() == b"keep me"


def test_without_a_database_there_is_nothing_to_back_up(source: Settings, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="No ExactDocs database"):
        create_backup(source, tmp_path / "backup.tar.gz")

    assert not source.data_dir.exists()


def test_other_databases_are_left_to_their_own_tools(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, database_url="postgresql://db/exactdocs")

    with pytest.raises(BackupError, match="pg_dump"):
        create_backup(settings, tmp_path / "backup.tar.gz")


async def test_the_cli_backs_up_to_stdout_and_restores(
    started: Settings, target: Settings, tmp_path: Path
) -> None:
    piped = io.BytesIO()
    with (
        patch.dict(os.environ, {"EXACTDOCS_DATA_DIR": str(started.data_dir)}),
        patch("sys.stdout", io.TextIOWrapper(piped, encoding="utf-8")),
    ):
        cli.app(["backup", "-"], exit_on_error=False, result_action="return_value")
        written = piped.getvalue()  # the wrapper closes it once dropped
    archive = tmp_path / "piped.tar.gz"
    archive.write_bytes(written)
    assert MANIFEST_MEMBER in _members(archive)

    output = io.StringIO()
    with (
        patch.dict(os.environ, {"EXACTDOCS_DATA_DIR": str(target.data_dir)}),
        redirect_stdout(output),
    ):
        # A thread: the command runs its own event loop, as it does in a shell.
        await asyncio.to_thread(
            cli.app, ["restore", str(archive)], exit_on_error=False, result_action="return_value"
        )

    assert "Restored" in output.getvalue()
    assert "holds no secret.key" in output.getvalue()
    assert _revision(target.data_dir / "exactdocs.db") == schema_head()


def test_the_cli_says_why_a_restore_is_refused(tmp_path: Path) -> None:
    with (
        patch.dict(os.environ, {"EXACTDOCS_DATA_DIR": str(tmp_path / "data")}),
        pytest.raises(SystemExit, match="exactdocs: There is no backup at"),
    ):
        cli.app(
            ["restore", str(tmp_path / "missing.tar.gz")],
            exit_on_error=False,
            result_action="return_value",
        )
