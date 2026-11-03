"""The in-process job worker: asyncio tasks that poll for jobs, started in the app's lifespan.

MVP-2 (E3-11) replaces it with DBOS behind the same driving ports.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from exactdocs.ingestion.ports.driving import RecoverJobs, RunNextJob

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class JobWorker:
    """Runs up to ``concurrency`` jobs at once; ``RunNextJob`` never starts two for one library."""

    recover_jobs: RecoverJobs
    run_next_job: RunNextJob
    concurrency: int = 2
    # ponytail: idle workers poll the database; a wake-up event on enqueue if latency matters.
    poll_interval: float = 0.5

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Recover interrupted jobs, run the worker for the duration of the block, then stop it.

        Stopping cancels running jobs where they are: they stay ``running`` in the database and
        are recovered by the next start.
        """
        await self.recover_jobs()
        tasks = [asyncio.create_task(self._work()) for _ in range(self.concurrency)]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _work(self) -> None:
        while True:
            try:
                ran = await self.run_next_job()
            except Exception:
                log.exception("job worker could not run the next job")
                ran = False
            if not ran:
                await asyncio.sleep(self.poll_interval)
