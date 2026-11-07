"""The job worker: DBOS runs every job as a durable workflow, started in the app's lifespan.

A workflow's completed steps are stored in DBOS's own SQLite file, so a job that was running
when the process died (a crash, a deploy, ``kill -9``) resumes at its first unfinished step on
the next start instead of starting over. The queue runs at most ``concurrency`` jobs at once and
one per library (the library is the queue's partition key).

A DBOS schedule (``schedule``, a cron expression with seconds) also runs ``RunScheduledChecks``
on every tick: the scheduled check of the libraries that are due (SYNC-02).
"""

import asyncio
import contextvars
import logging
import sqlite3
import threading
from collections.abc import AsyncGenerator, Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing, suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dbos import DBOS, DBOSConfig

from exactdocs.ingestion.constants import EVERY_MINUTE, SCHEDULE_WORKFLOW
from exactdocs.ingestion.constants._jobs import (
    _DONE,
    _FORGET_POLL,
    _FORGET_TRIES,
    _LIVE,
    _THREADS,
    _VACUUM_ABOVE,
    _WAIT_FOR_OTHER,
)
from exactdocs.ingestion.ports.driving import (
    RecoverJobs,
    RunJob,
    RunScheduledChecks,
    SubmitQueuedJobs,
    SwitchSchedule,
)

log = logging.getLogger(__name__)

# DBOS keeps one instance per process (its registry and its threads are module state), so one
# worker runs at a time per process; a second would take over the first one's workflows.
_one_per_process = threading.Lock()


