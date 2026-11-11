"""The probes keep their time budgets while a database statement is still running (#298).

SQLAlchemy closes a connection whose statement was cancelled by waiting, shielded, for
aiosqlite's ``close()``, and that waits for the statement. So the probes must not wait for the
database themselves: they give it their budget and answer, and the check finishes on its own.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy.pool import QueuePool

from exactdocs.bootstrap.constants import (
    LIVENESS_PATH,
    READINESS_PATH,
    READINESS_TIMEOUT_SECONDS,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from slow_database import SlowDatabase

FAST_SECONDS = 1.0
"""Kubernetes' default probe timeout: liveness must answer well within it."""
SLOW_STATEMENT_SECONDS = 3.0
"""How long the held statement runs: far beyond the liveness budget."""
SLOWER_STATEMENT_SECONDS = 4.0
"""How long the held statement runs for readiness: well beyond its 2 s budget."""
MARGIN_SECONDS = 0.5
"""Slack on top of a budget for the request itself."""
REPEATS = 5
"""Probes sent while the database is stuck."""
RECOVERY_ATTEMPTS = 20
"""Liveness probes the database gets to answer again once the statement is over."""
RECOVERY_PAUSE_SECONDS = 0.05
"""Pause between those probes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Probed:
    """A client of a running instance, and the switch that makes its database slow."""

    client: httpx.AsyncClient
    """A client with no cookie and no token, like an orchestrator."""
    container: Container
    """The instance."""
    slow: SlowDatabase
    """Stalls the instance's database statements."""


@pytest.fixture
async def probed(tmp_path: Path) -> AsyncIterator[Probed]:
    """A running instance whose statements can be held, left only once the database answers.

    Args:
        tmp_path: The test's temporary directory, used as data directory.

    Yields:
        The client, the instance and its switch.
    """
    container = Container.build(Settings(data_dir=tmp_path))
    slow = SlowDatabase.on(container.engine)
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),  # nothing else holds a connection
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        probed = Probed(client=client, container=container, slow=slow)
        yield probed
        await _until_the_database_answers(probed)


async def _until_the_database_answers(probed: Probed) -> None:
    """Wait for the held statement to end and liveness to see the database again.

    Args:
        probed: The instance.
    """
    await asyncio.sleep(probed.slow.remaining())
    for _ in range(RECOVERY_ATTEMPTS):
        if (await probed.client.get(LIVENESS_PATH)).json()["database_reachable"]:
            return
        await asyncio.sleep(RECOVERY_PAUSE_SECONDS)
    pytest.fail("the database did not answer again once the statement was over")


def _checked_out(container: Container) -> int:
    """Count the connections the instance's pool has handed out and not had back.

    Args:
        container: The instance.

    Returns:
        The number of connections in use.
    """
    pool = container.engine.pool
    assert isinstance(pool, QueuePool)
    return pool.checkedout()


async def _timed(client: httpx.AsyncClient, path: str) -> tuple[httpx.Response, float]:
    """Ask a probe and time the answer.

    Args:
        client: The client.
        path: The probe's path.

    Returns:
        The response and the seconds it took.
    """
    started = time.monotonic()
    response = await client.get(path)
    return response, time.monotonic() - started


async def test_liveness_answers_in_time_while_a_statement_runs(probed: Probed) -> None:
    probed.slow.stall(SLOW_STATEMENT_SECONDS)

    liveness, elapsed = await _timed(probed.client, LIVENESS_PATH)

    assert liveness.status_code == 200
    assert elapsed < FAST_SECONDS
    body = liveness.json()
    assert (body["status"], body["database_reachable"], body["schema_revision"]) == (
        "ok",
        False,
        None,
    )


async def test_liveness_sees_the_database_again_once_the_statement_ends(probed: Probed) -> None:
    probed.slow.stall(SLOW_STATEMENT_SECONDS)
    assert not (await probed.client.get(LIVENESS_PATH)).json()["database_reachable"]

    await _until_the_database_answers(probed)

    assert _checked_out(probed.container) == 0  # the abandoned check gave it back


async def test_readiness_answers_within_its_budget_while_a_statement_runs(probed: Probed) -> None:
    probed.slow.stall(SLOWER_STATEMENT_SECONDS)

    readiness, elapsed = await _timed(probed.client, READINESS_PATH)

    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready", "reason": "the database is unreachable"}
    assert elapsed < READINESS_TIMEOUT_SECONDS + MARGIN_SECONDS


async def test_repeated_probes_against_a_stuck_database_hold_one_connection_each(
    probed: Probed,
) -> None:
    probed.slow.stall(SLOWER_STATEMENT_SECONDS)
    tasks_before = len(asyncio.all_tasks())

    for _ in range(REPEATS):
        liveness, elapsed = await _timed(probed.client, LIVENESS_PATH)
        assert liveness.status_code == 200
        assert elapsed < FAST_SECONDS

    # One liveness check in flight, whatever the number of probes.
    assert _checked_out(probed.container) == 1
    assert len(asyncio.all_tasks()) <= tasks_before + 1
