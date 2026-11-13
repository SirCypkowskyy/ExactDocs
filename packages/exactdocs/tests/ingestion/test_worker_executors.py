"""The job worker with several processes on one database (PostgreSQL): what it decides alone.

DBOS's class methods are replaced by fakes here; ``tests/bootstrap/test_postgres.py`` runs the
same paths against a real database and real processes.
"""

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from exactdocs.ingestion.adapters.driving import dbos_worker
from exactdocs.ingestion.adapters.driving.dbos_worker import (
    DbosJobWorker,
    SlotState,
    sort_workflows,
    tick_retention,
)

LIVE = ["ENQUEUED", "PENDING", "DELAYED"]


def workflow(workflow_id: str, executor: str, status: str, version: str = "v2") -> Any:
    return SimpleNamespace(
        workflow_id=workflow_id, executor_id=executor, status=status, app_version=version
    )


@dataclass(kw_only=True)  # conventions: allow-mutable-dataclass, allow-dict -- a test fake
class FakeSlots:
    states: list[SlotState] = field(default_factory=list)
    dead: set[str] = field(default_factory=set)
    claim_grace: float = 15.0
    clock: list[float] | None = None
    claim_takes: float = 0.0
    """How long ``claim`` takes on ``clock``: ``claim_grace`` when the slot left pending jobs."""

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        if self.clock is not None:
            self.clock[0] += self.claim_takes
        yield "exactdocs-1"

    async def keep(self) -> SlotState:
        return self.states.pop(0)

    @asynccontextmanager
    async def orphaned(self, executor_ids: Collection[str]) -> AsyncGenerator[Collection[str]]:
        yield sorted(set(executor_ids) & self.dead)


async def _nothing(*_: object, **__: object) -> None:
    return None


def worker(
    slots: FakeSlots, lost: list[str] | None = None, now: list[float] | None = None
) -> DbosJobWorker:
    return DbosJobWorker(
        run_job=_nothing,
        recover_jobs=_nothing,
        submit_queued_jobs=_nothing,
        system_database_url="postgresql+psycopg://x/y",
        executors=slots,
        queue="q",
        workflow="w",
        version="v2",
        adopt_grace=10,
        slot_give_up=5,
        slot_check_interval=1,
        slot_check_timeout=0.5,
        halt_timeout=1,
        on_slot_lost=None if lost is None else lambda: lost.append("stop"),
        monotonic=(lambda: now[0]) if now is not None else lambda: 0.0,
    )


def test_a_rolling_upgrade_leaves_a_live_process_s_workflows_alone() -> None:
    workflows = [
        workflow("old-running", "exactdocs-1", "PENDING", version="v1"),  # live, older build
        workflow("old-done", "exactdocs-1", "SUCCESS", version="v1"),
        workflow("mine-old", "exactdocs-0", "PENDING", version="v1"),
        workflow("mine-now", "exactdocs-0", "PENDING"),
        workflow("dead-old", "exactdocs-2", "PENDING", version="v1"),
        workflow("dead-now", "exactdocs-2", "ENQUEUED"),
    ]

    stale, live = sort_workflows(workflows, "v2", {"exactdocs-0", "exactdocs-2"}, LIVE)

    assert stale == {"mine-old", "dead-old"}
    assert live == {"old-running", "mine-now", "dead-now"}  # their jobs are not recovered


def test_one_process_answers_for_every_workflow() -> None:
    workflows = [
        workflow("a", "local", "PENDING", version="v1"),
        workflow("b", "local", "ERROR"),
        workflow("c", "local", "ENQUEUED"),
    ]

    assert sort_workflows(workflows, "v2", None, LIVE) == ({"a", "b"}, {"c"})


