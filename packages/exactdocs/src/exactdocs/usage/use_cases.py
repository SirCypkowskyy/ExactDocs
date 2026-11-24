"""Use cases of the usage domain (#510): count, write, prune, report and rank."""

import logging
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date

from exactdocs.usage.constants import DEFAULT_PERIODS, NO_ACCOUNT, NO_TOKEN
from exactdocs.usage.dtos import (
    AccountUsageQuery,
    FlushedUsage,
    FlushUsageCommand,
    GetUsageSettingsQuery,
    Leaderboard,
    LeaderboardEntryOut,
    PrunedUsage,
    PruneUsageCommand,
    RecordUsageCommand,
    UsageBucketOut,
    UsageCountsOut,
    UsageGroupOut,
    UsageRange,
    UsageSettingsOut,
    UsageStats,
    UsageStatsQuery,
    ViewLeaderboardQuery,
)
from exactdocs.usage.errors import PeopleLeaderboardOffError
from exactdocs.usage.models import (
    Dimension,
    Grouping,
    Operation,
    Period,
    Span,
    Subject,
    UsageKey,
    UsagePolicy,
    UsageSelection,
    UsageSum,
    UsageTally,
    counted_library,
    period_of,
    periods_until,
    previous_of,
    ranks,
)
from exactdocs.usage.ports.driven import LibraryAccess, People, UsageCounts
from exactdocs.usage.ports.driving import FlushUsage
from exactdocs_kernel import Clock

logger = logging.getLogger(__name__)

type _Counts = defaultdict[Operation, int]


def _today(clock: Clock) -> date:
    """Return today in UTC, the day counts are kept by.

    Args:
        clock: The current time.

    Returns:
        Today's UTC date.
    """
    return clock.now().astimezone(UTC).date()


def _counts() -> _Counts:
    """Return an empty count per operation.

    Returns:
        Zero for every operation.
    """
    return defaultdict(int)


def _bucket(span: Span, counts: Mapping[Operation, int]) -> UsageBucketOut:
    """Report one period's counts.

    Args:
        span: The period.
        counts: Each operation's count.

    Returns:
        The bucket.
    """
    return UsageBucketOut(
        start=span.first,
        end=span.last,
        reads=counts.get(Operation.READ, 0),
        searches=counts.get(Operation.SEARCH, 0),
        answers=counts.get(Operation.ANSWER, 0),
    )


