"""Who queued a job, the ``origin`` filter, each library's latest sync and the jobs per day (#512).

The repository cases run over every ``JobRepository`` (memory, SQLite, PostgreSQL); the use cases
over the in-memory one.
"""

from collections.abc import AsyncIterator, Collection, Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JOB_KINDS, MAX_STATS_DAYS, JobKind
from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    JobStatsQuery,
    ListJobsQuery,
    PersonSummary,
    SyncStatesQuery,
)
from exactdocs.ingestion.errors import InvalidStatsRangeError
from exactdocs.ingestion.models import (
    Job,
    JobDayCount,
    JobId,
    JobState,
    Person,
    VersionOrigin,
)
from exactdocs.ingestion.ports import JobRepository
from exactdocs.ingestion.use_cases import (
    EnqueueJobUseCase,
    GetJobStatsUseCase,
    ListJobsUseCase,
    ListLibrariesInSyncStatesUseCase,
)
from library_access import FakeAccess

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
ALICE = Person(id="acc-alice", username="alice")


def job(
    job_id: str,
    *,
    library: str = "/acme/payments",
    kind: str = "import",
    at: datetime = T0,
    origin: VersionOrigin = VersionOrigin.MANUAL,
    created_by: Person | None = None,
) -> Job:
    return Job.queued(
        job_id=JobId(job_id),
        kind=JobKind(kind),
        library=library,
        version=None,
        now=at,
        origin=origin,
        created_by=created_by,
    )


def finished(queued: Job, state: JobState) -> Job:
    started = queued.started(queued.created_at)
    if state is JobState.SUCCEEDED:
        return started.succeeded(queued.created_at)
    if state is JobState.FAILED:
        return started.failed("gone", queued.created_at)
    if state is JobState.CANCELLED:
        return started.cancelled(queued.created_at)
    return started if state is JobState.RUNNING else queued


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[JobRepository]:
    if request.param == "memory":
        yield InMemoryJobRepository()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteJobRepository(engine=engine)
    await engine.dispose()


async def add_all(repository: JobRepository, jobs: Iterable[Job]) -> None:
    for each in jobs:
        await repository.add(each)


# ------------------------------------------------------------------ the repository


async def test_who_queued_a_job_survives_a_round_trip(repository: JobRepository) -> None:
    mine = job("j1", created_by=ALICE)
    nobody = job("j2", origin=VersionOrigin.AUTO)
    await add_all(repository, [mine, nobody])

    assert await repository.get(JobId("j1")) == mine
    assert (await repository.get(JobId("j1")) or mine).created_by == ALICE
    assert await repository.get(JobId("j2")) == nobody
    # Saving progress keeps who queued it.
    await repository.save(mine.started(T0))
    assert (await repository.get(JobId("j1")) or nobody).created_by == ALICE


async def test_the_origin_filter_keeps_only_jobs_of_those_origins(
    repository: JobRepository,
) -> None:
    await add_all(
        repository,
        [
            job("j1", created_by=ALICE),
            job("j2", origin=VersionOrigin.AUTO),
            job("j3", origin=VersionOrigin.AUTO, at=T0 + timedelta(minutes=1)),
        ],
    )
    use_case = ListJobsUseCase(jobs=repository, access=FakeAccess(role="admin"))

    auto = await use_case(ListJobsQuery(origin=[VersionOrigin.AUTO]))
    manual = await use_case(ListJobsQuery(origin=[VersionOrigin.MANUAL]))
    both = await use_case(ListJobsQuery(origin=[VersionOrigin.AUTO, VersionOrigin.MANUAL]))
    at_offset = await use_case(ListJobsQuery(origin=[VersionOrigin.AUTO], limit=1, offset=1))

    assert [j.id for j in auto.jobs] == ["j3", "j2"]
    assert auto.total == 2
    assert [(j.id, j.created_by) for j in manual.jobs] == [("j1", _summary(ALICE))]
    assert both.total == 3
    assert ([j.id for j in at_offset.jobs], at_offset.total) == (["j2"], 2)


