"""Ingestion use cases. Each one satisfies a driving port structurally, without inheriting it."""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddLibraryCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    EnqueueJobCommand,
    GetJobQuery,
    JobList,
    JobSummary,
    LatestJob,
    LatestJobs,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    RefOut,
    RepositoryRefs,
)
from exactdocs.ingestion.errors import JobNotFoundError, LibraryIdTakenError, UnknownJobKindError
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    Job,
    JobId,
    JobKind,
    NewLibrary,
    PathSelection,
    ProposedId,
    RefKind,
    RepositoryUrl,
    ref_tips,
    resolve_ref,
)
from exactdocs.ingestion.ports.driven import (
    GitRemote,
    JobHandler,
    JobRepository,
    LibraryIds,
    NewLibraries,
    RecoveryHook,
)
from exactdocs.ingestion.ports.driving import EnqueueJob
from exactdocs_kernel import Clock, DomainError, paginate

log = logging.getLogger(__name__)

MAX_LISTED_REFS = 1000
"""Branches and tags listed each; a repository with more is cut and flagged ``truncated``."""


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
            commit_sha=command.commit_sha,
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
class ListLatestJobsUseCase:
    """Implements ``ports.driving.ListLatestJobs``."""

    jobs: JobRepository

    async def __call__(self) -> LatestJobs:
        """List the newest job of every (library, version), without their skipped files."""
        # ponytail: not paged; one row per imported version, fine until thousands exist.
        return LatestJobs(jobs=[LatestJob.from_model(job) for job in await self.jobs.list_latest()])


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


@dataclass(frozen=True, slots=True)
class CheckRepositoryUseCase:
    """Implements ``ports.driving.CheckRepository``."""

    remote: GitRemote
    library_ids: LibraryIds

    async def __call__(self, command: CheckRepositoryCommand) -> CheckedRepository:
        """Parse the URL, refuse a taken ID, then ask the remote for its default branch."""
        repository = RepositoryUrl.parse(command.url)
        if await self.library_ids.is_taken(repository.library_id):
            raise LibraryIdTakenError(repository.library_id)
        refs = await self.remote.list_refs(repository, "HEAD")
        return CheckedRepository(
            host=repository.host_kind,
            library_id=repository.library_id,
            default_branch=refs.default_branch,
        )


@dataclass(frozen=True, slots=True)
class ListRepositoryRefsUseCase:
    """Implements ``ports.driving.ListRepositoryRefs``."""

    remote: GitRemote

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Parse the URL and list what the remote advertises, at most ``MAX_LISTED_REFS`` each."""
        refs = await self.remote.list_refs(RepositoryUrl.parse(query.url))
        tips = ref_tips(refs)
        branches = [
            RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.BRANCH
        ]
        tags = [RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.TAG]
        return RepositoryRefs(
            default_branch=refs.default_branch,
            branches=branches[:MAX_LISTED_REFS],
            tags=tags[:MAX_LISTED_REFS],
            truncated=max(len(branches), len(tags)) > MAX_LISTED_REFS,
        )


@dataclass(frozen=True, slots=True)
class AddLibraryUseCase:
    """Implements ``ports.driving.AddLibrary``."""

    remote: GitRemote
    library_ids: LibraryIds
    libraries: NewLibraries
    enqueue_job: EnqueueJob

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        """Check everything that can be checked first, then store the library and queue its import.

        If queueing fails, the new library is removed again, so a retry is not met with a 409.
        """
        repository = RepositoryUrl.parse(command.url)
        selection = PathSelection.of(command.include_paths, command.exclude_paths)
        library_id = ProposedId(command.library_id or repository.library_id)
        if await self.library_ids.is_taken(library_id):
            raise LibraryIdTakenError(library_id)
        refs = await self.remote.list_refs(repository)
        resolved = resolve_ref(refs, command.ref)
        created = await self.libraries.add(
            NewLibrary(
                library_id=library_id,
                title=library_id.rsplit("/", 1)[-1],
                source_url=repository.url,
                host=repository.host_kind,
                default_branch=refs.default_branch,
                selection=selection,
            )
        )
        try:
            job = await self.enqueue_job(
                EnqueueJobCommand(
                    kind=IMPORT_JOB,
                    library=created,
                    version=resolved.name,
                    commit_sha=resolved.commit_sha,
                )
            )
        except BaseException:
            try:
                await self.libraries.discard(created)
            except Exception:
                log.exception(
                    "could not remove library %s after its import failed to queue", created
                )
            raise
        return AddedLibrary.of(created, resolved, job)