def _group(
    counts: Mapping[Operation, int],
    *,
    library: str | None = None,
    account_id: str | None = None,
    username: str | None = None,
    token_id: str | None = None,
    others: bool = False,
) -> UsageGroupOut:
    """Report one group's counts.

    Args:
        counts: Each operation's count.
        library: The group's library.
        account_id: The group's person.
        username: That person's username.
        token_id: The group's API token.
        others: Whether it sums everyone not shown by name.

    Returns:
        The group.
    """
    return UsageGroupOut(
        reads=counts.get(Operation.READ, 0),
        searches=counts.get(Operation.SEARCH, 0),
        answers=counts.get(Operation.ANSWER, 0),
        library=library,
        account_id=account_id,
        username=username,
        token_id=token_id,
        others=others,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordUsageUseCase:
    """Implements ``ports.driving.RecordUsage``."""

    tally: UsageTally
    """The counts waiting to be written."""
    clock: Clock
    """The current time: which UTC day a request counts to."""

    async def __call__(self, command: RecordUsageCommand) -> None:
        """Count the request to today, its account, token and library.

        Args:
            command: What the request did, about which libraries, and who made it.
        """
        self.tally.add(
            UsageKey(
                day=_today(self.clock),
                account=command.account_id or NO_ACCOUNT,
                token=command.token_id or NO_TOKEN,
                library=counted_library(command.libraries),
                operation=command.operation,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FlushUsageUseCase:
    """Implements ``ports.driving.FlushUsage``."""

    tally: UsageTally
    """The counts waiting to be written."""
    counts: UsageCounts
    """The stored daily counts."""

    async def __call__(self, command: FlushUsageCommand) -> FlushedUsage:
        """Add the pending counts to the stored ones, in one transaction.

        A write that fails (or is cancelled) puts the counts back, so the next write carries
        them; the failure is raised.

        Args:
            command: Nothing to choose.

        Returns:
            How many counters were written and how many counts were dropped meanwhile.
        """
        del command
        pending, dropped = self.tally.take()
        if dropped:
            logger.warning(
                "%d usage counts were dropped: too many counters waited to be written", dropped
            )
        if pending:
            try:
                await self.counts.add(pending)
            except BaseException:
                self.tally.put_back(pending)
                raise
        return FlushedUsage(written=len(pending), dropped=dropped)


@dataclass(frozen=True, slots=True, kw_only=True)
class PruneUsageUseCase:
    """Implements ``ports.driving.PruneUsage``."""

    counts: UsageCounts
    """The stored daily counts."""
    policy: UsagePolicy
    """The retention."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: PruneUsageCommand) -> PrunedUsage:
        """Delete the counts of every day before the retention's first kept day.

        Args:
            command: Nothing to choose.

        Returns:
            The first day kept and how many counters were deleted.
        """
        del command
        first_kept = self.policy.retention.first_kept(_today(self.clock))
        return PrunedUsage(first_kept=first_kept, deleted=await self.counts.prune(first_kept))


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageReports:
    """What every report shares: the stored counts, written up to date, over a range of days."""

    counts: UsageCounts
    """The stored daily counts."""
    flush: FlushUsage
    """Writes the pending counts first, so a report includes the requests just served."""
    clock: Clock
    """The current time."""

    def today(self) -> date:
        """Return today in UTC.

        Returns:
            Today's UTC date.
        """
        return _today(self.clock)

    async def fresh(self) -> None:
        """Write the pending counts; a failure is logged and the report reads what is stored."""
        try:
            await self.flush(FlushUsageCommand())
        except Exception:
            logger.warning(
                "could not write the pending usage counts before a report", exc_info=True
            )

    def spans(self, query: UsageRange) -> list[Span]:
        """Return the periods a report covers, oldest first.

        Args:
            query: The kind and number of periods, and a day of the last one.

        Returns:
            The periods.
        """
        count = query.periods or DEFAULT_PERIODS[query.period.value]
        return periods_until(query.period, query.until or self.today(), count)

    async def sums(
        self,
        span: Span,
        by: Iterable[Dimension],
        *,
        account: str | None = None,
        library: str | None = None,
        operation: Operation | None = None,
    ) -> list[UsageSum]:
        """Sum the stored counts of a span.

        Args:
            span: The days.
            by: The columns to sum by.
            account: Only this account's counts.
            library: Only this library's counts.
            operation: Only this operation's counts.

        Returns:
            The sums.
        """
        selection = UsageSelection(
            first=span.first,
            last=span.last,
            by=frozenset(by),
            account=account,
            library=library,
            operation=operation,
        )
        return list(await self.counts.sums(selection))

    async def series(
        self,
        period: Period,
        spans: list[Span],
        *,
        account: str | None = None,
        library: str | None = None,
    ) -> list[UsageBucketOut]:
        """Return one bucket per period, zeros included.

        Args:
            period: The kind of period.
            spans: The periods, oldest first.
            account: Only this account's counts.
            library: Only this library's counts.

        Returns:
            The buckets, oldest first.
        """
        whole = Span(first=spans[0].first, last=spans[-1].last)
        buckets = {span.first: _counts() for span in spans}
        dimensions = (Dimension.DAY, Dimension.OPERATION)
        for found in await self.sums(whole, dimensions, account=account, library=library):
            if found.day is None or found.operation is None:
                continue
            bucket = buckets.get(period_of(period, found.day).first)
            if bucket is not None:
                bucket[found.operation] += found.count
        return [_bucket(span, buckets[span.first]) for span in spans]


def _total(series: Iterable[UsageBucketOut]) -> UsageCountsOut:
    """Add up the buckets of a report.

    Args:
        series: The buckets.

    Returns:
        Their sum.
    """
    buckets = list(series)
    return UsageCountsOut(
        reads=sum(bucket.reads for bucket in buckets),
        searches=sum(bucket.searches for bucket in buckets),
        answers=sum(bucket.answers for bucket in buckets),
    )


def _grouped[K](sums: Iterable[UsageSum], key: Callable[[UsageSum], K]) -> dict[K, _Counts]:
    """Add up sums per group and operation.

    Args:
        sums: The sums, each with its operation.
        key: The group a sum belongs to.

    Returns:
        Each group's counts per operation.
    """
    groups: dict[K, _Counts] = {}
    for found in sums:
        if found.operation is not None:
            groups.setdefault(key(found), _counts())[found.operation] += found.count
    return groups


def _listed(
    groups: list[UsageGroupOut], others: UsageGroupOut | None, limit: int
) -> tuple[list[UsageGroupOut], int]:
    """Sort the groups, most reads first, keep ``limit`` of them, and put ``others`` last.

    Args:
        groups: The named groups.
        others: The group of everyone not named, if any.
        limit: How many named groups to keep.

    Returns:
        The groups listed, and how many there are in all.
    """
    ordered = sorted(
        groups,
        key=lambda group: (
            -group.reads,
            -group.searches,
            -group.answers,
            group.library or group.username or "",
            group.token_id or "",
        ),
    )
    listed = ordered[:limit] + ([] if others is None else [others])
    return listed, len(groups) + (others is not None)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetUsageStatsUseCase:
    """Implements ``ports.driving.GetUsageStats``."""

    reports: UsageReports
    """The stored counts, written up to date."""
    people: People
    """Who may be shown by name."""
    policy: UsagePolicy
    """Whether the people leaderboard is on: without it, nobody is shown by name."""

    async def __call__(self, query: UsageStatsQuery) -> UsageStats:
        """Report the instance's usage per period, broken down as asked.

        Args:
            query: The periods, the breakdown and an optional library.

        Returns:
            The counts per period and per group.
        """
        await self.reports.fresh()
        library = None if query.library is None else query.library.casefold()
        spans = self.reports.spans(query)
        whole = Span(first=spans[0].first, last=spans[-1].last)
        series = await self.reports.series(query.period, spans, library=library)
        groups: list[UsageGroupOut] = []
        others = None
        match query.by:
            case Grouping.LIBRARY:
                found = await self.reports.sums(
                    whole, (Dimension.LIBRARY, Dimension.OPERATION), library=library
                )
                groups = [
                    _group(counts, library=name or None)
                    for name, counts in _grouped(found, lambda s: s.library or "").items()
                ]
            case Grouping.ACCOUNT | Grouping.CREDENTIAL:
                groups, others = await self._people(query.by, whole, library)
            case Grouping.NONE:
                pass
        listed, groups_total = _listed(groups, others, query.limit)
        return UsageStats(
            period=query.period,
            since=whole.first,
            until=whole.last,
            by=query.by,
            total=_total(series),
            series=series,
            groups=listed,
            groups_total=groups_total,
        )

    async def _people(
        self, by: Grouping, whole: Span, library: str | None
    ) -> tuple[list[UsageGroupOut], UsageGroupOut | None]:
        """Break the counts down by person (and token): named people, then everyone else.

        Args:
            by: ``account`` or ``token``.
            whole: The days.
            library: Only this library's counts.

        Returns:
            One group per named person (or person and token), and the group of the rest.
        """
        tokens = by is Grouping.CREDENTIAL
        dimensions = [Dimension.ACCOUNT, Dimension.OPERATION]
        if tokens:
            dimensions.append(Dimension.CREDENTIAL)
        found = await self.reports.sums(whole, dimensions, library=library)
        names = await _shown(self.people, self.policy, {s.account for s in found if s.account})
        named = _grouped(
            (s for s in found if s.account in names), lambda s: (s.account or "", s.token or "")
        )
        rest = _grouped((s for s in found if s.account not in names), lambda _: "")
        groups = [
            _group(
                counts,
                account_id=account,
                username=names[account],
                token_id=(token or None) if tokens else None,
            )
            for (account, token), counts in named.items()
        ]
        others = _group(rest[""], others=True) if rest else None
        return groups, others


async def _shown(people: People, policy: UsagePolicy, accounts: Collection[str]) -> dict[str, str]:
    """Return the people who may be shown by name among these accounts, with their usernames.

    Nobody while the people leaderboard is off.

    Args:
        people: Who opted in.
        policy: Whether the people leaderboard is on.
        accounts: The accounts asked about.

    Returns:
        Each shown account's username.
    """
    if not policy.people_leaderboard or not accounts:
        return {}
    return {person.id: person.username for person in await people.shown(accounts)}


@dataclass(frozen=True, slots=True, kw_only=True)
class GetAccountUsageUseCase:
    """Implements ``ports.driving.GetAccountUsage``."""

    reports: UsageReports
    """The stored counts, written up to date."""

    async def __call__(self, query: AccountUsageQuery) -> UsageStats:
        """Report one account's own usage per period, broken down as asked.

        Args:
            query: The account, the periods and the breakdown.

        Returns:
            Its counts per period and per group.
        """
        await self.reports.fresh()
        account = query.account_id
        spans = self.reports.spans(query)
        whole = Span(first=spans[0].first, last=spans[-1].last)
        series = await self.reports.series(query.period, spans, account=account)
        by = Grouping(query.by)
        groups: list[UsageGroupOut] = []
        if by is Grouping.LIBRARY:
            found = await self.reports.sums(
                whole, (Dimension.LIBRARY, Dimension.OPERATION), account=account
            )
            groups = [
                _group(counts, library=name or None)
                for name, counts in _grouped(found, lambda s: s.library or "").items()
            ]
        elif by is Grouping.CREDENTIAL:
            found = await self.reports.sums(
                whole, (Dimension.CREDENTIAL, Dimension.OPERATION), account=account
            )
            groups = [
                _group(counts, token_id=token or None)
                for token, counts in _grouped(found, lambda s: s.token or "").items()
            ]
        listed, groups_total = _listed(groups, None, query.limit)
        return UsageStats(
            period=query.period,
            since=whole.first,
            until=whole.last,
            by=by,
            total=_total(series),
            series=series,
            groups=listed,
            groups_total=groups_total,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetLeaderboardUseCase:
    """Implements ``ports.driving.GetLeaderboard``."""

    reports: UsageReports
    """The stored counts, written up to date."""
    people: People
    """Who may be shown by name."""
    libraries: LibraryAccess
    """Which libraries the viewer may read."""
    policy: UsagePolicy
    """Whether the people leaderboard is on."""

    async def __call__(self, query: ViewLeaderboardQuery) -> Leaderboard:
        """Rank libraries or people by a metric over a period, and give the previous rank.

        Both periods are ranked among the same visible subjects: libraries the viewer may read,
        or people who opted in. A subject with nothing counted is not ranked.

        Args:
            query: The subject, metric, period and the account viewing.

        Returns:
            The ranked entries.

        Raises:
            PeopleLeaderboardOffError: People were asked for while the board is off.
        """
        people = query.subject is Subject.PEOPLE
        if people and not self.policy.people_leaderboard:
            raise PeopleLeaderboardOffError
        await self.reports.fresh()
        span = period_of(query.period, query.at or self.reports.today())
        before = previous_of(query.period, span)
        dimension = Dimension.ACCOUNT if people else Dimension.LIBRARY
        operation = query.metric.operation
        current = await self._values(span, dimension, operation)
        previous = await self._values(before, dimension, operation)
        asked = set(current) | set(previous)
        if people:
            names = await _shown(self.people, self.policy, asked)
        else:
            names = {library: library for library in await self.libraries.readable(asked)}
        now = ranks({key: value for key, value in current.items() if key in names})
        then = ranks({key: value for key, value in previous.items() if key in names})
        entries = [
            LeaderboardEntryOut(
                rank=now[key],
                previous_rank=then.get(key),
                value=current[key],
                library=None if people else key,
                account_id=key if people else None,
                username=names[key] if people else None,
                you=people and key == query.viewer_id,
            )
            for key in sorted(now, key=lambda key: (now[key], names[key], key))
        ]
        listed = entries[: query.limit]
        mine = [entry for entry in entries[query.limit :] if entry.you]
        return Leaderboard(
            subject=query.subject,
            metric=query.metric,
            period=query.period,
            start=span.first,
            end=span.last,
            previous_start=before.first,
            previous_end=before.last,
            total=sum(current[key] for key in now),
            ranked=len(entries),
            entries=listed,
            you=mine[0] if mine else None,
        )

    async def _values(
        self, span: Span, dimension: Dimension, operation: Operation
    ) -> dict[str, int]:
        """Return each library's or account's count of one operation over a span.

        Args:
            span: The days.
            dimension: ``library`` or ``account``.
            operation: The operation counted.

        Returns:
            The counts, without the requests counted to no library or no account.
        """
        values: dict[str, int] = {}
        for found in await self.reports.sums(span, (dimension,), operation=operation):
            key = found.library if dimension is Dimension.LIBRARY else found.account
            if key:
                values[key] = values.get(key, 0) + found.count
        return values


@dataclass(frozen=True, slots=True, kw_only=True)
class GetUsageSettingsUseCase:
    """Implements ``ports.driving.GetUsageSettings``."""

    policy: UsagePolicy
    """The operator's decisions."""

    async def __call__(self, query: GetUsageSettingsQuery) -> UsageSettingsOut:
        """Return whether the people leaderboard is on and how long counts are kept.

        Args:
            query: Nothing to choose.

        Returns:
            The settings.
        """
        del query
        return UsageSettingsOut(
            people_leaderboard=self.policy.people_leaderboard,
            retention_months=self.policy.retention.months,
        )
