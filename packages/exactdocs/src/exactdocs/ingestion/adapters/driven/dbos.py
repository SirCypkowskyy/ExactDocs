"""DBOS behind ingestion's ``JobRunner`` and ``Checkpoints``: jobs as durable workflows.

Every job is one DBOS workflow, its ID the job's ID, queued on ``QUEUE`` with the library as
the partition key (the queue runs one workflow per partition at a time). ``DbosJobWorker``
(the driving adapter) registers the workflow under ``WORKFLOW`` and runs the queue; this module
only enqueues by name and records steps, so the two never import each other.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from dbos import DBOS, EnqueueOptions

from exactdocs.ingestion.models import Job

log = logging.getLogger(__name__)

QUEUE = "exactdocs-jobs"
SCHEDULE = "exactdocs-scheduled-checks"
"""The DBOS schedule that ticks the scheduled checks (the worker creates it)."""
WORKFLOW = "exactdocs.run_job"
STEPS_VERSION = "jobs-4"
"""DBOS's application version: bump it when a job's steps change (names, order or results).

``jobs-2`` added the steps of ``reprocess`` and ``retag`` (#61); ``jobs-3`` gave
``ImportedRef`` its ``origin`` and ``pinned`` (#81); ``jobs-4`` starts the import with "read
the chunking settings" and added the steps of ``rechunk`` (#67).

A workflow of another version is not resumed: its job starts over from the beginning.
"""


def enqueue_options(job_id: str, library: str) -> EnqueueOptions:
    """Return the options that queue the workflow of a job (the same ones on every start)."""
    return EnqueueOptions(
        workflow_name=WORKFLOW,
        queue_name=QUEUE,
        workflow_id=job_id,
        queue_partition_key=library,
        app_version=STEPS_VERSION,
    )


class DbosJobQueue:
    """Implements ``ports.driven.JobRunner``: queues the job's workflow in DBOS."""

    async def submit(self, job: Job) -> None:
        """Queue the workflow; a DBOS that is not running leaves the job for the next start.

        Queuing an ID that already has a workflow returns that one, so this is idempotent.
        """
        try:
            await DBOS.enqueue_workflow_with_options_async(
                enqueue_options(job.id, job.library), job.id
            )
        except Exception:  # e.g. no worker runs in this process: the job waits for one
            log.exception("job %s waits for the next start: DBOS did not take it", job.id)


class DbosCheckpoints:
    """Implements ``ports.driven.Checkpoints`` with DBOS steps of the running workflow."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Run ``run`` as a DBOS step: its result is stored and returned again on a resume.

        Outside a workflow (a job run inline by ``RunNextJob``) the step just runs.
        """
        if DBOS.workflow_id is None:
            return await run()

        # DBOS tells coroutine functions apart from plain ones by their definition, so a lambda
        # that returns an awaitable is wrapped in one.
        async def call() -> T:
            return await run()

        return await DBOS.run_step_async({"name": name}, call)


class DbosScheduleSwitch:
    """Implements ``ports.driven.ScheduleSwitch``: pauses or resumes the DBOS schedule by name.

    A paused schedule does not fire, so a server where no library has a schedule writes no tick
    workflow. The worker creates the schedule on start; until then (or in a process without
    one) there is nothing to switch, and the worker sets it from the stored schedules itself.
    """

    def __init__(self, schedule: str = SCHEDULE) -> None:
        self.schedule = schedule

    async def turn(self, *, on: bool) -> None:
        """Resume (``on``) or pause the schedule; nothing is written when it already is so."""
        try:
            found = await DBOS.get_schedule_async(self.schedule)
            if found is None or (found["status"] == "ACTIVE") == on:
                return
            change = DBOS.resume_schedule if on else DBOS.pause_schedule
            await asyncio.to_thread(change, self.schedule)
        except Exception:  # no DBOS in this process: the worker decides when it starts
            log.debug("could not switch the schedule %s", self.schedule, exc_info=True)
