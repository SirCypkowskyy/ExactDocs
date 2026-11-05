"""`serving()`: an app's lifespan held by an async fixture, also when it is interrupted."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from app_lifespan import serving


def app_with(events: list[str], *, startup: float = 0, fails: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        events.append("starting")
        try:
            await asyncio.sleep(startup)
            if fails:
                message = "startup failed"
                raise RuntimeError(message)
            events.append("started")
            yield
        finally:
            events.append("stopped")

    return FastAPI(lifespan=lifespan)


async def test_the_lifespan_runs_for_the_block() -> None:
    events: list[str] = []

    async with serving(app_with(events)):
        assert events == ["starting", "started"]

    assert events == ["starting", "started", "stopped"]


async def test_a_failed_startup_is_raised_where_the_fixture_waits() -> None:
    events: list[str] = []

    with pytest.raises(RuntimeError, match="startup failed"):
        async with serving(app_with(events, fails=True)):
            pytest.fail("the block must not run")

    assert events == ["starting", "stopped"]


async def test_cancelled_while_starting_it_stops_the_startup_instead_of_waiting() -> None:
    events: list[str] = []

    async def hold() -> None:
        async with serving(app_with(events, startup=30)):
            pytest.fail("the block must not run")

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.05)
    task.cancel()

    await asyncio.wait({task}, timeout=5)  # not the 30 s startup

    assert task.done(), "still waiting for the startup"
    assert task.cancelled()  # the cancellation, not an error from the half-started lifespan
    assert events == ["starting", "stopped"]
