"""Cancelling a job (#432): who may, which jobs, and what a cancelled job becomes."""

from datetime import UTC, datetime

import pytest

from cancelling import WHO, Canceller, run_job
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.constants import IMPORT_JOB
from exactdocs.ingestion.dtos import CancelJobCommand, GetJobQuery, ListLibraryJobsQuery
from exactdocs.ingestion.errors import (
    JobFinishedError,
    JobNotFoundError,
    LibraryAccessDeniedError,
)
from exactdocs.ingestion.models import Job, JobId, JobState
from exactdocs.ingestion.ports.driven import JobProgress
from exactdocs.ingestion.use_cases import (
    CancelJobUseCase,
    GetJobUseCase,
    ListLibraryJobsUseCase,
    RecoverJobsUseCase,
    RunJobUseCase,
    StopOnCancel,
    _NoCheckpoints,
)
from exactdocs_kernel import SystemClock
from library_access import FakeAccess

LIB = "/acme/docs"
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def queued(job_id: str = "j1", version: str = "v1") -> Job:
    return Job.queued(job_id=JobId(job_id), kind=IMPORT_JOB, library=LIB, version=version, now=T0)


def cancel_use_case(jobs: InMemoryJobRepository, role: str | None = "contributor"):
    return CancelJobUseCase(jobs=jobs, clock=SystemClock(), access=FakeAccess(role=role))


async def test_a_queued_job_is_cancelled_at_once_and_never_starts() -> None:
    jobs = InMemoryJobRepository()
    await jobs.add(queued())

    answer = await cancel_use_case(jobs)(CancelJobCommand(job_id="j1", by=WHO))
    ran: list[str] = []

    async def handler(job: Job, progress: JobProgress, /) -> None:
        del progress
        ran.append(job.id)

    await RunJobUseCase(jobs=jobs, clock=SystemClock(), handlers={IMPORT_JOB: handler}, hooks={})(
        "j1"
    )

    assert (answer.state, answer.cancelled_by) == (JobState.CANCELLED, WHO)
    assert answer.cancelled_at is not None
    assert ran == []
    stored = await jobs.get(JobId("j1"))
    assert stored is not None
    assert (stored.state, stored.started_at) == (JobState.CANCELLED, None)


async def test_a_running_job_is_flagged_and_asking_again_answers_the_same() -> None:
    jobs = InMemoryJobRepository()
    await jobs.add(queued().started(T0))
    cancel = cancel_use_case(jobs)

    first = await cancel(CancelJobCommand(job_id="j1", by=WHO))
    second = await cancel(CancelJobCommand(job_id="j1", by="bob"))

    assert (first.state, first.cancelled_by) == (JobState.RUNNING, WHO)
    assert second == first


@pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled"])
async def test_a_finished_job_is_refused_with_its_state(state: str) -> None:
    jobs = InMemoryJobRepository()
    job = queued()
    ended = {
        "succeeded": job.started(T0).succeeded(T0),
        "failed": job.started(T0).failed("boom", T0),
        "cancelled": job.cancelling(WHO, T0),
    }[state]
    await jobs.add(ended)

    with pytest.raises(JobFinishedError) as refused:
        await cancel_use_case(jobs)(CancelJobCommand(job_id="j1", by=WHO))

    assert refused.value.job_state == state


async def test_a_viewer_may_not_cancel_and_a_hidden_job_does_not_exist() -> None:
    jobs = InMemoryJobRepository()
    await jobs.add(queued())

    with pytest.raises(LibraryAccessDeniedError):
        await cancel_use_case(jobs, role="viewer")(CancelJobCommand(job_id="j1", by=WHO))
    with pytest.raises(JobNotFoundError):
        await cancel_use_case(jobs, role=None)(CancelJobCommand(job_id="j1", by=WHO))
    with pytest.raises(JobNotFoundError):
        await cancel_use_case(jobs)(CancelJobCommand(job_id="nope", by=WHO))
    stored = await jobs.get(JobId("j1"))
    assert stored is not None
    assert stored.state is JobState.QUEUED


async def test_the_jobs_say_whether_the_caller_may_cancel_them() -> None:
    jobs = InMemoryJobRepository()
    await jobs.add(queued("j1", "v1"))
    await jobs.add(queued("j2", "v2").started(T0).succeeded(T0))

    contributor = FakeAccess(role="contributor")
    listed = await ListLibraryJobsUseCase(jobs=jobs, access=contributor)(
        ListLibraryJobsQuery(library=LIB)
    )
    viewer = FakeAccess(role="viewer")
    seen = await GetJobUseCase(jobs=jobs, access=viewer)(GetJobQuery(job_id="j1"))

    assert {job.id: job.cancellable for job in listed.jobs} == {"j1": True, "j2": False}
    assert not seen.cancellable


async def test_a_job_that_ends_before_its_next_step_ends_as_it_would_have() -> None:
    jobs = InMemoryJobRepository()
    cancel = Canceller(jobs, job_id="j1")

    async def handler(job: Job, progress: JobProgress, /) -> None:
        del job, progress
        await cancel()  # too late: no step boundary follows

    ended = await run_job(jobs, queued(), handler)

    assert (ended.state, ended.cancelled_by) == (JobState.SUCCEEDED, WHO)


async def test_every_step_after_the_cancellation_is_skipped() -> None:
    jobs = InMemoryJobRepository()
    cancel = Canceller(jobs, job_id="j1")
    ran: list[str] = []

    async def handler(job: Job, progress: JobProgress, /) -> None:
        del job, progress
        for steps in (StopOnCancel(inner=_NoCheckpoints()), _NoCheckpoints()):
            for name in ("one", "two"):

                async def step(name: str = name) -> None:
                    ran.append(name)
                    await cancel()

                await steps.step(name, step)

    ended = await run_job(jobs, queued(), handler)

    assert ran == ["one"]
    assert ended.state is JobState.CANCELLED


async def test_a_job_interrupted_while_it_was_being_cancelled_ends_cancelled() -> None:
    jobs = InMemoryJobRepository()
    await jobs.add(queued("j1", "v1").started(T0))
    await jobs.add(queued("j2", "v2").started(T0))
    await jobs.cancel(JobId("j1"), by=WHO, now=T0)
    await jobs.cancel(JobId("j2"), by=WHO, now=T0)
    cleaned: list[str] = []

    async def hook(job: Job, /) -> None:
        cleaned.append(job.id)

    class Runner:
        async def submit(self, job: Job) -> None:
            raise AssertionError(job)

    await RecoverJobsUseCase(
        jobs=jobs, clock=SystemClock(), hooks={IMPORT_JOB: hook}, runner=Runner()
    )(resuming={"j2"})
    await RunJobUseCase(jobs=jobs, clock=SystemClock(), handlers={}, hooks={IMPORT_JOB: hook})("j2")

    assert cleaned == ["j1", "j2"]  # what each interrupted step left half done is discarded
    for job_id in ("j1", "j2"):
        stored = await jobs.get(JobId(job_id))
        assert stored is not None
        assert stored.state is JobState.CANCELLED