async def test_a_free_slot_is_adopted_only_once_it_stayed_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    resumed: list[list[str]] = []

    async def pending(**options: object) -> list[Any]:
        executors = options.get("executor_id")
        found = [workflow("job-1", "exactdocs-1", "PENDING")]
        return [w for w in found if not isinstance(executors, list) or w.executor_id in executors]

    async def resume(ids: list[str], *, queue_name: str) -> None:
        assert queue_name == "q"
        resumed.append(ids)

    monkeypatch.setattr(dbos_worker.DBOS, "list_workflows_async", pending)
    monkeypatch.setattr(dbos_worker.DBOS, "resume_workflows_async", resume)
    slots = FakeSlots(dead={"exactdocs-1"})
    subject = worker(slots, now=now)

    await subject.adopt_orphans("exactdocs-0", slots)  # first seen free: its owner may retake
    now[0] += 5
    await subject.adopt_orphans("exactdocs-0", slots)
    assert resumed == []
    now[0] += 6
    await subject.adopt_orphans("exactdocs-0", slots)
    assert resumed == [["job-1"]]


async def test_a_slot_taken_back_in_time_is_not_adopted(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    resumed: list[list[str]] = []

    async def pending(**_: object) -> list[Any]:
        return [workflow("job-1", "exactdocs-1", "PENDING")]

    async def resume(ids: list[str], **_: object) -> None:
        resumed.append(ids)

    monkeypatch.setattr(dbos_worker.DBOS, "list_workflows_async", pending)
    monkeypatch.setattr(dbos_worker.DBOS, "resume_workflows_async", resume)
    slots = FakeSlots(dead={"exactdocs-1"})
    subject = worker(slots, now=now)

    await subject.adopt_orphans("exactdocs-0", slots)
    slots.dead.clear()  # its process took it back
    now[0] += 5
    await subject.adopt_orphans("exactdocs-0", slots)
    slots.dead.add("exactdocs-1")  # free again: the wait starts over
    now[0] += 6
    await subject.adopt_orphans("exactdocs-0", slots)

    assert resumed == []


@pytest.fixture
def no_dbos(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record what the worker asks of DBOS when it stops (no DBOS runs in these tests).

    Returns:
        The calls, in order.
    """
    calls: list[str] = []

    def destroy(**_: object) -> None:
        calls.append("destroy")

    class Client:
        def __init__(self, **options: object) -> None:
            assert options["dbos_system_schema"] == "dbos"

        def resume_workflows(self, ids: list[str], *, queue_name: str) -> None:
            calls.append(f"resume {','.join(ids)} on {queue_name}")

        def destroy(self) -> None:
            calls.append("client closed")

    monkeypatch.setattr(dbos_worker.DBOS, "destroy", destroy)
    monkeypatch.setattr(dbos_worker, "DBOSClient", Client)
    return calls


async def test_a_lost_slot_stops_dbos_and_the_process(no_dbos: list[str]) -> None:
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.HELD, SlotState.LOST])
    subject = worker(slots, lost)

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.HELD
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST

    assert no_dbos == ["destroy"]  # its queue threads stop: nothing is dequeued here any more
    assert lost == ["stop"]


async def test_no_job_starts_after_the_slot_is_lost(no_dbos: list[str]) -> None:
    started: list[str] = []

    async def run_job(job_id: str) -> None:
        started.append(job_id)

    slots = FakeSlots(states=[SlotState.LOST])
    subject = replace(worker(slots, []), run_job=run_job)
    await subject.check_slot("exactdocs-0", slots)

    with pytest.raises(asyncio.CancelledError):  # the workflow stays pending...
        await subject.run_workflow("job-late")

    assert started == []
    await subject.check_slot("exactdocs-0", FakeSlots(states=[SlotState.LOST]))
    # ...and is queued again for another process, once DBOS stopped handing jobs over
    assert no_dbos == ["destroy", "resume job-late on q", "client closed"]


async def _delay_cancellation(released: asyncio.Event) -> None:
    """A job that keeps going once cancelled (cancelled again too) until ``released``.

    Raises:
        asyncio.CancelledError: Once ``released``.
    """
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        while not released.is_set():
            with suppress(asyncio.CancelledError):
                await released.wait()
        raise


async def test_a_lost_slot_is_given_up_within_halt_timeout_even_if_a_job_delays_its_cancellation(
    no_dbos: list[str],
) -> None:
    released = asyncio.Event()
    started = asyncio.Event()
    lost: list[str] = []

    async def slow_to_cancel(job_id: str) -> None:
        del job_id
        started.set()
        await _delay_cancellation(released)

    slots = FakeSlots(states=[SlotState.LOST])
    subject = replace(worker(slots, lost), run_job=slow_to_cancel)
    job = asyncio.create_task(subject.run_workflow("job-slow"))
    try:
        await started.wait()
        loop = asyncio.get_running_loop()
        began = loop.time()
        async with asyncio.timeout(subject.halt_timeout * 3):  # the bug: it waited for the job
            assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
        took = loop.time() - began

        assert took <= subject.halt_timeout + 0.25  # scheduling slack only
        assert lost == ["stop"]
        assert no_dbos == ["destroy"]  # DBOS hands over no more jobs, the job notwithstanding
        assert not job.done()  # still cleaning up: nothing waited for it
    finally:
        released.set()
        with suppress(asyncio.CancelledError):
            await job


async def test_a_halt_whose_dbos_hangs_still_stops_the_process_at_halt_timeout(
    monkeypatch: pytest.MonkeyPatch, no_dbos: list[str]
) -> None:
    unblock = threading.Event()

    def hanging_destroy(**_: object) -> None:
        no_dbos.append("destroy")
        unblock.wait(5)

    monkeypatch.setattr(dbos_worker.DBOS, "destroy", hanging_destroy)
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.LOST])
    subject = worker(slots, lost)
    loop = asyncio.get_running_loop()
    began = loop.time()
    try:
        assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
        took = loop.time() - began
    finally:
        unblock.set()

    assert took <= subject.halt_timeout + 0.25  # scheduling slack only
    assert lost == ["stop"]
    assert no_dbos == ["destroy"]


async def test_a_stop_cancelled_again_does_not_wait_for_a_job_that_delays_its_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)
    released = asyncio.Event()
    started = asyncio.Event()
    jobs: list[asyncio.Task[None]] = []

    async def slow_to_cancel(job_id: str) -> None:
        del job_id
        started.set()
        await _delay_cancellation(released)

    subject = replace(worker(FakeSlots()), executors=None, run_job=slow_to_cancel, stop_grace=0.01)

    async def serve() -> None:
        async with subject.running():
            jobs.append(asyncio.create_task(subject.run_workflow("job-slow")))
            await asyncio.Event().wait()  # until the server is stopped

    serving = asyncio.create_task(serve())
    try:
        await started.wait()
        serving.cancel()  # the server stops: the job is cancelled, and takes its time
        await asyncio.sleep(0.05)
        assert not serving.done()  # the normal stop waits for its jobs
        serving.cancel()  # stopped again (a second Ctrl-C): the stop ends now
        await asyncio.wait({serving}, timeout=1)

        assert serving.cancelled()
        assert StartingDbos.stopped == ["destroy"]  # DBOS does not outlive the worker
        assert not jobs[0].done()
    finally:
        released.set()
        with suppress(asyncio.CancelledError):
            await jobs[0]


async def test_a_job_that_ends_late_within_its_share_is_waited_for_and_the_refused_requeued(
    no_dbos: list[str],
) -> None:
    unwind = 0.3  # less than the jobs' share of halt_timeout (0.5 s of 1 s)
    started = asyncio.Event()
    ended: list[str] = []

    async def slow_to_end(job_id: str) -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(unwind)  # its cleanup, then it ends
            ended.append(job_id)
            raise

    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.LOST])
    subject = replace(worker(slots, lost), run_job=slow_to_end)
    job = asyncio.create_task(subject.run_workflow("job-slow"))
    await started.wait()
    loop = asyncio.get_running_loop()
    began = loop.time()
    check = asyncio.create_task(subject.check_slot("exactdocs-0", slots))
    await asyncio.sleep(0.05)
    with pytest.raises(asyncio.CancelledError):  # handed over while the halt waits: refused
        await subject.run_workflow("job-late")

    assert await check is SlotState.LOST
    took = loop.time() - began

    assert unwind <= took < 0.5  # its end, not the whole share (slack for a slow runner)
    assert ended == ["job-slow"]
    assert job.cancelled()
    assert no_dbos == ["destroy", "resume job-late on q", "client closed"]
    assert lost == ["stop"]


async def test_a_second_stop_during_stop_grace_still_cancels_every_task_before_dbos_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)
    cancelled: list[str] = []
    running = asyncio.Event()
    forgetting = asyncio.Event()

    async def hang(name: str, ready: asyncio.Event) -> None:
        ready.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    async def job(job_id: str) -> None:
        if job_id == "job-slow":
            await hang(job_id, running)

    async def workflow_status(job_id: str) -> None:
        await hang(f"forget {job_id}", forgetting)

    monkeypatch.setattr(
        StartingDbos, "get_workflow_status_async", staticmethod(workflow_status), raising=False
    )
    subject = replace(worker(FakeSlots()), executors=None, run_job=job, stop_grace=10)
    jobs: list[asyncio.Task[None]] = []
    seen_at_destroy: list[bool] = []

    def destroy(**_: object) -> None:  # every task must already be told to stop by now
        tasks = [*jobs, *subject._forgetting]  # ruff: ignore[private-member-access]
        seen_at_destroy.append(bool(tasks) and all(task.cancelling() for task in tasks))
        StartingDbos.stopped.append("destroy")

    monkeypatch.setattr(StartingDbos, "destroy", staticmethod(destroy))

    async def serve() -> None:
        async with subject.running():
            jobs.append(asyncio.create_task(subject.run_workflow("job-slow")))
            await subject.run_workflow("job-quick")  # done: its workflow is being deleted
            await asyncio.Event().wait()  # until the server is stopped

    serving = asyncio.create_task(serve())
    await running.wait()
    await forgetting.wait()
    serving.cancel()  # the server stops: the job gets stop_grace to finish
    await asyncio.sleep(0.05)
    assert not serving.done()
    serving.cancel()  # stopped again, well within stop_grace
    await asyncio.wait({serving}, timeout=1)
    await asyncio.wait(jobs, timeout=1)

    assert serving.cancelled()
    assert jobs[0].cancelled()  # the bug: it went on running after DBOS was destroyed
    assert sorted(cancelled) == ["forget job-quick", "job-slow"]
    assert StartingDbos.stopped == ["destroy"]
    assert seen_at_destroy == [True]  # cancelled before DBOS stops, not after


async def test_an_unreachable_database_is_waited_out_before_the_slot_counts_as_lost(
    no_dbos: list[str],
) -> None:
    now = [0.0]
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.UNKNOWN, SlotState.UNKNOWN, SlotState.HELD])
    subject = worker(slots, lost, now=now)

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.UNKNOWN
    now[0] += 4  # under the give-up time (5 s here) since the slot was last confirmed
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.UNKNOWN
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.HELD  # back in time
    assert (lost, no_dbos) == ([], [])

    slots.states += [SlotState.UNKNOWN, SlotState.UNKNOWN]
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.UNKNOWN
    now[0] += 5  # unconfirmed for the give-up time: it stops before anyone can adopt its jobs
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
    assert lost == ["stop"]


async def test_a_slot_check_that_hangs_counts_as_unknown() -> None:
    class Hanging(FakeSlots):
        async def keep(self) -> SlotState:
            await asyncio.sleep(60)
            return SlotState.HELD

    slots = Hanging()
    subject = replace(worker(slots, []), slot_check_timeout=0.05)

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.UNKNOWN


async def test_a_retaken_slot_whose_jobs_were_adopted_meanwhile_counts_as_lost(
    monkeypatch: pytest.MonkeyPatch, no_dbos: list[str]
) -> None:
    async def status(job_id: str) -> Any:
        return workflow(job_id, "exactdocs-3", "PENDING")  # another process runs it now

    monkeypatch.setattr(dbos_worker.DBOS, "get_workflow_status_async", status)
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.RETAKEN])
    subject = worker(slots, lost)
    subject.job_ids.add("job-1")

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
    assert lost == ["stop"]
    assert no_dbos == ["destroy"]


async def test_a_retaken_slot_with_its_jobs_still_its_own_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def status(job_id: str) -> Any:
        return workflow(job_id, "exactdocs-0", "PENDING")

    monkeypatch.setattr(dbos_worker.DBOS, "get_workflow_status_async", status)
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.RETAKEN])
    subject = worker(slots, lost)
    subject.job_ids.add("job-1")

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.HELD
    assert lost == []


async def test_a_retaken_slot_whose_job_check_hangs_is_given_up_within_one_check_timeout(
    monkeypatch: pytest.MonkeyPatch, no_dbos: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    # keep() uses most of the check's time, then the job check hangs. Both share one deadline,
    # so the check ends one slot_check_timeout after it began (the bound the timing invariants
    # count), not two.
    timeout = 0.4

    class SlowRetake(FakeSlots):
        async def keep(self) -> SlotState:
            await asyncio.sleep(timeout * 0.75)
            return SlotState.RETAKEN

    async def hanging_status(job_id: str) -> Any:
        await asyncio.sleep(60)
        return workflow(job_id, "exactdocs-0", "PENDING")

    monkeypatch.setattr(dbos_worker.DBOS, "get_workflow_status_async", hanging_status)
    loop = asyncio.get_running_loop()
    stopped: list[float] = []
    slots = SlowRetake()
    subject = replace(
        worker(slots), slot_check_timeout=timeout, on_slot_lost=lambda: stopped.append(loop.time())
    )
    subject.job_ids.add("job-1")
    started = loop.time()

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
    took = stopped[0] - started  # the halt itself is near instant here: no DBOS, no job tasks
    assert took < timeout * 1.25, f"the check and halt took {took:.2f} s"
    assert no_dbos == ["destroy"]
    assert "its jobs could not be checked" in caplog.text  # told apart from a real adoption


async def test_a_retaken_slot_with_no_jobs_is_held_even_at_the_deadline(
    no_dbos: list[str],
) -> None:
    # No job to check: a retake reported after the deadline has passed still keeps the slot.
    # keep() blocks the loop past the deadline, so its own timeout cannot fire first.
    timeout = 0.2

    class LateRetake(FakeSlots):
        async def keep(self) -> SlotState:
            # Blocks the loop on purpose: the deadline passes with no chance for a timeout.
            time.sleep(timeout * 1.5)  # ruff: ignore[blocking-sleep-in-async-function]
            return SlotState.RETAKEN

    slots = LateRetake()
    subject = replace(worker(slots), slot_check_timeout=timeout)

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.HELD
    assert no_dbos == []


@pytest.mark.parametrize(
    ("schedule", "kept"),
    [
        ("0 * * * * *", timedelta(minutes=10)),  # every minute: the floor
        ("0 0 * * * *", timedelta(hours=2)),  # hourly: two intervals
    ],
)
def test_ended_ticks_are_kept_long_enough_for_a_late_scheduler(
    schedule: str, kept: timedelta
) -> None:
    assert tick_retention(schedule) == kept


async def test_old_ended_ticks_are_pruned_and_recent_ones_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, object] = {}
    deleted: list[list[str]] = []

    async def listed(**options: object) -> list[Any]:
        asked.update(options)
        return [workflow("sched-x-1", "exactdocs-1", "SUCCESS")]

    async def delete(ids: list[str]) -> None:
        deleted.append(ids)

    monkeypatch.setattr(dbos_worker.DBOS, "list_workflows_async", listed)
    monkeypatch.setattr(dbos_worker.DBOS, "delete_workflows_async", delete)

    await worker(FakeSlots()).prune_ticks()

    assert asked["name"] == dbos_worker.SCHEDULE_WORKFLOW
    assert "end_time" in asked  # only those created before the retention
    assert deleted == [["sched-x-1"]]


async def test_the_give_up_clock_runs_from_the_last_confirmed_hold(no_dbos: list[str]) -> None:
    now = [0.0]
    lost: list[str] = []
    slots = FakeSlots(states=[SlotState.HELD, SlotState.UNKNOWN, SlotState.UNKNOWN])
    subject = worker(slots, lost, now=now)

    assert await subject.check_slot("exactdocs-0", slots) is SlotState.HELD
    now[0] += 4  # the first failed check comes late (a check that hung, then the interval)
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.UNKNOWN
    now[0] += 1  # 5 s since the last hold, though only 1 s since the first failure
    assert await subject.check_slot("exactdocs-0", slots) is SlotState.LOST
    assert lost == ["stop"]
    assert no_dbos == ["destroy"]


class StartingDbos:
    """DBOS as far as a worker's start and halt need it: nothing runs, the stop is recorded."""

    stopped: list[str]
    launched: bool = False

    def __init__(self, *, config: object) -> None:
        del config

    @staticmethod
    def workflow(*, name: str) -> Any:
        del name
        return lambda function: function

    @classmethod
    def launch(cls) -> None:
        cls.launched = True

    register_queue_async = staticmethod(_nothing)
    delete_schedule_async = staticmethod(_nothing)
    delete_workflows_async = staticmethod(_nothing)

    @staticmethod
    async def list_workflows_async(**_: object) -> list[Any]:
        return []

    @classmethod
    def destroy(cls, **_: object) -> None:
        cls.stopped.append("destroy")


async def test_a_slot_lost_during_a_slow_startup_is_given_up_counting_from_the_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    stopped_at: list[float] = []
    stopping = asyncio.Event()
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)

    async def slow_recovery(**_: object) -> None:
        now[0] += 6  # the startup outlasts the give-up time (5 s here)...

    def stop() -> None:
        stopped_at.append(now[0])
        stopping.set()

    slots = FakeSlots(states=[SlotState.UNKNOWN] * 50)  # ...and its slot's connection died
    subject = replace(
        worker(slots, now=now),
        recover_jobs=slow_recovery,
        on_slot_lost=stop,
        slot_check_interval=0.01,
    )

    async with subject.running(), asyncio.timeout(0.5):
        await stopping.wait()

    # 6 s since the claim: given up at the first check after it, before adoption.
    assert stopped_at == [6.0]
    assert stopped_at[0] < subject.adopt_grace
    assert StartingDbos.stopped == ["destroy"]


async def test_a_slot_lost_while_the_recovery_runs_stops_the_worker_before_adoption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    stopped_at: list[float] = []
    recovered: list[float] = []
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)

    async def endless_recovery(**_: object) -> None:
        for _step in range(40):  # 20 s: twice the adoption grace (10 s here)
            now[0] += 0.5
            await asyncio.sleep(0.01)
        recovered.append(now[0])

    slots = FakeSlots(states=[SlotState.UNKNOWN] * 1000)  # the database is gone from the claim
    subject = replace(
        worker(slots, now=now),
        recover_jobs=endless_recovery,
        on_slot_lost=lambda: stopped_at.append(now[0]),
        slot_check_interval=0.01,
    )

    with pytest.raises(RuntimeError, match="lost while the job worker started"):
        async with subject.running():
            pytest.fail("the worker started after its slot was lost")

    # The watchdog ran during the recovery: given up 5 s after the claim, stopped (DBOS too),
    # and the recovery cancelled, well before another process may adopt the slot's jobs.
    assert recovered == []
    assert subject.slot_give_up <= stopped_at[0] < subject.adopt_grace
    assert StartingDbos.stopped == ["destroy"]


