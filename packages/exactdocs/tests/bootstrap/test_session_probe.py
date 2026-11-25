"""The start-up probe that warns about a transaction-mode pooler in front of PostgreSQL (#279).

The direct-connection cases need ``EXACTDOCS_TEST_POSTGRES_URL``; the pooler cases also need
``EXACTDOCS_TEST_PGBOUNCER_URL`` (PgBouncer in transaction mode, ``databases.PGBOUNCER_URL``).
They are integration tests (#507): CI's integration job runs both.
"""

import logging
import time
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

import integration
from databases import SECRET_KEY, postgres_database, through_pgbouncer
from exactdocs.bootstrap import database
from exactdocs.bootstrap.constants import SESSION_PROBE
from exactdocs.bootstrap.database import (
    migrate,
    open_database,
    shown_url,
    warn_unless_session,
)
from exactdocs.bootstrap.settings import Settings

needs_postgres = integration.POSTGRES
needs_pgbouncer = integration.PGBOUNCER
PROBE_BUDGET_SECONDS = 0.2
"""A bound for the probe on a direct connection. It is two round trips on a pooled connection,
a few milliseconds on a local server; the margin is for a busy shared CI runner, so the test
catches a probe that opens a connection or waits, not ordinary jitter."""


def _pooler_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "session state" in record.getMessage()]


def _probe_failures(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "could not check" in record.getMessage().lower()]


@contextmanager
def _refusing_set_config(engine: AsyncEngine, error: BaseException) -> Generator[None]:
    """Make every ``set_config`` statement on ``engine`` raise ``error`` before it runs.

    It stands in for a pooler or proxy that refuses the statement, a dropped connection, or a
    ``statement_timeout``.
    """

    def refuse(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and "set_config" in statement:
            raise error

    event.listen(engine.sync_engine, "before_cursor_execute", refuse)
    try:
        yield
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", refuse)


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


@needs_postgres
async def test_a_probe_that_fails_is_a_warning_and_the_start_goes_on(
    direct: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        _refusing_set_config(direct, RuntimeError("pooler refused set_config")),
        caplog.at_level(logging.WARNING),
    ):
        lost = await warn_unless_session(direct)

    assert lost is False
    assert _pooler_warnings(caplog) == []
    [warning] = _probe_failures(caplog)
    assert warning.levelno == logging.WARNING
    message = warning.getMessage()
    assert "pooler refused set_config" in message
    assert ":***@" in message  # the URL is named with its password hidden


@needs_postgres
async def test_a_probe_that_fails_while_the_start_is_cancelled_raises(
    direct: AsyncEngine, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The error replaced the CancelledError of a stop: the stop must go on, not be logged away.
    monkeypatch.setattr(database, "being_cancelled", lambda: True)

    with (
        _refusing_set_config(direct, RuntimeError("connection dropped")),
        caplog.at_level(logging.WARNING),
        pytest.raises(RuntimeError, match="connection dropped"),
    ):
        await warn_unless_session(direct)

    assert _probe_failures(caplog) == []


@needs_postgres
async def test_the_probe_leaves_no_value_on_the_connection(direct: AsyncEngine) -> None:
    await warn_unless_session(direct)

    async with direct.connect() as connection:  # the probe's connection, from the pool
        left = await connection.scalar(
            text("SELECT current_setting(:name, true)"), {"name": SESSION_PROBE}
        )

    assert left in {None, ""}


def test_a_shown_url_hides_the_password_in_the_userinfo_and_in_the_query() -> None:
    url = make_url(
        "postgresql+psycopg://reader:secret@db.example:6543/docs?password=other&sslmode=require"
    )

    shown = shown_url(url)

    assert "secret" not in shown
    assert "other" not in shown
    assert shown == "postgresql+psycopg://reader:***@db.example:6543/docs?sslmode=require"


@needs_pgbouncer
async def test_the_warning_hides_a_password_given_in_the_query(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with postgres_database() as database:
        through = make_url(through_pgbouncer(database))
        password = through.password
        assert password
        url = through.set(password=None).update_query_dict({"password": str(password)})
        engine = await _migrated(url.render_as_string(hide_password=False), tmp_path)
        try:
            with caplog.at_level(logging.WARNING):
                lost = await warn_unless_session(engine)
        finally:
            await engine.dispose()

    assert lost is True
    [warning] = _pooler_warnings(caplog)
    assert f"password={password}" not in warning.getMessage()
