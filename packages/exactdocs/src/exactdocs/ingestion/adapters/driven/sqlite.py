import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    Row,
    Table,
    Text,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    InvalidCredentialError,
    VersionImportingError,
)
from exactdocs.ingestion.models import (
    ACTIVE_JOB_STATES,
    IMPORT_KINDS,
    Credential,
    FileProblem,
    Job,
    JobId,
    JobKind,
    JobState,
    ProblemCode,
    RefKind,
    dump_credential,
    load_credential,
)
from exactdocs.ingestion.ports.driven import SecretBox

# The ingestion's tables, prefixed `ingestion_`. The schema itself is created by an Alembic
# revision in `exactdocs.bootstrap`; this is only the adapter's query-side description of it.
metadata = MetaData()
jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("library", Text, nullable=False),
    Column("version", Text),
    Column("commit_sha", Text),
    Column("ref_kind", Text),
    Column("state", Text, nullable=False),
    Column("done", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    # ponytail: a JSON list rewritten on every progress save, fine for the few files that fail;
    # a table of problems if a job may skip thousands.
    Column("problems", Text, nullable=False),
    Column("chunked", Integer, nullable=False, server_default="0"),
    Column("reused", Integer, nullable=False, server_default="0"),
    Column("error", Text),
    Column("error_code", Text),  # null on rows that failed before codes were recorded
    # UTC ISO-8601 with microseconds, so text order is time order
    Column("created_at", Text, nullable=False),
    Column("started_at", Text),
    Column("finished_at", Text),
    Index("ingestion_jobs_library", "library", "created_at"),
    Index("ingestion_jobs_state", "state"),
    # At most one unfinished import per (library, ref): the atomic form of "version_importing".
    Index(
        "ingestion_jobs_active_import",
        "library",
        "version",
        unique=True,
        sqlite_where=text("state IN ('queued', 'running') AND kind IN ('import', 'refresh')"),
    ),
)


@dataclass(frozen=True, slots=True)
class SqliteJobRepository:
    """Implements ``ports.driven.JobRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine

    async def add(self, job: Job) -> None:
        """Store a new job; the unique index refuses a second unfinished import of a ref."""
        try:
            async with self.engine.begin() as connection:
                await connection.execute(insert(jobs).values(**_values(job)))
        except IntegrityError as error:
            if job.kind in IMPORT_KINDS and job.state in ACTIVE_JOB_STATES and job.version:
                raise VersionImportingError(job.library, job.version) from error
            raise

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID."""
        async with self.engine.begin() as connection:
            await connection.execute(update(jobs).where(jobs.c.id == job.id).values(**_values(job)))

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``."""
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(jobs).where(jobs.c.id == job_id))).first()
        return _job(row) if row else None

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered)."""
        query = select(jobs).where(jobs.c.library == library).order_by(jobs.c.id.desc())
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version."""
        # One grouped query (job IDs are time-ordered, so max(id) is the newest); NULL versions
        # group together.
        newest = select(func.max(jobs.c.id)).group_by(jobs.c.library, jobs.c.version)
        query = (
            select(jobs)
            .where(jobs.c.id.in_(newest))
            .order_by(jobs.c.library, func.coalesce(jobs.c.version, ""))
        )
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given), never a running one."""
        doomed = delete(jobs).where(jobs.c.library == library, jobs.c.state != JobState.RUNNING)
        if version is not None:
            doomed = doomed.where(jobs.c.version == version)
        async with self.engine.begin() as connection:
            await connection.execute(doomed)

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state."""
        query = select(jobs).where(jobs.c.state == JobState.RUNNING).order_by(jobs.c.id)
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        One UPDATE ... RETURNING statement, so SQLite's single writer decides the race, also
        between processes sharing the database. An idle poll only reads: it never takes the
        write lock that migrations and progress saves wait for.
        """
        async with self.engine.connect() as connection:
            waiting = select(jobs.c.id).where(jobs.c.state == JobState.QUEUED).limit(1)
            if (await connection.execute(waiting)).first() is None:
                return None
        busy = select(jobs.c.library).where(jobs.c.state == JobState.RUNNING)
        oldest = (
            select(jobs.c.id)
            .where(jobs.c.state == JobState.QUEUED, jobs.c.library.not_in(busy))
            .order_by(jobs.c.created_at, jobs.c.id)
            .limit(1)
            .scalar_subquery()
        )
        claim = (
            update(jobs)
            .where(jobs.c.id == oldest)
            .values(state=JobState.RUNNING, started_at=_text(now))
            .returning(*jobs.c)
        )
        async with self.engine.begin() as connection:
            row = (await connection.execute(claim)).first()
        return _job(row) if row else None


