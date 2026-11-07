"""The job worker: DBOS runs every job as a durable workflow, started in the app's lifespan.

A workflow's completed steps are stored in DBOS's system database (its own SQLite file, or a
schema of the app's PostgreSQL database), so a job that was running when the process died (a
crash, a deploy, ``kill -9``) resumes at its first unfinished step on the next start instead of
starting over. The queue runs at most ``concurrency`` jobs at once per process and one per
library across every process (the library is the queue's partition key).

On PostgreSQL several processes share the queue. Each runs DBOS under an executor ID of its own
(``executors``), and a process adopts the pending workflows of executors no live process holds,
at start and then every ``resubmit_interval``.

A DBOS schedule (``schedule``, a cron expression with seconds) also runs ``RunScheduledChecks``
on every tick: the scheduled check of the libraries that are due (SYNC-02).
"""

import asyncio
import contextvars
import logging
import sqlite3
import threading
from collections.abc import AsyncGenerator, Callable, Collection, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    closing,
    suppress,
)
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from dbos import DBOS, DBOSConfig, WorkflowStatus

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


class ExecutorSlots(Protocol):
    """Gives each process sharing DBOS's database an executor ID no live process has."""

    def claim(self) -> AbstractAsyncContextManager[str]:
        """Return this process's executor ID, held until the context ends.

        Returns:
            A context manager that yields the ID; the lowest one free, so a restarted process
            usually gets the ID its predecessor had and DBOS resumes that one's workflows.
        """
        ...

    def orphaned(
        self, executor_ids: Collection[str]
    ) -> AbstractAsyncContextManager[Collection[str]]:
        """Return those of the IDs no live process holds, held by this one while the context runs.

        Args:
            executor_ids: Executors that have pending workflows.

        Returns:
            A context manager that yields the IDs of dead executors.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class DbosJobWorker:
    """Runs queued jobs through DBOS; ``RunJob`` is the workflow, so a job resumes after a crash.

    ``queue``, ``workflow`` and ``version`` must be the ones the driven adapter enqueues with
    (``adapters.driven.dbos``); the composition root passes them.
    """

    run_job: RunJob
    recover_jobs: RecoverJobs
    submit_queued_jobs: SubmitQueuedJobs
    database: Path | None = None
    """DBOS's SQLite file (its workflows and their steps), unless ``system_database_url`` is set."""
    system_database_url: str | None = None
    """A PostgreSQL database for DBOS's tables instead of the file: the app's own database."""
    system_schema: str = "dbos"
    """With ``system_database_url``: the schema DBOS keeps its tables in."""
    executors: ExecutorSlots | None = None
    """With ``system_database_url``: the executor IDs of the processes sharing the queue. Without,
    the process is DBOS's one ``local`` executor."""
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
            async with AsyncExitStack() as stack:
                executor_id = None
                if self.executors is not None:
                    executor_id = await stack.enter_async_context(self.executors.claim())
                async with self._dbos(executor_id):
                    yield
        finally:
            _one_per_process.release()

    @asynccontextmanager
    async def _dbos(self, executor_id: str | None) -> AsyncGenerator[None]:
        """Configure and launch DBOS, recover, run, then stop and destroy it.

        Args:
            executor_id: This process's executor ID; ``None`` keeps DBOS's ``local``.

        Yields:
            Nothing, while jobs run.
        """
        DBOS(config=self._config(executor_id))
        try:

            async def run(job_id: str) -> None:
                """Run one job: the workflow (DBOS wraps functions, not bound methods).

                Args:
                    job_id: The job's ID, also the workflow's.
                """
                await self._run(job_id)

            async def tick(scheduled_at: datetime, context: object) -> None:
                """Run one tick of the scheduled checks: the schedule's workflow.

                Args:
                    scheduled_at: When the tick was due (unused: the clock decides).
                    context: DBOS's schedule context (unused).
                """
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
            await self._adopt_orphans(executor_id)
            await self._recover()
            await self._apply_schedule(tick)
            resubmit = asyncio.create_task(
                self._resubmit(executor_id), context=contextvars.Context()
            )
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

    def _config(self, executor_id: str | None) -> DBOSConfig:
        """Return DBOS's configuration: its system database, executor and limits.

        Args:
            executor_id: This process's executor ID, or ``None``.

        Returns:
            The configuration.
        """
        config = DBOSConfig(
            name="exactdocs",
            system_database_url=self.system_database_url or f"sqlite:///{self.database}",
            application_version=self.version,
            db_engine_kwargs=dict(self.engine_options),
            log_level="WARNING",
            notification_listener_polling_interval_sec=self.poll_interval,
            # DBOS makes its pool the loop's default executor (`asyncio.to_thread`); a
            # workflow holds one of its threads while it runs.
            max_executor_threads=_THREADS + self.concurrency,
        )
        if self.system_database_url is not None:
            config["dbos_system_schema"] = self.system_schema
        if executor_id is not None:
            config["executor_id"] = executor_id
        return config

    async def _adopt_orphans(self, executor_id: str | None) -> None:
        """Re-queue the pending workflows of executors no live process holds any more.

        A process that died with running jobs leaves their workflows pending under its executor
        ID. DBOS resumes them when a process starts under that ID; this covers the IDs no process
        took again (fewer processes than before). Re-queuing a workflow is idempotent, and only
        dead executors' are touched, so a live process's jobs never run twice.

        Args:
            executor_id: This process's executor ID; ``None`` (one process) adopts nothing.
        """
        if self.executors is None or executor_id is None:
            return
        pending = await self._pending()
        others = {w.executor_id for w in pending if w.executor_id and w.executor_id != executor_id}
        if not others:
            return
        async with self.executors.orphaned(others) as dead:
            if not dead:
                return
            # Listed again under the dead executors' locks: no other process can adopt these now,
            # so none of them has started anywhere else since.
            stranded = [w.workflow_id for w in await self._pending(executor_ids=sorted(dead))]
            if stranded:
                log.warning("resuming %d job(s) of stopped executors", len(stranded))
                await DBOS.resume_workflows_async(stranded, queue_name=self.queue)

    async def _pending(self, *, executor_ids: list[str] | None = None) -> list[WorkflowStatus]:
        """Return the pending job workflows of this version, of some executors or of all.

        Args:
            executor_ids: Only these executors' workflows; ``None`` for every executor's.

        Returns:
            Their statuses.
        """
        return await DBOS.list_workflows_async(
            status="PENDING",
            name=self.workflow,
            app_version=self.version,
            executor_id=executor_ids,
            load_input=False,
            load_output=False,
        )

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

    async def _resubmit(self, executor_id: str | None) -> None:
        """Hand the queued jobs to DBOS again now and then (queuing an ID twice is a no-op).

        Args:
            executor_id: This process's executor ID: stopped executors' jobs are adopted too.
        """
        while True:
            await asyncio.sleep(self.resubmit_interval)
            try:
                await self._adopt_orphans(executor_id)
                await self.submit_queued_jobs()
            except Exception:
                log.exception("could not hand the queued jobs to DBOS again")

    async def _reclaim(self) -> None:
        """Give the free pages of DBOS's file back (``VACUUM``) when no workflow is left in it.

        PostgreSQL reclaims space itself (autovacuum): nothing to do there.
        """
        if self.database is None or self.system_database_url is not None:
            return
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
