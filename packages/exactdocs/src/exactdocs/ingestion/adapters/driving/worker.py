"""The in-process job worker: asyncio tasks that poll for jobs, started in the app's lifespan.

MVP-2 (E3-11) replaces it with DBOS behind the same driving ports.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
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
    # How long a stopping worker lets a running job finish before cancelling it.
    stop_grace: float = 1.0

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Recover interrupted jobs, run the worker for the duration of the block, then stop it.

        Stopping lets idle workers finish their poll, then cancels the jobs still running after
        ``stop_grace`` seconds. A cancelled job stays ``running`` in the database and is
        recovered by the next start.
        """
        await self.recover_jobs()
        stopping = asyncio.Event()
        tasks = [asyncio.create_task(self._work(stopping)) for _ in range(self.concurrency)]
        try:
            yield
        finally:
            stopping.set()
            _, busy = await asyncio.wait(tasks, timeout=self.stop_grace)
            for task in busy:
                task.cancel()
            await asyncio.gather(*busy, return_exceptions=True)

    async def _work(self, stopping: asyncio.Event) -> None:
        while not stopping.is_set():
            try:
                ran = await self.run_next_job()
            except Exception:
                log.exception("job worker could not run the next job")
                ran = False
            if not ran:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stopping.wait(), self.poll_interval)