def _text(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="microseconds") if moment else None


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _values(job: Job) -> Mapping[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "library": job.library,
        "version": job.version,
        "commit_sha": job.commit_sha,
        "ref_kind": job.ref_kind,
        "state": job.state,
        "done": job.done,
        "total": job.total,
        "problems": json.dumps(
            [{"path": p.path, "code": p.code, "reason": p.reason} for p in job.problems]
        ),
        "chunked": job.chunked,
        "reused": job.reused,
        "error": job.error,
        "error_code": job.error_code,
        "created_at": _text(job.created_at),
        "started_at": _text(job.started_at),
        "finished_at": _text(job.finished_at),
    }


# Rows saved before problems had codes carry only the reason text.
_LEGACY_CODES = {
    "not valid UTF-8": ProblemCode.UNDECODABLE,
    "not a regular file": ProblemCode.NOT_A_FILE,
    "file name is not valid UTF-8": ProblemCode.BAD_FILE_NAME,
}


def _problem(raw: Mapping[str, str]) -> FileProblem:
    """Read a stored problem; a missing or unknown code (older or newer version) never fails."""
    path, reason = raw["path"], raw["reason"]
    try:
        code = ProblemCode(raw["code"])
    except KeyError, ValueError:
        if reason.startswith("larger than"):
            code = ProblemCode.TOO_LARGE
        elif not path:
            code = ProblemCode.TRUNCATED
        else:
            code = _LEGACY_CODES.get(reason, ProblemCode.UNREADABLE)
    return FileProblem(path, code, reason)


def _job(row: Row) -> Job:
    created_at = _moment(row.created_at)
    if created_at is None:
        message = "created_at is NOT NULL"
        raise AssertionError(message)
    problems = tuple(_problem(p) for p in json.loads(row.problems))
    return Job(
        id=JobId(row.id),
        kind=JobKind(row.kind),
        library=row.library,
        version=row.version,
        commit_sha=row.commit_sha,
        ref_kind=None if row.ref_kind is None else RefKind(row.ref_kind),
        state=JobState(row.state),
        done=row.done,
        total=row.total,
        problems=problems,
        notes=sum(p.code is ProblemCode.FRONT_MATTER for p in problems),
        chunked=row.chunked,
        reused=row.reused,
        error=row.error,
        error_code=row.error_code,
        created_at=created_at,
        started_at=_moment(row.started_at),
        finished_at=_moment(row.finished_at),
    )


credentials = Table(
    "ingestion_library_credentials",
    metadata,
    Column("library", Text, primary_key=True),
    # Fernet token of `dump_credential`'s JSON; the only place a secret is ever stored.
    Column("sealed", Text, nullable=False),
)


@dataclass(frozen=True, slots=True)
class SqliteCredentialVault:
    """Implements ``ports.driven.CredentialVault``: rows of encrypted credentials."""

    engine: AsyncEngine
    box: SecretBox

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential, replacing the one it had."""
        sealed = self.box.seal(dump_credential(library, scope, credential))
        statement = sqlite_insert(credentials).values(library=library, sealed=sealed)
        statement = statement.on_conflict_do_update(
            index_elements=[credentials.c.library], set_={"sealed": sealed}
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the credential, ``None`` if there is none; unreadable ones raise."""
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(credentials).where(credentials.c.library == library)
                )
            ).first()
        if row is None:
            return None
        try:
            return load_credential(library, scope, self.box.open(row.sealed))
        except ValueError, KeyError, TypeError, InvalidCredentialError:
            raise CredentialsRequiredError from None

    async def delete(self, library: str) -> None:
        """Forget the library's credential."""
        async with self.engine.begin() as connection:
            await connection.execute(delete(credentials).where(credentials.c.library == library))

    async def has(self, library: str) -> bool:
        """Whether a credential row exists; it is not opened."""
        async with self.engine.connect() as connection:
            row = await connection.execute(
                select(credentials.c.library).where(credentials.c.library == library)
            )
            return row.first() is not None
