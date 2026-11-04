"""Adapter contract: every ``JobRepository`` behaves the same, whatever stores the data."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.models import Job, JobId, JobKind, JobState
from exactdocs.ingestion.ports import JobRepository

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def queued(job_id: str, library: str = "/acme/payments", minute: int = 0) -> Job:
    return Job.queued(
        job_id=JobId(job_id),
        kind=JobKind("import"),
        library=library,
        version="1.4",
        commit_sha="c" * 40,  # the commit the version was pinned to must survive too
        now=T0 + timedelta(minutes=minute),
    )


@pytest.fixture(params=["memory", "sqlite"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[JobRepository]:
    if request.param == "memory":
        yield InMemoryJobRepository()
        return
    # Not a Container: its worker would pick up the queued jobs these tests look at.
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteJobRepository(engine)
    await engine.dispose()


async def test_starts_empty(repository: JobRepository) -> None:
    assert await repository.get(JobId("j1")) is None
    assert await repository.list_running() == []
    assert await repository.claim_next(T0) is None


async def test_every_field_survives_a_round_trip(repository: JobRepository) -> None:
    job = (
        queued("j1")
        .started(T0 + timedelta(seconds=5))
        .progressed(done=4, total=10)
        .with_problem("assets/logo.png", "binary")
        .with_problem("guide/ünï.md", "undecodable")
        .failed("boom", T0 + timedelta(seconds=9, microseconds=7))
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
    for job in (queued("job-2"), queued("job-1"), queued("job-3")):
        await repository.add(job)
    await repository.add(queued("job-4", library="/acme/ledger"))

    listed = await repository.list_for_library("/acme/payments")

    assert [job.id for job in listed] == ["job-3", "job-2", "job-1"]


async def test_list_running_returns_only_running_jobs(repository: JobRepository) -> None:
    await repository.add(queued("waiting"))
    await repository.add(queued("busy", library="/a/b").started(T0))
    await repository.add(queued("done", library="/c/d").started(T0).succeeded(T0))

    assert [job.id for job in await repository.list_running()] == ["busy"]


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
    await repository.add(queued("same-library", minute=2))
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
    repositories = [SqliteJobRepository(engine) for engine in engines]
    for number in range(30):
        await repositories[0].add(queued(f"job-{number:02}", library=f"/acme/lib-{number % 5}"))

    async def claim_all(repository: SqliteJobRepository) -> list[Job]:
        claimed = [await repository.claim_next(T0) for _ in range(10)]
        return [job for job in claimed if job is not None]

    results = await asyncio.gather(*(claim_all(r) for r in repositories for _ in range(4)))
    for engine in engines:
        await engine.dispose()

    claimed = [job for jobs in results for job in jobs]
    assert sorted(job.library for job in claimed) == [f"/acme/lib-{n}" for n in range(5)]
    assert len({job.id for job in claimed}) == 5
