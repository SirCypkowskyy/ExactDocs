"""``DbosJobWorker``: jobs run as DBOS workflows over a real DBOS SQLite file."""

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

from dbos import DBOS
from sqlalchemy import NullPool

from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driven.dbos import (
    QUEUE,
    STEPS_VERSION,
    WORKFLOW,
    DbosCheckpoints,
    DbosJobQueue,
)
from exactdocs.ingestion.adapters.driven.git_cli import MissingGit
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery
from exactdocs.ingestion.models import Job, JobId, JobKind, JobState
from exactdocs.ingestion.ports import JobHandler, JobProgress, JobRunner, RecoveryHook
from exactdocs_kernel import SystemClock

IMPORT = JobKind("import")


class _NoLibraryIds:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return False


class _NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


class FlakyQueue:
    """``DbosJobQueue``, except that it drops the first job it is handed (DBOS was busy)."""

    def __init__(self) -> None:
        self.dropped: list[str] = []
        self.inner = DbosJobQueue()

    async def submit(self, job: Job) -> None:
        if not self.dropped:
            self.dropped.append(job.id)
            return
        await self.inner.submit(job)


def module_of(
    jobs: InMemoryJobRepository,
    handlers: Mapping[JobKind, JobHandler],
    hooks: Mapping[JobKind, RecoveryHook] | None = None,
    runner: JobRunner | None = None,
) -> IngestionModule:
    return IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=MissingGit(),
        library_ids=_NoLibraryIds(),
        libraries=_NoLibraries(),
        removals=NoRemovals(),
        index=NoIndex(),
        handlers=handlers,
        recovery_hooks=hooks or {},
        runner=runner or DbosJobQueue(),
    )


def worker_of(
    module: IngestionModule, tmp_path: Path, concurrency: int = 2, resubmit: float = 30
) -> DbosJobWorker:
    return DbosJobWorker(
        run_job=module.run_job,
        recover_jobs=module.recover_jobs,
        submit_queued_jobs=module.submit_queued_jobs,
        database=tmp_path / "jobs.sqlite",
        queue=QUEUE,
        workflow=WORKFLOW,
        version=STEPS_VERSION,
        engine_options={"poolclass": NullPool},
        concurrency=concurrency,
        stop_grace=0.05,
        poll_interval=0.01,
        resubmit_interval=resubmit,
    )


async def state_of(module: IngestionModule, job_id: str) -> JobState:
    return (await module.get_job(GetJobQuery(job_id=job_id))).state


async def test_queued_jobs_run_in_the_background_to_the_end_and_leave_no_workflow(
    tmp_path: Path, eventually
) -> None:
    async def import_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=3, total=3)

    module = module_of(InMemoryJobRepository(), {IMPORT: import_files})

    async with worker_of(module, tmp_path).running():
        queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)

        async def forgotten() -> bool:  # its steps would otherwise stay in the file
            return not await DBOS.list_workflows_async()

        await eventually(forgotten)


async def test_jobs_of_one_library_never_overlap_but_other_libraries_run_alongside(
    tmp_path: Path, eventually
) -> None:
    running: dict[str, int] = {}
    most: dict[str, int] = {}
    both_libraries_busy = asyncio.Barrier(2)

    async def work(job: Job, _progress: JobProgress) -> None:
        running[job.library] = running.get(job.library, 0) + 1
        most[job.library] = max(most.get(job.library, 0), running[job.library])
        if job.version == "meet":
            async with asyncio.timeout(5):
                await both_libraries_busy.wait()  # only passes if the libraries overlap
        await asyncio.sleep(0.02)
        running[job.library] -= 1

    module = module_of(InMemoryJobRepository(), {IMPORT: work})
    async with worker_of(module, tmp_path, concurrency=3).running():
        ids = [
            (
                await module.enqueue_job(
                    EnqueueJobCommand(kind="import", library=library, version=version)
                )
            ).id
            for library, version in [
                ("/a/b", "meet"),
                ("/c/d", "meet"),
                ("/a/b", "1"),
                ("/a/b", "2"),
                ("/a/b", "3"),
            ]
        ]

        async def all_succeeded() -> bool:
            return all([await state_of(module, i) is JobState.SUCCEEDED for i in ids])

        await eventually(all_succeeded, seconds=15)

    assert most == {"/a/b": 1, "/c/d": 1}


