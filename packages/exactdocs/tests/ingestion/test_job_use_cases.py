"""Jobs end to end through the driving ports, with the in-memory repository."""

import asyncio
from datetime import UTC, datetime

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.dtos import EnqueueJobCommand, GetJobQuery, ListLibraryJobsQuery
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    JobNotFoundError,
    NoArticlesError,
    NotAGitRepositoryError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
    UnknownJobKindError,
)
from exactdocs.ingestion.models import Job, JobId, JobState, ProblemCode
from exactdocs.ingestion.ports import JobProgress
from exactdocs.ingestion.use_cases import ListLibraryJobsUseCase
from exactdocs_kernel import InvalidCursorError, ValidationError

IMPORT = JobKind("import")


def enqueue(kind: str = "import", library: str = "/acme/payments") -> EnqueueJobCommand:
    return EnqueueJobCommand(kind=kind, library=library)


def queued(clock, job_id: str, *, kind: JobKind = IMPORT, library: str = "/a/b") -> Job:
    return Job.queued(
        job_id=JobId(job_id), kind=kind, library=library, version=None, now=clock.now()
    )


async def succeed(job: Job, progress: JobProgress) -> None:
    await progress.report(done=job.total, total=job.total)


async def test_a_job_that_finished_4_of_10_files_reports_it(build_module) -> None:
    halfway = asyncio.Event()
    release = asyncio.Event()

    async def import_ten_files(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=4, total=10)
        halfway.set()
        await release.wait()

    module = build_module({IMPORT: import_ten_files})
    waiting = await module.enqueue_job(enqueue())
    running = asyncio.create_task(module.run_next_job())
    await halfway.wait()

    seen = await module.get_job(GetJobQuery(job_id=waiting.id))

    assert (seen.state, seen.done, seen.total) == (JobState.RUNNING, 4, 10)
    release.set()
    assert await running is True
    finished = await module.get_job(GetJobQuery(job_id=waiting.id))
    assert finished.state is JobState.SUCCEEDED
    assert finished.started_at is not None
    assert finished.finished_at is not None
    assert finished.created_at < finished.started_at < finished.finished_at


async def test_skipped_files_are_listed_with_their_reason(build_module) -> None:
    async def skip_one(_job: Job, progress: JobProgress) -> None:
        await progress.problem("assets/logo.png", ProblemCode.BINARY, "binary file")

    module = build_module({IMPORT: skip_one})
    waiting = await module.enqueue_job(enqueue())

    await module.run_next_job()

    problems = (await module.get_job(GetJobQuery(job_id=waiting.id))).problems
    assert [(p.path, p.code, p.is_skip) for p in problems] == [
        ("assets/logo.png", ProblemCode.BINARY, True)
    ]


async def test_a_domain_error_fails_the_job_with_its_message(build_module) -> None:
    async def refuse(_job: Job, _progress: JobProgress) -> None:
        message = "the repository has no docs folder"
        raise ValidationError(message)

    module = build_module({IMPORT: refuse})
    waiting = await module.enqueue_job(enqueue())

    await module.run_next_job()

    failed = await module.get_job(GetJobQuery(job_id=waiting.id))
    assert (failed.state, failed.error) == (JobState.FAILED, "the repository has no docs folder")
    assert failed.error_code == "validation_error"
    assert failed.finished_at is not None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NotAGitRepositoryError(), "repo_unreachable"),
        (RepositoryUnreachableError("connection refused"), "repo_unreachable"),
        (RepositoryAuthRequiredError(), "auth_failed"),
        (CredentialsRequiredError(), "auth_failed"),
        (NoArticlesError(), "no_articles"),
    ],
)
async def test_an_import_that_meets_an_upstream_problem_records_its_code(
    build_module, error: Exception, code: str
) -> None:
    async def refuse(_job: Job, _progress: JobProgress) -> None:
        raise error

    module = build_module({IMPORT: refuse})
    waiting = await module.enqueue_job(enqueue())

    await module.run_next_job()

    failed = await module.get_job(GetJobQuery(job_id=waiting.id))
    assert (failed.state, failed.error_code, failed.error) == (JobState.FAILED, code, str(error))


