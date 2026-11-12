"""Adapter contract: every ``JobRepository`` behaves the same, whatever stores the data."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven import sqlite as sql_adapter
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository, jobs
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.errors import VersionImportingError
from exactdocs.ingestion.models import FileProblem, Job, JobId, JobState, ProblemCode, RefKind
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


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_page_of_a_library_reads_only_that_pages_rows(
    backend: str, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    repository = SqliteJobRepository(engine=engine)
    for number in range(20):
        await repository.add(
            queued(f"job-{number:02}", version=f"v{number}").with_problem(
                f"skipped-{number:02}.png", ProblemCode.BINARY, "binary file"
            )
        )
    read: list[str] = []

    def counting(*, path: str, code: ProblemCode, reason: str) -> FileProblem:
        read.append(path)
        return FileProblem(path=path, code=code, reason=reason)

    # every stored problem the query brings back is read into a FileProblem
    monkeypatch.setattr(sql_adapter, "FileProblem", counting)

    page = await repository.list_page_for_library("/acme/payments", before="job-15", limit=4)
    await engine.dispose()

    assert [job.id for job in page] == ["job-14", "job-13", "job-12", "job-11"]
    assert read == [f"skipped-{n}.png" for n in (14, 13, 12, 11)]


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