async def test_a_library_s_sync_state_is_its_newest_import_s(repository: JobRepository) -> None:
    await add_all(
        repository,
        [
            finished(job("a1", library="/acme/a"), JobState.SUCCEEDED),
            finished(job("a2", library="/acme/a", kind="refresh"), JobState.FAILED),
            # Newer, but not an import: says nothing about the sync.
            finished(job("a3", library="/acme/a", kind="embed"), JobState.SUCCEEDED),
            finished(job("b1", library="/acme/b"), JobState.FAILED),
            job("b2", library="/acme/b", kind="refresh"),
            finished(job("c1", library="/acme/c", kind="collect"), JobState.SUCCEEDED),
        ],
    )

    assert await repository.sync_states() == {"/acme/a": JobState.FAILED, "/acme/b": "queued"}


async def test_jobs_are_counted_per_utc_day_state_and_kind(repository: JobRepository) -> None:
    late = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
    await add_all(
        repository,
        [
            finished(job("j1"), JobState.SUCCEEDED),
            finished(job("j2", at=T0 + timedelta(minutes=1)), JobState.SUCCEEDED),
            finished(job("j3", kind="embed", at=late), JobState.FAILED),
            job("j4", at=T0 + timedelta(days=1)),
            job("j5", at=T0 - timedelta(days=1)),  # before the range
            job("j6", at=T0 + timedelta(days=2)),  # after it
        ],
    )

    counts = await repository.daily_counts(
        start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 3, tzinfo=UTC)
    )

    assert sorted(counts, key=lambda c: (c.day, c.state, c.kind)) == [
        JobDayCount(day=date(2026, 1, 1), state=JobState.FAILED, kind="embed", count=1),
        JobDayCount(day=date(2026, 1, 1), state=JobState.SUCCEEDED, kind="import", count=2),
        JobDayCount(day=date(2026, 1, 2), state=JobState.QUEUED, kind="import", count=1),
    ]


