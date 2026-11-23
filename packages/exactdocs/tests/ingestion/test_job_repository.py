"""Adapter contract: every ``JobRepository`` behaves the same, whatever stores the data."""

import asyncio
import json
from collections.abc import AsyncIterator, Generator, Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import ADMIN_URL, SQL_BACKENDS, PostgresDatabase
from exactdocs.bootstrap.database import is_libsql, migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository, jobs
from exactdocs.ingestion.constants import ABOVE_EVERY_JOB_ID, JobKind
from exactdocs.ingestion.errors import PushQueuedError, VersionImportingError
from exactdocs.ingestion.models import Job, JobId, JobState, ProblemCode, RefKind
from exactdocs.ingestion.ports import JobRepository

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def queued(
    job_id: str, library: str = "/acme/payments", minute: int = 0, version: str = "1.4"
) -> Job:
    return Job.queued(
        job_id=JobId(job_id),
        kind=JobKind("import"),
        library=library,
        version=version,
        commit_sha="c" * 40,  # the commit the version was pinned to must survive too
        ref_kind=RefKind.TAG,  # and what the version is
        now=T0 + timedelta(minutes=minute),
    )


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[JobRepository]:
    if request.param == "memory":
        yield InMemoryJobRepository()
        return
    # Not a Container: its worker would pick up the queued jobs these tests look at.
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteJobRepository(engine=engine)
    await engine.dispose()


async def test_starts_empty(repository: JobRepository) -> None:
    assert await repository.get(JobId("j1")) is None
    assert await repository.list_running() == []
    assert await repository.list_queued() == []
    assert await repository.claim_next(T0) is None


async def test_every_field_survives_a_round_trip(repository: JobRepository) -> None:
    job = (
        queued("j1")
        .started(T0 + timedelta(seconds=5))
        .progressed(done=4, total=10)
        .chunking(chunked=2, reused=1)
        .parsing(parsed=3, taken=5)
        .with_problem("assets/logo.png", ProblemCode.BINARY, "binary file")
        .with_problem("guide/ünï.md", ProblemCode.UNDECODABLE, "not text")
        .failed("boom", T0 + timedelta(seconds=9, microseconds=7), code="tag_moved")
    )

    await repository.add(job)

    assert await repository.get(JobId("j1")) == job


async def test_a_version_less_job_stays_version_less(repository: JobRepository) -> None:
    job = Job.queued(job_id=JobId("j1"), kind=JobKind("sync"), library="/a/b", version=None, now=T0)

    await repository.add(job)

    assert await repository.get(JobId("j1")) == job


async def test_save_replaces_the_job(repository: JobRepository) -> None:
    await repository.add(queued("j1"))
    progressed = queued("j1").started(T0).progressed(done=1, total=2)

    await repository.save(progressed)

    assert await repository.get(JobId("j1")) == progressed


async def test_a_library_lists_its_own_jobs_newest_first(repository: JobRepository) -> None:
    # IDs are time-ordered (uuid7), so "newest" is the highest ID
    for job in (
        queued("job-2", version="v2"),
        queued("job-1", version="v1"),
        queued("job-3", version="v3"),
    ):
        await repository.add(job)
    await repository.add(queued("job-4", library="/acme/ledger"))

    listed = await repository.list_for_library("/acme/payments")

    assert [job.id for job in listed] == ["job-3", "job-2", "job-1"]


async def test_a_library_with_more_jobs_than_a_page_is_paged_newest_first(
    repository: JobRepository,
) -> None:
    for number in range(7):
        await repository.add(queued(f"job-{number}", version=f"v{number}"))
    await repository.add(queued("job-9", library="/acme/ledger"))  # newer, another library

    pages: list[list[str]] = []
    before: str | None = None
    while True:
        page = await repository.list_page_for_library("/acme/payments", before=before, limit=3)
        pages.append([job.id for job in page])
        if len(page) < 3:
            break
        before = page[-1].id

    assert pages == [["job-6", "job-5", "job-4"], ["job-3", "job-2", "job-1"], ["job-0"]]