@dataclass(frozen=True, slots=True, kw_only=True)
class DbosJobWorker:
    """Runs queued jobs through DBOS; ``RunJob`` is the workflow, so a job resumes after a crash.

    ``queue``, ``workflow`` and ``version`` must be the ones the driven adapter enqueues with
    (``adapters.driven.dbos``); the composition root passes them.
    """

    run_job: RunJob
    recover_jobs: RecoverJobs
    submit_queued_jobs: SubmitQueuedJobs
    database: Path
    """DBOS's SQLite file (its workflows and their steps)."""
    queue: str
    workflow: str
    version: str
    engine_options: Mapping[str, object] = field(default_factory=dict)
    """SQLAlchemy engine options for that file: the composition root picks ``NullPool``, so that
    a connection one of DBOS's threads still holds when it stops is closed, not left behind."""
    concurrency: int = 2
    # How long a stopping worker lets a running job finish before cancelling it.
    stop_grace: float = 1.0
    poll_interval: float = 1.0
    """How often DBOS looks for a queued job to start: an idle server only polls this often."""
    resubmit_interval: float = 30.0
    """How often queued jobs are handed to DBOS again, in case one was not taken when queued."""
    run_scheduled_checks: RunScheduledChecks | None = None
    """One tick of the libraries' scheduled checks; without it no schedule is kept."""
    switch_schedule: SwitchSchedule | None = None
    """Pauses the schedule while no library has one (an idle server then writes nothing)."""
    schedule_name: str = "exactdocs-scheduled-checks"
    """The DBOS schedule; the one ``adapters.driven.dbos.DbosScheduleSwitch`` pauses."""
    schedule: str = EVERY_MINUTE
    """When it ticks: a DBOS cron expression with seconds. Libraries are due by their interval."""
    _running: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)
    _forgetting: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Start DBOS, resume or re-queue the unfinished jobs, run them, then stop.

        On start, DBOS resumes the workflows it has (jobs that were queued or running); every
        other unfinished job is recovered (``RecoverJobs``: its hook runs, then it is queued
        again from the beginning) and submitted. Workflows that ended, or that another
        ``version`` started, are deleted first. Stopping lets running jobs finish for
        ``stop_grace`` seconds, then cancels them: a cancelled job stays ``running`` and its
        workflow pending, so the next start resumes it.
        """
        # A worker that is still stopping (a server in another thread) is waited for.
        if not await asyncio.to_thread(_one_per_process.acquire, timeout=_WAIT_FOR_OTHER):
            message = "a DBOS job worker is already running in this process"
            raise RuntimeError(message)
        try:
            DBOS(
                config=DBOSConfig(
                    name="exactdocs",
                    system_database_url=f"sqlite:///{self.database}",
                    application_version=self.version,
                    db_engine_kwargs=dict(self.engine_options),
                    log_level="WARNING",
                    notification_listener_polling_interval_sec=self.poll_interval,
                    # DBOS makes its pool the loop's default executor (`asyncio.to_thread`); a
                    # workflow holds one of its threads while it runs.
                    max_executor_threads=_THREADS + self.concurrency,
                )
            )
            try:

                async def run(job_id: str) -> None:  # DBOS wraps functions, not bound methods
                    await self._run(job_id)

                async def tick(scheduled_at: datetime, context: object) -> None:
                    del scheduled_at, context
                    await self._tick()

                DBOS.workflow(name=self.workflow)(run)
                DBOS.workflow(name=SCHEDULE_WORKFLOW)(tick)
                DBOS.launch()  # here, on the running loop: DBOS then runs workflows on it
                await DBOS.register_queue_async(
                    self.queue,
                    worker_concurrency=self.concurrency,
                    partition_concurrency=1,
                    polling_interval_sec=self.poll_interval,
                    on_conflict="always_update",
                )
                await self._recover()
                await self._apply_schedule(tick)
                resubmit = asyncio.create_task(self._resubmit(), context=contextvars.Context())
                try:
                    yield
                finally:
                    await self._cancel({resubmit})
            finally:
                await self._stop()
                await self._cancel(self._forgetting)  # the next start deletes what they had left
                await asyncio.to_thread(DBOS.destroy, destroy_registry=True)
                await self._cancel(self._running | self._forgetting)
                # DBOS shut its pool down; `asyncio.to_thread` needs one after the worker stops.
                asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(_THREADS))
        finally:
            _one_per_process.release()

    async def _run(self, job_id: str) -> None:
        """Run the job (the workflow); a resumed workflow skips the steps it completed."""
        task = asyncio.current_task()
        if task is not None:
            self._running.add(task)
        try:
            await self.run_job(job_id)
        finally:
            if task is not None:
                self._running.discard(task)
        # Outside the workflow's context: DBOS would take its calls for steps of the job.
        forget = asyncio.get_running_loop().create_task(
            self._forget(job_id), context=contextvars.Context()
        )
        self._forgetting.add(forget)
        forget.add_done_callback(self._forgetting.discard)

    async def _apply_schedule(
        self, tick: Callable[[datetime, object], Coroutine[object, object, None]]
    ) -> None:
        """Keep the DBOS schedule in line with ``run_scheduled_checks`` and ``schedule``."""
        if self.run_scheduled_checks is None:
            await DBOS.delete_schedule_async(self.schedule_name)
            return
        await DBOS.apply_schedules_async(
            [{"schedule_name": self.schedule_name, "workflow_fn": tick, "schedule": self.schedule}]
        )
        if self.switch_schedule is not None:
            await self.switch_schedule()  # paused again at once while no library has one

    async def _tick(self) -> None:
        """Run one tick (the scheduled workflow), then delete its workflow.

        The checks run outside the workflow's context: the jobs they queue are workflows of
        their own, not steps of this one, and a tick needs no durability (the next one checks
        whatever this one did not).
        """
        if self.run_scheduled_checks is None:
            return
        task = asyncio.current_task()
        if task is not None:
            self._running.add(task)
        workflow_id = DBOS.workflow_id
        try:
            await asyncio.get_running_loop().create_task(
                self._check(self.run_scheduled_checks), context=contextvars.Context()
            )
        finally:
            if task is not None:
                self._running.discard(task)
        if workflow_id is not None:
            forget = asyncio.get_running_loop().create_task(
                self._forget(workflow_id), context=contextvars.Context()
            )
            self._forgetting.add(forget)
            forget.add_done_callback(self._forgetting.discard)

    @staticmethod
    async def _check(run_scheduled_checks: RunScheduledChecks) -> None:
        try:
            await run_scheduled_checks()
        except Exception:  # the next tick tries again
            log.exception("the scheduled checks failed")

    async def _forget(self, job_id: str) -> None:
        """Delete a finished workflow (its steps hold the whole text of an import).

        Once no workflow is left, the file is compacted: deleted steps only free pages.
        """
        try:
            ended = await self._ended(job_id)
            if ended:
                await DBOS.delete_workflow_async(job_id)
        except Exception:  # the next start deletes it
            log.exception("could not delete the finished workflow of job %s", job_id)
        else:
            if ended:
                await self._reclaim()

    @staticmethod
    async def _ended(job_id: str) -> bool:
        """Wait until DBOS has recorded the end of the workflow; ``False`` if it never does."""
        for _ in range(_FORGET_TRIES):
            status = await DBOS.get_workflow_status_async(job_id)
            if status is None:
                return False
            if status.status in _DONE:
                return True
            await asyncio.sleep(_FORGET_POLL)
        return False

    async def _recover(self) -> None:
        workflows = await DBOS.list_workflows_async(load_input=False, load_output=False)
        live = {
            workflow.workflow_id
            for workflow in workflows
            if workflow.status in _LIVE and workflow.app_version == self.version
        }
        stale = [workflow.workflow_id for workflow in workflows if workflow.workflow_id not in live]
        if stale:
            await DBOS.delete_workflows_async(stale)
        await self._reclaim()
        await self.recover_jobs(resuming=live)

    async def _resubmit(self) -> None:
        """Hand the queued jobs to DBOS again now and then (queuing an ID twice is a no-op)."""
        while True:
            await asyncio.sleep(self.resubmit_interval)
            try:
                await self.submit_queued_jobs()
            except Exception:
                log.exception("could not hand the queued jobs to DBOS again")

    async def _reclaim(self) -> None:
        """Give the free pages of DBOS's file back (``VACUUM``) when no workflow is left in it."""
        try:
            if await DBOS.list_workflows_async(load_input=False, load_output=False, limit=1):
                return
            await asyncio.to_thread(_vacuum, self.database)
        except Exception:  # only space: tried again after the next job
            log.exception("could not compact %s", self.database)

    async def _stop(self) -> None:
        if self._running:
            _, busy = await asyncio.wait(self._running, timeout=self.stop_grace)
            await self._cancel(busy)

    @staticmethod
    async def _cancel(tasks: set[asyncio.Task[None]]) -> None:
        for task in tasks:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)


def _vacuum(database: Path) -> None:
    """``VACUUM`` the file when at least half of it (and 1 MiB) is free pages."""
    with closing(sqlite3.connect(database, timeout=30, isolation_level=None)) as connection:
        free = connection.execute("PRAGMA freelist_count").fetchone()[0]
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
        if free * 2 >= pages and free * size >= _VACUUM_ABOVE:
            connection.execute("VACUUM")
