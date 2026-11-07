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
import time
from collections.abc import AsyncGenerator, Callable, Collection, Coroutine, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    closing,
    suppress,
)
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from croniter import croniter
from dbos import DBOS, DBOSConfig, WorkflowStatus

from exactdocs.ingestion.constants import EVERY_MINUTE, SCHEDULE_WORKFLOW
from exactdocs.ingestion.constants._jobs import (
    _DONE,
    _FORGET_POLL,
    _FORGET_TRIES,
    _LIVE,
    _MIN_TICK_RETENTION,
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


class SlotState(StrEnum):
    """What ``ExecutorSlots.keep`` found."""

    HELD = "held"
    """This process still holds its slot."""
    RETAKEN = "retaken"
    """The slot was lost (its connection died) and this process holds it again."""
    LOST = "lost"
    """Another process holds the slot now."""
    UNKNOWN = "unknown"
    """The database cannot be reached to tell (an outage, a failover in progress)."""


class ExecutorSlots(Protocol):
    """Gives each process sharing DBOS's database an executor ID no live process has."""

    def claim(self) -> AbstractAsyncContextManager[str]:
        """Return this process's executor ID, held until the context ends.

        Returns:
            A context manager that yields the ID; the lowest one free, so a restarted process
            usually gets the ID its predecessor had and DBOS resumes that one's workflows.
        """
        ...

    async def keep(self) -> SlotState:
        """Check that this process still holds its slot, taking it again if it was freed.

        Returns:
            Whether the slot is held, was taken again, or is lost.
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
    slot_check_interval: float = 5.0
    """With ``executors``: how often the worker checks that it still holds its slot, and looks
    for the jobs of stopped executors."""
    adopt_grace: float = 15.0
    """With ``executors``: how long a slot must stay free before its jobs are adopted, so that a
    process whose slot connection merely dropped can take it again first."""
    slot_check_timeout: float = 4.0
    """Bound on one slot check (``keep`` and the job check after a retake), well under
    ``adopt_grace - slot_check_interval``: a check that hangs counts as ``unknown``."""
    on_slot_lost: Callable[[], None] | None = None
    """Called when another process took this one's slot: the composition root stops the
    process (its jobs are then another executor's, and must not run here as well)."""
    _running: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)
    job_ids: set[str] = field(default_factory=set, init=False, repr=False)
    """The jobs this process is running now."""
    monotonic: Callable[[], float] = time.monotonic
    """The clock ``adopt_grace`` is measured with (tests pass their own)."""
    _suspects: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    """Executors whose slots were seen free, and since when (``monotonic``)."""
    _unconfirmed: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    """Since when (``monotonic``) the slot could not be confirmed, while it cannot."""
    _lost: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set once the slot is lost: no job starts here any more."""
    _refused: set[str] = field(default_factory=set, init=False, repr=False)
    """Jobs DBOS handed over after the slot was lost: queued again for another process."""
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
                await self.run_workflow(job_id)

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
            await self._recover(executor_id)
            await self._apply_schedule(tick)
            background = {
                asyncio.create_task(self._resubmit(), context=contextvars.Context()),
            }
            if executor_id is not None and self.executors is not None:
                background.add(
                    asyncio.create_task(
                        self._watch(executor_id, self.executors), context=contextvars.Context()
                    )
                )
            try:
                yield
            finally:
                await self._cancel(background)
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

    async def _watch(self, executor_id: str, executors: ExecutorSlots) -> None:
        """Every ``slot_check_interval``: keep the slot, then adopt stopped executors' jobs.

        A slot lost and taken again is fine only while no other process adopted this one's jobs
        meanwhile; otherwise, as when another process holds the slot, this process stops its
        jobs and asks to be stopped (``on_slot_lost``), so no job runs twice for long.

        Args:
            executor_id: This process's executor ID.
            executors: The slots.
        """
        while True:
            await asyncio.sleep(self.slot_check_interval)
            try:
                state = await self.check_slot(executor_id, executors)
                if state is SlotState.LOST:
                    return
                if state is SlotState.HELD:
                    await self.adopt_orphans(executor_id, executors)
            except Exception:  # the next round tries again
                log.exception("could not check executor slot %s", executor_id)

    async def check_slot(self, executor_id: str, executors: ExecutorSlots) -> SlotState:
        """Keep the slot; when it is lost, stop taking and running jobs and report it.

        A database that cannot be reached is not a lost slot: the worker waits, adopting
        nothing, and only gives up once the slot went unconfirmed for ``adopt_grace`` (another
        process may have adopted its jobs by then). A slot another process holds is lost at once.

        Args:
            executor_id: This process's executor ID.
            executors: The slots.

        Returns:
            ``held`` (go on), ``unknown`` (go on, adopt nothing) or ``lost`` (stopped).
        """
        try:
            state = await asyncio.wait_for(executors.keep(), self.slot_check_timeout)
        except TimeoutError:
            state = SlotState.UNKNOWN
        if state is SlotState.RETAKEN:
            try:
                ours = await asyncio.wait_for(
                    self._still_ours(executor_id), self.slot_check_timeout
                )
            except TimeoutError:
                ours = False
            state = SlotState.HELD if ours else SlotState.LOST
        if state is SlotState.UNKNOWN:
            since = self._unconfirmed.setdefault("since", self.monotonic())
            if self.monotonic() - since < self.adopt_grace:
                return SlotState.UNKNOWN
            state = SlotState.LOST
        self._unconfirmed.clear()
        if state is SlotState.HELD:
            return SlotState.HELD
        log.error("executor slot %s is lost: no more jobs run in this process", executor_id)
        await self._halt()
        if self.on_slot_lost is not None:
            self.on_slot_lost()
        return SlotState.LOST

    async def _halt(self) -> None:
        """Stop taking jobs first, then cancel the running ones and stop DBOS's threads.

        A job DBOS still hands over is refused (its workflow stays pending) and queued again,
        so the process that now holds this executor ID does not inherit it unnoticed.
        """
        self._lost.set()
        await self._cancel(set(self._running))
        if self._refused:
            with suppress(Exception):
                await DBOS.resume_workflows_async(sorted(self._refused), queue_name=self.queue)
        await asyncio.to_thread(DBOS.destroy)

    async def _still_ours(self, executor_id: str) -> bool:
        """Tell whether every job running here is still this executor's pending workflow.

        Args:
            executor_id: This process's executor ID.

        Returns:
            ``False`` when another process adopted one while the slot was free.
        """
        for job_id in list(self.job_ids):
            status = await DBOS.get_workflow_status_async(job_id)
            if status is None or status.status != "PENDING" or status.executor_id != executor_id:
                return False
        return True

    async def adopt_orphans(self, executor_id: str, executors: ExecutorSlots) -> None:
        """Re-queue the pending workflows of executors no live process has held for a while.

        A process that died with running jobs leaves their workflows pending under its executor
        ID. DBOS resumes them when a process starts under that ID; this covers the IDs no process
        takes again (fewer processes than before). A slot must be seen free for ``adopt_grace``
        first, so a live process whose connection dropped takes it back before anyone adopts.

        Args:
            executor_id: This process's executor ID.
            executors: The slots.
        """
        pending = await self._pending()
        others = {w.executor_id for w in pending if w.executor_id and w.executor_id != executor_id}
        async with executors.orphaned(others) as dead:
            now = self.monotonic()
            for gone in set(self._suspects) - set(dead):
                del self._suspects[gone]
            ripe = sorted(
                d for d in dead if now - self._suspects.setdefault(d, now) >= self.adopt_grace
            )
            if not ripe:
                return
            # Listed again under the dead executors' locks: no other process can adopt these now,
            # so none of them has started anywhere else since.
            stranded = [w.workflow_id for w in await self._pending(executor_ids=ripe)]
            if stranded:
                log.warning("resuming %d job(s) of stopped executors", len(stranded))
                await DBOS.resume_workflows_async(stranded, queue_name=self.queue)
            for adopted in ripe:
                del self._suspects[adopted]

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

    async def run_workflow(self, job_id: str) -> None:
        """Run the job (the workflow); a resumed workflow skips the steps it completed.

        Once the slot is lost no job starts: the workflow ends cancelled, stays pending, and
        ``_halt`` queues it again for another process.
        """
        if self._lost.is_set():
            self._refused.add(job_id)
            raise asyncio.CancelledError
        task = asyncio.current_task()
        if task is not None:
            self._running.add(task)
        self.job_ids.add(job_id)
        try:
            await self.run_job(job_id)
        finally:
            self.job_ids.discard(job_id)
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
        # With several processes the tick's workflow stays (``prune_ticks``): DBOS starts a tick
        # only if its workflow ID is new, and another process's scheduler may come late.
        if workflow_id is not None and self.executors is None:
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

    async def _recover(self, executor_id: str | None) -> None:
        """Delete ended and outdated workflows, then recover the jobs no workflow will resume.

        With several processes (``executors``), only this executor's workflows and those of
        executors no live process holds are deleted or recovered: a live process's workflows,
        of any version, are its own business (a rolling upgrade). See ``sort_workflows``.

        Args:
            executor_id: This process's executor ID, or ``None`` for the one ``local``.
        """
        workflows = await DBOS.list_workflows_async(load_input=False, load_output=False)
        if self.executors is None or executor_id is None:
            await self._recover_these(workflows, None)
            return
        others = {
            w.executor_id for w in workflows if w.executor_id and w.executor_id != executor_id
        }
        async with self.executors.orphaned(others) as dead:
            await self._recover_these(workflows, {executor_id, *dead})

    async def _recover_these(
        self, workflows: Sequence[WorkflowStatus], ours: Collection[str] | None
    ) -> None:
        """Delete the stale ones among ``workflows``, then recover the jobs of the others.

        Args:
            workflows: Every workflow DBOS has.
            ours: The executors whose workflows this process may delete; ``None`` for all.
        """
        stale, live = sort_workflows(workflows, self.version, ours, _LIVE)
        if stale:
            await DBOS.delete_workflows_async(sorted(stale))
        await self._reclaim()
        await self.recover_jobs(resuming=live)

    async def _resubmit(self) -> None:
        """Hand the queued jobs to DBOS again now and then (queuing an ID twice is a no-op).

        On PostgreSQL it also deletes the tick workflows that are old enough (``prune_ticks``).
        """
        while True:
            await asyncio.sleep(self.resubmit_interval)
            try:
                if self.executors is not None:
                    await self.prune_ticks()
                await self.submit_queued_jobs()
            except Exception:
                log.exception("could not hand the queued jobs to DBOS again")

    async def prune_ticks(self) -> None:
        """Delete the ended tick workflows older than ``tick_retention`` of the schedule."""
        before = datetime.now(UTC) - tick_retention(self.schedule)
        ended = await DBOS.list_workflows_async(
            name=SCHEDULE_WORKFLOW,
            status=sorted(_DONE),
            end_time=before.isoformat(),
            load_input=False,
            load_output=False,
        )
        if ended:
            await DBOS.delete_workflows_async([w.workflow_id for w in ended])

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


def sort_workflows(
    workflows: Sequence[WorkflowStatus],
    version: str,
    ours: Collection[str] | None,
    live_states: Collection[str],
) -> tuple[set[str], set[str]]:
    """Split the workflows a starting worker finds into the stale and the live.

    A workflow of an executor not in ``ours`` (another live process) is never stale, whatever
    its version, and is live while it is queued or running. One of ours (``None``: every
    executor is ours) is stale when it ended or another ``version`` started it.

    Args:
        workflows: Every workflow DBOS has.
        version: This build's ``STEPS_VERSION``.
        ours: The executors this process answers for, or ``None`` for all.
        live_states: The statuses of a queued or running workflow.

    Returns:
        The IDs to delete, and the IDs a workflow will resume (their jobs are left alone).
    """
    stale, live = set(), set()
    for workflow in workflows:
        mine = ours is None or workflow.executor_id in ours
        if workflow.status in live_states and (not mine or workflow.app_version == version):
            live.add(workflow.workflow_id)
        elif mine:
            stale.add(workflow.workflow_id)
    return stale, live


def tick_retention(schedule: str) -> timedelta:
    """Return how long an ended tick workflow is kept when several processes share the schedule.

    Two of the schedule's intervals (DBOS's scheduler may come up to a tenth of one late), and
    at least 10 minutes.

    Args:
        schedule: The DBOS cron expression, seconds first.

    Returns:
        The retention.
    """
    times = croniter(schedule, datetime.now(UTC), second_at_beginning=True)
    first, second = times.get_next(datetime), times.get_next(datetime)
    return max(2 * (second - first), _MIN_TICK_RETENTION)
