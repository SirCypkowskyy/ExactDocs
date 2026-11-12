"""The start-up probe that warns about a transaction-mode pooler in front of PostgreSQL (#279).

The direct-connection cases need ``EXACTDOCS_TEST_POSTGRES_URL``; the pooler cases also need
``EXACTDOCS_TEST_PGBOUNCER_URL`` (PgBouncer in transaction mode, ``databases.PGBOUNCER_URL``).
CI runs both; without them those cases are skipped.
"""

import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from databases import ADMIN_URL, PGBOUNCER_URL, SECRET_KEY, postgres_database, through_pgbouncer
from exactdocs.bootstrap.database import migrate, open_database, warn_unless_session
from exactdocs.bootstrap.settings import Settings

needs_postgres = pytest.mark.skipif(
    ADMIN_URL is None, reason="needs a PostgreSQL server (EXACTDOCS_TEST_POSTGRES_URL)"
)
needs_pgbouncer = pytest.mark.skipif(
    ADMIN_URL is None or PGBOUNCER_URL is None,
    reason="needs PgBouncer in transaction mode (EXACTDOCS_TEST_PGBOUNCER_URL)",
)
PROBE_BUDGET_SECONDS = 0.5
"""A generous bound for the probe on a direct connection: two round trips on a pooled
connection, a few milliseconds on a local server."""


def _pooler_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "session state" in record.getMessage()]


async def _migrated(url: str, data_dir: Path) -> AsyncEngine:
    engine = open_database(Settings(data_dir=data_dir, database_url=url, secret_key=SECRET_KEY))
    await migrate(engine)
    return engine


@pytest.fixture
async def direct(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A migrated engine on a new database, connected to PostgreSQL directly.

    Yields:
        The engine; disposed and its database dropped afterwards.
    """
    with postgres_database() as database:
        engine = await _migrated(database.url, tmp_path)
        yield engine
        await engine.dispose()


@pytest.fixture
async def pooled(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A migrated engine on a new database, reached through PgBouncer in transaction mode.

    Yields:
        The engine; disposed and its database dropped afterwards.
    """
    with postgres_database() as database:
        engine = await _migrated(through_pgbouncer(database), tmp_path)
        yield engine
        await engine.dispose()


async def test_sqlite_has_no_session_to_probe(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = await _migrated(f"sqlite+aiosqlite:///{tmp_path / 'exactdocs.db'}", tmp_path)
    try:
        with caplog.at_level(logging.WARNING):
            lost = await warn_unless_session(engine)
    finally:
        await engine.dispose()

    assert lost is False
    assert _pooler_warnings(caplog) == []


@needs_postgres
async def test_a_direct_connection_is_not_warned_about(
    direct: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        started = time.perf_counter()
        lost = await warn_unless_session(direct)
        took = time.perf_counter() - started

    assert lost is False
    assert _pooler_warnings(caplog) == []
    assert took < PROBE_BUDGET_SECONDS, f"the probe took {took * 1000:.1f} ms"


@needs_postgres
async def test_the_probe_opens_no_connection_of_its_own(direct: AsyncEngine) -> None:
    pool = direct.sync_engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.checkedin() == 1  # the migration's connection, back in the pool

    await warn_unless_session(direct)

    assert (pool.checkedin(), pool.checkedout()) == (1, 0)  # the same one, and given back


@needs_pgbouncer
async def test_a_transaction_mode_pooler_that_loses_state_is_warned_about_once(
    pooled: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        lost = await warn_unless_session(pooled)

    assert lost is True
    [warning] = _pooler_warnings(caplog)
    assert warning.levelno == logging.WARNING
    message = warning.getMessage()
    assert "transaction mode" in message
    assert "session pooler" in message
    assert "direct connection" in message
    assert ":***@" in message  # the URL is named with its password hidden
