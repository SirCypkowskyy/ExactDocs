"""ExactDocs on PostgreSQL: what several processes sharing one database rely on.

Every test gets a new database (``on_postgres``). Without ``EXACTDOCS_TEST_POSTGRES_URL`` this
module is skipped as a whole; CI sets ``EXACTDOCS_REQUIRE_POSTGRES=1``, so there it always runs.
"""

import asyncio
import json
import signal
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Collection
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import ADMIN_URL, TERMINATE_WAIT_MS, PostgresDatabase
from exactdocs.bootstrap import database
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import (
    StartupError,
    WriteTurnTimeoutError,
    current_revision,
    migrate,
    open_database,
)
from exactdocs.bootstrap.executors import PostgresExecutorSlots
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.postgres import PostgresLibraryLocks
from exactdocs.ingestion.adapters.driving import dbos_worker
from exactdocs.ingestion.adapters.driving.dbos_worker import DbosJobWorker, SlotState
from exactdocs.retrieval.adapters.driven.memory import ReadOnlySpendLedger
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.models import SpendEntry, SpendWindow
from import_child import big_repository, page, run

if ADMIN_URL is None:
    pytest.skip("needs a PostgreSQL server (EXACTDOCS_TEST_POSTGRES_URL)", allow_module_level=True)

pytestmark = pytest.mark.usefixtures("on_postgres")

FILES = 200


@pytest.fixture
async def engines() -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """Two engines on the migrated database: as two processes would see it.

    Yields:
        The two engines; both are disposed afterwards.
    """
    first, second = open_database(Settings()), open_database(Settings())
    await migrate(first)
    yield first, second
    await first.dispose()
    await second.dispose()


async def test_processes_starting_together_migrate_once_and_agree() -> None:
    engines = [open_database(Settings()) for _ in range(3)]
    try:
        await asyncio.gather(*(migrate(engine) for engine in engines))
        revisions = {await current_revision(engine) for engine in engines}
    finally:
        for engine in engines:
            await engine.dispose()

    assert len(revisions) == 1
    assert None not in revisions


async def test_text_compares_and_sorts_by_code_point_whatever_the_locale(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, _ = engines
    async with engine.connect() as connection:
        other = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = current_schema() AND data_type = 'text'"
                " AND table_name ~ '^(catalog|identity|ingestion|retrieval)_'"
                " AND coalesce(collation_name, '') <> 'C'"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO catalog_libraries (id, title, description, source_url, host,"
                " settings) VALUES ('/a/b', 'x', '', 'u', 'git', '{}'),"
                " ('/A/c', 'x', '', 'u', 'git', '{}')"
            )
        )
        ordered = (
            await connection.execute(text("SELECT id FROM catalog_libraries ORDER BY id"))
        ).scalars()

        assert other == 0
        assert list(ordered) == ["/A/c", "/a/b"]  # SQLite's BINARY order: upper case first


