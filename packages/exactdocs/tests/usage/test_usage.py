"""Usage counts (#510): counting, writing, pruning, reports and leaderboards, in memory."""

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from exactdocs.usage import UsageModule
from exactdocs.usage.adapters.driven.memory import (
    InMemoryLibraryAccess,
    InMemoryPeople,
    InMemoryUsageCounts,
)
from exactdocs.usage.constants import NO_ACCOUNT, NO_LIBRARY, NO_TOKEN
from exactdocs.usage.dtos import (
    AccountUsageQuery,
    FlushUsageCommand,
    GetUsageSettingsQuery,
    PruneUsageCommand,
    RecordUsageCommand,
    UsageStatsQuery,
    ViewLeaderboardQuery,
)
from exactdocs.usage.errors import InvalidRetentionError, PeopleLeaderboardOffError
from exactdocs.usage.models import (
    Grouping,
    Metric,
    Operation,
    Period,
    Retention,
    Span,
    Subject,
    UsageKey,
    UsagePolicy,
    UsageSelection,
    UsageSum,
    UsageTally,
    counted_library,
    months_before,
    period_of,
    periods_until,
    previous_of,
    ranks,
)

# Monday 2026-11-23, noon UTC.
NOON = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
TODAY = NOON.date()
ALICE, BOB, CAROL = "id-alice", "id-bob", "id-carol"
ACME, BETA, GAMMA = "/acme/docs", "/beta/docs", "/gamma/docs"


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class FailingCounts:
    """A store whose writes fail until ``healed``; reads and prunes go to the memory store."""

    def __init__(self) -> None:
        self.inner = InMemoryUsageCounts()
        self.healed = False

    async def add(self, counts: Mapping[UsageKey, int]) -> None:
        if not self.healed:
            message = "database is locked"
            raise OSError(message)
        await self.inner.add(counts)

    async def sums(self, selection: UsageSelection) -> Sequence[UsageSum]:
        return await self.inner.sums(selection)

    async def prune(self, before: date) -> int:
        return await self.inner.prune(before)


class Stand:
    """A usage module on in-memory stores, with alice and carol opted in to the people board."""

    def __init__(
        self,
        *,
        people_board: bool = True,
        readable: Collection[str] | None = None,
        retention: int = 13,
        counts: Any = None,
    ) -> None:
        self.clock = Clock()
        self.counts = InMemoryUsageCounts() if counts is None else counts
        self.module = UsageModule.build(
            counts=self.counts,
            people=InMemoryPeople(people={ALICE: "alice", CAROL: "carol"}),
            libraries=InMemoryLibraryAccess(
                readable_libraries=None if readable is None else frozenset(readable)
            ),
            clock=self.clock,
            policy=UsagePolicy(
                people_leaderboard=people_board, retention=Retention(months=retention)
            ),
        )

    async def record(
        self,
        operation: Operation = Operation.READ,
        libraries: Sequence[str] = (ACME,),
        *,
        account: str | None = ALICE,
        token: str | None = None,
        times: int = 1,
    ) -> None:
        for _ in range(times):
            await self.module.record_usage(
                RecordUsageCommand(
                    operation=operation,
                    libraries=list(libraries),
                    account_id=account,
                    token_id=token,
                )
            )

    def seed(
        self,
        day: date,
        count: int,
        *,
        library: str = ACME,
        account: str = ALICE,
        operation: Operation = Operation.READ,
        token: str = NO_TOKEN,
    ) -> None:
        key = UsageKey(day=day, account=account, token=token, library=library, operation=operation)
        store = self.counts.inner if isinstance(self.counts, FailingCounts) else self.counts
        store.counts[key] = store.counts.get(key, 0) + count


# --- periods, in UTC


