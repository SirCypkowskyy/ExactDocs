"""Adapter contract: every ``FailedSignInLog`` behaves the same, whatever keeps the counts."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryFailedSignInLog
from exactdocs.identity.adapters.driven.sqlite import SqliteFailedSignInLog
from exactdocs.identity.constants import (
    FIRST_WAIT,
    FORGET_FAILURES_AFTER,
    FREE_FAILURES,
    REMEMBER_SIGN_INS_FOR,
)
from exactdocs.identity.models import FailedSignIns
from exactdocs.identity.ports import FailedSignInLog

START = datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC)
LATER = START + timedelta(seconds=1)


@asynccontextmanager
async def _sql_log(request: pytest.FixtureRequest) -> AsyncGenerator[SqliteFailedSignInLog]:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteFailedSignInLog(engine=container.engine)


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def log(request: pytest.FixtureRequest) -> AsyncIterator[FailedSignInLog]:
    if request.param == "memory":
        yield InMemoryFailedSignInLog()
        return
    async with _sql_log(request) as sql:
        yield sql


@pytest.fixture(params=SQL_BACKENDS)
async def sql_log(request: pytest.FixtureRequest) -> AsyncIterator[SqliteFailedSignInLog]:
    async with _sql_log(request) as sql:
        yield sql


async def test_an_unknown_key_has_no_record(log: FailedSignInLog) -> None:
    assert await log.get("address:a") is None


async def test_a_charge_against_no_key_goes_ahead(log: FailedSignInLog) -> None:
    assert await log.charge([], START) == timedelta(0)


async def test_each_charge_counts_once_against_every_key(log: FailedSignInLog) -> None:
    await log.charge(["address:a", "username:ada"], START)
    await log.charge(["address:a"], LATER)

    assert await log.get("address:a") == FailedSignIns(count=2, last_at=LATER, previous_at=START)
    assert await log.get("username:ada") == FailedSignIns(count=1, last_at=START)


async def test_a_refused_charge_counts_nothing(log: FailedSignInLog) -> None:
    for _ in range(FREE_FAILURES):
        assert await log.charge(["address:a"], START) == timedelta(0)

    assert await log.charge(["address:a", "username:b"], START) == FIRST_WAIT
    assert await log.get("username:b") is None
    record = await log.get("address:a")
    assert record is not None
    assert record.count == FREE_FAILURES


async def test_a_charge_after_a_quiet_hour_starts_a_fresh_count(log: FailedSignInLog) -> None:
    for _ in range(FREE_FAILURES):
        await log.charge(["address:a"], START)
    later = START + FORGET_FAILURES_AFTER

    assert await log.charge(["address:a"], later) == timedelta(0)
    assert await log.get("address:a") == FailedSignIns(count=1, last_at=later)


async def test_a_refund_after_a_later_attempt_only_lowers_the_count(log: FailedSignInLog) -> None:
    await log.charge(["address:a"], START)
    await log.charge(["address:a"], LATER)

    await log.refund("address:a", START)  # the first attempt was the right password

    record = await log.get("address:a")
    assert record is not None
    assert (record.count, record.last_at) == (1, LATER)


async def test_a_refund_of_the_latest_attempt_puts_its_wait_back(log: FailedSignInLog) -> None:
    await log.charge(["address:a"], START)
    await log.charge(["address:a"], LATER)

    await log.refund("address:a", LATER)

    assert await log.get("address:a") == FailedSignIns(count=1, last_at=START)


async def test_refunding_the_only_attempt_leaves_no_record(log: FailedSignInLog) -> None:
    await log.charge(["address:a"], START)

    await log.refund("address:a", START)
    await log.refund("address:b", START)  # nothing to refund: nothing happens

    assert await log.get("address:a") is None


async def test_forget_drops_one_record_and_tolerates_a_missing_one(log: FailedSignInLog) -> None:
    await log.charge(["address:a", "username:ada"], START)

    await log.forget("username:ada")
    await log.forget("username:ada")

    assert await log.get("username:ada") is None
    assert await log.get("address:a") is not None


async def test_a_sign_in_is_remembered_for_a_while(log: FailedSignInLog) -> None:
    await log.remember_sign_in("ada@address:a", START)

    assert await log.signed_in_before("ada@address:a", START + timedelta(days=1))
    assert not await log.signed_in_before("ada@address:b", START)
    assert not await log.signed_in_before("ada@address:a", START + REMEMBER_SIGN_INS_FOR)


async def test_a_new_sign_in_renews_the_memory(log: FailedSignInLog) -> None:
    await log.remember_sign_in("ada@address:a", START)
    renewed = START + timedelta(days=20)

    await log.remember_sign_in("ada@address:a", renewed)

    assert await log.signed_in_before("ada@address:a", renewed + timedelta(days=20))


async def test_a_concurrent_burst_is_counted_no_further_than_the_free_ones(
    log: FailedSignInLog,
) -> None:
    waits = await asyncio.gather(
        *(log.charge(["address:a", "username:ada"], START) for _ in range(3 * FREE_FAILURES))
    )

    assert waits.count(timedelta(0)) == FREE_FAILURES
    for key in ("address:a", "username:ada"):
        record = await log.get(key)
        assert record is not None
        assert record.count == FREE_FAILURES


async def test_two_logs_on_one_database_share_their_counts(sql_log: SqliteFailedSignInLog) -> None:
    other = SqliteFailedSignInLog(engine=sql_log.engine)  # as another process would see it
    for n in range(FREE_FAILURES):
        await (sql_log, other)[n % 2].charge(["address:a"], START)

    assert await sql_log.charge(["address:a"], START) == FIRST_WAIT
    assert await other.charge(["address:a"], START) == FIRST_WAIT


async def test_old_failures_are_pruned_when_another_is_counted(
    sql_log: SqliteFailedSignInLog,
) -> None:
    for _ in range(FREE_FAILURES):
        await sql_log.charge(["address:old"], START)
    await sql_log.charge(["address:recent"], START + timedelta(minutes=30))

    await sql_log.charge(["address:new"], START + FORGET_FAILURES_AFTER)

    assert await sql_log.get("address:old") is None
    assert await sql_log.get("address:recent") is not None


async def test_old_sign_ins_are_pruned_when_another_is_remembered(
    sql_log: SqliteFailedSignInLog,
) -> None:
    await sql_log.remember_sign_in("ada@address:old", START)
    await sql_log.remember_sign_in("ada@address:recent", START + timedelta(days=1))

    await sql_log.remember_sign_in("ada@address:new", START + REMEMBER_SIGN_INS_FOR)

    async with sql_log.engine.connect() as connection:
        rows = await connection.execute(text("SELECT key FROM identity_known_sign_ins"))
    assert {key for (key,) in rows} == {"ada@address:recent", "ada@address:new"}


@pytest.fixture(params=[backend for backend in SQL_BACKENDS if backend == "postgres"])
async def postgres_log(request: pytest.FixtureRequest) -> AsyncIterator[SqliteFailedSignInLog]:
    async with _sql_log(request) as sql:
        yield sql


async def test_a_flood_on_one_username_leaves_the_pool_to_other_queries(
    sql_log: SqliteFailedSignInLog,
) -> None:
    engine = sql_log.engine
    other = SqliteFailedSignInLog(engine=engine)  # another process, holding the username's turn
    async with other._turn(["username:admin"]):  # ruff: ignore[private-member-access]
        flood = [
            asyncio.create_task(sql_log.charge([f"address:10.0.0.{n}", "username:admin"], START))
            for n in range(40)  # more than the pool's 5 connections and 10 of overflow
        ]
        await asyncio.sleep(0.2)  # every attempt is now waiting its turn
        pool = engine.pool
        assert isinstance(pool, QueuePool)
        checked_out = pool.checkedout()
        async with asyncio.timeout(1), engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar() == 1
    waits = await asyncio.gather(*flood)

    assert checked_out <= 2  # the holder's connection and the one attempt in the database
    assert waits.count(timedelta(0)) == FREE_FAILURES


async def test_a_charge_that_waits_too_long_for_its_turn_is_refused_uncounted(
    sql_log: SqliteFailedSignInLog,
) -> None:
    impatient = SqliteFailedSignInLog(engine=sql_log.engine, turn_timeout=timedelta(seconds=0.2))
    async with impatient._turn(["username:ada"]):  # ruff: ignore[private-member-access]
        wait = await impatient.charge(["address:a", "username:ada"], START)

    assert wait == impatient.turn_timeout
    assert await impatient.get("address:a") is None
    assert await impatient.get("username:ada") is None


async def test_a_charge_that_waits_too_long_for_another_process_is_refused_uncounted(
    postgres_log: SqliteFailedSignInLog,
) -> None:
    impatient = SqliteFailedSignInLog(
        engine=postgres_log.engine, turn_timeout=timedelta(seconds=0.2)
    )
    async with postgres_log._turn(["username:ada"]):  # ruff: ignore[private-member-access]
        wait = await impatient.charge(["address:a", "username:ada"], START)

    assert wait == impatient.turn_timeout  # PostgreSQL's lock_timeout ran out: fail closed
    assert await impatient.get("address:a") is None


async def test_forget_waits_for_a_charge_holding_the_turn(sql_log: SqliteFailedSignInLog) -> None:
    other = SqliteFailedSignInLog(engine=sql_log.engine)  # the right password, on another process
    await sql_log.charge(["username:ada"], START)
    async with sql_log._turn(["username:ada"]) as connection:  # ruff: ignore[private-member-access]
        forgetting = asyncio.create_task(other.forget("username:ada"))
        await asyncio.sleep(0.2)
        assert not forgetting.done()
        mid_charge = {"username:ada": FailedSignIns(count=2, last_at=LATER)}
        await sql_log._replace(connection, mid_charge)
    await forgetting

    assert await sql_log.get("username:ada") is None