async def test_a_write_transaction_waits_for_another_process_s(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = engines
    order: list[str] = []

    async def write(engine: AsyncEngine, name: str, hold: float) -> None:
        async with engine.execution_options(begin_immediate=True).begin() as connection:
            await connection.execute(text("SELECT 1"))
            order.append(f"{name} in")
            await asyncio.sleep(hold)
            order.append(f"{name} out")

    holder = asyncio.create_task(write(first, "a", 0.3))
    await asyncio.sleep(0.1)
    await write(second, "b", 0)
    await holder

    assert order == ["a in", "a out", "b in", "b out"]


async def test_a_library_s_lock_is_held_across_processes_and_per_purpose(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = engines
    tags_a = PostgresLibraryLocks(engine=first, purpose="tags")
    tags_b = PostgresLibraryLocks(engine=second, purpose="tags")
    settings_b = PostgresLibraryLocks(engine=second, purpose="settings")
    order: list[str] = []

    async def hold(locks: PostgresLibraryLocks, library: str, name: str, seconds: float) -> None:
        async with locks.of(library):
            order.append(f"{name} in")
            await asyncio.sleep(seconds)
            order.append(f"{name} out")

    holder = asyncio.create_task(hold(tags_a, "/Acme/Docs", "a", 0.4))
    await asyncio.sleep(0.1)
    # Another purpose and another library do not wait; the same library (any case) does.
    await hold(settings_b, "/acme/docs", "settings", 0)
    await hold(tags_b, "/other/lib", "other", 0)
    await hold(tags_b, "/acme/docs", "b", 0)
    await holder

    assert order == [
        "a in",
        "settings in",
        "settings out",
        "other in",
        "other out",
        "a out",
        "b in",
        "b out",
    ]


async def test_each_process_takes_the_lowest_free_executor_slot(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = (PostgresExecutorSlots(engine=e) for e in engines)

    async with first.claim() as one:
        async with second.claim() as two:
            assert (one, two) == ("exactdocs-0", "exactdocs-1")
            async with second.orphaned([one, two, "local", "exactdocs-x"]) as dead:
                assert list(dead) == []  # both alive: neither may be adopted
        async with first.orphaned([one, two]) as dead:
            assert list(dead) == ["exactdocs-1"]  # its process stopped
            async with second.claim() as again:
                assert again == "exactdocs-2"  # slot 1 is held while it is adopted
        async with second.claim() as again:
            assert again == "exactdocs-1"


async def test_an_import_killed_halfway_resumes_in_the_next_process(tmp_path: Path) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    log = tmp_path / "chunked.log"

    code, _, err = await run(str(tmp_path / "one"), url, commit, str(log), "120")
    assert code == -signal.SIGKILL, err
    log.unlink()
    # Another data directory: on PostgreSQL the jobs live in the database, not next to it.
    code, out, err = await run(str(tmp_path / "two"), url, "-", str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == [page(n) for n in range(121, FILES + 1)]
    job = json.loads(out)
    assert (job["state"], job["done"], job["total"]) == ("succeeded", FILES, FILES)
    assert job["articles"] == [page(n) for n in range(1, FILES + 1)]


async def test_the_jobs_of_a_process_that_never_comes_back_are_adopted(tmp_path: Path) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    log = tmp_path / "chunked.log"
    engine = open_database(Settings())
    await migrate(engine)
    try:
        # A live process holds slot 0, so the one that is killed runs as exactdocs-1.
        async with PostgresExecutorSlots(engine=engine).claim() as live:
            assert live == "exactdocs-0"
            code, _, err = await run(str(tmp_path / "one"), url, commit, str(log), "120")
        assert code == -signal.SIGKILL, err
    finally:
        await engine.dispose()
    log.unlink()
    # The next process takes slot 0: DBOS resumes nothing of its own, the worker adopts slot 1's.
    code, out, err = await run(str(tmp_path / "two"), url, "-", str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == [page(n) for n in range(121, FILES + 1)]
    job = json.loads(out)
    assert (job["state"], job["done"], job["total"]) == ("succeeded", FILES, FILES)
    assert job["articles"] == [page(n) for n in range(1, FILES + 1)]


def test_dbos_keeps_its_tables_in_the_configured_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_DBOS_SYSTEM_SCHEMA", "exactdocs_jobs")
    container = Container.build(Settings())

    worker = container.job_worker
    assert worker.system_database_url == container.engine.url.render_as_string(hide_password=False)
    assert worker.system_schema == "exactdocs_jobs"
    assert worker.database is None
    assert worker.executors is not None


def test_a_dbos_schema_must_be_a_plain_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_DBOS_SYSTEM_SCHEMA", 'dbos"; drop table x; --')
    with pytest.raises(ValueError, match="dbos_system_schema"):
        Settings()


async def test_the_stdio_server_refuses_an_empty_database() -> None:
    container = ReadOnlyContainer.build(Settings())
    with pytest.raises(StartupError, match="is empty"):
        async with container.running():
            pass


async def test_the_stdio_server_reads_postgresql_but_cannot_write_to_it() -> None:
    engine = open_database(Settings())
    await migrate(engine)
    await engine.dispose()
    container = ReadOnlyContainer.build(Settings())

    async with container.running(), container.engine.connect() as connection:
        with pytest.raises(DBAPIError, match="read-only transaction"):
            await connection.execute(text("DELETE FROM catalog_libraries"))


@pytest.mark.parametrize("cursor", ["AA", "am9iLQA"])  # "\x00" and "job-\x00"
async def test_a_job_list_cursor_holding_nul_is_a_422_not_a_server_error(
    demo_catalog: dict[str, str], cursor: str
) -> None:
    # PostgreSQL text cannot hold NUL: such a key must be refused before it reaches the query.
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", cookies=demo_catalog
        ) as client,
    ):
        response = await client.get(
            "/api/v1/libraries/acme/payments/jobs", params={"cursor": cursor}
        )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_cursor"


async def test_the_stdio_server_s_spend_reaches_the_shared_ledger_once_per_replay() -> None:
    server = open_database(Settings())
    await migrate(server)
    container = ReadOnlyContainer.build(Settings())
    spent = SpendEntry(
        scope_kind="instance",
        scope_id="",
        window=SpendWindow.DAY,
        window_start=date(2026, 11, 12),
        input_tokens=50,
        output_tokens=10,
        requests=1,
        token="response-1",
    )
    stdio = ReadOnlySpendLedger(
        shared=SqliteSpendLedger(engine=container.engine),
        writer=SqliteSpendLedger(engine=container.spend_engine),
    )
    try:
        async with container.running():
            await stdio.add([spent])
            await stdio.add([spent])  # a replay: counted once, as for a server
            async with container.engine.connect() as connection:  # every other write refused
                with pytest.raises(DBAPIError, match="read-only transaction"):
                    await connection.execute(text("DELETE FROM retrieval_ai_spend"))
        row = (await SqliteSpendLedger(engine=server).get([spent.key]))[spent.key]
    finally:
        await server.dispose()

    assert (row.input_tokens, row.output_tokens, row.requests) == (50, 10, 1)
    assert stdio.local.rows == {}, "nothing was kept in memory only"


async def test_collation_keeps_a_column_s_type_and_skips_what_generated_columns_read(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    engine, _ = engines
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE catalog_later (short varchar(5), read text,"
                " words tsvector GENERATED ALWAYS AS (to_tsvector('simple', read)) STORED)"
            )
        )
    await migrate(engine)  # as a later revision's columns would be collated

    async with engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name, data_type, character_maximum_length, collation_name"
                    " FROM information_schema.columns WHERE table_name = 'catalog_later'"
                    " AND column_name IN ('short', 'read') ORDER BY column_name"
                )
            )
        ).all()

    assert [tuple(c) for c in columns] == [
        ("read", "text", None, None),
        ("short", "character varying", 5, "C"),
    ]