@pytest.mark.parametrize(
    ("period", "day", "first", "last"),
    [
        (Period.DAY, date(2026, 11, 23), date(2026, 11, 23), date(2026, 11, 23)),
        (Period.WEEK, date(2026, 11, 23), date(2026, 11, 23), date(2026, 11, 29)),
        (Period.WEEK, date(2026, 11, 29), date(2026, 11, 23), date(2026, 11, 29)),
        # ISO weeks cross the year: Thursday 2026-01-01 is in the week from Monday 2025-12-29.
        (Period.WEEK, date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 4)),
        (Period.MONTH, date(2026, 11, 23), date(2026, 11, 1), date(2026, 11, 30)),
        (Period.MONTH, date(2028, 2, 10), date(2028, 2, 1), date(2028, 2, 29)),
        (Period.YEAR, date(2026, 11, 23), date(2026, 1, 1), date(2026, 12, 31)),
    ],
)
def test_a_period_holds_its_calendar_days(
    period: Period, day: date, first: date, last: date
) -> None:
    assert period_of(period, day) == Span(first=first, last=last)


def test_the_previous_period_is_the_one_just_before() -> None:
    assert previous_of(Period.DAY, period_of(Period.DAY, TODAY)) == Span(
        first=date(2026, 11, 22), last=date(2026, 11, 22)
    )
    assert previous_of(Period.WEEK, period_of(Period.WEEK, TODAY)).first == date(2026, 11, 16)
    assert previous_of(Period.MONTH, period_of(Period.MONTH, date(2026, 3, 31))) == Span(
        first=date(2026, 2, 1), last=date(2026, 2, 28)
    )
    assert previous_of(Period.YEAR, period_of(Period.YEAR, TODAY)).first == date(2025, 1, 1)


def test_periods_until_are_consecutive_and_oldest_first() -> None:
    spans = periods_until(Period.MONTH, TODAY, 3)

    assert [span.first for span in spans] == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]
    assert spans[-1].last == date(2026, 11, 30)


# --- what is counted


def test_a_request_counts_to_its_one_library_or_to_none() -> None:
    assert counted_library(["/Acme/Docs"]) == ACME
    assert counted_library([ACME, "/ACME/docs"]) == ACME
    assert counted_library([ACME, BETA]) == NO_LIBRARY
    assert counted_library([]) == NO_LIBRARY


def test_only_counts_cross_the_boundary_never_what_was_asked() -> None:
    with pytest.raises(ValidationError):
        RecordUsageCommand.model_validate(
            {"operation": "search", "libraries": [ACME], "query": "how do I pay?"}
        )
    assert set(RecordUsageCommand.model_fields) == {
        "operation",
        "libraries",
        "account_id",
        "token_id",
    }
    assert set(UsageKey.__dataclass_fields__) == {
        "day",
        "account",
        "token",
        "library",
        "operation",
    }


