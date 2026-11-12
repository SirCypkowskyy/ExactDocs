"""Steps for executor slots: a real job worker (DBOS on SQLite) whose slot is lost while it starts.

The slot is a stand-in: from the moment its connection dies, its check cannot reach the database
(``unknown``), as during an outage or a failover. ``tests/bootstrap/test_postgres.py`` runs the
PostgreSQL slots themselves.
"""

import asyncio
import tempfile
import time
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when
from behave.runner import Context
from dbos import DBOS
from sqlalchemy import NullPool

from exactdocs.ingestion.adapters.driven.dbos import enqueue_options
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker, SlotState
from exactdocs.ingestion.constants import QUEUE, STEPS_VERSION, WORKFLOW

# Short production-shaped timings: given up 3 s after the last confirmed hold, and stopped by
# 3 + 1 + 0.5 + 2 = 6.5 s, under the 10 s a slot must stay free before its jobs are adopted.
GIVE_UP, INTERVAL, CHECK_TIMEOUT, HALT, ADOPT_GRACE, CLAIM_GRACE = 3.0, 1.0, 0.5, 2.0, 10.0, 4.0
STOP_BY = GIVE_UP + INTERVAL + CHECK_TIMEOUT + HALT
DEADLINE = 30.0


class DyingSlot:
    """One executor slot whose connection can die; it records when it was claimed."""

    claim_grace = CLAIM_GRACE

    def __init__(self, slot: int) -> None:
        self.executor_id = f"exactdocs-{slot}"
        self.claimed_at: float | None = None
        self.dead = False

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        self.claimed_at = time.monotonic()
        yield self.executor_id

    async def keep(self) -> SlotState:
        return SlotState.UNKNOWN if self.dead else SlotState.HELD

    def die(self) -> None:
        self.dead = True

    @asynccontextmanager
    async def orphaned(self, executor_ids: Collection[str]) -> AsyncGenerator[Collection[str]]:
        del executor_ids
        yield []


async def _nothing(*_: object, **__: object) -> None:
    return None


@given("a process claims executor slot {slot:d}")
def step_claims_slot(context: Context, slot: int) -> None:
    context.slot = DyingSlot(slot)


@given("its slot connection dies while DBOS is still starting")
def step_slot_dies_while_starting(context: Context) -> None:
    context.dies_in_startup = context.slot.die


@given("the startup takes longer than other processes wait before adopting slot {slot:d}'s jobs")
def step_startup_outlasts_adoption(context: Context, slot: int) -> None:
    assert context.slot.executor_id == f"exactdocs-{slot}"
    context.startup_ended = None

    async def slow_recovery(**_: object) -> None:  # the startup's recovery, after DBOS launched
        context.dies_in_startup()
        await asyncio.sleep(ADOPT_GRACE + 2)
        context.startup_ended = time.monotonic()

    context.recover_jobs = slow_recovery


@when("the worker starts")
def step_worker_starts(context: Context) -> None:
    slot: DyingSlot = context.slot
    stack_dir = tempfile.TemporaryDirectory(prefix="exactdocs-slots-")
    context.add_cleanup(stack_dir.cleanup)
    context.stopped_at = None
    stopping = asyncio.Event()

    def stopped() -> None:  # the composition root would stop the process
        context.stopped_at = time.monotonic()
        stopping.set()

    worker = DbosJobWorker(
        run_job=_nothing,
        recover_jobs=context.recover_jobs,
        submit_queued_jobs=_nothing,
        database=Path(stack_dir.name) / "jobs.sqlite",
        engine_options={"poolclass": NullPool},
        executors=slot,
        queue="q",
        workflow="w",
        version="v1",
        slot_give_up=GIVE_UP,
        slot_check_interval=INTERVAL,
        slot_check_timeout=CHECK_TIMEOUT,
        halt_timeout=HALT,
        adopt_grace=ADOPT_GRACE,
        on_slot_lost=stopped,
    )

    async def run() -> None:
        async with asyncio.timeout(DEADLINE):
            try:
                async with worker.running():
                    await stopping.wait()
            except RuntimeError as error:  # the startup fails: the slot was lost meanwhile
                context.start_failure = error

    context.start_failure = None
    asyncio.run(run())


@then("the process stops while it is still starting")
def step_stops_while_starting(context: Context) -> None:
    # The watchdog runs from DBOS's launch on, through the recovery, not only after it.
    assert context.stopped_at is not None, "the process was never stopped"
    assert context.startup_ended is None, "the startup ran to its end"
    assert context.start_failure is not None, "the worker started after its slot was lost"


@then("the process stops before another process may adopt slot {slot:d}'s jobs")
def step_stops_before_adoption(context: Context, slot: int) -> None:
    assert context.slot.executor_id == f"exactdocs-{slot}"
    since_claim = context.stopped_at - context.slot.claimed_at
    # Given up GIVE_UP after the claim (the last confirmed hold), at a check, then halted.
    assert since_claim < STOP_BY, f"stopped {since_claim:.1f} s after the claim"
    assert since_claim < ADOPT_GRACE