async def test_a_writer_that_waits_too_long_for_its_turn_fails_clearly(
    engines: tuple[AsyncEngine, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "WRITE_LOCK_TIMEOUT_MS", 200)
    first, second = engines
    async with first.execution_options(begin_immediate=True).begin() as holder:
        await holder.execute(text("SELECT 1"))
        with pytest.raises(WriteTurnTimeoutError, match="write turn"):
            async with second.execution_options(begin_immediate=True).begin() as waiter:
                await waiter.execute(text("SELECT 1"))
    async with second.execution_options(begin_immediate=True).begin() as later:
        assert await later.scalar(text("SHOW lock_timeout")) == "0"  # only the turn waits


async def _drop_slot_connection(engine: AsyncEngine, slot: int) -> None:
    """Kill the backend that holds the slot, as a failover or an idle timeout would.

    Only this test's database is searched: another run on the same server holds slots of its own.
    Returns once the backend has exited, so its advisory lock is released by then.
    """
    async with engine.connect() as connection:
        killed = (
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(l.pid, :wait) FROM pg_locks l"
                    " JOIN pg_database d ON d.oid = l.database"
                    " WHERE d.datname = current_database() AND l.locktype = 'advisory'"
                    " AND l.classid = 1163412547 AND l.objid = :slot AND l.objsubid = 2"
                ),
                {"slot": slot, "wait": TERMINATE_WAIT_MS},
            )
        ).scalars()
        exited = list(killed)
        await connection.commit()
    assert exited == [True]  # one holder, gone within the wait


async def test_a_process_whose_slot_connection_died_takes_it_back_or_stops(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    first, second = (PostgresExecutorSlots(engine=e) for e in engines)

    async with first.claim() as mine:  # its release must not fail on a dead connection
        assert await first.keep() is SlotState.HELD
        await _drop_slot_connection(engines[0], 0)
        assert await first.keep() is SlotState.RETAKEN  # nobody took it meanwhile
        assert await first.keep() is SlotState.HELD

        await _drop_slot_connection(engines[0], 0)
        async with second.claim() as theirs:  # a process starting now gets the free slot
            assert theirs == mine
            assert await first.keep() is SlotState.LOST  # so this one must stop


def _allow_connections(database: str, *, allowed: bool) -> None:
    """Let connections into the database, or keep every new one out (an outage, seen from it)."""
    admin_url = make_url(ADMIN_URL or "").set(drivername="postgresql")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as a:
        a.execute(
            sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS {}").format(
                sql.Identifier(database), sql.Literal(allowed)
            )
        )


