"""``exactdocs backup`` and ``exactdocs restore``: one archive holds a whole instance.

A backup is a gzipped tar of consistent SQLite snapshots, taken with SQLite's online backup API
while the server keeps serving, plus the small files of the data directory that matter:

- ``exactdocs.db``: everything ExactDocs stores (libraries, versions, articles, chunks, images,
  settings, accounts, sessions, token hashes, encrypted repository credentials);
- ``jobs.sqlite``: DBOS's durable steps, so an import that was running resumes after a restore;
- ``known_hosts``: the SSH host keys trusted so far;
- ``secret.key``: only on request, because next to the encrypted credentials it decrypts them;
- ``manifest.json``: the archive format, the ExactDocs version and schema revision, and a
  SHA-256 of every other member.

``jobs.sqlite`` is copied before the database: a resumed import may then redo a step the database
already recorded (steps are idempotent), but never skip one it lacks.

A restore writes into a data directory that holds no instance yet, refuses a schema newer than
this build knows, and migrates an older one, as ``serve`` would.
"""

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    BACKUP_FORMAT,
    BUSY_TIMEOUT_MS,
    COPY_CHUNK_BYTES,
    DATABASE_MEMBER,
    JOBS_FILE,
    KNOWN_HOSTS_FILE,
    MANIFEST_MEMBER,
    PRIVATE_FILE_MODE,
)
from exactdocs.bootstrap.container import ReadOnlyContainer
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.constants import KEY_FILE


class BackupError(RuntimeError):
    """A backup or restore cannot be done; the message says why and what to do."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BackupSummary:
    """What ``create_backup`` wrote."""

    path: Path
    """The archive."""
    schema_revision: str
    """Schema revision of the database in it."""
    members: tuple[str, ...]
    """The files it holds, manifest excluded."""
    size: int
    """Its size in bytes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreSummary:
    """What ``restore_backup`` did."""

    members: tuple[str, ...]
    """The files restored."""
    version: str
    """The ExactDocs version that made the backup."""
    schema_from: str
    """The schema revision in the backup."""
    schema_to: str | None
    """The schema revision after the migration (this build's head)."""
    reindex_required: bool
    """The search index was built in an older format: ``exactdocs reindex`` rebuilds it."""


def create_backup(
    settings: Settings, destination: Path, *, include_secret_key: bool = False
) -> BackupSummary:
    """Write a consistent archive of the instance, while it may be serving.

    Args:
        settings: Where the instance keeps its data.
        destination: The archive to write; it must not exist yet.
        include_secret_key: Also store ``secret.key`` (then guard the archive like the key).

    Returns:
        What was written.

    Raises:
        BackupError: There is no database, or the archive cannot be written there.
    """
    database = database_path(settings)
    if not database.is_file():
        message = (
            f"No ExactDocs database at {database}: set EXACTDOCS_DATA_DIR (or "
            "EXACTDOCS_DATABASE_URL) to the instance's, and run the backup where the server runs."
        )
        raise BackupError(message)
    if destination.exists():
        message = f"{destination} already exists: choose another path, or remove it first."
        raise BackupError(message)
    key = settings.data_dir / KEY_FILE
    if include_secret_key and not key.is_file():
        message = f"There is no {key} to include" + (
            ": the key is EXACTDOCS_SECRET_KEY; keep that variable instead."
            if settings.secret_key
            else "."
        )
        raise BackupError(message)
    try:
        revision, members = _stage_and_write(
            settings, database, destination, include_secret_key=include_secret_key
        )
    except OSError as exc:
        message = f"Cannot write the backup to {destination}: {exc.strerror or exc}."
        raise BackupError(message) from exc
    return BackupSummary(
        path=destination,
        schema_revision=revision,
        members=members,
        size=destination.stat().st_size,
    )


