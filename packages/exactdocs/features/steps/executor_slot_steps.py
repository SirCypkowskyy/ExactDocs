"""Steps for executor slots: a real job worker (DBOS on SQLite) whose slot is lost while it starts.

The slot is a stand-in: from the moment its connection dies, its check cannot reach the database
(``unknown``), as during an outage or a failover. ``tests/bootstrap/test_postgres.py`` runs the
PostgreSQL slots themselves.
"""

import asyncio
import tempfile
import time
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from sqlalchemy import NullPool

from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker, SlotState

# Short production-shaped timings: given up 3 s after the last confirmed hold, and stopped by
# 3 + 1 + 0.5 + 2 = 6.5 s, under the 8 s a slot must stay free before its jobs are adopted.
GIVE_UP, INTERVAL, CHECK_TIMEOUT, HALT, ADOPT_GRACE, CLAIM_GRACE = 3.0, 1.0, 0.5, 2.0, 8.0, 4.0
STARTUP = 5.0
"""How long the startup takes after DBOS launched: longer than the give-up time."""
DEADLINE = 20.0


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
    slot: DyingSlot = context.slot

    async def slow_startup(**_: object) -> None:
        slot.dead = True
        await asyncio.sleep(STARTUP)
        context.startup_ended = time.monotonic()

    context.recover_jobs = slow_startup


@when("the watcher starts")
def step_watcher_starts(context: Context) -> None:
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
        async with worker.running(), asyncio.timeout(DEADLINE):
            await stopping.wait()

    asyncio.run(run())


@then("the give-up clock counts from the claim")
def step_clock_from_claim(context: Context) -> None:
    # Unconfirmed since the claim for longer than the give-up time: the watcher's first check
    # gives it up, rather than a whole give-up time after the watcher started.
    waited = context.stopped_at - context.startup_ended
    assert waited < GIVE_UP, f"stopped {waited:.1f} s after the startup ended"


@then("the process stops before another process may adopt slot {slot:d}'s jobs")
def step_stops_before_adoption(context: Context, slot: int) -> None:
    assert context.slot.executor_id == f"exactdocs-{slot}"
    since_claim = context.stopped_at - context.slot.claimed_at
    assert since_claim < ADOPT_GRACE, f"stopped {since_claim:.1f} s after the claim"
