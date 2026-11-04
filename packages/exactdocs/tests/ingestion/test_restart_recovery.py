"""A restart over a real SQLite file: the interrupted job is cleaned up and runs again."""

import asyncio
from collections.abc import Mapping

from doubles import NoIndex, NoRemovals
from sqlalchemy.ext.asyncio import AsyncEngine

from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driven.git_cli import MissingGit
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.adapters.driving.worker import JobWorker
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery
from exactdocs.ingestion.models import Job, JobKind, JobState
from exactdocs.ingestion.ports import JobHandler, JobProgress, RecoveryHook
from exactdocs_kernel import SystemClock

IMPORT = JobKind("import")


class _NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


class _NoLibraryIds:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return False


def start_app(
    handlers: Mapping[JobKind, JobHandler], hooks: Mapping[JobKind, RecoveryHook] | None = None
) -> tuple[IngestionModule, JobWorker, AsyncEngine]:
    """What the container does at start: one engine, one module, one worker."""
    engine = open_database(Settings())
    module = IngestionModule.build(
        jobs=SqliteJobRepository(engine),
        clock=SystemClock(),
        remote=MissingGit(),
        library_ids=_NoLibraryIds(),
        libraries=_NoLibraries(),
        removals=NoRemovals(),
        index=NoIndex(),
        handlers=handlers,
        recovery_hooks=hooks or {},
    )
    worker = JobWorker(
        recover_jobs=module.recover_jobs,
        run_next_job=module.run_next_job,
        concurrency=1,
        poll_interval=0.01,
        stop_grace=0.05,
    )
    return module, worker, engine


async def test_a_job_running_when_the_app_stopped_is_cleaned_up_and_run_from_the_beginning(
    eventually,
) -> None:
    events: list[str] = []
    halfway = asyncio.Event()

    async def import_then_get_killed(_job: Job, progress: JobProgress) -> None:
        events.append("first run")
        await progress.report(done=4, total=10)
        halfway.set()
        await asyncio.Event().wait()

    module, worker, engine = start_app({IMPORT: import_then_get_killed})
    await migrate(engine)
    queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/acme/payments"))
    async with worker.running():
        await halfway.wait()
    await engine.dispose()  # the process is gone; the job is still `running` in the file

    async def discard_pending_manifest(job: Job) -> None:
        events.append(f"hook for {job.id} at {job.done} of {job.total}")

    async def import_all(job: Job, progress: JobProgress) -> None:
        events.append(f"second run from {job.done} of {job.total}")
        await progress.report(done=10, total=10)

    module, worker, engine = start_app({IMPORT: import_all}, {IMPORT: discard_pending_manifest})
    await migrate(engine)
    assert (await module.get_job(GetJobQuery(job_id=queued.id))).state is JobState.RUNNING
    async with worker.running():

        async def finished() -> bool:
            return (await module.get_job(GetJobQuery(job_id=queued.id))).state is JobState.SUCCEEDED

        await eventually(finished)
    await engine.dispose()

    assert events == [
        "first run",
        f"hook for {queued.id} at 4 of 10",
        "second run from 0 of 0",
    ]
