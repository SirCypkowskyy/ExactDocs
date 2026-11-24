import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    Row,
    Select,
    Table,
    Text,
    case,
    delete,
    func,
    insert,
    literal_column,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from exactdocs.ingestion.constants import (
    ABOVE_EVERY_JOB_ID,
    ACTIVE_JOB_STATES,
    IMPORT_KINDS,
    LEGACY_CODES,
    PUSH_JOB,
    QUEUED_PUSH_SQL,
    UNFINISHED_JOBS_SQL,
    JobKind,
)
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    InvalidCredentialError,
    PushQueuedError,
    VersionImportingError,
    WebhookSecretUnreadableError,
)
from exactdocs.ingestion.models import (
    AutoSync,
    Credential,
    FileProblem,
    Job,
    JobDayCount,
    JobFilter,
    JobId,
    JobState,
    Person,
    ProblemCode,
    RefKind,
    VersionOrigin,
    Webhook,
    WebhookDelivery,
    dump_credential,
    load_credential,
)
from exactdocs.ingestion.ports.driven import SecretBox
from exactdocs_kernel import SealedTextUnreadableError, Sort, SortValue, like_pattern

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
    Column("parsed", Integer, nullable=False, server_default="0"),
    Column("taken", Integer, nullable=False, server_default="0"),
    Column("error", Text),
    Column("error_code", Text),  # null on rows that failed before codes were recorded
    Column("origin", Text, nullable=False, server_default="manual"),
    # UTC ISO-8601 with microseconds, so text order is time order
    Column("created_at", Text, nullable=False),
    Column("started_at", Text),
    Column("finished_at", Text),
    # Who cancelled the job and when; only `cancel` writes them (never `save`).
    Column("cancelled_by", Text),
    Column("cancelled_at", Text),
    # Who queued the job (#512): their account ID and the user name it had then; null when no
    # person did, and on the rows of jobs queued before.
    Column("created_by_id", Text),
    Column("created_by_name", Text),
    # A page of a library's jobs is a range of this index (see `list_page_for_library`).
    Index("ingestion_jobs_library_id", "library", "id"),
    Index("ingestion_jobs_state", "state"),
    # The job statistics count the jobs of a range of days (#512).
    Index("ingestion_jobs_created_at", "created_at"),
    # A library's unfinished jobs, newest first, without reading its finished ones (#329).
    Index(
        "ingestion_jobs_unfinished",
        "library",
        "id",
        sqlite_where=text(UNFINISHED_JOBS_SQL),
        postgresql_where=text(UNFINISHED_JOBS_SQL),
    ),
    # At most one unfinished import per (library, ref): the atomic form of "version_importing".
    Index(
        "ingestion_jobs_active_import",
        "library",
        "version",
        unique=True,
        sqlite_where=text("state IN ('queued', 'running') AND kind IN ('import', 'refresh')"),
        postgresql_where=text("state IN ('queued', 'running') AND kind IN ('import', 'refresh')"),
    ),
    # At most one queued push per (library, ref, kind): a burst of pushes coalesces (#114).
    Index(
        "ingestion_jobs_queued_push",
        "library",
        "version",
        "ref_kind",
        unique=True,
        sqlite_where=text(QUEUED_PUSH_SQL),
        postgresql_where=text(QUEUED_PUSH_SQL),
    ),
)