async def test_a_page_of_a_library_carries_its_jobs_problems(repository: JobRepository) -> None:
    for number in range(5):
        await repository.add(
            queued(f"job-{number}", version=f"v{number}")
            .started(T0)
            .with_problem(f"skipped-{number}.png", ProblemCode.BINARY, "binary file")
            .succeeded(T0)
        )

    page = await repository.list_page_for_library("/acme/payments", before="job-4", limit=2)

    assert [(job.id, [p.path for p in job.problems]) for job in page] == [
        ("job-3", ["skipped-3.png"]),
        ("job-2", ["skipped-2.png"]),
    ]


@contextmanager
def selects_of_jobs(engine: AsyncEngine) -> Generator[list[tuple[str, Any]]]:
    """Record the SELECTs of ``ingestion_jobs`` sent while the block runs.

    Yields:
        ``(statement, parameters)`` per SELECT, parameters as the driver got them (SQLite's a
        tuple, psycopg's a dict of named parameters).
    """
    sent: list[tuple[str, Any]] = []

    def record(*args: object) -> None:  # (conn, cursor, statement, parameters, context, many)
        statement, parameters = str(args[2]), args[3]
        if statement.lstrip().upper().startswith("SELECT") and "ingestion_jobs" in statement:
            sent.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


def _values(parameters: object) -> set[object]:
    values = parameters.values() if isinstance(parameters, Mapping) else parameters
    assert isinstance(values, Iterable)
    return set(values)


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        (None, ["job-19", "job-18", "job-17", "job-16"]),
        ("job-15", ["job-14", "job-13", "job-12", "job-11"]),
    ],
    ids=["first page", "later page"],
)
@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_page_of_a_library_is_one_select_bounded_by_the_cursor_and_limit(
    backend: str, before: str | None, expected: list[str], request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    repository = SqliteJobRepository(engine=engine)
    for number in range(20):
        await repository.add(queued(f"job-{number:02}", version=f"v{number}"))
    with selects_of_jobs(engine) as sent:
        page = await repository.list_page_for_library("/acme/payments", before=before, limit=4)
    (statement, parameters), *others = sent
    plan: list[str] = []
    if backend == "sqlite":
        async with engine.connect() as connection:
            rows = await connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters)
            plan = [row.detail for row in rows]
    await engine.dispose()

    assert [job.id for job in page] == expected
    assert others == []  # one query, not one per job or a second pass
    assert "LIMIT" in statement.upper()
    # The first page is bounded too, so both pages are one statement with one plan.
    bound = {"/acme/payments", before or ABOVE_EVERY_JOB_ID, 4}
    assert bound <= _values(parameters)
    assert _values(parameters) - bound <= {0}  # SQLite also binds OFFSET 0
    if backend == "sqlite":  # a range of the (library, id) index, no sort of the whole library
        assert any("USING INDEX ingestion_jobs_library_id" in step for step in plan), plan
        assert not any("TEMP B-TREE" in step for step in plan), plan


async def test_a_page_never_holds_a_neighbouring_library_s_jobs(repository: JobRepository) -> None:
    # Libraries whose IDs sort just before and just after this one, with newer and older jobs.
    await repository.add(queued("job-0", library="/acme/pay", version="v0"))
    await repository.add(queued("job-1", version="v1"))
    await repository.add(queued("job-2", library="/acme/payments-old"))
    await repository.add(queued("job-3", version="v3"))
    await repository.add(queued("job-4", library="/acme/payments/"))
    await repository.add(queued("job-5", library="/acme/pay", version="v5"))

    first = await repository.list_page_for_library("/acme/payments", before=None, limit=10)
    later = await repository.list_page_for_library("/acme/payments", before="job-3", limit=10)
    above = await repository.list_page_for_library("/acme/payments", before="zzz", limit=10)

    assert [job.id for job in first] == ["job-3", "job-1"]
    assert [job.id for job in later] == ["job-1"]
    assert [job.id for job in above] == ["job-3", "job-1"]