def _slot_worker(stopped: list[str], slots: PostgresExecutorSlots) -> DbosJobWorker:
    """A worker that only checks its slot here (no DBOS runs), with the production timings."""

    async def nothing(*_: object, **__: object) -> None:
        return None

    return DbosJobWorker(
        run_job=nothing,
        recover_jobs=nothing,
        submit_queued_jobs=nothing,
        system_database_url="postgresql+psycopg://unused/unused",
        executors=slots,
        queue="q",
        workflow="w",
        version="v",
        on_slot_lost=lambda: stopped.append("stop"),
    )


async def test_a_12_second_outage_is_waited_out(
    engines: tuple[AsyncEngine, AsyncEngine], on_postgres: PostgresDatabase
) -> None:
    stopped: list[str] = []
    slots = PostgresExecutorSlots(engine=engines[0])
    worker = _slot_worker(stopped, slots)

    async with slots.claim() as mine:
        assert await worker.check_slot(mine, slots) is SlotState.HELD
        _allow_connections(on_postgres.name, allowed=False)
        try:
            await _drop_slot_connection_as_admin(on_postgres.name)  # the slot's connection dies
            outage_ends = time.monotonic() + 12
            seen = set()
            while time.monotonic() < outage_ends:  # checks every slot_check_interval, as _watch
                seen.add(await worker.check_slot(mine, slots))
                await asyncio.sleep(worker.slot_check_interval)
        finally:
            _allow_connections(on_postgres.name, allowed=True)
        assert seen == {SlotState.UNKNOWN}
        assert await worker.check_slot(mine, slots) is SlotState.HELD  # taken back

    assert stopped == []