async def test_each_request_is_counted_to_its_utc_day_account_token_library_and_operation() -> None:
    stand = Stand()
    await stand.record(token="tok-1", times=2)
    await stand.record(Operation.SEARCH, [ACME, BETA], token="tok-1")
    await stand.record(Operation.ANSWER, [], account=None)
    # 23:30 in New York on the 23rd is the 24th in UTC.
    stand.clock.at = datetime(2026, 11, 23, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    await stand.record(account=BOB)

    flushed = await stand.module.flush_usage(FlushUsageCommand())

    assert flushed.written == 4
    assert flushed.dropped == 0
    assert stand.counts.counts == {
        UsageKey(
            day=TODAY, account=ALICE, token="tok-1", library=ACME, operation=Operation.READ
        ): 2,
        UsageKey(
            day=TODAY, account=ALICE, token="tok-1", library=NO_LIBRARY, operation=Operation.SEARCH
        ): 1,
        UsageKey(
            day=TODAY,
            account=NO_ACCOUNT,
            token=NO_TOKEN,
            library=NO_LIBRARY,
            operation=Operation.ANSWER,
        ): 1,
        UsageKey(
            day=date(2026, 11, 24),
            account=BOB,
            token=NO_TOKEN,
            library=ACME,
            operation=Operation.READ,
        ): 1,
    }


# --- the tally and its write


def test_the_tally_drops_new_counters_past_its_limit_but_still_adds_to_known_ones() -> None:
    tally = UsageTally(limit=2)
    keys = [
        UsageKey(day=TODAY, account=a, token="", library=ACME, operation=Operation.READ)
        for a in (ALICE, BOB, CAROL)
    ]

    for key in keys:
        tally.add(key)
    tally.add(keys[0], 4)

    taken, dropped = tally.take()
    assert taken == {keys[0]: 5, keys[1]: 1}
    assert dropped == 1
    assert tally.take() == ({}, 0)


async def test_a_write_adds_to_the_stored_counts_and_empties_the_tally() -> None:
    stand = Stand()
    await stand.record(times=3)
    await stand.module.flush_usage(FlushUsageCommand())
    await stand.record(times=2)

    await stand.module.flush_usage(FlushUsageCommand())
    again = await stand.module.flush_usage(FlushUsageCommand())

    assert list(stand.counts.counts.values()) == [5]
    assert again.written == 0


async def test_counts_that_fail_to_write_are_kept_for_the_next_write() -> None:
    counts = FailingCounts()
    stand = Stand(counts=counts)
    await stand.record(times=2)

    with pytest.raises(OSError, match="locked"):
        await stand.module.flush_usage(FlushUsageCommand())
    await stand.record()
    counts.healed = True
    flushed = await stand.module.flush_usage(FlushUsageCommand())

    assert flushed.written == 1
    assert list(counts.inner.counts.values()) == [3]


async def test_a_report_includes_the_requests_not_written_yet() -> None:
    stand = Stand()
    await stand.record(times=2)

    own = await stand.module.get_account_usage(AccountUsageQuery(account_id=ALICE))

    assert own.total.reads == 2


async def test_a_report_still_answers_while_the_database_cannot_be_written() -> None:
    counts = FailingCounts()
    stand = Stand(counts=counts)
    stand.seed(TODAY, 4)
    await stand.record()

    own = await stand.module.get_account_usage(AccountUsageQuery(account_id=ALICE))

    assert own.total.reads == 4  # the stored ones; the pending one is written later
    counts.healed = True
    assert (await stand.module.flush_usage(FlushUsageCommand())).written == 1


# --- retention


def test_counts_are_kept_thirteen_months_by_default() -> None:
    assert Retention().months == 13
    assert Retention().first_kept(TODAY) == date(2025, 10, 23)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_before(date(2026, 1, 15), 1) == date(2025, 12, 15)


@pytest.mark.parametrize("months", [0, -1, 121])
def test_a_retention_out_of_bounds_is_refused(months: int) -> None:
    with pytest.raises(InvalidRetentionError) as raised:
        Retention(months=months)

    assert raised.value.code == "invalid_retention"


async def test_pruning_deletes_the_days_before_the_retention() -> None:
    stand = Stand(retention=2)
    stand.seed(date(2026, 9, 22), 1)
    stand.seed(date(2026, 9, 23), 2)
    stand.seed(TODAY, 3)

    pruned = await stand.module.prune_usage(PruneUsageCommand())

    assert pruned.first_kept == date(2026, 9, 23)
    assert pruned.deleted == 1
    assert sorted(key.day for key in stand.counts.counts) == [date(2026, 9, 23), TODAY]


# --- usage reports


async def test_the_series_has_one_bucket_per_period_zeros_included() -> None:
    stand = Stand()
    stand.seed(TODAY, 2)
    stand.seed(TODAY - timedelta(days=7), 5, operation=Operation.SEARCH)
    stand.seed(TODAY - timedelta(days=30), 9)  # before the three weeks asked

    stats = await stand.module.get_usage_stats(UsageStatsQuery(period=Period.WEEK, periods=3))

    assert [(b.start, b.reads, b.searches) for b in stats.series] == [
        (date(2026, 11, 9), 0, 0),
        (date(2026, 11, 16), 0, 5),
        (date(2026, 11, 23), 2, 0),
    ]
    assert (stats.since, stats.until) == (date(2026, 11, 9), date(2026, 11, 29))
    assert stats.total.model_dump() == {"reads": 2, "searches": 5, "answers": 0}
    assert stats.groups == []


@pytest.mark.parametrize(
    ("period", "count"), [("day", 30), ("week", 12), ("month", 12), ("year", 2)]
)
async def test_a_report_covers_a_default_number_of_periods(period: str, count: int) -> None:
    stats = await Stand().module.get_usage_stats(UsageStatsQuery(period=Period(period)))

    assert len(stats.series) == count
    assert stats.series[-1].start == period_of(Period(period), TODAY).first


async def test_the_usage_by_library_puts_multi_library_requests_under_none() -> None:
    stand = Stand()
    stand.seed(TODAY, 5, library=ACME)
    stand.seed(TODAY, 2, library=BETA, account=BOB)
    stand.seed(TODAY, 3, library=NO_LIBRARY, operation=Operation.SEARCH)

    stats = await stand.module.get_usage_stats(UsageStatsQuery(by=Grouping.LIBRARY))
    only_beta = await stand.module.get_usage_stats(
        UsageStatsQuery(by=Grouping.LIBRARY, library="/BETA/docs")
    )

    assert [(g.library, g.reads, g.searches) for g in stats.groups] == [
        (ACME, 5, 0),
        (BETA, 2, 0),
        (None, 0, 3),
    ]
    assert stats.groups_total == 3
    assert [(g.library, g.reads) for g in only_beta.groups] == [(BETA, 2)]
    assert only_beta.total.reads == 2


async def test_operators_see_people_by_name_only_when_the_board_is_on_and_they_opted_in() -> None:
    stand = Stand()
    stand.seed(TODAY, 5, account=ALICE)
    stand.seed(TODAY, 7, account=BOB)  # bob did not opt in
    stand.seed(TODAY, 1, account=NO_ACCOUNT)

    on = await stand.module.get_usage_stats(UsageStatsQuery(by=Grouping.ACCOUNT))
    off = await Stand(people_board=False, counts=stand.counts).module.get_usage_stats(
        UsageStatsQuery(by=Grouping.ACCOUNT)
    )

    assert [(g.account_id, g.username, g.reads, g.others) for g in on.groups] == [
        (ALICE, "alice", 5, False),
        (None, None, 8, True),
    ]
    assert [(g.account_id, g.reads, g.others) for g in off.groups] == [(None, 13, True)]
    assert on.total.reads == off.total.reads == 13


async def test_the_usage_by_token_names_the_tokens_of_people_shown_by_name() -> None:
    stand = Stand()
    stand.seed(TODAY, 3, account=ALICE, token="tok-a")
    stand.seed(TODAY, 1, account=ALICE)
    stand.seed(TODAY, 4, account=BOB, token="tok-b")

    stats = await stand.module.get_usage_stats(UsageStatsQuery(by=Grouping.CREDENTIAL))

    assert [(g.account_id, g.token_id, g.reads, g.others) for g in stats.groups] == [
        (ALICE, "tok-a", 3, False),
        (ALICE, None, 1, False),
        (None, None, 4, True),
    ]
    assert "tok-b" not in stats.model_dump_json()


async def test_a_report_lists_at_most_limit_groups_and_always_the_others() -> None:
    stand = Stand()
    for n, library in enumerate([ACME, BETA, GAMMA], start=1):
        stand.seed(TODAY, n, library=library, account=ALICE)
    stand.seed(TODAY, 1, library=GAMMA, account=BOB)

    by_library = await stand.module.get_usage_stats(UsageStatsQuery(by=Grouping.LIBRARY, limit=2))
    by_person = await stand.module.get_usage_stats(UsageStatsQuery(by=Grouping.ACCOUNT, limit=1))

    assert [g.library for g in by_library.groups] == [GAMMA, BETA]
    assert by_library.groups_total == 3
    assert [(g.account_id, g.others) for g in by_person.groups] == [(ALICE, False), (None, True)]


async def test_own_usage_holds_only_the_callers_counts() -> None:
    stand = Stand()
    stand.seed(TODAY, 3, account=BOB, token="tok-b")
    stand.seed(TODAY, 2, account=BOB, library=BETA)
    stand.seed(TODAY, 9, account=ALICE)

    by_token = await stand.module.get_account_usage(
        AccountUsageQuery(account_id=BOB, by="token", period=Period.MONTH, periods=1)
    )
    by_library = await stand.module.get_account_usage(
        AccountUsageQuery(account_id=BOB, by="library")
    )

    assert by_token.total.reads == 5
    assert [(g.token_id, g.reads) for g in by_token.groups] == [("tok-b", 3), (None, 2)]
    assert [(g.library, g.reads) for g in by_library.groups] == [(ACME, 3), (BETA, 2)]
    assert ALICE not in by_token.model_dump_json() + by_library.model_dump_json()


def test_own_usage_cannot_be_broken_down_by_person() -> None:
    with pytest.raises(ValidationError):
        AccountUsageQuery.model_validate({"account_id": BOB, "by": "account"})


# --- leaderboards


async def test_libraries_are_ranked_with_their_rank_in_the_previous_period() -> None:
    stand = Stand()
    last_week = TODAY - timedelta(days=7)
    for library, now, before in [(ACME, 9, 3), (BETA, 4, 8), (GAMMA, 4, 0)]:
        stand.seed(TODAY, now, library=library)
        if before:
            stand.seed(last_week, before, library=library)
    stand.seed(TODAY, 50, library=NO_LIBRARY)  # a search over several: on no library's row
    stand.seed(TODAY, 70, library=ACME, operation=Operation.SEARCH)  # another metric

    board = await stand.module.get_leaderboard(ViewLeaderboardQuery(viewer_id=ALICE))

    assert (board.subject, board.metric, board.period) == ("libraries", "reads", "week")
    assert (board.start, board.end) == (date(2026, 11, 23), date(2026, 11, 29))
    assert (board.previous_start, board.previous_end) == (date(2026, 11, 16), date(2026, 11, 22))
    assert [(e.library, e.rank, e.previous_rank, e.value) for e in board.entries] == [
        (ACME, 1, 2, 9),
        (BETA, 2, 1, 4),
        (GAMMA, 2, None, 4),
    ]
    assert board.total == 17
    assert board.ranked == 3
    assert all(e.account_id is None and not e.you for e in board.entries)


@pytest.mark.parametrize(
    ("period", "earlier", "previous_start"),
    [
        (Period.DAY, timedelta(days=1), date(2026, 11, 22)),
        (Period.MONTH, timedelta(days=30), date(2026, 10, 1)),
        (Period.YEAR, timedelta(days=365), date(2025, 1, 1)),
    ],
)
async def test_every_period_ranks_against_the_one_before(
    period: Period, earlier: timedelta, previous_start: date
) -> None:
    stand = Stand()
    stand.seed(TODAY, 1, library=ACME, operation=Operation.ANSWER)
    stand.seed(TODAY, 2, library=BETA, operation=Operation.ANSWER)
    stand.seed(TODAY - earlier, 5, library=ACME, operation=Operation.ANSWER)

    board = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(metric=Metric.ANSWERS, period=period)
    )

    assert board.previous_start == previous_start
    assert [(e.library, e.rank, e.previous_rank) for e in board.entries] == [
        (BETA, 1, None),
        (ACME, 2, 1),
    ]