SKEWED_JOBS = 3000
"""Jobs in the skewed data set: enough for PostgreSQL's planner to weigh the indexes, few enough
for CI."""


@pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")
async def test_every_page_of_an_old_large_library_is_a_range_of_its_index_on_postgresql(
    on_postgres: PostgresDatabase,
) -> None:
    # #330: one library holds 10% of the jobs, every one among the oldest 20% of IDs, and its
    # name sorts after the others'. A backward walk of the primary key that filters on the
    # library looks cheap to the planner here but reads every newer job of the other libraries.
    del on_postgres
    old = "/zeta/archive"
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO ingestion_jobs"
                    " (id, kind, library, state, done, total, problems, created_at)"
                    " SELECT 'job-' || lpad(n::text, 5, '0'), 'import',"
                    "  CASE WHEN n <= :total / 5 AND n % 2 = 0 THEN :old"
                    "   ELSE '/acme/library-' || (n % 50) END,"
                    "  'succeeded', 0, 0, '[]', '2026-01-01T00:00:00.000000+00:00'"
                    " FROM generate_series(1, :total) AS n"
                ),
                {"old": old, "total": SKEWED_JOBS},
            )
            await connection.exec_driver_sql("ANALYZE ingestion_jobs")
        repository = SqliteJobRepository(engine=engine)
        plans: list[str] = []
        pages: list[list[str]] = []
        for before in (None, "job-00300"):
            with selects_of_jobs(engine) as sent:
                page = await repository.list_page_for_library(old, before=before, limit=20)
            pages.append([job.id for job in page])
            ((statement, parameters),) = sent
            async with engine.connect() as connection:
                rows = await connection.exec_driver_sql(
                    f"EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) {statement}",
                    parameters,
                )
                plans.append("\n".join(row[0] for row in rows))
    finally:
        await engine.dispose()

    newest = SKEWED_JOBS // 5
    assert pages == [
        [f"job-{n:05}" for n in range(newest, newest - 40, -2)],
        [f"job-{n:05}" for n in range(298, 258, -2)],
    ]
    for plan in plans:
        assert "ingestion_jobs_library_id" in plan, plan
        assert "ingestion_jobs_pkey" not in plan, plan
        assert "Filter" not in plan, plan  # no other library's row is read and dropped