def _conflict_insert(
    bind: AsyncConnection | AsyncEngine, table: Table
) -> sqlite.Insert | postgresql.Insert:
    """Return an ``INSERT`` that takes ``ON CONFLICT`` clauses, in the database's dialect.

    Args:
        bind: Where the statement runs (SQLite or PostgreSQL).
        table: The table to insert into.

    Returns:
        The statement; both dialects spell ``on_conflict_do_update``/``_nothing`` alike.
    """
    if bind.dialect.name == "postgresql":
        return postgres_insert(table)
    return sqlite_insert(table)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteJobRepository:
    """Implements ``ports.driven.JobRepository`` with SQLAlchemy Core on SQLite."""

    engine: AsyncEngine
    """The database the jobs table lives in."""

    async def add(self, job: Job) -> None:
        """Store a new job; the unique index refuses a second unfinished import of a ref.

        Args:
            job: The new job.

        Raises:
            VersionImportingError: ``job`` is an unfinished import of a ref that has one.
            PushQueuedError: ``job`` is a queued push of a ref that has one queued.
            IntegrityError: Another constraint refused the row (a job ID that exists).
        """
        try:
            async with self.engine.begin() as connection:
                await connection.execute(insert(jobs).values(**_values(job)))
        except IntegrityError as error:
            if job.kind in IMPORT_KINDS and job.state in ACTIVE_JOB_STATES and job.version:
                raise VersionImportingError(job.library, job.version) from error
            if job.kind == PUSH_JOB and job.state is JobState.QUEUED and job.version:
                raise PushQueuedError(job.library, job.version, job.ref_kind or "ref") from error
            raise

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID, unless it is ``cancelled``.

        The cancellation columns are not written: a running job's progress never wipes out a
        cancellation stored meanwhile (only ``cancel`` writes them).

        Args:
            job: The job as it is now.
        """
        values = {
            k: v for k, v in _values(job).items() if k not in {"cancelled_by", "cancelled_at"}
        }
        saved = (
            update(jobs)
            .where(jobs.c.id == job.id, jobs.c.state != JobState.CANCELLED)
            .values(**values)
        )
        async with self.engine.begin() as connection:
            await connection.execute(saved)

    async def cancel(self, job_id: JobId, *, by: str | None, now: datetime) -> Job | None:
        """Ask to cancel a queued or running job in one UPDATE; a finished one is left alone.

        The statement decides the race with the worker: a queued job becomes ``cancelled`` (its
        ``CASE`` reads the row as it was), a running one is only flagged; a job that ended, or
        that was asked already, matches nothing.

        Args:
            job_id: The job's ID.
            by: Who cancels it.
            now: The time of the request.

        Returns:
            The job after the request, or ``None`` when no row has this ID.
        """
        queued = jobs.c.state == JobState.QUEUED
        asked = (
            update(jobs)
            .where(
                jobs.c.id == job_id,
                jobs.c.state.in_([JobState.QUEUED, JobState.RUNNING]),
                jobs.c.cancelled_at.is_(None),
            )
            .values(
                state=case((queued, JobState.CANCELLED.value), else_=jobs.c.state),
                finished_at=case((queued, _text(now)), else_=jobs.c.finished_at),
                cancelled_by=by,
                cancelled_at=_text(now),
            )
        )
        async with self.engine.begin() as connection:
            await connection.execute(asked)
            row = (await connection.execute(select(jobs).where(jobs.c.id == job_id))).first()
        return _job(row) if row else None

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``.

        Args:
            job_id: The job's ID.

        Returns:
            The job, or ``None`` when no row has this ID.
        """
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(jobs).where(jobs.c.id == job_id))).first()
        return _job(row) if row else None

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered).

        Args:
            library: The library ID.

        Returns:
            Every job of the library.
        """
        query = select(jobs).where(jobs.c.library == library).order_by(jobs.c.id.desc())
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def list_newest_of_kind(self, library: str, kind: JobKind) -> Sequence[Job]:
        """Return the newest job of ``kind`` of each version of the library, in one query.

        Job IDs are time-ordered, so the greatest ID of each version is its newest job; only
        those rows are read in full.

        Args:
            library: The library ID.
            kind: The job kind.

        Returns:
            One job per version.
        """
        newest = (
            select(func.max(jobs.c.id))
            .where(jobs.c.library == library, jobs.c.kind == kind)
            .group_by(jobs.c.version)
        )
        query = select(jobs).where(jobs.c.id.in_(newest))
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def list_unfinished_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's ``queued`` and ``running`` jobs, newest first.

        One SELECT that reads the partial index ``ingestion_jobs_unfinished`` (``library, id``
        over unfinished rows only), so the library's finished jobs and their problems are never
        read, and the rows come out in ID order without a sort.

        Args:
            library: The library ID.

        Returns:
            The library's unfinished jobs, highest ID first.
        """
        query = (
            select(jobs)
            .where(jobs.c.library == library, text(UNFINISHED_JOBS_SQL))
            .order_by(jobs.c.id.desc())
        )
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def list_page_for_library(
        self, library: str, *, before: str | None, limit: int
    ) -> Sequence[Job]:
        """Return up to ``limit`` of the library's jobs with an ID below ``before``, newest first.

        A keyset query that reads a range of the ``(library, id)`` index, so only the page's
        rows, problems included, are read. Text columns compare by code point on both databases
        (PostgreSQL's are collated ``C`` by the migration), as Python compares str.

        It is spelled ``library >= :l AND (library, id) < (:l, :before) ORDER BY library DESC,
        id DESC``, which selects the same rows as ``library = :l AND id < :before ORDER BY id
        DESC`` (#330). With ``library = :l`` PostgreSQL drops ``library`` from the sort order, so
        a backward walk of the primary key that filters on the library serves the order as well;
        for an old library behind many newer jobs of others it can look cheaper than the index
        and read every one of those jobs. Without the equality only ``(library, id)`` gives the
        order, and the row comparison bounds both ends of the range. The first page is bounded
        by ``ABOVE_EVERY_JOB_ID``, so it and later pages are one statement with one plan.

        Args:
            library: The library whose jobs are listed.
            before: Only jobs whose ID sorts before this one; ``None`` starts at the newest.
            limit: At most this many jobs.

        Returns:
            The page, highest ID first.
        """
        bound = ABOVE_EVERY_JOB_ID if before is None else before
        query = (
            select(jobs)
            .where(
                jobs.c.library >= library,
                tuple_(jobs.c.library, jobs.c.id) < tuple_(library, bound),
            )
            .order_by(jobs.c.library.desc(), jobs.c.id.desc())
            .limit(limit)
        )
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    def _filtered(self, job_filter: JobFilter) -> Select[Any]:
        """Build the query for the jobs that pass the filter, without order or limit.

        Args:
            job_filter: Which jobs.

        Returns:
            The query, selecting whole jobs.
        """
        query = select(jobs)
        if job_filter.libraries is not None:
            query = query.where(jobs.c.library.in_(sorted(job_filter.libraries)))
        if job_filter.states:
            query = query.where(jobs.c.state.in_(sorted(s.value for s in job_filter.states)))
        if job_filter.kinds:
            query = query.where(jobs.c.kind.in_(sorted(job_filter.kinds)))
        if job_filter.origins:
            query = query.where(jobs.c.origin.in_(sorted(o.value for o in job_filter.origins)))
        if job_filter.version is not None:
            query = query.where(jobs.c.version == job_filter.version)
        if job_filter.created_after is not None:
            query = query.where(jobs.c.created_at >= _utc_text(job_filter.created_after))
        if job_filter.created_before is not None:
            query = query.where(jobs.c.created_at < _utc_text(job_filter.created_before))
        if job_filter.text:
            pattern = like_pattern(job_filter.text)
            query = query.where(
                or_(
                    func.lower(jobs.c.library).like(pattern, escape="\\"),
                    func.lower(func.coalesce(jobs.c.version, "")).like(pattern, escape="\\"),
                    func.lower(func.coalesce(jobs.c.error, "")).like(pattern, escape="\\"),
                )
            )
        return query

    async def search(
        self,
        job_filter: JobFilter,
        *,
        sort: Sort,
        after: tuple[SortValue, str] | None,
        limit: int,
        offset: int = 0,
    ) -> Sequence[Job]:
        """Return up to ``limit`` of the jobs that pass the filter, in ``sort`` order.

        A keyset query: ``(sort value, id)`` compares as a row, in the sort's direction. Text
        columns compare by code point on both databases (PostgreSQL's are collated ``C`` by the
        migration), as Python compares str. A page of one library's jobs by ID keeps the range
        scan of ``list_page_for_library`` (the library bounds the row comparison on both ends).
        An offset is the database's ``OFFSET`` over the same order.

        Args:
            job_filter: Which jobs.
            sort: The order.
            after: The sort value and ID of the last job of the previous page.
            limit: At most this many jobs.
            offset: How many of the jobs in order (after ``after``) to skip first.

        Returns:
            The jobs in order, with their problems.
        """
        column = jobs.c[sort.field]
        query = self._filtered(job_filter)
        order: tuple[Any, ...] = (
            (column.desc(), jobs.c.id.desc()) if sort.descending else (column, jobs.c.id)
        )
        libraries = job_filter.libraries
        if sort.field == "id" and libraries is not None and len(libraries) == 1:
            (library,) = libraries
            if sort.descending:
                bound = ABOVE_EVERY_JOB_ID if after is None else after[1]
                query = query.where(
                    jobs.c.library >= library,
                    tuple_(jobs.c.library, jobs.c.id) < tuple_(library, bound),
                )
                order = (jobs.c.library.desc(), jobs.c.id.desc())
            else:
                bound = "" if after is None else after[1]
                query = query.where(
                    jobs.c.library <= library,
                    tuple_(jobs.c.library, jobs.c.id) > tuple_(library, bound),
                )
                order = (jobs.c.library, jobs.c.id)
        elif after is not None:
            row, bound = tuple_(column, jobs.c.id), tuple_(*after)
            query = query.where(row < bound if sort.descending else row > bound)
        query = query.order_by(*order).limit(limit)
        if offset:
            query = query.offset(offset)
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def count(self, job_filter: JobFilter) -> int:
        """Count the jobs that pass the filter.

        Args:
            job_filter: Which jobs.

        Returns:
            How many there are.
        """
        query = select(func.count()).select_from(self._filtered(job_filter).subquery())
        async with self.engine.connect() as connection:
            return (await connection.execute(query)).scalar_one()

    async def libraries(self) -> Sequence[str]:
        """Return every library that has a job, as spelled in the jobs.

        Returns:
            The distinct library IDs.
        """
        async with self.engine.connect() as connection:
            return list((await connection.execute(select(jobs.c.library).distinct())).scalars())

    async def list_latest(self) -> Sequence[Job]:
        """Return the newest job of every (library, version), ordered by library and version.

        ``push`` jobs are left out: they name a ref but say nothing about how its version fared.

        Returns:
            One job per pair; the jobs without a version count as one pair per library.
        """
        # One grouped query (job IDs are time-ordered, so max(id) is the newest); NULL versions
        # group together. A `push` job names a ref but says nothing about how the version fared.
        newest = (
            select(func.max(jobs.c.id))
            .where(jobs.c.kind != PUSH_JOB)
            .group_by(jobs.c.library, jobs.c.version)
        )
        query = (
            select(jobs)
            .where(jobs.c.id.in_(newest))
            .order_by(jobs.c.library, func.coalesce(jobs.c.version, ""))
        )
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def sync_states(self) -> Mapping[str, JobState]:
        """Return the state of every library's newest ``import`` or ``refresh`` job, in one query.

        Job IDs are time-ordered, so the greatest ID of a library's imports is its latest sync;
        only those rows' states are read.

        Returns:
            The state by library, as spelled in the jobs.
        """
        newest = (
            select(func.max(jobs.c.id))
            .where(jobs.c.kind.in_(sorted(IMPORT_KINDS)))
            .group_by(jobs.c.library)
        )
        query = select(jobs.c.library, jobs.c.state).where(jobs.c.id.in_(newest))
        async with self.engine.connect() as connection:
            rows = await connection.execute(query)
            return {row.library: JobState(row.state) for row in rows}

    async def daily_counts(self, *, start: datetime, end: datetime) -> Sequence[JobDayCount]:
        """Count the jobs queued in ``[start, end)`` by UTC day, state and kind, in one query.

        ``created_at`` is stored as UTC ISO-8601 text, so its first ten characters are the UTC
        day and the range is a text range of the ``ingestion_jobs_created_at`` index.

        Args:
            start: The first moment counted.
            end: The first moment no longer counted.

        Returns:
            One count per (day, state, kind) that has jobs.
        """
        # Literal positions: PostgreSQL groups by the expression only if it is spelled the same.
        day = func.substr(jobs.c.created_at, literal_column("1"), literal_column("10"))
        query = (
            select(day.label("day"), jobs.c.state, jobs.c.kind, func.count().label("jobs"))
            .where(jobs.c.created_at >= _utc_text(start), jobs.c.created_at < _utc_text(end))
            .group_by(day, jobs.c.state, jobs.c.kind)
        )
        async with self.engine.connect() as connection:
            rows = await connection.execute(query)
            return [
                JobDayCount(
                    day=date.fromisoformat(row.day),
                    state=JobState(row.state),
                    kind=row.kind,
                    count=row.jobs,
                )
                for row in rows
            ]

    async def delete_for(self, library: str, version: str | None = None) -> None:
        """Delete the library's jobs (only those of ``version`` when given), never a running one.

        Args:
            library: The library ID.
            version: Only the jobs of this ref; ``None`` deletes every job of the library.
        """
        doomed = delete(jobs).where(jobs.c.library == library, jobs.c.state != JobState.RUNNING)
        if version is not None:
            doomed = doomed.where(jobs.c.version == version)
        async with self.engine.begin() as connection:
            await connection.execute(doomed)

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state.

        Returns:
            The running jobs, by ID.
        """
        query = select(jobs).where(jobs.c.state == JobState.RUNNING).order_by(jobs.c.id)
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def list_queued(self) -> Sequence[Job]:
        """Return every job in the ``queued`` state, oldest first.

        Returns:
            The queued jobs.
        """
        query = (
            select(jobs)
            .where(jobs.c.state == JobState.QUEUED)
            .order_by(jobs.c.created_at, jobs.c.id)
        )
        async with self.engine.connect() as connection:
            return [_job(row) for row in await connection.execute(query)]

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job.

        One UPDATE ... RETURNING statement, so SQLite's single writer decides the race, also
        between processes sharing the database. An idle poll only reads: it never takes the
        write lock that migrations and progress saves wait for.

        Args:
            now: The time recorded as the job's ``started_at``.

        Returns:
            The started job, or ``None`` when no queued job may start.
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
    """Store a moment as ISO-8601 text with microseconds.

    Args:
        moment: The moment, or None.

    Returns:
        The text, or None.
    """
    return moment.isoformat(timespec="microseconds") if moment else None


def _utc_text(moment: datetime) -> str:
    """Spell a moment as the stored columns do, in UTC, so text order is time order.

    Args:
        moment: The moment (with an offset).

    Returns:
        ISO-8601 text with microseconds and a ``+00:00`` offset.
    """
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _moment(text: str | None) -> datetime | None:
    """Read a moment stored by ``_text``.

    Args:
        text: The stored text, or None.

    Returns:
        The moment, or None.
    """
    return datetime.fromisoformat(text) if text else None


def _values(job: Job) -> Mapping[str, Any]:
    """Turn a job into the columns of its row.

    Args:
        job: The job.

    Returns:
        The column values; problems as JSON, moments as text.
    """
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
        "parsed": job.parsed,
        "taken": job.taken,
        "error": job.error,
        "error_code": job.error_code,
        "origin": job.origin.value,
        "created_at": _text(job.created_at),
        "started_at": _text(job.started_at),
        "finished_at": _text(job.finished_at),
        "cancelled_by": job.cancelled_by,
        "cancelled_at": _text(job.cancelled_at),
        "created_by_id": None if job.created_by is None else job.created_by.id,
        "created_by_name": None if job.created_by is None else job.created_by.username,
    }


def _problem(raw: Mapping[str, str]) -> FileProblem:
    """Read a stored problem; a missing or unknown code (older or newer version) never fails.

    Args:
        raw: The problem's JSON object.

    Returns:
        The problem; a code it lacks is inferred from its text, else ``unreadable``.
    """
    path, reason = raw["path"], raw["reason"]
    try:
        code = ProblemCode(raw["code"])
    except KeyError, ValueError:
        if reason.startswith("larger than"):
            code = ProblemCode.TOO_LARGE
        elif not path:
            code = ProblemCode.TRUNCATED
        else:
            code = ProblemCode(LEGACY_CODES.get(reason, ProblemCode.UNREADABLE))
    return FileProblem(path=path, code=code, reason=reason)


def _origin(stored: str) -> VersionOrigin:
    """Read a stored origin; an unknown one (a newer release) counts as ``manual``: kept.

    Args:
        stored: The stored text.

    Returns:
        The origin.
    """
    try:
        return VersionOrigin(stored)
    except ValueError:
        return VersionOrigin.MANUAL


def _job(row: Row) -> Job:
    """Read a job from its row.

    Args:
        row: A row of the jobs table.

    Returns:
        The job, with its problems and its count of front-matter notes.

    Raises:
        AssertionError: The row has no ``created_at``, which the schema forbids.
    """
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
        parsed=row.parsed,
        taken=row.taken,
        error=row.error,
        error_code=row.error_code,
        origin=_origin(row.origin),
        created_at=created_at,
        started_at=_moment(row.started_at),
        finished_at=_moment(row.finished_at),
        cancelled_by=row.cancelled_by,
        cancelled_at=_moment(row.cancelled_at),
        created_by=(
            None
            if row.created_by_id is None
            else Person(id=row.created_by_id, username=row.created_by_name or row.created_by_id)
        ),
    )


credentials = Table(
    "ingestion_library_credentials",
    metadata,
    Column("library", Text, primary_key=True),
    # Fernet token of `dump_credential`'s JSON; the only place a secret is ever stored.
    Column("sealed", Text, nullable=False),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteCredentialVault:
    """Implements ``ports.driven.CredentialVault``: rows of encrypted credentials."""

    engine: AsyncEngine
    """The database the credentials table lives in."""
    box: SecretBox
    """Seals credentials before they are stored and opens them when they are read."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Store the library's credential, replacing the one it had.

        Args:
            library: The library ID.
            scope: Where the credential may be offered (``RepositoryUrl.credential_scope``).
            credential: The token or deploy key.
        """
        sealed = self.box.seal(dump_credential(library, scope, credential))
        statement = _conflict_insert(self.engine, credentials).values(
            library=library, sealed=sealed
        )
        statement = statement.on_conflict_do_update(
            index_elements=[credentials.c.library], set_={"sealed": sealed}
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def load(self, library: str, scope: str) -> Credential | None:
        """Return the credential, ``None`` if there is none; unreadable ones raise.

        Args:
            library: The library ID.
            scope: The library's ``credential_scope`` now.

        Returns:
            The credential, or ``None``.

        Raises:
            CredentialsRequiredError: The stored credential cannot be opened with the secret
                key, cannot be parsed, or was stored for another scope.
        """
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
        except (
            SealedTextUnreadableError,
            ValueError,
            KeyError,
            TypeError,
            InvalidCredentialError,
        ):
            raise CredentialsRequiredError from None

    async def delete(self, library: str) -> None:
        """Forget the library's credential.

        Args:
            library: The library ID.
        """
        async with self.engine.begin() as connection:
            await connection.execute(delete(credentials).where(credentials.c.library == library))

    async def has(self, library: str) -> bool:
        """Whether a credential row exists; it is not opened.

        Args:
            library: The library ID.

        Returns:
            True when the library has a row.
        """
        async with self.engine.connect() as connection:
            row = await connection.execute(
                select(credentials.c.library).where(credentials.c.library == library)
            )
            return row.first() is not None


auto_syncs = Table(
    "ingestion_auto_syncs",
    metadata,
    Column("library", Text, primary_key=True),  # by value: the catalog's library ID
    Column("tag_pattern", Text),
    Column("keep_last", Integer, nullable=False),
    Column("interval_minutes", Integer, nullable=False),
    Column("sync_branches", Boolean, nullable=False),
    Column("checked_at", Text),  # UTC ISO-8601
    Column("last_error", Text),
    Column("revision", Text, nullable=False, server_default=""),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteAutoSyncStore:
    """Implements ``ports.driven.AutoSyncStore``: one row per library checked on its own."""

    engine: AsyncEngine
    """The database the schedules table lives in."""

    async def get(self, library: str) -> AutoSync | None:
        """Return the library's schedule, or ``None``.

        Args:
            library: The library ID.

        Returns:
            The schedule, or ``None`` when the library has none.
        """
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(auto_syncs).where(auto_syncs.c.library == library))
            ).first()
        return None if row is None else _auto_sync(row)

    async def save(self, auto_sync: AutoSync) -> None:
        """Store the schedule, replacing the library's earlier one.

        Args:
            auto_sync: The schedule.
        """
        values = {
            "tag_pattern": auto_sync.tag_pattern,
            "keep_last": auto_sync.keep_last,
            "interval_minutes": auto_sync.interval_minutes,
            "sync_branches": auto_sync.sync_branches,
            "checked_at": _text(auto_sync.checked_at),
            "last_error": auto_sync.last_error,
            "revision": auto_sync.revision,
        }
        statement = _conflict_insert(self.engine, auto_syncs).values(
            library=auto_sync.library, **values
        )
        statement = statement.on_conflict_do_update(
            index_elements=[auto_syncs.c.library], set_=values
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def delete(self, library: str) -> None:
        """Forget the library's schedule.

        Args:
            library: The library ID.
        """
        async with self.engine.begin() as connection:
            await connection.execute(delete(auto_syncs).where(auto_syncs.c.library == library))

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Compare and set: store the check only on the row the check read.

        Args:
            read: The schedule as the check read it.
            checked: The same schedule with the check's ``checked_at`` and ``last_error``.

        Returns:
            True when the row still had ``read``'s revision and ``checked_at`` and was updated.
        """
        before = _text(read.checked_at)
        statement = (
            update(auto_syncs)
            .where(
                auto_syncs.c.library == read.library,
                auto_syncs.c.revision == read.revision,
                auto_syncs.c.checked_at.is_(None)
                if before is None
                else auto_syncs.c.checked_at == before,
            )
            .values(checked_at=_text(checked.checked_at), last_error=checked.last_error)
        )
        async with self.engine.begin() as connection:
            return (await connection.execute(statement)).rowcount == 1

    async def list_all(self) -> Sequence[AutoSync]:
        """Return every schedule, by library.

        Returns:
            The schedules, ordered by library ID.
        """
        async with self.engine.connect() as connection:
            rows = await connection.execute(select(auto_syncs).order_by(auto_syncs.c.library))
            return [_auto_sync(row) for row in rows]


