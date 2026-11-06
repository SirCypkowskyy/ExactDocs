"""DBOS behind ingestion's ``JobRunner`` and ``Checkpoints``: jobs as durable workflows.

Every job is one DBOS workflow, its ID the job's ID, queued on ``QUEUE`` with the library as
the partition key (the queue runs one workflow per partition at a time). ``DbosJobWorker``
(the driving adapter) registers the workflow under ``WORKFLOW`` and runs the queue; this module
only enqueues by name and records steps, so the two never import each other.
"""

import logging
from collections.abc import Awaitable, Callable

from dbos import DBOS, EnqueueOptions

from exactdocs.ingestion.models import Job

log = logging.getLogger(__name__)

QUEUE = "exactdocs-jobs"
WORKFLOW = "exactdocs.run_job"
STEPS_VERSION = "jobs-3"
"""DBOS's application version: bump it when a job's steps change (names, order or results).

``jobs-2`` added the steps of ``reprocess`` and ``retag`` (#61). ``jobs-3`` starts the import
with "read the chunking settings" and added the steps of ``rechunk`` (#67).

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