async def test_a_past_period_is_ranked_when_asked_for() -> None:
    stand = Stand()
    stand.seed(date(2026, 10, 5), 3, library=BETA)
    stand.seed(TODAY, 3, library=ACME)

    board = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(period=Period.MONTH, at=date(2026, 10, 20))
    )

    assert [e.library for e in board.entries] == [BETA]


async def test_the_libraries_board_lists_only_libraries_the_viewer_may_read() -> None:
    stand = Stand(readable={ACME})
    stand.seed(TODAY, 1, library=ACME)
    stand.seed(TODAY, 5, library=BETA)
    stand.seed(TODAY - timedelta(days=7), 9, library=BETA)
    stand.seed(TODAY - timedelta(days=7), 1, library=ACME)

    board = await stand.module.get_leaderboard(ViewLeaderboardQuery())

    assert [(e.library, e.rank, e.previous_rank) for e in board.entries] == [(ACME, 1, 1)]
    assert board.total == 1


def test_ranks_share_equal_values_and_skip_nothing_counted() -> None:
    assert ranks({"a": 5, "b": 3, "c": 3, "d": 1, "e": 0}) == {"a": 1, "b": 2, "c": 2, "d": 4}


async def test_the_people_board_is_refused_while_the_operator_has_it_off() -> None:
    stand = Stand(people_board=False)
    stand.seed(TODAY, 3, account=ALICE)

    with pytest.raises(PeopleLeaderboardOffError) as raised:
        await stand.module.get_leaderboard(ViewLeaderboardQuery(subject=Subject.PEOPLE))

    assert raised.value.code == "people_leaderboard_off"
    libraries = await stand.module.get_leaderboard(ViewLeaderboardQuery())
    assert [e.library for e in libraries.entries] == [ACME]


