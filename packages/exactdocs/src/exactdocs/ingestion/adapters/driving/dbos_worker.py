"""The job worker: DBOS runs every job as a durable workflow, started in the app's lifespan.

A workflow's completed steps are stored in DBOS's own SQLite file, so a job that was running
when the process died (a crash, a deploy, ``kill -9``) resumes at its first unfinished step on
the next start instead of starting over. The queue runs at most ``concurrency`` jobs at once and
one per library (the library is the queue's partition key).
"""

import asyncio
import contextvars
import logging
import threading
from collections.abc import AsyncGenerator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from dbos import DBOS, DBOSConfig

from exactdocs.ingestion.ports.driving import RecoverJobs, RunJob

log = logging.getLogger(__name__)

# DBOS keeps one instance per process (its registry and its threads are module state), so one
# worker runs at a time per process; a second would take over the first one's workflows.
_ONE_PER_PROCESS = threading.Lock()
_WAIT_FOR_OTHER = 30.0  # seconds
_THREADS = 32  # asyncio's own default at most
_LIVE = ["ENQUEUED", "PENDING", "DELAYED"]
_DONE = frozenset({"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"})


@dataclass(frozen=True, slots=True, kw_only=True)
class DbosJobWorker:
    """Runs queued jobs through DBOS; ``RunJob`` is the workflow, so a job resumes after a crash.

    ``queue``, ``workflow`` and ``version`` must be the ones the driven adapter enqueues with
    (``adapters.driven.dbos``); the composition root passes them.
    """

    run_job: RunJob
    recover_jobs: RecoverJobs
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
    poll_interval: float = 0.05
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
        if not await asyncio.to_thread(_ONE_PER_PROCESS.acquire, timeout=_WAIT_FOR_OTHER):
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

                DBOS.workflow(name=self.workflow)(run)
                DBOS.launch()  # here, on the running loop: DBOS then runs workflows on it
                await DBOS.register_queue_async(
                    self.queue,
                    worker_concurrency=self.concurrency,
                    partition_concurrency=1,
                    polling_interval_sec=self.poll_interval,
                    on_conflict="always_update",
                )
                await self._recover()
                yield
            finally:
                await self._stop()
                await asyncio.to_thread(DBOS.destroy, destroy_registry=True)
                await self._cancel(self._running | self._forgetting)
                # DBOS shut its pool down; `asyncio.to_thread` needs one after the worker stops.
                asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(_THREADS))
        finally:
            _ONE_PER_PROCESS.release()

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

    async def _forget(self, job_id: str) -> None:
        """Delete a finished workflow (its steps hold the whole text of an import)."""
        try:
            for _ in range(200):
                status = await DBOS.get_workflow_status_async(job_id)
                if status is None:
                    return
                if status.status in _DONE:
                    await DBOS.delete_workflow_async(job_id)
                    return
                await asyncio.sleep(self.poll_interval)
        except Exception:  # the next start deletes it
            log.exception("could not delete the finished workflow of job %s", job_id)

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
        await self.recover_jobs(resuming=live)

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
