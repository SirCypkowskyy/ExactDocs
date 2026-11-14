"""DBOS behind ingestion's ``JobRunner`` and ``Checkpoints``: jobs as durable workflows.

Every job is one DBOS workflow, its ID the job's ID, queued on ``QUEUE`` with the library as
the partition key (the queue runs one workflow per partition at a time). ``DbosJobWorker``
(the driving adapter) registers the workflow under ``WORKFLOW`` and runs the queue; this module
only enqueues by name and records steps, so the two never import each other.
"""

import asyncio
import contextvars
import logging
from collections.abc import Awaitable, Callable

from dbos import DBOS, EnqueueOptions

from exactdocs.ingestion.constants import QUEUE, SCHEDULE, STEPS_VERSION, WORKFLOW
from exactdocs.ingestion.models import Job

log = logging.getLogger(__name__)


def enqueue_options(job_id: str, library: str) -> EnqueueOptions:
    """Return the options that queue the workflow of a job (the same ones on every start).

    Args:
        job_id: The job's ID, used as the workflow's ID.
        library: The job's library, the queue's partition key.

    Returns:
        The options naming ``WORKFLOW``, ``QUEUE`` and the steps version.
    """
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

        Queuing an ID that already has a workflow returns that one, so this is idempotent. It
        is queued outside the context of any running workflow: a job that queues another (an
        import queuing ``embed`` jobs) gets a workflow of its own, not a child step.

        Args:
            job: The job to run.
        """
        try:
            await asyncio.get_running_loop().create_task(
                DBOS.enqueue_workflow_with_options_async(
                    enqueue_options(job.id, job.library), job.id
                ),
                context=contextvars.Context(),
            )
        except Exception:  # e.g. no worker runs in this process: the job waits for one
            log.exception("job %s waits for the next start: DBOS did not take it", job.id)


class DbosCheckpoints:
    """Implements ``ports.driven.Checkpoints`` with DBOS steps of the running workflow."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Run ``run`` as a DBOS step: its result is stored and returned again on a resume.

        Outside a workflow (a job run inline by ``RunNextJob``) the step just runs.

        Args:
            name: The step's name in the workflow's history.
            run: Runs the step.

        Returns:
            What ``run`` returned, or the stored result on a resume.
        """
        if DBOS.workflow_id is None:
            return await run()

        # DBOS tells coroutine functions apart from plain ones by their definition, so a lambda
        # that returns an awaitable is wrapped in one.
        async def call() -> T:
            """Await ``run`` from a coroutine function DBOS recognizes as one.

            Returns:
                What ``run`` returned.
            """
            return await run()

        return await DBOS.run_step_async({"name": name}, call)


class DbosScheduleSwitch:
    """Implements ``ports.driven.ScheduleSwitch``: pauses or resumes the DBOS schedule by name.

    A paused schedule does not fire, so a server where no library has a schedule writes no tick
    workflow. The worker creates the schedule on start; until then (or in a process without
    one) there is nothing to switch, and the worker sets it from the stored schedules itself.
    """

    def __init__(self, schedule: str = SCHEDULE) -> None:
        """Switch one schedule.

        Args:
            schedule: The DBOS schedule's name.
        """
        self.schedule = schedule

    async def turn(self, *, on: bool) -> None:
        """Resume (``on``) or pause the schedule; nothing is written when it already is so.

        Args:
            on: True resumes the schedule, False pauses it.
        """
        try:
            found = await DBOS.get_schedule_async(self.schedule)
            if found is None or (found["status"] == "ACTIVE") == on:
                return
            change = DBOS.resume_schedule if on else DBOS.pause_schedule
            await asyncio.to_thread(change, self.schedule)
        except Exception:  # no DBOS in this process: the worker decides when it starts
            log.debug("could not switch the schedule %s", self.schedule, exc_info=True)