async def test_a_slot_held_after_a_long_claim_still_waits_out_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OutageFromLaunch(FakeSlots):
        """Held until DBOS launches; then the database cannot be reached."""

        async def keep(self) -> SlotState:
            return SlotState.UNKNOWN if StartingDbos.launched else SlotState.HELD

    now = [0.0]
    lost: list[str] = []
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(StartingDbos, "launched", False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)
    # The slot left pending jobs: the claim waited its grace, longer than the give-up time (5 s).
    slots = OutageFromLaunch(clock=now, claim_takes=15)
    subject = worker(slots, lost, now=now)

    async with subject.running():
        await asyncio.sleep(0.05)  # the watchdog's first check: the database is unreachable

    # Confirmed just before DBOS started: the outage is waited out, as after any other hold.
    assert lost == []


async def test_a_restarted_worker_counts_a_slot_free_only_from_what_it_saw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    resumed: list[list[str]] = []

    async def pending(**options: object) -> list[Any]:
        executors = options.get("executor_id")
        found = [workflow("job-2", "exactdocs-2", "PENDING")]
        return [w for w in found if not isinstance(executors, list) or w.executor_id in executors]

    async def resume(ids: list[str], *, queue_name: str) -> None:
        del queue_name
        resumed.append(ids)

    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(StartingDbos, "list_workflows_async", staticmethod(pending))
    monkeypatch.setattr(StartingDbos, "resume_workflows_async", staticmethod(resume), raising=False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)
    slots = FakeSlots(dead={"exactdocs-2"})
    subject = worker(slots, [], now=now)

    for _ in range(2):  # slot 2 seen free once, then again by the same worker restarted later
        slots.states += [SlotState.HELD, SlotState.HELD]
        async with subject.running():
            await asyncio.sleep(0.05)  # the watchdog's first round
        now[0] += 100

    # The second run saw slot 2 free just now: not for the adoption grace yet.
    assert resumed == []
    assert slots.states == []


