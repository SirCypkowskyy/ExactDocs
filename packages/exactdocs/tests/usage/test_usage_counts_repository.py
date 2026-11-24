"""Adapter contract: every ``UsageCounts`` store behaves the same (memory, SQLite, PostgreSQL)."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.usage.adapters.driven.memory import InMemoryUsageCounts
from exactdocs.usage.adapters.driven.sqlite import SqliteUsageCounts
from exactdocs.usage.models import Dimension, Operation, UsageKey, UsageSelection, UsageSum
from exactdocs.usage.ports import UsageCounts

DAY = date(2026, 11, 23)
FIRST = DAY - timedelta(days=6)
ALICE, BOB = "id-alice", "id-bob"
ACME, BETA = "/acme/docs", "/beta/docs"


def key(
    day: date = DAY,
    *,
    account: str = ALICE,
    token: str = "",
    library: str = ACME,
    operation: Operation = Operation.READ,
) -> UsageKey:
    return UsageKey(day=day, account=account, token=token, library=library, operation=operation)


def week(
    *by: Dimension,
    account: str | None = None,
    library: str | None = None,
    operation: Operation | None = None,
) -> UsageSelection:
    return UsageSelection(
        first=FIRST,
        last=DAY,
        by=frozenset(by),
        account=account,
        library=library,
        operation=operation,
    )


def found(sums: Sequence[UsageSum]) -> set[UsageSum]:
    return set(sums)


@dataclass(frozen=True, slots=True, kw_only=True)
class Store:
    counts: UsageCounts
    container: Container | None = None


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "memory":
        yield Store(counts=InMemoryUsageCounts())
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield Store(counts=SqliteUsageCounts(engine=container.engine), container=container)


async def test_nothing_counted_sums_to_nothing(store: Store) -> None:
    assert await store.counts.sums(week()) == []
    assert await store.counts.sums(week(Dimension.LIBRARY)) == []


async def test_adding_to_a_counter_again_adds_up(store: Store) -> None:
    await store.counts.add({key(): 2, key(operation=Operation.SEARCH): 1})
    await store.counts.add({key(): 3})
    await store.counts.add({})
    await store.counts.add({key(account=BOB): 0})  # a zero creates no counter

    assert found(await store.counts.sums(week(Dimension.OPERATION))) == {
        UsageSum(count=5, operation=Operation.READ),
        UsageSum(count=1, operation=Operation.SEARCH),
    }
    assert found(await store.counts.sums(week(Dimension.ACCOUNT))) == {
        UsageSum(count=6, account=ALICE)
    }


async def test_the_counts_are_summed_by_every_column(store: Store) -> None:
    await store.counts.add(
        {
            key(): 2,
            key(day=DAY - timedelta(days=1), token="tok-a"): 3,
            key(account=BOB, library=BETA, operation=Operation.ANSWER): 4,
            key(account="", library="", operation=Operation.SEARCH): 5,
        }
    )

    assert await store.counts.sums(week()) == [UsageSum(count=14)]
    assert found(await store.counts.sums(week(Dimension.DAY))) == {
        UsageSum(count=11, day=DAY),
        UsageSum(count=3, day=DAY - timedelta(days=1)),
    }
    assert found(await store.counts.sums(week(Dimension.CREDENTIAL, Dimension.ACCOUNT))) == {
        UsageSum(count=2, account=ALICE, token=""),
        UsageSum(count=3, account=ALICE, token="tok-a"),
        UsageSum(count=4, account=BOB, token=""),
        UsageSum(count=5, account="", token=""),
    }
    assert found(await store.counts.sums(week(Dimension.LIBRARY, Dimension.OPERATION))) == {
        UsageSum(count=5, library=ACME, operation=Operation.READ),
        UsageSum(count=4, library=BETA, operation=Operation.ANSWER),
        UsageSum(count=5, library="", operation=Operation.SEARCH),
    }
    every = found(await store.counts.sums(week(*Dimension)))
    assert (
        UsageSum(
            count=3,
            day=DAY - timedelta(days=1),
            account=ALICE,
            token="tok-a",
            library=ACME,
            operation=Operation.READ,
        )
        in every
    )
    assert len(every) == 4


async def test_the_filters_and_the_days_narrow_the_sums(store: Store) -> None:
    await store.counts.add(
        {
            key(): 1,
            key(day=FIRST): 2,
            key(day=FIRST - timedelta(days=1)): 4,  # the day before the range
            key(day=DAY + timedelta(days=1)): 8,  # the day after
            key(account=BOB): 16,
            key(library=BETA): 32,
            key(operation=Operation.SEARCH): 64,
        }
    )

    assert await store.counts.sums(week(account=ALICE, library=ACME, operation=Operation.READ)) == [
        UsageSum(count=3)
    ]
    assert await store.counts.sums(week(account=BOB)) == [UsageSum(count=16)]
    assert await store.counts.sums(week(library=BETA)) == [UsageSum(count=32)]
    assert await store.counts.sums(week(operation=Operation.SEARCH)) == [UsageSum(count=64)]
    one_day = UsageSelection(first=DAY + timedelta(days=1), last=DAY + timedelta(days=1))
    assert await store.counts.sums(one_day) == [UsageSum(count=8)]


async def test_pruning_deletes_only_the_days_before_the_first_kept(store: Store) -> None:
    await store.counts.add(
        {
            key(day=FIRST - timedelta(days=1)): 1,
            key(day=FIRST - timedelta(days=400), account=BOB): 1,
            key(day=FIRST): 2,
            key(): 3,
        }
    )

    assert await store.counts.prune(FIRST) == 2
    assert await store.counts.prune(FIRST) == 0
    assert found(await store.counts.sums(week(Dimension.DAY))) == {
        UsageSum(count=2, day=FIRST),
        UsageSum(count=3, day=DAY),
    }


async def test_concurrent_writes_to_the_same_counters_lose_nothing(store: Store) -> None:
    keys = [key(), key(account=BOB), key(library=BETA, operation=Operation.SEARCH)]

    await asyncio.gather(*(store.counts.add(dict.fromkeys(keys, 1)) for _ in range(20)))

    assert found(await store.counts.sums(week(Dimension.ACCOUNT, Dimension.LIBRARY))) == {
        UsageSum(count=20, account=ALICE, library=ACME),
        UsageSum(count=20, account=BOB, library=ACME),
        UsageSum(count=20, account=ALICE, library=BETA),
    }


async def test_a_large_write_is_split_into_statements_and_kept_whole(store: Store) -> None:
    many = {key(account=f"id-{n:04d}"): n + 1 for n in range(1_201)}

    await store.counts.add(many)

    assert await store.counts.sums(week()) == [UsageSum(count=sum(many.values()))]
    assert len(await store.counts.sums(week(Dimension.ACCOUNT))) == 1_201


async def test_only_counts_are_stored_never_text(store: Store) -> None:
    if store.container is None:
        pytest.skip("only a database has columns")
    await store.counts.add({key(token="tok-a"): 1})

    async with store.container.engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM usage_daily_counts"))).mappings()
        stored = [dict(row) for row in rows]

    assert stored == [
        {
            "day": "2026-11-23",
            "account_id": ALICE,
            "token_id": "tok-a",
            "library": ACME,
            "operation": "read",
            "requests": 1,
        }
    ]


async def test_an_operation_a_newer_release_counts_is_left_out(store: Store) -> None:
    if store.container is None:
        pytest.skip("only a database keeps rows written by a newer release")
    await store.counts.add({key(): 2})
    async with store.container.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO usage_daily_counts"
                " (day, account_id, token_id, library, operation, requests)"
                " VALUES ('2026-11-23', 'id-alice', '', '/acme/docs', 'browse', 7)"
            )
        )

    assert await store.counts.sums(week(Dimension.OPERATION)) == [
        UsageSum(count=2, operation=Operation.READ)
    ]