async def test_a_slot_another_process_took_stops_this_one_before_any_adoption(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    stopped: list[str] = []
    slots, other = (
        PostgresExecutorSlots(engine=engines[0]),
        PostgresExecutorSlots(engine=engines[1]),
    )
    worker = _slot_worker(stopped, slots)

    async with slots.claim() as mine:
        await _drop_slot_connection(engines[0], 0)  # its connection dies, the slot is free...
        async with other.claim() as theirs:  # ...and a process starting now takes it
            assert theirs == mine
            started = time.monotonic()
            assert await worker.check_slot(mine, slots) is SlotState.LOST
            assert stopped == ["stop"]
            # Stopped within one check and the halt, long before anyone adopts its jobs.
            assert time.monotonic() - started < worker.slot_check_timeout + worker.halt_timeout
            assert worker.slot_check_interval + worker.slot_check_timeout < worker.adopt_grace


class _NoDbos:
    """DBOS as far as the worker's start and stop need it: nothing runs, the launch is recorded."""

    launched = False
    on_launch: Callable[[], None] = staticmethod(lambda: None)

    def __init__(self, *, config: object) -> None:
        del config

    @staticmethod
    def workflow(*, name: str) -> Callable[[object], object]:
        del name
        return lambda function: function

    @classmethod
    def launch(cls) -> None:
        cls.launched = True
        cls.on_launch()

    @staticmethod
    async def register_queue_async(*_: object, **__: object) -> None:
        return None

    @staticmethod
    async def delete_schedule_async(*_: object) -> None:
        return None

    @staticmethod
    async def list_workflows_async(**_: object) -> list[object]:
        return []

    @staticmethod
    def destroy(**_: object) -> None:
        return None


class _Slots:
    """Real slots, with something done to them between the claim and the start, and the answers
    the worker got from ``keep`` recorded."""

    def __init__(
        self,
        slots: PostgresExecutorSlots,
        after_claim: Callable[[], AbstractAsyncContextManager[None]],
    ) -> None:
        self.slots = slots
        self.after_claim = after_claim
        self.answers: list[SlotState] = []
        self.watched = asyncio.Event()
        """Set at the second answer: the watchdog's first check, after the one before launch."""
        self.claim_grace = slots.claim_grace

    @asynccontextmanager
    async def claim(self) -> AsyncGenerator[str]:
        async with self.slots.claim() as mine, self.after_claim():
            yield mine

    async def keep(self) -> SlotState:
        answer = await self.slots.keep()
        self.answers.append(answer)
        if len(self.answers) >= 2:
            self.watched.set()
        return answer

    @asynccontextmanager
    async def orphaned(self, executor_ids: Collection[str]) -> AsyncGenerator[Collection[str]]:
        if not executor_ids:  # nothing to look at (no DBOS runs): no connection during an outage
            yield []
            return
        async with self.slots.orphaned(executor_ids) as dead:
            yield dead


def _starting_worker(stopped: list[str], slots: _Slots, now: list[float]) -> DbosJobWorker:
    """A worker that starts on the slots with a fake DBOS, the production timings and ``now``."""
    return replace(
        _slot_worker(stopped, PostgresExecutorSlots(engine=slots.slots.engine)),
        executors=slots,
        monotonic=lambda: now[0],
    )


async def test_a_slot_still_held_after_a_long_claim_is_confirmed_before_dbos_starts(
    engines: tuple[AsyncEngine, AsyncEngine],
    on_postgres: PostgresDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now, stopped = [0.0], []

    @asynccontextmanager
    async def claim_grace() -> AsyncGenerator[None]:
        now[0] += 15  # the claim waited claim_grace: the whole give-up time
        yield

    def outage() -> None:  # from DBOS's launch on, the database cannot be reached
        _allow_connections(on_postgres.name, allowed=False)
        _terminate_backends(on_postgres.name)

    monkeypatch.setattr(_NoDbos, "launched", False)
    monkeypatch.setattr(_NoDbos, "on_launch", staticmethod(outage))
    monkeypatch.setattr(dbos_worker, "DBOS", _NoDbos)
    slots = _Slots(PostgresExecutorSlots(engine=engines[0]), claim_grace)
    worker = _starting_worker(stopped, slots, now)

    try:
        async with worker.running(), asyncio.timeout(5):
            await slots.watched.wait()  # the watchdog's first check meets the outage
    finally:
        _allow_connections(on_postgres.name, allowed=True)

    # Held just before DBOS started: the give-up time counts from there, the outage is waited out.
    assert slots.answers[:2] == [SlotState.HELD, SlotState.UNKNOWN]
    assert stopped == []


async def test_a_slot_retaken_before_dbos_starts_is_kept(
    engines: tuple[AsyncEngine, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    now, stopped = [0.0], []

    @asynccontextmanager
    async def connection_dies() -> AsyncGenerator[None]:
        await _drop_slot_connection(engines[0], 0)
        yield

    monkeypatch.setattr(_NoDbos, "launched", False)
    monkeypatch.setattr(dbos_worker, "DBOS", _NoDbos)
    slots = _Slots(PostgresExecutorSlots(engine=engines[0]), connection_dies)
    worker = _starting_worker(stopped, slots, now)

    async with worker.running(), asyncio.timeout(5):
        await slots.watched.wait()

    # Taken again before DBOS started (nobody held it meanwhile), then held by the watchdog.
    assert slots.answers[:2] == [SlotState.RETAKEN, SlotState.HELD]
    assert (_NoDbos.launched, stopped) == (True, [])


async def test_a_slot_taken_by_another_process_before_dbos_starts_fails_the_start(
    engines: tuple[AsyncEngine, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    now, stopped = [0.0], []
    other = PostgresExecutorSlots(engine=engines[1])

    @asynccontextmanager
    async def taken_meanwhile() -> AsyncGenerator[None]:
        await _drop_slot_connection(engines[0], 0)  # its connection dies during the claim...
        async with other.claim() as theirs:  # ...and a process starting then takes the slot
            assert theirs == "exactdocs-0"
            yield

    monkeypatch.setattr(_NoDbos, "launched", False)
    monkeypatch.setattr(dbos_worker, "DBOS", _NoDbos)
    slots = _Slots(PostgresExecutorSlots(engine=engines[0]), taken_meanwhile)
    worker = _starting_worker(stopped, slots, now)

    with pytest.raises(RuntimeError, match="taken by another process before the job worker"):
        async with worker.running():
            pytest.fail("the worker started on a slot another process holds")

    # DBOS never launched: none of the other process's jobs was resumed or dequeued here.
    assert slots.answers == [SlotState.LOST]
    assert (_NoDbos.launched, stopped) == (False, [])


def _terminate_backends(database: str) -> None:
    """Kill every backend on the database, from outside it, and wait until they have exited."""
    admin_url = make_url(ADMIN_URL or "").set(drivername="postgresql")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as a:
        # Client backends only: an autovacuum or parallel worker may exit on its own first, and
        # pg_terminate_backend answers false for a pid that is already gone.
        exited = a.execute(
            "SELECT pid, pg_terminate_backend(pid, %s) FROM pg_stat_activity"
            " WHERE datname = %s AND backend_type = 'client backend'"
            " AND pid <> pg_backend_pid()",
            (TERMINATE_WAIT_MS, database),
        ).fetchall()
    stuck = [pid for pid, gone in exited if not gone]
    assert not stuck, f"backends still there after {TERMINATE_WAIT_MS} ms: {stuck}"


async def _drop_slot_connection_as_admin(database: str) -> None:
    """Kill every backend on the database, from outside it, and wait until they have exited."""
    await asyncio.to_thread(_terminate_backends, database)
