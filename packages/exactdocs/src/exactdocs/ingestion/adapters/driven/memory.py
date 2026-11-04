from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from exactdocs.ingestion.models import Job, JobId, JobState


@dataclass(slots=True)
class InMemoryJobRepository:
    """Implements ``ports.driven.JobRepository``. For tests."""

    jobs: dict[JobId, Job] = field(default_factory=dict)

    @classmethod
    def of(cls, jobs: Iterable[Job]) -> Self:
        """Create a repository pre-filled with ``jobs``."""
        return cls({job.id: job for job in jobs})

    async def add(self, job: Job) -> None:
        """Store a new job."""
        self.jobs[job.id] = job

    async def save(self, job: Job) -> None:
        """Replace the stored job that has the same ID."""
        self.jobs[job.id] = job

    async def get(self, job_id: JobId) -> Job | None:
        """Return the job, or ``None``."""
        return self.jobs.get(job_id)

    async def list_for_library(self, library: str) -> Sequence[Job]:
        """Return the library's jobs, newest first (job IDs are time-ordered)."""
        mine = [job for job in self.jobs.values() if job.library == library]
        return sorted(mine, key=lambda job: job.id, reverse=True)

    async def list_running(self) -> Sequence[Job]:
        """Return every job in the ``running`` state."""
        return [job for job in self.jobs.values() if job.state is JobState.RUNNING]

    async def claim_next(self, now: datetime) -> Job | None:
        """Atomically start the oldest queued job whose library has no running job."""
        busy = {job.library for job in self.jobs.values() if job.state is JobState.RUNNING}
        waiting = [job for job in self.jobs.values() if job.state is JobState.QUEUED]
        for job in sorted(waiting, key=lambda job: (job.created_at, job.id)):
            if job.library not in busy:
                started = job.started(now)
                self.jobs[job.id] = started
                return started
        return None