async def test_an_unexpected_error_fails_the_job_without_leaking_internals(
    build_module, caplog: pytest.LogCaptureFixture
) -> None:
    async def crash(_job: Job, progress: JobProgress) -> None:
        await progress.report(done=2, total=5)
        message = "/home/me/secret/token.txt"
        raise RuntimeError(message)

    module = build_module({IMPORT: crash})
    waiting = await module.enqueue_job(enqueue())

    with caplog.at_level("ERROR"):
        await module.run_next_job()

    failed = await module.get_job(GetJobQuery(job_id=waiting.id))
    assert (failed.state, failed.error, failed.done) == (
        JobState.FAILED,
        "unexpected RuntimeError",
        2,
    )
    assert failed.error_code == "unexpected"
    assert "token.txt" in caplog.text  # the details go to the log


async def test_a_job_whose_kind_lost_its_handler_fails(clock, jobs, build_module) -> None:
    await jobs.add(queued(clock, "j1", kind=JobKind("gone")))

    await build_module().run_next_job()

    failed = await build_module().get_job(GetJobQuery(job_id="j1"))
    assert failed.state is JobState.FAILED
    assert failed.error == "no handler is registered for job kind 'gone'"


async def test_nothing_waiting_means_nothing_runs(build_module) -> None:
    assert await build_module().run_next_job() is False


async def test_a_kind_nothing_can_run_is_refused_when_queued(
    jobs: InMemoryJobRepository, build_module
) -> None:
    module = build_module({IMPORT: succeed})

    with pytest.raises(UnknownJobKindError):
        await module.enqueue_job(enqueue(kind="teleport"))

    assert jobs.jobs == {}


async def test_an_unknown_job_is_not_found(build_module) -> None:
    with pytest.raises(JobNotFoundError):
        await build_module().get_job(GetJobQuery(job_id="nope"))


async def test_a_library_lists_only_its_own_jobs_newest_first(build_module) -> None:
    module = build_module({IMPORT: succeed})
    first = await module.enqueue_job(enqueue(library="/acme/payments"))
    await module.enqueue_job(enqueue(library="/acme/ledger"))
    second = await module.enqueue_job(enqueue(library="/acme/payments"))

    listed = await module.list_library_jobs(ListLibraryJobsQuery(library="/acme/payments"))
    page = await module.list_library_jobs(ListLibraryJobsQuery(library="/acme/payments", limit=1))
    rest = await module.list_library_jobs(
        ListLibraryJobsQuery(library="/acme/payments", limit=1, cursor=page.next_cursor)
    )

    assert [job.id for job in listed.jobs] == [second.id, first.id]
    assert listed.next_cursor is None
    assert [job.id for job in page.jobs] == [second.id]
    assert [job.id for job in rest.jobs] == [first.id]
    assert rest.next_cursor is None


async def test_two_jobs_for_one_library_never_run_together(build_module) -> None:
    started: list[str] = []
    release = asyncio.Event()

    async def hold(job: Job, _progress: JobProgress) -> None:
        started.append(job.id)
        await release.wait()

    module = build_module({IMPORT: hold})
    first = await module.enqueue_job(enqueue(library="/acme/payments"))
    second = await module.enqueue_job(enqueue(library="/acme/payments"))
    other = await module.enqueue_job(enqueue(library="/acme/ledger"))

    first_slot = asyncio.create_task(module.run_next_job())
    other_slot = asyncio.create_task(module.run_next_job())
    third_slot = asyncio.create_task(module.run_next_job())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # the second job of the library waits; the other library's job takes the free slot
    assert started == [first.id, other.id]
    assert await third_slot is False
    release.set()
    assert await asyncio.gather(first_slot, other_slot) == [True, True]
    assert await module.run_next_job() is True
    assert started == [first.id, other.id, second.id]