async def test_a_library_lists_only_its_unfinished_jobs_newest_first(
    repository: JobRepository,
) -> None:
    await repository.add(queued("job-1", version="v1").started(T0).succeeded(T0))
    await repository.add(queued("job-2", version="v2").started(T0).failed("boom", T0))
    await repository.add(
        queued("job-3", version="v3")
        .started(T0)
        .with_problem("logo.png", ProblemCode.BINARY, "binary file")
    )
    await repository.add(queued("job-4", version="v4"))
    await repository.add(queued("job-5", library="/acme/ledger"))  # another library

    unfinished = await repository.list_unfinished_for_library("/acme/payments")

    assert [(job.id, job.state) for job in unfinished] == [
        ("job-4", JobState.QUEUED),
        ("job-3", JobState.RUNNING),
    ]
    assert [p.path for p in unfinished[1].problems] == ["logo.png"]
    assert await repository.list_unfinished_for_library("/acme/nobody") == []


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_library_s_unfinished_jobs_are_one_select_that_skips_its_finished_ones(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    repository = SqliteJobRepository(engine=engine)
    async with engine.begin() as connection:  # one insert: a thousand adds would be slow
        await connection.execute(
            jobs.insert(),
            [
                {
                    "id": f"job-{number:04}",
                    "kind": "import",
                    "library": "/acme/payments",
                    "version": f"v{number}",
                    "state": "succeeded",
                    "done": 0,
                    "total": 0,
                    "problems": json.dumps([{"path": "a.png", "code": "binary", "reason": "x"}]),
                    "created_at": T0.isoformat(),
                }
                for number in range(1000)
            ],
        )
    await repository.add(queued("job-1000", version="v1000").started(T0))
    await repository.add(queued("job-1001", version="v1001"))
    # With statistics the planner knows the library's rows are many. A libSQL server refuses
    # ANALYZE (#474): its planner goes by the indexes alone, and still takes the partial one.
    if backend == "sqlite" and not is_libsql(engine):
        async with engine.begin() as connection:
            await connection.exec_driver_sql("ANALYZE")
    sent: list[tuple[str, list[object]]] = []

    def record(*args: object) -> None:  # (conn, cursor, statement, parameters, context, many)
        statement, parameters = str(args[2]), args[3]
        if statement.lstrip().upper().startswith("SELECT") and "ingestion_jobs" in statement:
            values = parameters.values() if isinstance(parameters, Mapping) else parameters
            assert isinstance(values, Iterable)
            sent.append((statement, list(values)))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        unfinished = await repository.list_unfinished_for_library("/acme/payments")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    (statement, parameters), *others = sent
    plan: list[str] = []
    if backend == "sqlite":
        async with engine.connect() as connection:
            rows = await connection.exec_driver_sql(
                f"EXPLAIN QUERY PLAN {statement}", tuple(parameters)
            )
            plan = [row.detail for row in rows]
    await engine.dispose()

    assert [job.id for job in unfinished] == ["job-1001", "job-1000"]
    assert others == []  # one query, not one per job or a second pass
    assert "state IN ('queued', 'running')" in statement  # literal: the partial index applies
    assert parameters == ["/acme/payments"]
    if backend == "sqlite":  # the partial index alone: no finished job read, no sort
        assert plan == ["SEARCH ingestion_jobs USING INDEX ingestion_jobs_unfinished (library=?)"]


async def test_the_latest_job_of_each_library_and_version_is_listed(
    repository: JobRepository,
) -> None:
    def job(job_id: str, library: str, version: str | None) -> Job:
        return Job.queued(
            job_id=JobId(job_id), kind=JobKind("import"), library=library, version=version, now=T0
        )

    for added in (
        job("1", "/acme/payments", "v1").succeeded(T0),  # superseded below
        job("2", "/acme/payments", "v1"),  # supersedes 1
        job("3", "/acme/payments", "v2"),
        job("4", "/acme/ledger", None),
    ):
        await repository.add(added)

    latest = await repository.list_latest()

    assert [(j.library, j.version, j.id) for j in latest] == [
        ("/acme/ledger", None, "4"),
        ("/acme/payments", "v1", "2"),
        ("/acme/payments", "v2", "3"),
    ]


async def test_list_running_returns_only_running_jobs(repository: JobRepository) -> None:
    await repository.add(queued("waiting"))
    await repository.add(queued("busy", library="/a/b").started(T0))
    await repository.add(queued("done", library="/c/d").started(T0).succeeded(T0))

    assert [job.id for job in await repository.list_running()] == ["busy"]


async def test_list_queued_returns_only_queued_jobs_oldest_first(repository: JobRepository) -> None:
    await repository.add(queued("young", library="/a/b", minute=2))
    await repository.add(queued("old", library="/c/d", minute=1))
    await repository.add(queued("busy", library="/e/f").started(T0))

    assert [job.id for job in await repository.list_queued()] == ["old", "young"]


async def test_claim_starts_the_oldest_queued_job(repository: JobRepository) -> None:
    await repository.add(queued("young", library="/a/b", minute=2))
    await repository.add(queued("old", library="/c/d", minute=1))
    now = T0 + timedelta(hours=1)

    claimed = await repository.claim_next(now)

    assert claimed == queued("old", library="/c/d", minute=1).started(now)
    assert await repository.get(JobId("old")) == claimed


async def test_claim_skips_a_library_that_already_has_a_running_job(
    repository: JobRepository,
) -> None:
    await repository.add(queued("running", minute=1).started(T0))
    await repository.add(queued("same-library", minute=2, version="v2"))
    await repository.add(queued("other-library", library="/acme/ledger", minute=3))

    first = await repository.claim_next(T0)
    second = await repository.claim_next(T0)

    assert first is not None
    assert first.id == "other-library"
    assert second is None


async def test_claim_never_hands_out_a_job_twice(repository: JobRepository) -> None:
    await repository.add(queued("only"))

    first = await repository.claim_next(T0)
    second = await repository.claim_next(T0)

    assert (first is not None and first.state is JobState.RUNNING, second) == (True, None)


async def test_claimers_on_separate_connections_get_one_job_per_library_and_no_duplicates() -> None:
    """Several engines on one file stand in for several processes."""
    engines = [open_database(Settings()) for _ in range(4)]
    await migrate(engines[0])
    repositories = [SqliteJobRepository(engine=engine) for engine in engines]
    for number in range(30):
        await repositories[0].add(
            queued(f"job-{number:02}", library=f"/acme/lib-{number % 5}", version=f"v{number}")
        )

    async def claim_all(repository: SqliteJobRepository) -> list[Job]:
        claimed = [await repository.claim_next(T0) for _ in range(10)]
        return [job for job in claimed if job is not None]

    results = await asyncio.gather(*(claim_all(r) for r in repositories for _ in range(4)))
    for engine in engines:
        await engine.dispose()

    claimed = [job for jobs in results for job in jobs]
    assert sorted(job.library for job in claimed) == [f"/acme/lib-{n}" for n in range(5)]
    assert len({job.id for job in claimed}) == 5


async def test_problems_saved_by_another_version_are_read_without_failing() -> None:
    engine = open_database(Settings())
    await migrate(engine)
    repository = SqliteJobRepository(engine=engine)
    await repository.add(queued("j1"))
    old_and_new = [
        {"path": "a.md", "reason": "not valid UTF-8"},
        {"path": "b.md", "reason": "larger than 50 bytes"},
        {"path": "c.md", "reason": "something else"},
        {"path": "", "reason": "more files were skipped; they are not listed"},
        {"path": "d.md", "code": "from_the_future", "reason": "x"},
    ]
    async with engine.begin() as connection:
        await connection.execute(
            jobs.update().values(problems=json.dumps(old_and_new)).where(jobs.c.id == "j1")
        )

    job = await repository.get(JobId("j1"))

    assert job is not None
    assert [p.code for p in job.problems] == [
        ProblemCode.UNDECODABLE,
        ProblemCode.TOO_LARGE,
        ProblemCode.UNREADABLE,
        ProblemCode.TRUNCATED,
        ProblemCode.UNREADABLE,
    ]
    await engine.dispose()


async def test_a_second_unfinished_import_of_a_ref_is_refused_but_a_finished_one_is_not(
    repository: JobRepository,
) -> None:
    await repository.add(queued("j1"))
    with pytest.raises(VersionImportingError):
        await repository.add(queued("j2"))
    await repository.add(queued("j3", library="/acme/orders"))  # another library
    await repository.save(queued("j1").failed("boom", T0))  # finished jobs do not count

    await repository.add(queued("j2"))
    await repository.add(queued("j4").failed("boom", T0))  # nor are they refused


def push(job_id: str, ref: str = "main", kind: RefKind = RefKind.BRANCH) -> Job:
    return Job.queued(
        job_id=JobId(job_id),
        kind=JobKind("push"),
        library="/acme/payments",
        version=ref,
        ref_kind=kind,
        now=T0,
    )


async def test_a_push_job_is_never_a_version_s_latest_job(repository: JobRepository) -> None:
    await repository.add(queued("1", version="main").started(T0).succeeded(T0))
    await repository.add(push("2").started(T0))  # newer, but says nothing about the version
    await repository.add(push("3", ref="v2.1.0", kind=RefKind.TAG).started(T0).failed("x", T0))

    latest = await repository.list_latest()

    assert [(j.version, j.id) for j in latest] == [("main", "1")]


async def test_a_second_queued_push_of_a_ref_is_refused_but_a_running_one_lets_it_in(
    repository: JobRepository,
) -> None:
    await repository.add(push("p1"))
    with pytest.raises(PushQueuedError, match="sync of branch 'main'"):
        await repository.add(push("p2"))
    await repository.add(push("p3", ref="next"))  # another branch
    await repository.add(push("p4", kind=RefKind.TAG))  # a tag of the same name
    await repository.add(queued("j1", version="main"))  # an import of the ref is no push

    await repository.save(push("p1").started(T0))  # it lists the remote: a later push may wait
    await repository.add(push("p2"))
    with pytest.raises(PushQueuedError):
        await repository.add(push("p5"))


# ---------------------------------------------------------------- cancellation (#432)


async def test_a_queued_job_is_cancelled_at_once(repository: JobRepository) -> None:
    await repository.add(queued("j1"))
    at = T0 + timedelta(minutes=1)

    cancelled = await repository.cancel(JobId("j1"), by="alice", now=at)

    assert cancelled is not None
    assert (cancelled.state, cancelled.cancelled_by) == (JobState.CANCELLED, "alice")
    assert (cancelled.cancelled_at, cancelled.finished_at) == (at, at)
    assert await repository.get(JobId("j1")) == cancelled
    assert await repository.list_queued() == []
    assert await repository.claim_next(T0) is None


async def test_a_running_job_is_only_flagged_and_its_progress_never_wipes_the_flag(
    repository: JobRepository,
) -> None:
    running = queued("j1").started(T0)
    await repository.add(running)

    flagged = await repository.cancel(JobId("j1"), by="alice", now=T0)
    await repository.save(running.progressed(done=1, total=2))  # read before the cancel

    stored = await repository.get(JobId("j1"))
    assert flagged is not None
    assert stored is not None
    assert (flagged.state, flagged.cancelled_by) == (JobState.RUNNING, "alice")
    assert (stored.state, stored.done, stored.cancelled_by) == (JobState.RUNNING, 1, "alice")


async def test_a_second_request_and_a_finished_job_are_left_as_they_are(
    repository: JobRepository,
) -> None:
    await repository.add(queued("run", version="v1").started(T0))
    await repository.add(queued("done", version="v2").started(T0).succeeded(T0))
    await repository.cancel(JobId("run"), by="alice", now=T0)

    again = await repository.cancel(JobId("run"), by="bob", now=T0 + timedelta(minutes=1))
    finished = await repository.cancel(JobId("done"), by="bob", now=T0)

    assert again is not None
    assert finished is not None
    assert (again.cancelled_by, again.cancelled_at) == ("alice", T0)
    assert (finished.state, finished.cancelled_at) == (JobState.SUCCEEDED, None)
    assert await repository.cancel(JobId("nope"), by="bob", now=T0) is None


async def test_a_cancelled_job_is_never_saved_over(repository: JobRepository) -> None:
    await repository.add(queued("j1"))
    await repository.cancel(JobId("j1"), by="alice", now=T0)

    await repository.save(queued("j1").started(T0))  # a worker that read it before

    stored = await repository.get(JobId("j1"))
    assert stored is not None
    assert (stored.state, stored.started_at) == (JobState.CANCELLED, None)


async def test_a_cancelled_import_frees_its_ref(repository: JobRepository) -> None:
    await repository.add(queued("j1"))
    await repository.cancel(JobId("j1"), by="alice", now=T0)

    await repository.add(queued("j2", minute=1))  # no VersionImportingError

    assert {job.id for job in await repository.list_queued()} == {"j2"}


async def test_the_newest_job_of_a_kind_of_each_version_is_listed(
    repository: JobRepository,
) -> None:
    embed = JobKind("embed")
    for job_id, version, kind in (
        ("a1", "v1", embed),
        ("a2", "v1", embed),
        ("a3", "v1", JobKind("import")),
        ("b1", "v2", embed),
    ):
        job = Job.queued(job_id=JobId(job_id), kind=kind, library="/a/b", version=version, now=T0)
        await repository.add(job.started(T0).succeeded(T0))
    other = Job.queued(job_id=JobId("c9"), kind=embed, library="/a/c", version="v1", now=T0)
    await repository.add(other)

    newest = await repository.list_newest_of_kind("/a/b", embed)

    assert sorted(job.id for job in newest) == ["a2", "b1"]
