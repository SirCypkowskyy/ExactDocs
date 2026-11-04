"""Ingestion use cases. Each one satisfies a driving port structurally, without inheriting it."""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from exactdocs.ingestion.dtos import (
    EnqueueJobCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    ListLibraryJobsQuery,
)
from exactdocs.ingestion.errors import JobNotFoundError, UnknownJobKindError
from exactdocs.ingestion.models import Job, JobId, JobKind
from exactdocs.ingestion.ports.driven import JobHandler, JobRepository, RecoveryHook
from exactdocs_kernel import Clock, DomainError, paginate

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EnqueueJobUseCase:
    """Implements ``ports.driving.EnqueueJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        """Queue the job; the worker picks it up."""
        kind = JobKind(command.kind)
        if kind not in self.handlers:
            raise UnknownJobKindError(kind)
        job = Job.queued(
            job_id=JobId(str(uuid.uuid7())),  # time-ordered, so IDs sort like creation time
            kind=kind,
            library=command.library,
            version=command.version,
            now=self.clock.now(),
        )
        await self.jobs.add(job)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class GetJobUseCase:
    """Implements ``ports.driving.GetJob``."""

    jobs: JobRepository

    async def __call__(self, query: GetJobQuery) -> JobSummary:
        """Fetch one job by its ID."""
        job = await self.jobs.get(JobId(query.job_id))
        if job is None:
            raise JobNotFoundError(query.job_id)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class ListLibraryJobsUseCase:
    """Implements ``ports.driving.ListLibraryJobs``."""

    jobs: JobRepository

    async def __call__(self, query: ListLibraryJobsQuery) -> JobList:
        """List a page of the library's jobs, newest first."""
        # ponytail: loads all of the library's jobs, then pages in memory; a keyset query in
        # the repository once a library has thousands of jobs.
        jobs = await self.jobs.list_for_library(query.library)
        page = paginate(
            jobs, key=lambda job: job.id, limit=query.limit, cursor=query.cursor, descending=True
        )
        return JobList.from_page(page)


@dataclass(frozen=True, slots=True)
class RecoverJobsUseCase:
    """Implements ``ports.driving.RecoverJobs``."""

    jobs: JobRepository
    clock: Clock
    hooks: Mapping[JobKind, RecoveryHook]

    async def __call__(self) -> None:
        """Run the hook of every job left ``running``, then queue it again to run from scratch.

        A kind without a hook has nothing to clean up. A hook that raises fails its job instead
        of keeping the app from starting, because re-running over unclean state would be worse.
        """
        # ponytail: assumes one live process runs jobs on the database (the HTTP server; stdio
        # does not). Several would re-queue each other's running jobs: add a lease/heartbeat
        # column and re-queue only expired leases if that ever changes.
        for job in await self.jobs.list_running():
            hook = self.hooks.get(job.kind)
            try:
                if hook is not None:
                    await hook(job)
            except Exception as error:
                log.exception("recovery of job %s (%s) failed", job.id, job.kind)
                await self.jobs.save(
                    job.failed(f"recovery failed: {_describe(error)}", self.clock.now())
                )
            else:
                await self.jobs.save(job.requeued())


@dataclass(frozen=True, slots=True)
class RunNextJobUseCase:
    """Implements ``ports.driving.RunNextJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]

    async def __call__(self) -> bool:
        """Claim the next job that may run, run it, and record how it ended."""
        job = await self.jobs.claim_next(self.clock.now())
        if job is None:
            return False
        progress = _Progress(self.jobs, job)
        handler = self.handlers.get(job.kind)
        try:
            if handler is None:
                failure = f"no handler is registered for job kind {job.kind!r}"
            else:
                await handler(job, progress)
                failure = None
        except Exception as error:
            log.exception("job %s (%s) failed", job.id, job.kind)
            failure = _describe(error)
        now = self.clock.now()
        final = (
            progress.job.succeeded(now) if failure is None else progress.job.failed(failure, now)
        )
        try:
            await self.jobs.save(final)
        except Exception:
            log.exception("could not store the end of job %s (%s)", job.id, job.kind)
            raise
        return True


@dataclass(slots=True)
class _Progress:
    """Implements ``ports.driven.JobProgress``: keeps the latest job and stores every change."""

    jobs: JobRepository
    job: Job

    async def report(self, *, done: int, total: int) -> None:
        self.job = self.job.progressed(done=done, total=total)
        await self.jobs.save(self.job)

    async def problem(self, path: str, reason: str) -> None:
        self.job = self.job.with_problem(path, reason)
        await self.jobs.save(self.job)


def _describe(error: Exception) -> str:
    """Return the text users see: a domain error says what is wrong, else only its type."""
    return str(error) if isinstance(error, DomainError) else f"unexpected {type(error).__name__}"