async def test_a_slot_lost_while_dbos_fails_to_stop_still_stops_the_process(
    monkeypatch: pytest.MonkeyPatch, no_dbos: list[str]
) -> None:
    loop = asyncio.get_running_loop()
    lost: list[str] = []
    stopping = asyncio.Event()

    class FailingToStop(StartingDbos):
        @classmethod
        def destroy(cls, **_: object) -> None:
            # DBOS's queue thread hands one more job over while it stops, then the stop fails.
            handover = asyncio.run_coroutine_threadsafe(subject.run_workflow("job-late"), loop)
            with suppress(concurrent.futures.CancelledError):
                handover.result(timeout=1)
            message = "DBOS could not stop"
            raise RuntimeError(message)

    def stop() -> None:
        lost.append("stop")
        stopping.set()

    monkeypatch.setattr(dbos_worker, "DBOS", FailingToStop)
    slots = FakeSlots(states=[SlotState.HELD, SlotState.HELD, SlotState.HELD, SlotState.LOST])
    subject = replace(worker(slots), on_slot_lost=stop, slot_check_interval=0.01)

    async with subject.running(), asyncio.timeout(1):
        await stopping.wait()
        await asyncio.sleep(0.05)  # the watchdog does not check again, nor stop twice

    assert lost == ["stop"]
    assert no_dbos == ["resume job-late on q", "client closed"]  # the refused job, queued again
    assert slots.states == []