async def test_an_interrupted_job_is_cleaned_up_then_queued_to_run_from_the_beginning(
    clock, jobs: InMemoryJobRepository, build_module
) -> None:
    calls: list[tuple[str, JobState]] = []

    async def discard_pending(job: Job) -> None:
        stored = await jobs.get(job.id)
        assert stored is not None
        calls.append((f"hook {job.id}", stored.state))

    async def import_again(job: Job, progress: JobProgress) -> None:
        calls.append((f"run {job.id} from {job.done}", job.state))
        await progress.report(done=10, total=10)

    module = build_module({IMPORT: import_again}, {IMPORT: discard_pending})
    interrupted = queued(clock, "j1").started(clock.now()).progressed(done=4, total=10)
    await jobs.add(interrupted.with_problem("x", ProblemCode.BINARY, "y"))

    await module.recover_jobs()

    requeued = await module.get_job(GetJobQuery(job_id="j1"))
    assert (requeued.state, requeued.done, requeued.total, requeued.problems) == (
        JobState.QUEUED,
        0,
        0,
        [],
    )
    assert requeued.started_at is None
    assert calls == [("hook j1", JobState.RUNNING)]  # the hook ran while the job was still running

    await module.run_next_job()

    assert calls[1] == ("run j1 from 0", JobState.RUNNING)
    assert (await module.get_job(GetJobQuery(job_id="j1"))).state is JobState.SUCCEEDED


async def test_a_kind_without_a_hook_is_just_queued_again(clock, jobs, build_module) -> None:
    await jobs.add(queued(clock, "j1").started(clock.now()))

    await build_module({IMPORT: succeed}).recover_jobs()

    assert (await jobs.get(JobId("j1"))).state is JobState.QUEUED


async def test_queued_and_finished_jobs_are_left_alone_by_recovery(
    clock, jobs: InMemoryJobRepository, build_module
) -> None:
    hooked: list[str] = []

    async def hook(job: Job) -> None:
        hooked.append(job.id)

    finished = queued(clock, "done").started(clock.now()).succeeded(clock.now())
    failed = queued(clock, "bad").started(clock.now()).failed("boom", clock.now())
    for each in (queued(clock, "waiting"), finished, failed):
        await jobs.add(each)

    await build_module(recovery_hooks={IMPORT: hook}).recover_jobs()

    assert hooked == []
    assert jobs.jobs[JobId("done")] == finished
    assert jobs.jobs[JobId("bad")] == failed


async def test_a_failing_hook_fails_its_job_and_the_others_are_still_recovered(
    clock, jobs: InMemoryJobRepository, build_module
) -> None:
    async def broken(_job: Job) -> None:
        message = "disk on fire"
        raise OSError(message)

    fragile = JobKind("fragile")
    await jobs.add(queued(clock, "a", kind=fragile, library="/a/x").started(clock.now()))
    await jobs.add(queued(clock, "b", library="/b/x").started(clock.now()))
    module = build_module({IMPORT: succeed}, {fragile: broken})

    await module.recover_jobs()

    assert jobs.jobs[JobId("a")].state is JobState.FAILED
    assert jobs.jobs[JobId("a")].error == "recovery failed: unexpected OSError"
    assert jobs.jobs[JobId("b")].state is JobState.QUEUED


class Runner:
    """A ``JobRunner`` that records what it is handed."""

    def __init__(self) -> None:
        self.submitted: list[str] = []

    async def submit(self, job: Job) -> None:
        assert job.state is JobState.QUEUED
        self.submitted.append(job.id)


async def test_a_queued_job_is_handed_to_the_runner(build_module) -> None:
    runner = Runner()

    job = await build_module({IMPORT: succeed}, runner=runner).enqueue_job(enqueue())

    assert runner.submitted == [job.id]


async def test_recovery_leaves_the_jobs_the_runner_resumes_and_submits_the_queued_ones(
    clock, jobs: InMemoryJobRepository, build_module
) -> None:
    hooked: list[str] = []

    async def hook(job: Job) -> None:
        hooked.append(job.id)

    runner = Runner()
    resumed = queued(clock, "resumed", library="/a/x").started(clock.now())
    for each in (queued(clock, "older"), resumed, queued(clock, "lost", library="/b/x")):
        await jobs.add(each)
    await jobs.save(jobs.jobs[JobId("lost")].started(clock.now()))

    await build_module({IMPORT: succeed}, {IMPORT: hook}, runner=runner).recover_jobs(
        resuming={"resumed"}
    )

    assert hooked == ["lost"]
    assert jobs.jobs[JobId("resumed")] == resumed
    assert runner.submitted == ["older", "lost"]  # oldest first


