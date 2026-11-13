"""DBOS's system database pool on PostgreSQL closes what DBOS's threads return late (#333).

``DBOS.destroy`` stops its executor without waiting, then disposes its engine. A thread still
recording a step returns its connection after that, to the disposed pool, where a plain
``QueuePool`` leaves it open until the garbage collector finds it, in some later test.
"""

import asyncio
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from dbos import DBOS
from sqlalchemy import QueuePool, create_engine
from sqlalchemy.engine import make_url

from databases import ADMIN_URL, PostgresDatabase, postgres_database
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import ClosingQueuePool
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion import IngestionModule
from exactdocs.ingestion.adapters.driven.dbos import DbosJobQueue
from exactdocs.ingestion.adapters.driven.git_cli import MissingGit
from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker
from exactdocs.ingestion.constants import QUEUE, STEPS_VERSION, WORKFLOW, JobKind
from exactdocs.ingestion.dtos import EnqueueJobCommand
from exactdocs.ingestion.models import Job
from exactdocs.ingestion.ports import JobProgress
from exactdocs_kernel import SystemClock

pytestmark = pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")

STEP = JobKind("import")
WAIT = 10.0
"""Seconds a test waits for PostgreSQL to show what it expects."""


@pytest.fixture
def database() -> Iterator[PostgresDatabase]:
    """A throwaway database.

    Yields:
        The database.
    """
    with postgres_database() as created:
        yield created


def libpq(database: PostgresDatabase) -> str:
    """Return the database's URL as psycopg takes it."""
    return make_url(database.url).set(drivername="postgresql").render_as_string(hide_password=False)


def test_a_connection_returned_after_dispose_is_closed(database: PostgresDatabase) -> None:
    engine = create_engine(database.url, poolclass=ClosingQueuePool)
    late = engine.connect()
    raw = late.connection.dbapi_connection

    engine.dispose()
    late.close()

    assert raw is not None
    assert raw.closed


def test_a_recreated_pool_keeps_what_is_returned_to_it(database: PostgresDatabase) -> None:
    engine = create_engine(database.url, poolclass=ClosingQueuePool)
    engine.dispose()

    with engine.connect() as connection:
        raw = connection.connection.dbapi_connection

    assert isinstance(engine.pool, ClosingQueuePool)
    assert raw is not None
    assert not raw.closed  # back in the live pool, for reuse
    engine.dispose()
    assert raw.closed


def test_a_check_in_does_not_wait_for_another_pools_dispose(database: PostgresDatabase) -> None:
    one = create_engine(database.url, poolclass=ClosingQueuePool)
    other = create_engine(database.url, poolclass=ClosingQueuePool).pool
    assert isinstance(other, ClosingQueuePool)
    late = one.connect()
    holding, release, returned = threading.Event(), threading.Event(), threading.Event()

    def hold_others_lock() -> None:  # as ``other.dispose()`` does while it closes connections
        with other._disposing:  # ruff: ignore[private-member-access]
            holding.set()
            release.wait(10.0)

    threading.Thread(target=hold_others_lock, daemon=True).start()
    holding.wait(5.0)
    threading.Thread(target=lambda: (late.close(), returned.set()), daemon=True).start()

    try:
        assert returned.wait(1.0)
    finally:
        release.set()
        returned.wait(5.0)
        one.dispose()
        other.dispose()


def test_a_return_inside_the_pools_own_dispose_lock_does_not_deadlock(
    database: PostgresDatabase,
) -> None:
    engine = create_engine(database.url, poolclass=ClosingQueuePool)
    pool = engine.pool
    assert isinstance(pool, ClosingQueuePool)
    late = engine.connect()
    done = threading.Event()

    def return_holding_the_lock() -> None:
        with pool._disposing:  # ruff: ignore[private-member-access]
            late.close()
        done.set()

    threading.Thread(target=return_holding_the_lock, daemon=True).start()

    assert done.wait(5.0)
    engine.dispose()


