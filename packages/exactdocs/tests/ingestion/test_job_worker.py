import asyncio
from collections.abc import Callable

from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driving.worker import JobWorker
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery
from exactdocs.ingestion.models import Job, JobKind, JobState
from exactdocs.ingestion.ports import JobProgress

IMPORT = JobKind("import")


def worker_of(module: IngestionModule, concurrency: int = 2) -> JobWorker:
    return JobWorker(
        stop_grace=0.05,
        recover_jobs=module.recover_jobs,
        run_next_job=module.run_next_job,
        concurrency=concurrency,
        poll_interval=0.01,
    )


async def state_of(module: IngestionModule, job_id: str) -> JobState:
    return (await module.get_job(GetJobQuery(job_id=job_id))).state


async def test_queued_jobs_run_in_the_background_to_the_end(
    build_module: Callable[..., IngestionModule], eventually
) -> None:
    async def import_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=3, total=3)

    module = build_module({IMPORT: import_files})

    async with worker_of(module).running():
        queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))

        async def finished() -> bool:
            return await state_of(module, queued.id) is JobState.SUCCEEDED

        await eventually(finished)


async def test_jobs_of_one_library_never_overlap_but_other_libraries_run_alongside(
    build_module: Callable[..., IngestionModule], eventually
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

    module = build_module({IMPORT: work})
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

    async with worker_of(module, concurrency=3).running():

        async def all_succeeded() -> bool:
            return all([await state_of(module, i) is JobState.SUCCEEDED for i in ids])

        await eventually(all_succeeded)

    assert most == {"/a/b": 1, "/c/d": 1}


async def test_stopping_the_worker_leaves_a_running_job_running(
    build_module: Callable[..., IngestionModule],
) -> None:
    started = asyncio.Event()

    async def hang(_job: Job, _progress: JobProgress) -> None:
        started.set()
        await asyncio.Event().wait()

    module = build_module({IMPORT: hang})
    queued = await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))

    async with worker_of(module).running():
        await started.wait()

    assert await state_of(module, queued.id) is JobState.RUNNING


async def test_an_error_in_the_repository_does_not_stop_the_worker(
    build_module: Callable[..., IngestionModule], eventually
) -> None:
    calls = 0

    async def run_next_job() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            message = "database is locked"
            raise OSError(message)
        return False

    worker = JobWorker(
        recover_jobs=build_module().recover_jobs,
        run_next_job=run_next_job,
        concurrency=1,
        poll_interval=0.01,
    )

    async with worker.running():

        async def tried_again() -> bool:
            return calls >= 2

        await eventually(tried_again)
