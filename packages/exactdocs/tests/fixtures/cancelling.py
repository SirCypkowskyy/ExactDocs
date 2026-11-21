"""Run a job handler through ``RunJob`` while the job is cancelled from inside one of its steps.

The handler's steps see the cancellation only at their next boundary (``StopOnCancel``); a
test cancels the job, as ``POST /jobs/{id}/cancel`` would, from a fake the step calls.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.models import Job, JobId
from exactdocs.ingestion.ports.driven import JobHandler
from exactdocs.ingestion.use_cases import RunJobUseCase
from exactdocs_kernel import SystemClock

WHO = "alice"
"""Who cancels the jobs of these tests."""


@dataclass(slots=True)
class Canceller:
    """Cancels one job of a repository when called (the first time only)."""

    jobs: InMemoryJobRepository
    job_id: str = ""
    calls: int = 0
    after: int = 1
    """Cancel on this call, counting from 1."""
    cancelled: list[Job] = field(default_factory=list)

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls == self.after:
            job = await self.jobs.cancel(JobId(self.job_id), by=WHO, now=datetime.now(UTC))
            assert job is not None
            self.cancelled.append(job)


async def run_job(jobs: InMemoryJobRepository, job: Job, handler: JobHandler) -> Job:
    """Queue ``job``, run it with ``handler`` as ``RunJob`` does, and return how it ended.

    Args:
        jobs: Where the job is stored.
        job: The queued job.
        handler: Runs its kind.

    Returns:
        The job as stored at its end.
    """
    await jobs.add(job)
    run = RunJobUseCase(jobs=jobs, clock=SystemClock(), handlers={job.kind: handler}, hooks={})
    await run(job.id)
    ended = await jobs.get(job.id)
    assert ended is not None
    return ended
