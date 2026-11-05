"""Run an app's lifespan for the length of an async fixture (#203).

The lifespan is the container's one run (``Container.running()``) plus the MCP session manager.
pytest-asyncio sets a fixture up and tears it down in different tasks, and the session manager's
anyio task group must be left in the task that entered it, so the lifespan gets a task of its own.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncGenerator[FastAPI]:
    """Start the app's lifespan in its own task, yield the started app, then stop it.

    Yields:
        The app, its lifespan started.
    """
    started: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()

    async def run() -> None:
        try:
            async with app.router.lifespan_context(app):
                if not started.done():  # cancelled while starting: nobody waits for it any more
                    started.set_result(None)
                await stop.wait()
        except BaseException as exc:
            if started.done():
                raise
            started.set_exception(exc)  # startup failed: raised where the fixture awaits it

    task = asyncio.create_task(run())
    try:
        await started
        yield app
    finally:
        stop.set()
        if not started.done() or started.cancelled():
            # Interrupted while starting: stop the startup instead of waiting for it. The
            # cancellation that got us here is already on its way out.
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        else:
            await task
