"""How a probe runs its database check: one at a time, within a budget, settled at shutdown (#298).

The check is a fake held by an ``asyncio.Event``, so these run in milliseconds; the database-backed
tests are in ``test_probe_budgets.py``.
"""

import asyncio
import gc
import logging
import time
from dataclasses import dataclass, field

import pytest
from fastapi import APIRouter

from exactdocs.bootstrap.probes import Probes, _OneCheckAtATime

BUDGET_SECONDS = 0.05
"""How long a call waits for the fake check."""
SETTLE_SECONDS = 0.05
"""How long ``settle`` gives the fake check."""
BOUND_SLACK_SECONDS = 0.5
"""Scheduling slack on top of ``settle``'s bound."""
REPEATS = 5
"""Calls made while the check is held."""


class CheckBugError(RuntimeError):
    """The fake check's bug."""


@dataclass(slots=True, kw_only=True)
class GatedCheck:
    """A check that answers its number once ``gate`` is set, or fails then when ``fails``."""

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    """Set to let the check end."""
    fails: bool = False
    """The check raises instead of answering."""
    stubborn: bool = False
    """The check ignores cancellation and keeps waiting for the gate, like a stuck statement."""
    started: int = 0
    """Checks started so far."""
    cancelled: int = 0
    """Checks cancelled so far."""

    async def __call__(self) -> int:
        """Wait for the gate, then answer which check this was.

        Returns:
            The check's number, from 1.

        Raises:
            CheckBugError: When ``fails``.
            asyncio.CancelledError: When cancelled, unless ``stubborn``.
        """
        self.started += 1
        number = self.started
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            if not self.stubborn:
                raise
            await self.gate.wait()
        if self.fails:
            raise CheckBugError(number)
        return number


def _runner(check: GatedCheck) -> _OneCheckAtATime[int]:
    """Run the fake check with the test budget.

    Args:
        check: The fake check.

    Returns:
        The runner.
    """
    return _OneCheckAtATime(check=check, budget=BUDGET_SECONDS)


async def test_calls_while_a_check_is_stuck_wait_for_that_one_check() -> None:
    check = GatedCheck()
    runner = _runner(check)

    for _ in range(REPEATS):
        with pytest.raises(TimeoutError):
            await runner()

    assert check.started == 1
    check.gate.set()
    await runner.settle(SETTLE_SECONDS)


async def test_a_call_gets_the_result_of_the_check_an_earlier_call_started() -> None:
    check = GatedCheck()
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()

    check.gate.set()

    assert await runner() == 1
    assert check.started == 1


async def test_a_new_check_starts_once_the_earlier_one_is_over() -> None:
    check = GatedCheck()
    check.gate.set()
    runner = _runner(check)

    assert await runner() == 1
    assert await runner() == 2  # a finished check is not reused as a cache


async def test_a_check_failing_after_the_budget_is_logged_and_not_left_unretrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unhandled: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(lambda _, context: unhandled.append(context))
    check = GatedCheck(fails=True)
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()

    with caplog.at_level(logging.ERROR, logger="exactdocs.bootstrap.probes"):
        check.gate.set()
        await runner.settle(SETTLE_SECONDS)
    gc.collect()

    assert runner.pending is None
    [record] = caplog.records
    assert record.getMessage() == "a probe's database check failed"
    assert isinstance(record.exc_info and record.exc_info[1], CheckBugError)
    assert unhandled == []


async def test_settle_lets_a_check_that_ends_in_time_finish() -> None:
    check = GatedCheck()
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()

    asyncio.get_running_loop().call_soon(check.gate.set)
    await runner.settle(SETTLE_SECONDS)

    assert (check.cancelled, runner.pending) == (0, None)


async def test_settle_cancels_a_check_that_outlasts_it_and_waits_for_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = GatedCheck()
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()

    with caplog.at_level(logging.WARNING, logger="exactdocs.bootstrap.probes"):
        await runner.settle(SETTLE_SECONDS)

    assert (check.cancelled, runner.pending) == (1, None)
    assert "cancelling it" in caplog.text


async def test_settle_with_no_check_in_flight_returns_at_once() -> None:
    check = GatedCheck()

    await _runner(check).settle(SETTLE_SECONDS)

    assert check.started == 0


async def test_the_probes_settle_every_check_they_left_running() -> None:
    liveness, readiness = GatedCheck(), GatedCheck()
    runners = (_runner(liveness), _runner(readiness))
    for runner in runners:
        with pytest.raises(TimeoutError):
            await runner()

    await Probes(router=APIRouter(), checks=runners).settle(SETTLE_SECONDS)

    assert [runner.pending for runner in runners] == [None, None]
    assert (liveness.cancelled, readiness.cancelled) == (1, 1)


async def test_settle_abandons_a_check_that_ignores_its_cancellation_within_twice_grace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = GatedCheck(stubborn=True)
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()
    task = runner.pending
    assert task is not None

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="exactdocs.bootstrap.probes"):
        # The timeout only turns a hang into a failure; ``took`` is the assertion.
        async with asyncio.timeout(2 * SETTLE_SECONDS + BOUND_SLACK_SECONDS):
            await runner.settle(SETTLE_SECONDS)
    took = time.monotonic() - started

    assert check.cancelled == 1
    assert not task.done()
    assert took < 2 * SETTLE_SECONDS + BOUND_SLACK_SECONDS
    assert "abandoning it and its connection" in caplog.text
    check.gate.set()
    await task  # the test's own cleanup: the stubborn check ends once let through


async def test_cancelling_settle_cancels_the_check_in_flight() -> None:
    check = GatedCheck()
    runner = _runner(check)
    with pytest.raises(TimeoutError):
        await runner()
    task = runner.pending
    assert task is not None

    settling = asyncio.create_task(runner.settle(SETTLE_SECONDS * 100))
    await asyncio.sleep(0)
    settling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await settling
    await asyncio.wait({task}, timeout=SETTLE_SECONDS)
    check.gate.set()  # lets the check end even when settle failed to cancel it

    assert (check.cancelled, task.cancelled()) == (1, True)
