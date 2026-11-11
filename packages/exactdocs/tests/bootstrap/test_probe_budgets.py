"""The probes keep their time budgets while a database statement is still running (#298).

SQLAlchemy closes a connection whose statement was cancelled by waiting, shielded, for
aiosqlite's ``close()``, and that waits for the statement. So the probes must not wait for the
database themselves: they give it their budget and answer, and the check finishes on its own.
When the app stops, it waits for that check before it disposes of the engine (#291).

How one check at a time is run is tested on a fake check in ``test_probe_checks.py``.
"""

import asyncio
import gc
import sys
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from app_lifespan import serving
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
LIVENESS_STALL_SECONDS = 2.0
"""How long the held statement runs for liveness: double Kubernetes' timeout."""
READINESS_STALL_SECONDS = 3.0
"""How long the held statement runs for readiness: well beyond its 2 s budget."""
SHUTDOWN_STALL_SECONDS = 1.0
"""How long the held statement runs when the app stops: beyond liveness' budget."""
SCHEMA_READ = "alembic_version"
"""What the probes' statement reads; the app's own work at shutdown leaves it alone."""
MARGIN_SECONDS = 1.0
"""Slack on top of a budget for the request itself."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Probed:
    """A client of a running instance, and the switch that makes its database slow."""

    client: httpx.AsyncClient
    """A client with no cookie and no token, like an orchestrator."""
    slow: SlowDatabase
    """Stalls the instance's database statements."""


@pytest.fixture
async def probed(tmp_path: Path) -> AsyncIterator[Probed]:
    """An instance served through its app's lifespan, whose statements can be held.

    Args:
        tmp_path: The test's temporary directory, used as data directory.

    Yields:
        The client and the switch.
    """
    container = Container.build(Settings(data_dir=tmp_path))
    slow = SlowDatabase.on(container.engine)
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with (
        serving(app),  # its end settles the checks a probe left running
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        yield Probed(client=client, slow=slow)


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
    probed.slow.stall(LIVENESS_STALL_SECONDS)

    liveness, elapsed = await _timed(probed.client, LIVENESS_PATH)

    assert liveness.status_code == 200
    assert elapsed < FAST_SECONDS
    body = liveness.json()
    assert (body["status"], body["database_reachable"], body["schema_revision"]) == (
        "ok",
        False,
        None,
    )


async def test_readiness_answers_within_its_budget_while_a_statement_runs(probed: Probed) -> None:
    probed.slow.stall(READINESS_STALL_SECONDS)

    readiness, elapsed = await _timed(probed.client, READINESS_PATH)

    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready", "reason": "the database is unreachable"}
    assert elapsed < READINESS_TIMEOUT_SECONDS + MARGIN_SECONDS


async def test_stopping_the_app_leaves_no_probe_check_holding_a_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = Container.build(Settings(data_dir=tmp_path))
    slow = SlowDatabase.on(container.engine)
    app = create_app(container)
    checked_out_at_dispose: list[int] = []
    dispose = AsyncEngine.dispose

    async def recording_dispose(engine: AsyncEngine, close: bool = True) -> None:
        if engine is container.engine:
            pool = engine.pool
            assert isinstance(pool, QueuePool)
            checked_out_at_dispose.append(pool.checkedout())
        await dispose(engine, close)

    monkeypatch.setattr(AsyncEngine, "dispose", recording_dispose)
    unraisable: list[object] = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)

    async with (
        serving(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        # Only the probe's statement: the app's own work then stops at once, before the stall ends.
        slow.stall(SHUTDOWN_STALL_SECONDS, only=SCHEMA_READ)
        assert not (await client.get(LIVENESS_PATH)).json()["database_reachable"]
    await asyncio.sleep(slow.remaining())  # a stranded check would hand its connection back now
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()

    assert checked_out_at_dispose == [0]
    assert [w for w in caught if issubclass(w.category, ResourceWarning)] == []
    assert unraisable == []