def test_a_plain_queue_pool_leaves_it_open(database: PostgresDatabase) -> None:
    """Why ``ClosingQueuePool`` exists: the default pool keeps a late connection open."""
    engine = create_engine(database.url, poolclass=QueuePool)
    late = engine.connect()
    raw = late.connection.dbapi_connection

    engine.dispose()
    late.close()

    assert raw is not None
    assert not raw.closed
    raw.close()


def test_a_connection_returned_before_dispose_is_pooled_then_closed(
    database: PostgresDatabase,
) -> None:
    engine = create_engine(database.url, poolclass=ClosingQueuePool)
    with engine.connect() as first:
        raw = first.connection.dbapi_connection
    with engine.connect() as again:
        reused = again.connection.dbapi_connection

    engine.dispose()

    assert reused is raw
    assert raw is not None
    assert raw.closed


@pytest.mark.usefixtures("on_postgres")
def test_the_job_worker_on_postgres_gets_the_closing_pool() -> None:
    container = Container.build(Settings())

    assert container.job_worker.engine_options.get("poolclass") is ClosingQueuePool


class _NoLibraryIds:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return False


class _NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


async def _step() -> None:
    """A step with nothing to do: only recording its result touches the database."""


async def _record_a_step(_job: Job, _progress: JobProgress) -> None:
    await DBOS.run_step_async({"name": "blocked"}, _step)


def _others(admin: psycopg.Connection, *, waiting: bool = False) -> int:
    """Count the other sessions on the database (only those waiting on a lock, if asked).

    Returns:
        The number of those sessions.
    """
    query = (
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        " AND pid <> pg_backend_pid()"
    )
    if waiting:
        query += " AND wait_event_type = 'Lock'"
    row = admin.execute(query).fetchone()
    assert row is not None
    return row[0]


async def _until(check: Callable[[], bool], what: str) -> None:
    """Poll ``check`` in a thread until it is true, or fail."""
    deadline = asyncio.get_running_loop().time() + WAIT
    while not await asyncio.to_thread(check):
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail(f"timed out waiting until {what}")
        await asyncio.sleep(0.05)


async def test_a_step_still_recording_when_the_worker_stops_leaves_no_connection_open(
    database: PostgresDatabase, tmp_path: Path
) -> None:
    jobs = InMemoryJobRepository()
    module = IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=MissingGit(),
        library_ids=_NoLibraryIds(),
        libraries=_NoLibraries(),
        removals=NoRemovals(),
        index=NoIndex(),
        handlers={STEP: _record_a_step},
        recovery_hooks={},
        runner=DbosJobQueue(),
    )
    worker = DbosJobWorker(
        run_job=module.run_job,
        recover_jobs=module.recover_jobs,
        submit_queued_jobs=module.submit_queued_jobs,
        database=tmp_path / "unused.sqlite",
        system_database_url=database.url,
        queue=QUEUE,
        workflow=WORKFLOW,
        version=STEPS_VERSION,
        engine_options={"poolclass": ClosingQueuePool},
        concurrency=1,
        stop_grace=0.05,
        poll_interval=0.01,
    )
    with psycopg.connect(libpq(database)) as admin:
        admin.autocommit = True
        async with worker.running():
            locker = await asyncio.to_thread(psycopg.connect, libpq(database))
            try:
                # Hold the table the step's result goes to: DBOS's thread waits on it, holding
                # a pooled connection, until the worker has stopped and DBOS disposed its engine.
                locker.execute("LOCK TABLE dbos.operation_outputs IN EXCLUSIVE MODE")
                await module.enqueue_job(EnqueueJobCommand(kind="import", library="/a/b"))
                await _until(lambda: _others(admin, waiting=True) > 0, "the step waits")
            except BaseException:
                locker.close()
                raise
        locker.rollback()
        locker.close()

        await _until(lambda: _others(admin) == 0, "DBOS's late connection is closed")
