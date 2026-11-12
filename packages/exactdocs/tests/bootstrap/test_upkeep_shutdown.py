"""The nightly upkeep stops when the server stops, whatever its cancellation turns into (#308).

A statement cancelled while it runs can raise another error as it unwinds (a
``PendingRollbackError``, or a database error during the rollback): that error replaces the
``CancelledError``. The upkeep must stop all the same, and stopping never waits on it unbounded.
"""

import asyncio
import gc
import logging
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import PendingRollbackError

from exactdocs.bootstrap import container as container_module
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.embedding import RequeueLeader, requeue_nightly
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
    """A queueing that goes on after every cancellation, until the test lets it end.

    Then it fails with ``error``, or stops as cancelled; ``ended`` is set either way.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.ended = asyncio.Event()
        self.error = error

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        del command
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            while not self.release.is_set():  # it goes on after it was cancelled, again
                with suppress(asyncio.CancelledError):
                    await self.release.wait()
            if self.error is not None:
                raise self.error from None
            raise
        finally:
            self.ended.set()
        return QueuedEmbedding(queued=0)


class StopsOnSecondCancellation:
    """A queueing that goes on after its first cancellation and stops on the second."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.ended = asyncio.Event()

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        del command
        self.started.set()
        try:
            with suppress(asyncio.CancelledError):
                await asyncio.Event().wait()
            await asyncio.Event().wait()  # its connection is still checked out
        finally:
            self.ended.set()
        return QueuedEmbedding(queued=0)


def _with_queueing(
    tmp_path: Path,
    queueing: FailsWhileCancelled | IgnoresCancellation | StopsOnSecondCancellation,
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


class LockSessions:
    """Lock sessions: the first fails like a dropped connection when it is cancelled."""

    def __init__(self) -> None:
        self.opened = 0
        self.checking = asyncio.Event()

    async def open(self) -> LockSessions:
        self.opened += 1
        return self

    async def holds_lock(self, *, held_before: bool) -> bool:
        del held_before
        if self.opened > 1:
            return True  # a new session would hold the lock and run the night's upkeep
        self.checking.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as cancelled:
            message = "server closed the connection unexpectedly"
            raise ConnectionError(message) from cancelled
        return True

    async def close(self) -> None: ...


async def test_the_leader_check_ends_when_an_error_replaces_its_cancellation() -> None:
    sessions = LockSessions()
    queued: list[int] = []

    async def queue() -> None:
        queued.append(1)

    async def sleep(seconds: float) -> None:
        del seconds
        await asyncio.sleep(0)

    loop = asyncio.create_task(
        requeue_nightly(
            leader=RequeueLeader(open_session=sessions.open),
            queue=queue,
            now=lambda: datetime(2026, 11, 12, tzinfo=UTC),
            sleep=sleep,
            jitter=lambda: 0.0,
        )
    )
    await sessions.checking.wait()
    loop.cancel()

    done, _ = await asyncio.wait({loop}, timeout=DEADLINE)

    assert done == {loop}  # it did not retry, queue and sleep until the next midnight
    assert isinstance(loop.exception(), ConnectionError)
    assert sessions.opened == 1  # no new connection was opened while the server stopped
    assert queued == []


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


async def test_the_server_cancels_the_upkeep_again_after_its_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(container_module, "UPKEEP_STOP_SECONDS", 0.2)
    queueing = StopsOnSecondCancellation()
    container = _with_queueing(tmp_path, queueing)

    async def serve_until_the_upkeep_runs() -> None:
        async with container.running():
            await queueing.started.wait()

    with caplog.at_level(logging.WARNING, logger="exactdocs"):
        await asyncio.wait_for(serve_until_the_upkeep_runs(), timeout=DEADLINE)

    assert queueing.ended.is_set()  # it ended before the engine was disposed, not after
    assert "did not stop within 0.2 s" in caplog.text
    assert "the server stops without it" not in caplog.text


async def test_the_server_stops_after_its_bounds_when_the_upkeep_does_not_stop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(container_module, "UPKEEP_STOP_SECONDS", 0.2)
    monkeypatch.setattr(container_module, "UPKEEP_RECANCEL_SECONDS", 0.1)
    queueing = IgnoresCancellation(error=RuntimeError("the connection was closed late"))
    container = _with_queueing(tmp_path, queueing)
    unhandled: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(lambda _, context: unhandled.append(context))

    async def serve_until_the_upkeep_runs() -> None:
        async with container.running():
            await queueing.started.wait()

    try:
        with caplog.at_level(logging.WARNING, logger="exactdocs"):
            await asyncio.wait_for(serve_until_the_upkeep_runs(), timeout=DEADLINE)

            assert "did not stop within 0.2 s" in caplog.text
            assert "the server stops without it" in caplog.text
            assert not queueing.ended.is_set()
    finally:
        queueing.release.set()  # the abandoned upkeep ends before the test's loop closes
        await asyncio.wait_for(queueing.ended.wait(), timeout=DEADLINE)
    await asyncio.sleep(0)  # its done callbacks run
    gc.collect()

    assert "the nightly upkeep left behind failed" in caplog.text
    assert unhandled == []  # its late failure was read, never "exception was never retrieved"
