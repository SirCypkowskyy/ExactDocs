"""The nightly upkeep stops when the server stops, whatever its cancellation turns into (#308).

A statement cancelled while it runs can raise another error as it unwinds (a
``PendingRollbackError``, or a database error during the rollback): that error replaces the
``CancelledError``. The upkeep must stop all the same, and stopping never waits on it unbounded.
"""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import PendingRollbackError

from exactdocs.bootstrap import container as container_module
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.embedding import requeue_nightly
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.dtos import QueuedEmbedding, QueueEmbeddingCommand

DEADLINE = 10.0
"""Far longer than any of these stops may take: past it, the stop hangs."""


class FailsWhileCancelled:
    """A queueing whose statement raises ``PendingRollbackError`` when it is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        del command
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as cancelled:
            message = "Can't reconnect until invalid transaction is rolled back"
            raise PendingRollbackError(message) from cancelled
        return QueuedEmbedding(queued=0)


class IgnoresCancellation:
    """A queueing that goes on after it is cancelled, until the test lets it end."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        del command
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self.release.wait()  # it goes on after it was cancelled
            raise
        return QueuedEmbedding(queued=0)


def _with_queueing(
    tmp_path: Path, queueing: FailsWhileCancelled | IgnoresCancellation
) -> Container:
    container = Container.build(Settings(data_dir=tmp_path))
    return replace(container, ingestion=replace(container.ingestion, queue_embedding=queueing))


async def test_the_nightly_upkeep_stops_when_an_error_replaces_its_cancellation(
    tmp_path: Path,
) -> None:
    queueing = FailsWhileCancelled()
    container = _with_queueing(tmp_path, queueing)
    try:
        upkeep = asyncio.create_task(container.nightly())
        await queueing.started.wait()
        upkeep.cancel()

        done, _ = await asyncio.wait({upkeep}, timeout=DEADLINE)

        assert done == {upkeep}  # it ended; it did not go on to prune the caches and beyond
        assert isinstance(upkeep.exception(), PendingRollbackError)
    finally:
        await container.engine.dispose()


async def test_a_failure_to_queue_that_is_no_cancellation_is_still_only_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Fails:
        async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
            del command
            message = "database is locked"
            raise RuntimeError(message)

    container = Container.build(Settings(data_dir=tmp_path))
    container = replace(container, ingestion=replace(container.ingestion, queue_embedding=Fails()))
    try:
        await container.queue_embedding()
    finally:
        await container.engine.dispose()

    assert "could not queue the embedding" in caplog.text


async def test_the_midnight_loop_ends_when_an_error_replaces_its_cancellation() -> None:
    started = asyncio.Event()

    async def queue() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as cancelled:
            message = "the connection was closed during the rollback"
            raise PendingRollbackError(message) from cancelled

    async def sleep(seconds: float) -> None:
        del seconds
        await asyncio.sleep(0)

    loop = asyncio.create_task(
        requeue_nightly(
            leader=None,
            queue=queue,
            now=lambda: datetime(2026, 11, 12, tzinfo=UTC),
            sleep=sleep,
            jitter=lambda: 0.0,
        )
    )
    await started.wait()
    loop.cancel()

    done, _ = await asyncio.wait({loop}, timeout=DEADLINE)

    assert done == {loop}  # it did not log the error and sleep until the next midnight
    assert isinstance(loop.exception(), PendingRollbackError)


async def test_the_server_stops_when_an_error_replaces_the_upkeep_cancellation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queueing = FailsWhileCancelled()
    container = _with_queueing(tmp_path, queueing)

    async def serve_until_the_upkeep_runs() -> None:
        async with container.running():
            await queueing.started.wait()

    with caplog.at_level(logging.WARNING, logger="exactdocs"):
        await asyncio.wait_for(serve_until_the_upkeep_runs(), timeout=DEADLINE)

    assert "the nightly upkeep failed while it stopped" in caplog.text


async def test_the_server_stops_after_its_bound_when_the_upkeep_does_not_stop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(container_module, "UPKEEP_STOP_SECONDS", 0.2)
    queueing = IgnoresCancellation()
    container = _with_queueing(tmp_path, queueing)

    async def serve_until_the_upkeep_runs() -> None:
        async with container.running():
            await queueing.started.wait()

    try:
        with caplog.at_level(logging.WARNING, logger="exactdocs"):
            await asyncio.wait_for(serve_until_the_upkeep_runs(), timeout=DEADLINE)

        assert "did not stop within 0.2 s" in caplog.text
    finally:
        queueing.release.set()  # the abandoned upkeep ends before the test's loop closes
        await asyncio.sleep(0.05)
