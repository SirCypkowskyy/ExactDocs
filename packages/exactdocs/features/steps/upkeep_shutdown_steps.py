"""Steps for the server's stop while its nightly upkeep runs (#308).

The upkeep's queueing of the embedding is a stand-in that blocks until it is cancelled, then
either fails as a cancelled statement can (``PendingRollbackError``) or ignores every
cancellation until the scenario lets it end.
"""

import asyncio
import logging
import tempfile
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from sqlalchemy.exc import PendingRollbackError

from exactdocs.bootstrap import container as container_module
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.dtos import QueuedEmbedding, QueueEmbeddingCommand

BOUND = 0.5
"""The upkeep's stop bound in these scenarios (production: ``UPKEEP_STOP_SECONDS``)."""
RECANCEL_BOUND = 0.2
"""The wait after the second cancellation (production: ``UPKEEP_RECANCEL_SECONDS``)."""
DEADLINE = 20.0
"""Far past any bounded stop: a stop still running then hangs."""


class Queueing:
    """The upkeep's queueing: it runs until cancelled, then fails or goes on."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.on_cancel = "stop"
        self.release: asyncio.Event | None = None
        self.ended: asyncio.Event | None = None

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        del command
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as cancelled:
            if self.on_cancel == "fail":
                message = "Can't reconnect until invalid transaction is rolled back"
                raise PendingRollbackError(message) from cancelled
            while self.on_cancel == "go on" and self.release and not self.release.is_set():
                with suppress(asyncio.CancelledError):  # the second cancellation too
                    await self.release.wait()
            raise
        finally:
            if self.ended is not None:
                self.ended.set()
        return QueuedEmbedding(queued=0)


class Records(logging.Handler):
    """Keeps the warnings ExactDocs logs."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@given("a server whose nightly upkeep is queueing the embedding")
def step_upkeep_queueing(context: Context) -> None:
    context.queueing = Queueing()


@given("the database fails while that queueing is cancelled")
def step_fails_while_cancelled(context: Context) -> None:
    context.queueing.on_cancel = "fail"


@given("that queueing goes on after it is cancelled")
def step_goes_on_after_cancel(context: Context) -> None:
    context.queueing.on_cancel = "go on"


@when("the server stops")
def step_server_stops(context: Context) -> None:
    queueing: Queueing = context.queueing
    records = Records()
    log = logging.getLogger("exactdocs")
    log.addHandler(records)
    bounds = container_module.UPKEEP_STOP_SECONDS, container_module.UPKEEP_RECANCEL_SECONDS
    container_module.UPKEEP_STOP_SECONDS = BOUND
    container_module.UPKEEP_RECANCEL_SECONDS = RECANCEL_BOUND

    async def serve_then_stop(data: Path) -> None:
        built = Container.build(Settings(data_dir=data))
        container = replace(built, ingestion=replace(built.ingestion, queue_embedding=queueing))
        queueing.release = asyncio.Event()
        queueing.ended = asyncio.Event()
        async with container.running():
            await queueing.started.wait()
            context.stop_began = time.monotonic()
        context.stop_took = time.monotonic() - context.stop_began
        queueing.release.set()  # an upkeep left behind ends before the loop closes
        await asyncio.wait_for(queueing.ended.wait(), timeout=DEADLINE)

    try:
        with tempfile.TemporaryDirectory(prefix="exactdocs-upkeep-") as data:
            asyncio.run(asyncio.wait_for(serve_then_stop(Path(data)), timeout=DEADLINE))
    finally:
        container_module.UPKEEP_STOP_SECONDS, container_module.UPKEEP_RECANCEL_SECONDS = bounds
        log.removeHandler(records)
    context.warnings = records.messages


@then("it has stopped without waiting for the next midnight")
def step_stopped(context: Context) -> None:
    assert context.stop_took < BOUND, context.stop_took  # it did not need the fallback


@then("the failure is logged as a warning of the stop")
def step_failure_logged(context: Context) -> None:
    assert "the nightly upkeep failed while it stopped" in context.warnings, context.warnings


@then("it has stopped within the upkeep's bound")
def step_stopped_within_bound(context: Context) -> None:
    assert BOUND + RECANCEL_BOUND <= context.stop_took < BOUND + RECANCEL_BOUND + 5.0, (
        context.stop_took
    )


@then("a warning says the upkeep did not stop in time")
def step_warning_not_stopped(context: Context) -> None:
    warnings = context.warnings
    assert any("did not stop within" in message for message in warnings), warnings
    assert any("the server stops without it" in message for message in warnings), warnings
