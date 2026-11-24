"""#511: operators read one scope's AI spend per UTC day or month, zero-filled, in a bounded range.

The history reads the same ledger rows the budgets and ``GET /ai/usage`` read; it adds nothing to
them.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from exactdocs.retrieval.adapters.driven.memory import (
    InMemoryChunkRepository,
    InMemoryLibraries,
    InMemoryLibraryModes,
    InMemorySearchIndex,
    InMemorySpendLedger,
)
from exactdocs.retrieval.constants import (
    SPEND_HISTORY_MAX_DAYS,
    SPEND_HISTORY_MAX_MONTHS,
    SPEND_SCOPE_KINDS,
)
from exactdocs.retrieval.dtos import SpendHistoryOut, SpendHistoryQuery, SpendScope
from exactdocs.retrieval.errors import InvalidSpendHistoryError
from exactdocs.retrieval.models import (
    DocTarget,
    ManifestStatus,
    SearchableVersion,
    SpendEntry,
    SpendHistorySpan,
    SpendWindow,
)
from exactdocs.retrieval.module import RetrievalModule

DAY, MONTH = SpendWindow.DAY, SpendWindow.MONTH
NOW = datetime(2026, 11, 23, 22, 30, tzinfo=UTC)
USD = 1_000_000


@dataclass(slots=True)
class Clock:
    at: datetime = NOW

    def now(self) -> datetime:
        return self.at


class NoVersions:
    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del library, ref

    async def all(self) -> list[SearchableVersion]:
        return []

    async def active_id(self, target: DocTarget) -> None:
        del target

    async def statuses(self, manifest_ids: object) -> dict[str, ManifestStatus]:
        del manifest_ids
        return {}


@dataclass(slots=True)
class World:
    module: RetrievalModule
    ledger: InMemorySpendLedger
    clock: Clock

    async def spend(
        self, kind: str, scope_id: str, day: date, *, calls: int = 1, local: int = 0
    ) -> None:
        """Book ``calls`` calls on a day, to its day and its month, as a real call is booked."""
        for _ in range(calls):
            await self.ledger.add(
                [
                    SpendEntry(
                        scope_kind=kind,
                        scope_id=scope_id,
                        window=window,
                        window_start=window.containing(day),
                        input_tokens=600,
                        output_tokens=400,
                        local_tokens=local,
                        requests=1,
                        usd_micros=USD,
                    )
                    for window in SpendWindow
                ]
            )

    async def history(self, **query: object) -> SpendHistoryOut:
        return await self.module.get_spend_history(SpendHistoryQuery.model_validate(query))


@pytest.fixture
def world() -> World:
    chunks = InMemoryChunkRepository()
    index = InMemorySearchIndex(chunks=chunks)
    versions = NoVersions()
    ledger = InMemorySpendLedger()
    clock = Clock()
    module = RetrievalModule.build(
        defaults=versions,
        libraries=InMemoryLibraries(),
        searchable=versions,
        manifests=versions,
        chunks=chunks,
        search=index,
        maintenance=index,
        library_modes=InMemoryLibraryModes(),
        spend=ledger,
        clock=clock,
    )
    return World(module=module, ledger=ledger, clock=clock)


def _spent(history: SpendHistoryOut) -> dict[date, tuple[int, int, float]]:
    return {e.window_start: (e.tokens, e.requests, e.usd) for e in history.entries}


# ---------------------------------------------------------------- per day and month


async def test_each_day_of_the_range_has_one_entry_and_a_day_without_spend_shows_zero(
    world: World,
) -> None:
    await world.spend("instance", "", date(2026, 11, 3))
    await world.spend("instance", "", date(2026, 11, 20), calls=2)
    await world.spend("instance", "", date(2026, 10, 31))  # before the range
    await world.spend("user", "account-ada", date(2026, 11, 5))  # another scope

    history = await world.history(scope="instance", first="2026-11-01", last="2026-11-23")

    assert (history.scope, history.id, history.window) == ("instance", "", DAY)
    assert (history.first, history.last) == (date(2026, 11, 1), date(2026, 11, 23))
    spent = _spent(history)
    assert list(spent) == [date(2026, 11, d) for d in range(1, 24)]
    assert spent[date(2026, 11, 3)] == (1000, 1, 1.0)
    assert spent[date(2026, 11, 20)] == (2000, 2, 2.0)
    others = {d: s for d, s in spent.items() if d not in {date(2026, 11, 3), date(2026, 11, 20)}}
    assert set(others.values()) == {(0, 0, 0.0)}


async def test_an_entry_carries_every_counter_of_the_usage(world: World) -> None:
    await world.spend("instance", "", date(2026, 11, 3), local=100)

    history = await world.history(first="2026-11-03", last="2026-11-03")

    (entry,) = history.entries
    assert entry.model_dump() == {
        "input_tokens": 600,
        "output_tokens": 400,
        "tokens": 900,
        "local_tokens": 100,
        "requests": 1,
        "usd": 1.0,
        "unpriced_requests": 0,
        "window_start": date(2026, 11, 3),
    }


async def test_months_are_their_own_rows_and_any_day_stands_for_its_month(world: World) -> None:
    await world.spend("embedding", "", date(2025, 12, 31))
    await world.spend("embedding", "", date(2026, 2, 1), calls=3)
    await world.spend("embedding", "", date(2026, 2, 28))

    history = await world.history(
        scope="embedding", window="month", first="2025-11-15", last="2026-02-02"
    )

    assert (history.first, history.last) == (date(2025, 11, 1), date(2026, 2, 1))
    assert _spent(history) == {
        date(2025, 11, 1): (0, 0, 0.0),
        date(2025, 12, 1): (1000, 1, 1.0),
        date(2026, 1, 1): (0, 0, 0.0),
        date(2026, 2, 1): (4000, 4, 4.0),
    }


async def test_a_library_is_named_in_any_letter_case_and_an_account_as_it_is(
    world: World,
) -> None:
    await world.spend("library", "/acme/payments", date(2026, 11, 23))
    await world.spend("user", "Account-Ada", date(2026, 11, 23))

    library = await world.history(scope="library", id="/Acme/Payments", first="2026-11-23")
    user = await world.history(scope="user", id="Account-Ada", first="2026-11-23")
    other = await world.history(scope="user", id="account-ada", first="2026-11-23")

    assert (library.id, _spent(library)) == ("/acme/payments", {NOW.date(): (1000, 1, 1.0)})
    assert _spent(user) == {NOW.date(): (1000, 1, 1.0)}
    assert _spent(other) == {NOW.date(): (0, 0, 0.0)}


# ---------------------------------------------------------------- defaults


@pytest.mark.parametrize(
    ("query", "first", "last"),
    [
        ({}, date(2026, 10, 25), date(2026, 11, 23)),  # 30 days ending today
        ({"window": "month"}, date(2025, 12, 1), date(2026, 11, 1)),  # 12 months ending now
        ({"last": "2026-02-10"}, date(2026, 1, 12), date(2026, 2, 10)),
        ({"window": "month", "last": "2026-02-10"}, date(2025, 3, 1), date(2026, 2, 1)),
        ({"first": "2026-11-20"}, date(2026, 11, 20), date(2026, 11, 23)),  # until today
        ({"first": "2027-01-01", "last": "2027-01-02"}, date(2027, 1, 1), date(2027, 1, 2)),
    ],
)
async def test_without_from_or_to_the_range_defaults_around_today(
    world: World, query: dict[str, str], first: date, last: date
) -> None:
    history = await world.history(**query)

    assert (history.first, history.last) == (first, last)
    assert len(history.entries) == history.window.windows_between(first, last)


async def test_today_is_the_utc_day(world: World) -> None:
    world.clock.at = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)

    history = await world.history(window="month")

    assert history.last == date(2026, 12, 1)
    assert len(history.entries) == 12


# ---------------------------------------------------------------- the bound


@pytest.mark.parametrize(
    ("window", "first", "last"),
    [
        ("day", "2025-11-23", "2026-11-23"),  # 366 days
        ("month", "2021-12-01", "2026-11-01"),  # 60 months
    ],
)
async def test_the_longest_range_is_shown(world: World, window: str, first: str, last: str) -> None:
    history = await world.history(window=window, first=first, last=last)

    most = SPEND_HISTORY_MAX_DAYS if window == "day" else SPEND_HISTORY_MAX_MONTHS
    assert len(history.entries) == most


@pytest.mark.parametrize(
    ("query", "says"),
    [
        ({"first": "2025-11-22", "last": "2026-11-23"}, "367 days asked for, at most 366"),
        ({"window": "month", "first": "2021-11-30", "last": "2026-11-01"}, "61 months"),
        ({"first": "2026-11-23", "last": "2026-11-22"}, "before it starts"),
        ({"first": "2026-12-01"}, "before it starts"),  # from after today, no to
        ({"scope": "instance", "id": "x"}, "the instance scope takes no ID"),
        ({"scope": "embedding", "id": "x"}, "the embedding scope takes no ID"),
        ({"scope": "library"}, "the library scope needs an ID"),
        ({"scope": "user", "id": ""}, "the user scope needs an ID"),
        ({"last": "0001-01-05"}, "before year 1"),
    ],
)
async def test_a_range_that_cannot_be_shown_is_refused(
    world: World, query: dict[str, str], says: str
) -> None:
    with pytest.raises(InvalidSpendHistoryError, match=says) as refused:
        await world.history(**query)

    assert refused.value.code == "invalid_spend_history"


@pytest.mark.parametrize(
    "query",
    [{"scope": "team"}, {"window": "week"}, {"first": "2026-02-30"}, {"id": "x" * 257}],
)
def test_the_query_refuses_unknown_scopes_windows_and_dates(query: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SpendHistoryQuery.model_validate(query)


def test_a_span_is_made_of_window_starts() -> None:
    with pytest.raises(InvalidSpendHistoryError, match="does not start a month"):
        SpendHistorySpan(
            scope_kind="instance",
            scope_id="",
            window=MONTH,
            first=date(2026, 1, 2),
            last=date(2026, 2, 1),
        )


def test_the_scope_names_are_the_ledgers() -> None:
    assert set(get_args(SpendScope)) == SPEND_SCOPE_KINDS


def test_months_shift_and_count_across_years() -> None:
    assert MONTH.shift(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert MONTH.shift(date(2025, 12, 1), 14) == date(2027, 2, 1)
    assert MONTH.windows_between(date(2025, 12, 1), date(2027, 2, 1)) == 15
    assert DAY.windows_between(date(2024, 2, 28), date(2024, 3, 1)) == 3