async def test_run_job_runs_a_queued_job_to_its_end(clock, jobs, build_module) -> None:
    await jobs.add(queued(clock, "j1"))

    await build_module({IMPORT: succeed}).run_job("j1")

    job = jobs.jobs[JobId("j1")]
    assert job.state is JobState.SUCCEEDED
    assert job.started_at is not None


async def test_run_job_resumes_a_running_job_after_its_hook_with_its_progress_reset(
    clock, jobs: InMemoryJobRepository, build_module
) -> None:
    calls: list[str] = []

    async def hook(job: Job) -> None:
        calls.append(f"hook at {job.done}")

    async def resume(job: Job, progress: JobProgress) -> None:
        calls.append(f"run from {job.done} with {len(job.problems)} problems")
        await progress.report(done=10, total=10)

    interrupted = queued(clock, "j1").started(clock.now()).progressed(done=4, total=10)
    await jobs.add(interrupted.with_problem("x", ProblemCode.BINARY, "y"))

    await build_module({IMPORT: resume}, {IMPORT: hook}).run_job("j1")

    assert calls == ["hook at 4", "run from 0 with 0 problems"]
    assert jobs.jobs[JobId("j1")].state is JobState.SUCCEEDED


async def test_run_job_fails_a_resumed_job_whose_hook_fails(clock, jobs, build_module) -> None:
    async def broken(_job: Job) -> None:
        message = "disk on fire"
        raise OSError(message)

    await jobs.add(queued(clock, "j1").started(clock.now()))

    await build_module({IMPORT: succeed}, {IMPORT: broken}).run_job("j1")

    assert jobs.jobs[JobId("j1")].error == "recovery failed: unexpected OSError"


@pytest.mark.parametrize("job_id", ["finished", "unknown"])
async def test_run_job_leaves_a_finished_or_unknown_job_alone(
    clock, jobs: InMemoryJobRepository, build_module, job_id: str
) -> None:
    finished = queued(clock, "finished").started(clock.now()).succeeded(clock.now())
    await jobs.add(finished)

    await build_module({IMPORT: succeed}).run_job(job_id)

    assert jobs.jobs == {JobId("finished"): finished}


class _PagesOnly(InMemoryJobRepository):
    """A repository that refuses to hand over a library's jobs except one page at a time."""

    async def list_for_library(self, library: str) -> list[Job]:
        loaded_everything = f"every job of {library} was loaded to serve one page"
        raise AssertionError(loaded_everything)


async def test_a_page_of_jobs_is_read_from_the_repository_one_page_at_a_time() -> None:
    jobs = _PagesOnly()
    for number in range(5):
        await jobs.add(
            Job.queued(
                job_id=JobId(f"job-{number}"),
                kind=IMPORT,
                library="/acme/payments",
                version=f"v{number}",
                now=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    listing = ListLibraryJobsUseCase(jobs=jobs)

    first = await listing(ListLibraryJobsQuery(library="/acme/payments", limit=2))
    second = await listing(
        ListLibraryJobsQuery(library="/acme/payments", limit=2, cursor=first.next_cursor)
    )
    last = await listing(
        ListLibraryJobsQuery(library="/acme/payments", limit=2, cursor=second.next_cursor)
    )

    assert [[job.id for job in page.jobs] for page in (first, second, last)] == [
        ["job-4", "job-3"],
        ["job-2", "job-1"],
        ["job-0"],
    ]
    assert last.next_cursor is None


async def test_a_malformed_cursor_of_the_job_list_is_refused() -> None:
    listing = ListLibraryJobsUseCase(jobs=InMemoryJobRepository())

    with pytest.raises(InvalidCursorError):
        await listing(ListLibraryJobsQuery(library="/acme/payments", cursor="!"))