@contextmanager
def selects(engine: AsyncEngine) -> Generator[list[str]]:
    sent: list[str] = []

    def record(*args: object) -> None:
        statement = args[2]
        assert isinstance(statement, str)
        if statement.lstrip().upper().startswith("SELECT"):
            sent.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_the_sync_states_and_the_day_counts_are_one_select_each(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    repository = SqliteJobRepository(engine=engine)
    await add_all(
        repository,
        [finished(job(f"j{n:02}", library=f"/acme/l{n}"), JobState.SUCCEEDED) for n in range(12)],
    )
    with selects(engine) as sent:
        states = await repository.sync_states()
        counts = await repository.daily_counts(start=T0 - timedelta(days=1), end=T0 + timedelta(1))
    await engine.dispose()

    assert len(states) == 12
    assert [c.count for c in counts] == [12]
    assert len(sent) == 2  # never one query per library or per day


# ------------------------------------------------------------------ the use cases


class _Reads(FakeAccess):
    """Library roles that let the caller read only some libraries."""

    def __init__(self, *readable: str) -> None:
        super().__init__(role="viewer")
        self.allowed = frozenset(readable)

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        return frozenset(lib.casefold() for lib in libraries if lib.casefold() in self.allowed)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class _Runner:
    def __init__(self) -> None:
        self.submitted: list[Job] = []

    async def submit(self, job: Job) -> None:
        self.submitted.append(job)


def _summary(person: Person) -> PersonSummary:
    return PersonSummary(id=person.id, username=person.username)


async def _alice() -> Person | None:
    return ALICE


async def _handler(queued: Job, progress: object, /) -> None:
    del queued, progress


def enqueue(jobs: InMemoryJobRepository) -> EnqueueJobUseCase:
    return EnqueueJobUseCase(
        jobs=jobs,
        clock=_Clock(T0),
        handlers={JobKind("import"): _handler, JobKind("push"): _handler},
        runner=_Runner(),
        requester=_alice,
    )


async def test_a_job_names_the_person_whose_request_queued_it() -> None:
    jobs = InMemoryJobRepository()

    queued = await enqueue(jobs)(EnqueueJobCommand(kind="import", library="/acme/payments"))

    assert queued.created_by is not None
    assert (queued.created_by.id, queued.created_by.username) == ("acc-alice", "alice")
    assert queued.origin is VersionOrigin.MANUAL
    assert jobs.jobs[JobId(queued.id)].created_by == ALICE


async def test_a_job_the_instance_queues_on_its_own_names_nobody() -> None:
    jobs = InMemoryJobRepository()

    queued = await enqueue(jobs)(
        EnqueueJobCommand(kind="push", library="/acme/payments", origin=VersionOrigin.AUTO)
    )

    assert (queued.created_by, queued.origin) == (None, VersionOrigin.AUTO)


async def test_without_a_requester_no_job_names_a_person() -> None:
    jobs = InMemoryJobRepository()
    use_case = EnqueueJobUseCase(
        jobs=jobs, clock=_Clock(T0), handlers={JobKind("import"): _handler}, runner=_Runner()
    )

    queued = await use_case(EnqueueJobCommand(kind="import", library="/acme/payments"))

    assert queued.created_by is None


async def test_the_stats_list_every_day_state_and_kind_zero_filled() -> None:
    jobs = InMemoryJobRepository()
    await add_all(
        jobs,
        [
            finished(job("j1"), JobState.SUCCEEDED),
            finished(job("j2", kind="embed"), JobState.FAILED),
            job("j3", at=T0 + timedelta(days=2)),
        ],
    )
    use_case = GetJobStatsUseCase(jobs=jobs, clock=_Clock(T0))

    stats = await use_case(JobStatsQuery(start=date(2026, 1, 1), end=date(2026, 1, 3)))

    assert [d.day for d in stats.days] == [date(2026, 1, d) for d in (1, 2, 3)]
    first, empty, third = stats.days
    assert first.total == 2
    assert first.by_state == {
        JobState.QUEUED: 0,
        JobState.RUNNING: 0,
        JobState.SUCCEEDED: 1,
        JobState.FAILED: 1,
        JobState.CANCELLED: 0,
    }
    assert list(first.by_kind) == list(JOB_KINDS)
    assert (first.by_kind["import"], first.by_kind["embed"]) == (1, 1)
    assert empty.total == 0
    assert set(empty.by_state.values()) == {0}
    assert set(empty.by_kind.values()) == {0}
    assert (third.total, third.by_state[JobState.QUEUED]) == (1, 1)


async def test_the_stats_default_to_the_last_30_days_ending_today_in_utc() -> None:
    now = datetime(2026, 3, 10, 23, 30, tzinfo=UTC)
    use_case = GetJobStatsUseCase(jobs=InMemoryJobRepository(), clock=_Clock(now))

    stats = await use_case(JobStatsQuery())

    assert (stats.start, stats.end, len(stats.days)) == (date(2026, 2, 9), date(2026, 3, 10), 30)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 1, 2), date(2026, 1, 1)),  # ends before it starts
        (date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=MAX_STATS_DAYS)),  # one day too many
    ],
    ids=["backwards", "too long"],
)
async def test_the_stats_refuse_a_range_backwards_or_too_long(start: date, end: date) -> None:
    use_case = GetJobStatsUseCase(jobs=InMemoryJobRepository(), clock=_Clock(T0))

    with pytest.raises(InvalidStatsRangeError) as raised:
        await use_case(JobStatsQuery(start=start, end=end))

    assert raised.value.code == "invalid_range"


async def test_the_longest_range_is_counted() -> None:
    use_case = GetJobStatsUseCase(jobs=InMemoryJobRepository(), clock=_Clock(T0))
    start = date(2025, 1, 1)

    stats = await use_case(
        JobStatsQuery(start=start, end=start + timedelta(days=MAX_STATS_DAYS - 1))
    )

    assert len(stats.days) == MAX_STATS_DAYS


async def test_only_readable_libraries_in_the_states_asked_for_are_named() -> None:
    jobs = InMemoryJobRepository()
    await add_all(
        jobs,
        [
            finished(job("a1", library="/acme/a"), JobState.FAILED),
            finished(job("b1", library="/acme/b"), JobState.FAILED),
            finished(job("c1", library="/acme/c"), JobState.SUCCEEDED),
        ],
    )
    use_case = ListLibrariesInSyncStatesUseCase(jobs=jobs, access=_Reads("/acme/a", "/acme/c"))

    failed = await use_case(SyncStatesQuery(states=[JobState.FAILED]))
    either = await use_case(SyncStatesQuery(states=[JobState.FAILED, JobState.SUCCEEDED]))

    assert failed.libraries == ["/acme/a"]  # /acme/b is hidden from the caller
    assert either.libraries == ["/acme/a", "/acme/c"]