async def test_a_slot_taken_before_dbos_launches_fails_the_start_before_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lost: list[str] = []
    monkeypatch.setattr(StartingDbos, "stopped", [], raising=False)
    monkeypatch.setattr(StartingDbos, "launched", False)
    monkeypatch.setattr(dbos_worker, "DBOS", StartingDbos)
    # The slot's connection died during the claim's grace, and another process took the slot.
    slots = FakeSlots(states=[SlotState.LOST])
    subject = worker(slots, lost)

    with pytest.raises(RuntimeError, match="taken by another process before the job worker"):
        async with subject.running():
            pytest.fail("the worker started on a slot another process holds")

    # DBOS never launched, so it resumed and dequeued none of that process's jobs.
    assert StartingDbos.launched is False
    assert (StartingDbos.stopped, lost) == ([], [])


@dataclass(kw_only=True)  # conventions: allow-mutable-dataclass -- a test scenario's state
class FailingStartup:
    """A recovery that fails while the watchdog stops DBOS for a lost slot.

    The stop (``destroy``) waits until the recovery has failed, then until ``released``: the
    worker's start sees a finished, failed startup while the watchdog is still stopping.
    """

    destroying: asyncio.Event = field(default_factory=asyncio.Event)
    failed: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> DbosJobWorker:
        loop = asyncio.get_running_loop()
        scenario = self

        class SlowToStop(StartingDbos):
            @classmethod
            def destroy(cls, **_: object) -> None:
                loop.call_soon_threadsafe(scenario.destroying.set)
                scenario.failed.wait(1)
                scenario.released.wait(1)

        async def failing_recovery(**_: object) -> None:
            await self.destroying.wait()
            self.failed.set()
            message = "the recovery failed"
            raise ValueError(message)

        monkeypatch.setattr(dbos_worker, "DBOS", SlowToStop)
        slots = FakeSlots(states=[SlotState.HELD, SlotState.LOST])
        return replace(worker(slots, []), recover_jobs=failing_recovery)