def _auto_sync(row: Row) -> AutoSync:
    """Read a schedule from its row.

    Args:
        row: A row of the schedules table.

    Returns:
        The schedule.
    """
    return AutoSync(
        library=row.library,
        tag_pattern=row.tag_pattern,
        keep_last=row.keep_last,
        interval_minutes=row.interval_minutes,
        sync_branches=bool(row.sync_branches),
        checked_at=_moment(row.checked_at),
        last_error=row.last_error,
        revision=row.revision,
    )


webhooks = Table(
    "ingestion_webhooks",
    metadata,
    Column("library", Text, primary_key=True),  # by value: the catalog's library ID
    # Fernet token of the secret, sealed under its own purpose; never logged or returned.
    Column("sealed", Text, nullable=False),
    Column("created_at", Text, nullable=False),  # UTC ISO-8601
)
webhook_deliveries = Table(
    "ingestion_webhook_deliveries",
    metadata,
    Column("library", Text, primary_key=True),
    Column("provider", Text, primary_key=True),
    Column("delivery_id", Text, primary_key=True),
    Column("received_at", Text, nullable=False),  # UTC ISO-8601, so text order is time order
    Index("ingestion_webhook_deliveries_received_at", "received_at"),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteWebhookSecrets:
    """Implements ``ports.driven.WebhookSecrets``: one sealed secret per library."""

    engine: AsyncEngine
    """The database the webhooks table lives in."""
    box: SecretBox
    """Seals secrets before they are stored and opens them when they are read."""

    async def save(self, webhook: Webhook) -> None:
        """Store the library's webhook, replacing the one it had.

        Args:
            webhook: The webhook and its secret.
        """
        values = {"sealed": self.box.seal(webhook.secret), "created_at": _text(webhook.created_at)}
        statement = _conflict_insert(self.engine, webhooks).values(
            library=webhook.library, **values
        )
        statement = statement.on_conflict_do_update(
            index_elements=[webhooks.c.library], set_=values
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def get(self, library: str) -> Webhook | None:
        """Return the library's webhook with its secret opened, or ``None``.

        Args:
            library: The library ID.

        Returns:
            The webhook, or ``None``.

        Raises:
            WebhookSecretUnreadableError: The secret does not open with the instance's key.
            AssertionError: The row has no ``created_at``, which the schema forbids.
        """
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(webhooks).where(webhooks.c.library == library))
            ).first()
        if row is None:
            return None
        try:
            secret = self.box.open(row.sealed)
        except SealedTextUnreadableError:
            raise WebhookSecretUnreadableError(library) from None
        created_at = _moment(row.created_at)
        if created_at is None:
            message = "created_at is NOT NULL"
            raise AssertionError(message)
        return Webhook(library=library, secret=secret, created_at=created_at)

    async def created_at(self, library: str) -> datetime | None:
        """Say when the library's webhook was created; the secret is not opened.

        Args:
            library: The library ID.

        Returns:
            When, or ``None`` without one.
        """
        query = select(webhooks.c.created_at).where(webhooks.c.library == library)
        async with self.engine.connect() as connection:
            found = (await connection.execute(query)).scalar()
        return _moment(found)

    async def delete(self, library: str) -> None:
        """Forget the library's webhook.

        Args:
            library: The library ID.
        """
        async with self.engine.begin() as connection:
            await connection.execute(delete(webhooks).where(webhooks.c.library == library))


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteWebhookDeliveries:
    """Implements ``ports.driven.WebhookDeliveries``: rows inserted ``ON CONFLICT DO NOTHING``.

    The insert is the check: of two processes recording one delivery, the database lets one
    row in, so exactly one sees it as new. Old rows are pruned in the same transaction.
    """

    engine: AsyncEngine
    """The database the deliveries table lives in."""

    async def record(self, delivery: WebhookDelivery, *, prune_before: datetime) -> bool:
        """Forget the old deliveries, then insert this one unless it is known.

        Args:
            delivery: The delivery.
            prune_before: Older deliveries are forgotten.

        Returns:
            True when the row was inserted.
        """
        statement = (
            _conflict_insert(self.engine, webhook_deliveries)
            .values(
                library=delivery.library,
                provider=delivery.provider.value,
                delivery_id=delivery.delivery_id,
                received_at=_text(delivery.received_at),
            )
            .on_conflict_do_nothing()
            # preserve_rowcount: an INSERT's rowcount is only kept on request (psycopg reports -1).
            .execution_options(preserve_rowcount=True)
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(webhook_deliveries).where(
                    webhook_deliveries.c.received_at < _text(prune_before)
                )
            )
            return (await connection.execute(statement)).rowcount == 1

    async def forget(self, delivery: WebhookDelivery) -> None:
        """Forget the delivery.

        Args:
            delivery: The delivery.
        """
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(webhook_deliveries).where(
                    webhook_deliveries.c.library == delivery.library,
                    webhook_deliveries.c.provider == delivery.provider.value,
                    webhook_deliveries.c.delivery_id == delivery.delivery_id,
                )
            )

    async def delete_for(self, library: str) -> None:
        """Forget every delivery of the library.

        Args:
            library: The library ID.
        """
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(webhook_deliveries).where(webhook_deliveries.c.library == library)
            )