class TakenSlot:
    """Executor slot 1, held until another process takes it; it records when that was seen."""

    claim_grace = CLAIM_GRACE

    def __init__(self, slot: int) -> None:
        self.executor_id = f"exactdocs-{slot}"
        self.taken_at: float | None = None
        self.lost_seen_at: float | None = None

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        yield self.executor_id

    async def keep(self) -> SlotState:
        if self.taken_at is None:
            return SlotState.HELD
        if self.lost_seen_at is None:
            self.lost_seen_at = time.monotonic()
        return SlotState.LOST

    def take(self) -> None:
        self.taken_at = time.monotonic()

    @asynccontextmanager
    async def orphaned(self, executor_ids: Collection[str]) -> AsyncGenerator[Collection[str]]:
        del executor_ids
        yield []


# The job keeps going this long once cancelled: past the halt, and past the newcomer's wait.
SLOW_TO_CANCEL = CLAIM_GRACE + 2


@given(
    "a process holds executor slot {slot:d} and runs a job that takes long to react to cancellation"
)
def step_holds_slot_with_slow_job(context: Context, slot: int) -> None:
    context.slot = TakenSlot(slot)
    context.job_started = None
    context.step_ran_at = None

    async def record_step() -> None:
        context.step_ran_at = time.monotonic()

    async def slow_to_cancel(job_id: str) -> None:  # the job, run by DBOS as a workflow
        del job_id
        context.job_started.set()
        try:
            await asyncio.sleep(DEADLINE)
        except asyncio.CancelledError:
            until = time.monotonic() + SLOW_TO_CANCEL
            while (left := until - time.monotonic()) > 0:  # cancelled again: still cleaning up
                with suppress(asyncio.CancelledError):
                    await asyncio.sleep(left)
            # Then the job's next step: DBOS records it only if it still runs this executor.
            with suppress(Exception):
                await DBOS.run_step_async({"name": "after the cleanup"}, record_step)
            raise

    context.run_job = slow_to_cancel


@when("another process takes slot {slot:d}")
def step_another_process_takes_slot(context: Context, slot: int) -> None:
    slot_: TakenSlot = context.slot
    assert slot_.executor_id == f"exactdocs-{slot}"
    stack_dir = tempfile.TemporaryDirectory(prefix="exactdocs-slots-")
    context.add_cleanup(stack_dir.cleanup)
    context.stopped_at = None
    context.destroyed_at = None
    stopping = asyncio.Event()

    def stopped() -> None:  # the composition root would stop the process
        context.stopped_at = time.monotonic()
        stopping.set()

    destroy = DBOS.destroy

    def recording_destroy(**options: bool) -> None:  # DBOS's own stop, timed
        context.destroyed_at = time.monotonic()
        destroy(**options)

    recording = patch.object(DBOS, "destroy", recording_destroy)
    recording.start()
    context.add_cleanup(recording.stop)
    worker = DbosJobWorker(
        run_job=context.run_job,
        recover_jobs=_nothing,
        submit_queued_jobs=_nothing,
        database=Path(stack_dir.name) / "jobs.sqlite",
        engine_options={"poolclass": NullPool},
        executors=slot_,
        queue=QUEUE,
        workflow=WORKFLOW,
        version=STEPS_VERSION,
        poll_interval=0.02,
        stop_grace=0.05,
        slot_give_up=GIVE_UP,
        slot_check_interval=INTERVAL,
        slot_check_timeout=CHECK_TIMEOUT,
        halt_timeout=HALT,
        adopt_grace=ADOPT_GRACE,
        on_slot_lost=stopped,
    )

    async def run() -> None:
        context.job_started = asyncio.Event()
        async with asyncio.timeout(DEADLINE), worker.running():
            await DBOS.enqueue_workflow_with_options_async(
                enqueue_options("job-1", "/a/b"), "job-1"
            )
            await context.job_started.wait()
            slot_.take()
            await stopping.wait()

    asyncio.run(run())


@then(
    "the process stops taking jobs and stops DBOS within halt_timeout of the check that found "
    "the slot lost"
)
def step_stops_dbos_within_halt_timeout(context: Context) -> None:
    lost_seen_at = context.slot.lost_seen_at
    assert lost_seen_at is not None, "no check found the slot lost"
    assert context.destroyed_at is not None, "DBOS was never stopped"
    took = context.destroyed_at - lost_seen_at
    assert took < HALT, f"DBOS was stopped {took:.1f} s after the slot was found lost"


@then("it asks to be stopped within that time")
def step_asks_to_stop_within_halt_timeout(context: Context) -> None:
    assert context.stopped_at is not None, "the process was never stopped"
    took = context.stopped_at - context.slot.lost_seen_at
    assert took < HALT + CHECK_TIMEOUT, f"asked to stop {took:.1f} s after the slot was lost"


@then(
    "no job of slot {slot:d} runs in it after another process may resume or adopt the slot's jobs"
)
def step_no_job_after_resume(context: Context, slot: int) -> None:
    slot_: TakenSlot = context.slot
    assert slot_.executor_id == f"exactdocs-{slot}"
    assert slot_.taken_at is not None
    resumable_at = slot_.taken_at + CLAIM_GRACE  # the newcomer's DBOS resumes the slot's jobs
    assert context.stopped_at < resumable_at, "the process still ran when the jobs were resumed"
    assert context.destroyed_at < resumable_at, "DBOS still ran when the jobs were resumed"
    ran = context.step_ran_at
    assert ran is None or ran < resumable_at, "the job took a step after its jobs were resumed"