def _startup_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(r.exc_info[1])
        for r in caplog.records
        if r.getMessage() == "the job worker's startup failed too" and r.exc_info
    ]


async def test_a_startup_that_fails_while_the_slot_is_lost_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    scenario = FailingStartup(released=threading.Event())
    scenario.released.set()
    subject = scenario.install(monkeypatch)

    with pytest.raises(RuntimeError, match="lost while the job worker started"):
        async with subject.running():
            pytest.fail("the worker started after its slot was lost")

    # The lost slot is what the start reports; the recovery's own error is not swallowed.
    assert _startup_errors(caplog) == ["the recovery failed"]


async def test_a_caller_cancelled_while_the_watchdog_stops_still_ends_the_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    scenario = FailingStartup()
    subject = scenario.install(monkeypatch)

    async def start() -> None:
        async with subject.running():
            pytest.fail("the worker started after its slot was lost")

    starting = asyncio.create_task(start())
    try:
        await scenario.destroying.wait()
        await asyncio.sleep(0.05)  # the recovery failed; the start waits for the watchdog
        assert not starting.done()
        starting.cancel()  # e.g. the server is stopped while it starts
        with pytest.raises(asyncio.CancelledError):
            await starting
    finally:
        scenario.released.set()

    # The startup was ended with the worker, and its error was seen, not left unretrieved.
    assert _startup_errors(caplog) == ["the recovery failed"]