def _stage_and_write(
    settings: Settings, database: Path, destination: Path, *, include_secret_key: bool
) -> tuple[str, tuple[str, ...]]:
    """Snapshot and copy every member next to the destination, then write the archive.

    Args:
        settings: Where the instance keeps its data.
        database: The database file.
        destination: The archive to write.
        include_secret_key: Also store ``secret.key``.

    Returns:
        The database's schema revision and the members written (manifest excluded).

    Raises:
        BackupError: The database has no schema revision, or a copy is damaged.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".exactdocs-backup-") as tmp:
        staging = Path(tmp)
        members: dict[str, Path] = {}
        # Jobs first: a resumed import may redo a step, never skip one (module docstring).
        jobs = settings.data_dir / JOBS_FILE
        if jobs.is_file():
            members[JOBS_FILE] = _snapshot(jobs, staging / JOBS_FILE)
        members[DATABASE_MEMBER] = _snapshot(database, staging / DATABASE_MEMBER)
        revision = _revision(members[DATABASE_MEMBER])
        if revision is None:
            message = f"{database} is not an ExactDocs database (it has no schema revision)."
            raise BackupError(message)
        copies = [(KNOWN_HOSTS_FILE, settings.data_dir / KNOWN_HOSTS_FILE)]
        if include_secret_key:
            copies.append((KEY_FILE, settings.data_dir / KEY_FILE))
        for name, source in copies:
            if source.is_file():
                members[name] = shutil.copyfile(source, staging / name)
        manifest = {
            "format": BACKUP_FORMAT,
            "exactdocs_version": __version__,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_revision": revision,
            "files": {name: _sha256(path) for name, path in members.items()},
        }
        manifest_path = staging / MANIFEST_MEMBER
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _write_archive(destination, [(MANIFEST_MEMBER, manifest_path), *members.items()])
    return revision, tuple(members)


async def restore_backup(settings: Settings, archive: Path) -> RestoreSummary:
    """Restore an archive into a data directory that holds no instance, then migrate it.

    Nothing is written before the archive is known to be complete, intact and not newer than
    this build.

    Args:
        settings: Where the restored instance will keep its data.
        archive: An archive ``create_backup`` wrote.

    Returns:
        What was restored.

    Raises:
        BackupError: The archive is unusable or newer, or the data directory is not empty.
    """
    database = database_path(settings)
    targets = {
        DATABASE_MEMBER: database,
        JOBS_FILE: settings.data_dir / JOBS_FILE,
        KNOWN_HOSTS_FILE: settings.data_dir / KNOWN_HOSTS_FILE,
        KEY_FILE: settings.data_dir / KEY_FILE,
    }
    with _open_archive(archive) as tar:
        manifest = _manifest(tar, archive, allowed=set(targets))
        revision = str(manifest["schema_revision"])
        _refuse_newer(revision)
        files: dict[str, str] = manifest["files"]
        occupied = [
            path
            for path in (*(targets[name] for name in files), database, _sidecar(database, "-wal"))
            if path.exists()
        ]
        if occupied:
            message = (
                f"{occupied[0]} already exists: the data directory already holds an instance. "
                "Restore only into an empty data directory (EXACTDOCS_DATA_DIR), with the server "
                "stopped."
            )
            raise BackupError(message)
        _extract(tar, archive, files, targets)
    engine = open_database(settings)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()
    read = ReadOnlyContainer.build(settings)
    async with read.running():
        index = await read.retrieval.get_search_index_state()
    return RestoreSummary(
        members=tuple(files),
        version=str(manifest.get("exactdocs_version", "unknown")),
        schema_from=revision,
        schema_to=_head(),
        reindex_required=index.needs_rebuild,
    )


def database_path(settings: Settings) -> Path:
    """Return the SQLite file the settings name, without touching the disk.

    Args:
        settings: The instance's settings.

    Returns:
        The database file.

    Raises:
        BackupError: The database is not a SQLite file (PostgreSQL: use ``pg_dump``).
    """
    try:
        url = make_url(settings.effective_database_url)
    except ArgumentError as exc:
        message = "EXACTDOCS_DATABASE_URL is not a valid database URL."
        raise BackupError(message) from exc
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        message = (
            "exactdocs backup copies a SQLite database file; back up other databases with their "
            "own tools (PostgreSQL: pg_dump)."
        )
        raise BackupError(message)
    return Path(url.database)


def _snapshot(source: Path, target: Path) -> Path:
    """Copy a live SQLite database consistently with the online backup API.

    One step: the copy is one read transaction's view, and in WAL mode writers carry on.

    Args:
        source: The database, possibly in use.
        target: Where the copy goes (a self-contained file, rollback journal mode).

    Returns:
        ``target``.

    Raises:
        BackupError: The copy fails its integrity check.
    """
    uri = f"{source.resolve().as_uri()}?mode=rw"  # never create a missing file
    with (
        contextlib.closing(
            sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
        ) as reader,
        contextlib.closing(sqlite3.connect(target)) as writer,
    ):
        reader.execute("PRAGMA query_only=ON")
        reader.backup(writer)
        writer.execute("PRAGMA journal_mode=DELETE")
        check = writer.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        message = f"The copy of {source} fails SQLite's integrity check: {check}"
        raise BackupError(message)
    return target


def _revision(database: Path) -> str | None:
    """Read the schema revision of a database file.

    Args:
        database: The file.

    Returns:
        The Alembic revision, or ``None`` when there is none.
    """
    with contextlib.closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        try:
            row = db.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return row[0] if row else None


def _head() -> str | None:
    """Return this build's schema head.

    Returns:
        The head revision.
    """
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _refuse_newer(revision: str) -> None:
    """Refuse a schema revision this build does not know: a newer release wrote it.

    Args:
        revision: The backup's schema revision.

    Raises:
        BackupError: The revision is unknown.
    """
    script = ScriptDirectory.from_config(alembic_config())
    if revision in {r.revision for r in script.walk_revisions()}:
        return
    message = (
        f"The backup's database is at schema revision {revision}, newer than this ExactDocs "
        f"{__version__} knows (up to {script.get_current_head()}). Restore it with the release "
        "that made it, or a newer one (for uvx: `uvx --refresh exactdocs`)."
    )
    raise BackupError(message)


def _sha256(path: Path) -> str:
    """Hash a file.

    Args:
        path: The file.

    Returns:
        Its SHA-256, hex.
    """
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _write_archive(destination: Path, members: list[tuple[str, Path]]) -> None:
    """Write the gzipped tar, private from the first byte, and move it into place at the end.

    Args:
        destination: The archive's final path.
        members: Name in the archive and file, in order.
    """
    partial = destination.with_name(f".{destination.name}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb") as file, tarfile.open(fileobj=file, mode="w:gz") as tar:
            for name, path in members:
                info = tar.gettarinfo(path, arcname=name)
                info.mode, info.uid, info.gid, info.uname, info.gname = (
                    PRIVATE_FILE_MODE,
                    0,
                    0,
                    "",
                    "",
                )
                with path.open("rb") as content:
                    tar.addfile(info, content)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


@contextlib.contextmanager
def _open_archive(archive: Path) -> Generator[tarfile.TarFile]:
    """Open a backup archive for reading.

    Args:
        archive: The file.

    Yields:
        The open tar.

    Raises:
        BackupError: It is missing, not a gzipped tar, or cut short.
    """
    if not archive.is_file():
        message = f"There is no backup at {archive}."
        raise BackupError(message)
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            yield tar
    except (tarfile.TarError, EOFError, zlib.error) as exc:
        message = f"{archive} is not a readable ExactDocs backup (a gzipped tar): {exc}."
        raise BackupError(message) from exc


def _manifest(tar: tarfile.TarFile, archive: Path, *, allowed: set[str]) -> dict:
    """Read and check the archive's manifest.

    Args:
        tar: The open archive.
        archive: Its path, for messages.
        allowed: The member names a restore knows how to place.

    Returns:
        The manifest.

    Raises:
        BackupError: It is missing, of another format, or lists unknown or missing files.
    """
    try:
        member = tar.getmember(MANIFEST_MEMBER)
        file = tar.extractfile(member) if member.isreg() else None
        manifest = json.load(file) if file else None
    except KeyError, ValueError, tarfile.TarError, OSError, EOFError:
        manifest = None
    if not isinstance(manifest, dict):
        message = f"{archive} is not an ExactDocs backup (no readable {MANIFEST_MEMBER})."
        raise BackupError(message)
    if manifest.get("format") != BACKUP_FORMAT:
        message = (
            f"{archive} is a backup of format {manifest.get('format')!r}; this ExactDocs "
            f"{__version__} reads format {BACKUP_FORMAT}. Restore it with the release that made "
            f"it ({manifest.get('exactdocs_version', 'unknown')}) or a newer one."
        )
        raise BackupError(message)
    files = manifest.get("files")
    if (
        not isinstance(files, dict)
        or DATABASE_MEMBER not in files
        or not set(files) <= allowed
        or not isinstance(manifest.get("schema_revision"), str)
    ):
        message = f"{archive} has a damaged manifest: restore from another backup."
        raise BackupError(message)
    return manifest


def _sidecar(database: Path, suffix: str) -> Path:
    """Name a SQLite companion file of the database (``-wal``, ``-shm``).

    Args:
        database: The database file.
        suffix: The companion's suffix.

    Returns:
        Its path.
    """
    return database.with_name(database.name + suffix)


def _extract(
    tar: tarfile.TarFile, archive: Path, files: dict[str, str], targets: dict[str, Path]
) -> None:
    """Write every member next to its target, check it, then move them all into place.

    Args:
        tar: The open archive.
        archive: Its path, for messages.
        files: Member name to expected SHA-256.
        targets: Member name to the path it is restored to.

    Raises:
        BackupError: A member is missing, not a file, or differs from its checksum.
    """
    staged: dict[str, Path] = {}
    try:
        for name, expected in files.items():
            target = targets[name]
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            staged[name] = target.with_name(f".{target.name}.restoring")
            if _copy_member(tar, name, staged[name]) != expected:
                message = f"{archive} is damaged ({name} differs from its checksum)."
                raise BackupError(message)
        if _revision(staged[DATABASE_MEMBER]) is None:
            message = f"{archive} holds no ExactDocs database."
            raise BackupError(message)
        for name, path in staged.items():
            path.replace(targets[name])
        staged.clear()
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def _copy_member(tar: tarfile.TarFile, name: str, target: Path) -> str:
    """Copy one regular-file member out of the archive (never a link or a path of its own).

    Args:
        tar: The open archive.
        name: The member.
        target: The new file to write, private.

    Returns:
        The SHA-256 of what was written.

    Raises:
        BackupError: The member is missing or not a regular file.
    """
    try:
        member = tar.getmember(name)
    except KeyError:
        member = None
    source: IO[bytes] | None = tar.extractfile(member) if member and member.isreg() else None
    if source is None:
        message = f"The backup lacks {name}, or it is not a regular file."
        raise BackupError(message)
    digest = hashlib.sha256()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "wb") as file, source:
        while chunk := source.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
            file.write(chunk)
    return digest.hexdigest()