async def test_the_people_board_ranks_only_people_who_opted_in() -> None:
    stand = Stand()
    stand.seed(TODAY, 9, account=BOB)  # the most, but bob did not opt in
    stand.seed(TODAY, 4, account=ALICE)
    stand.seed(TODAY, 6, account=CAROL)
    stand.seed(TODAY, 2, account=NO_ACCOUNT)
    stand.seed(TODAY - timedelta(days=7), 1, account=CAROL)
    stand.seed(TODAY - timedelta(days=7), 8, account=BOB)

    as_bob = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(subject=Subject.PEOPLE, viewer_id=BOB)
    )
    as_alice = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(subject=Subject.PEOPLE, viewer_id=ALICE)
    )

    assert [(e.username, e.rank, e.previous_rank, e.you) for e in as_alice.entries] == [
        ("carol", 1, 1, False),
        ("alice", 2, None, True),
    ]
    assert as_alice.total == 10
    assert all(not e.you for e in as_bob.entries)
    assert BOB not in as_bob.model_dump_json()
    assert all(e.library is None for e in as_alice.entries)


async def test_the_viewer_ranked_beyond_the_limit_gets_their_own_entry() -> None:
    stand = Stand()
    stand.seed(TODAY, 6, account=CAROL)
    stand.seed(TODAY, 4, account=ALICE)

    board = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(subject=Subject.PEOPLE, viewer_id=ALICE, limit=1)
    )
    carol = await stand.module.get_leaderboard(
        ViewLeaderboardQuery(subject=Subject.PEOPLE, viewer_id=CAROL, limit=1)
    )

    assert [e.username for e in board.entries] == ["carol"]
    assert board.ranked == 2
    assert board.you is not None
    assert (board.you.username, board.you.rank, board.you.you) == ("alice", 2, True)
    assert carol.you is None  # already listed


async def test_the_settings_are_the_operators_configuration() -> None:
    on = await Stand(retention=24).module.get_usage_settings(GetUsageSettingsQuery())
    off = await Stand(people_board=False).module.get_usage_settings(GetUsageSettingsQuery())

    assert on.model_dump() == {"people_leaderboard": True, "retention_months": 24}
    assert off.model_dump() == {"people_leaderboard": False, "retention_months": 13}


def test_the_default_policy_has_the_people_board_off_and_thirteen_months() -> None:
    assert UsagePolicy() == UsagePolicy(people_leaderboard=False, retention=Retention(months=13))