@pytest.mark.parametrize(
    ("adopt_grace", "give_up", "halt", "complaint"),
    [
        # 15 + 2 + 1.5 + 5 = 23.5 s: a process may still run its jobs when they are adopted
        (23.0, 15.0, 5.0, "adopt_grace"),
        (30.0, 22.0, 5.0, "adopt_grace"),
        # 2 + 1.5 + 12 = 15.5 s: a starting process could resume jobs their holder still runs
        (60.0, 15.0, 12.0, "claim_grace"),
    ],
)
def test_slot_timings_that_could_run_a_job_twice_are_refused(
    adopt_grace: float, give_up: float, halt: float, complaint: str
) -> None:
    with pytest.raises(ValueError, match=complaint):
        DbosJobWorker(
            run_job=_nothing,
            recover_jobs=_nothing,
            submit_queued_jobs=_nothing,
            system_database_url="postgresql+psycopg://x/y",
            executors=FakeSlots(claim_grace=15),
            queue="q",
            workflow="w",
            version="v2",
            adopt_grace=adopt_grace,
            slot_give_up=give_up,
            halt_timeout=halt,
        )


def test_the_default_slot_timings_hold_together() -> None:
    worker_ = DbosJobWorker(
        run_job=_nothing,
        recover_jobs=_nothing,
        submit_queued_jobs=_nothing,
        system_database_url="postgresql+psycopg://x/y",
        executors=FakeSlots(claim_grace=15),
        queue="q",
        workflow="w",
        version="v2",
    )

    assert (worker_.slot_check_interval, worker_.slot_check_timeout) == (2.0, 1.5)
    assert (worker_.slot_give_up, worker_.halt_timeout, worker_.adopt_grace) == (15.0, 5.0, 30.0)