async def test_a_job_stopped_halfway_resumes_after_its_last_completed_step(
    tmp_path: Path, eventually
) -> None:
    ran: list[str] = []
    halfway = asyncio.Event()
    checkpoints = DbosCheckpoints()

    async def batch(name: str) -> str:
        ran.append(name)
        if name == "second" and not halfway.is_set():
            halfway.set()
            await asyncio.Event().wait()  # the app stops here
        return name.upper()

    async def import_in_steps(_job: Job, progress: JobProgress) -> None:
        results = [
            await checkpoints.step(name, lambda name=name: batch(name))
            for name in ("first", "second", "third")
        ]
        await progress.report(done=len(results), total=3)

    jobs = InMemoryJobRepository()
    module = module_of(jobs, {IMPORT: import_in_steps})
    async with worker_of(module, tmp_path).running():
        queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))
        await halfway.wait()
    assert await state_of(module, queued.id) is JobState.RUNNING
    assert ran == ["first", "second"]

    async with worker_of(module_of(jobs, {IMPORT: import_in_steps}), tmp_path).running():

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)

    assert ran == ["first", "second", "second", "third"]  # "first" is not done again


async def test_a_running_job_without_a_workflow_is_cleaned_up_and_run_from_the_beginning(
    tmp_path: Path, eventually
) -> None:
    """A job the in-process worker of an earlier version left running (or a lost DBOS file)."""
    jobs = InMemoryJobRepository()
    events: list[str] = []

    async def hook(job: Job) -> None:
        events.append(f"hook at {job.done} of {job.total}")

    async def import_all(job: Job, progress: JobProgress) -> None:
        events.append(f"run from {job.done} of {job.total}")
        await progress.report(done=10, total=10)

    module = module_of(jobs, {IMPORT: import_all}, {IMPORT: hook})
    queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))
    job = await jobs.get(JobId(queued.id))
    assert job is not None
    await jobs.save(job.started(SystemClock().now()).progressed(done=4, total=10))

    async with worker_of(module, tmp_path).running():

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)

    assert events == ["hook at 4 of 10", "run from 0 of 0"]


async def test_a_job_queued_while_no_worker_ran_runs_on_the_next_start(
    tmp_path: Path, eventually
) -> None:
    async def import_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=1, total=1)

    module = module_of(InMemoryJobRepository(), {IMPORT: import_files})
    queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))
    assert await state_of(module, queued.id) is JobState.QUEUED

    async with worker_of(module, tmp_path).running():

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)


async def test_a_job_dbos_did_not_take_when_queued_is_handed_over_again(
    tmp_path: Path, eventually
) -> None:
    async def import_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=1, total=1)

    runner = FlakyQueue()
    module = module_of(InMemoryJobRepository(), {IMPORT: import_files}, runner=runner)
    async with worker_of(module, tmp_path, resubmit=0.05).running():
        queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))
        assert runner.dropped == [queued.id]

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)


async def test_the_steps_of_a_finished_job_leave_no_space_behind(
    tmp_path: Path, eventually
) -> None:
    checkpoints = DbosCheckpoints()

    async def big(name: str) -> str:
        return name * 2**20  # a few MiB of stored step results

    async def import_text(_job: Job, progress: JobProgress) -> None:
        for name in "abcd":
            await checkpoints.step(name, lambda name=name: big(name))
        await progress.report(done=1, total=1)

    module = module_of(InMemoryJobRepository(), {IMPORT: import_text})
    database = tmp_path / "jobs.sqlite"
    async with worker_of(module, tmp_path).running():
        queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))

        async def compacted() -> bool:
            done = await state_of(module, queued.id) is JobState.SUCCEEDED
            return done and database.stat().st_size < 2**20

        await eventually(compacted, seconds=15)


async def test_stopping_right_after_a_job_ended_logs_no_error(
    tmp_path: Path, caplog, eventually
) -> None:
    async def import_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=1, total=1)

    module = module_of(InMemoryJobRepository(), {IMPORT: import_files})
    with caplog.at_level(logging.ERROR):
        async with worker_of(module, tmp_path).running():
            queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))

            async def finished() -> bool:
                return await state_of(module, queued.id) is JobState.SUCCEEDED

            await eventually(finished)

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
