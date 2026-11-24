"""Usage counts (#510): how often each person, token and library is read, searched and asked.

Nothing but counts is kept: one number per UTC day, account, API token, library and operation.
No query, no article path, no text. Counts are added up in memory as requests are served and
written in batches; reports group them into days, ISO weeks, months or years.
"""

import calendar
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from exactdocs.usage.constants import (
    DEFAULT_RETENTION_MONTHS,
    MAX_PENDING_COUNTS,
    MAX_RETENTION_MONTHS,
    NO_LIBRARY,
)
from exactdocs.usage.errors import InvalidRetentionError


class Operation(StrEnum):
    """What a counted request did."""

    READ = "read"
    """Read an article or a chunk (MCP, REST, the web reader)."""
    SEARCH = "search"
    """Searched one library, several or all (MCP's search tools and `query-docs`, REST)."""
    ANSWER = "answer"
    """Asked the answering agent a question (REST `/answer`)."""


class Metric(StrEnum):
    """What a leaderboard ranks by: one operation's counts."""

    READS = "reads"
    """Articles and chunks read."""
    SEARCHES = "searches"
    """Searches."""
    ANSWERS = "answers"
    """Agent answers."""

    @property
    def operation(self) -> Operation:
        """The operation this metric counts.

        Returns:
            The operation.
        """
        match self:
            case Metric.READS:
                return Operation.READ
            case Metric.SEARCHES:
                return Operation.SEARCH
            case Metric.ANSWERS:
                return Operation.ANSWER


class Subject(StrEnum):
    """Who or what a leaderboard ranks."""

    LIBRARIES = "libraries"
    """Libraries, by how much they were used: always available."""
    PEOPLE = "people"
    """People: only while the operator has it on, and only those who opted in."""


class Grouping(StrEnum):
    """What a usage report breaks its counts down by."""

    NONE = "none"
    """No breakdown: the totals per period only."""
    LIBRARY = "library"
    """Per library."""
    ACCOUNT = "account"
    """Per person (only those shown by name; the rest summed into one group)."""
    CREDENTIAL = "token"
    """Per person and API token (the same rule as per person)."""


class Period(StrEnum):
    """A calendar period in UTC: what counts are added up over."""

    DAY = "day"
    """One UTC day."""
    WEEK = "week"
    """An ISO week, Monday to Sunday."""
    MONTH = "month"
    """A calendar month."""
    YEAR = "year"
    """A calendar year."""


class Dimension(StrEnum):
    """A column the stored counts can be summed by."""

    DAY = "day"
    """The UTC day."""
    ACCOUNT = "account"
    """The account (``NO_ACCOUNT`` when no person made the request)."""
    CREDENTIAL = "token"
    """The API token (``NO_TOKEN`` for a session)."""
    LIBRARY = "library"
    """The library (``NO_LIBRARY`` for an operation over several)."""
    OPERATION = "operation"
    """The operation."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Span:
    """A run of whole UTC days, both ends included: one period, or several."""

    first: date
    """The first day."""
    last: date
    """The last day (included)."""

    def __contains__(self, day: object) -> bool:
        """Tell whether a day falls in the span.

        Args:
            day: The day.

        Returns:
            Whether it is between ``first`` and ``last``, both included.
        """
        return isinstance(day, date) and self.first <= day <= self.last


def period_of(period: Period, day: date) -> Span:
    """Return the period of the given kind that holds a day.

    Args:
        period: Day, ISO week, month or year.
        day: The day.

    Returns:
        The period's first and last day.
    """
    match period:
        case Period.DAY:
            return Span(first=day, last=day)
        case Period.WEEK:
            monday = day - timedelta(days=day.weekday())
            return Span(first=monday, last=monday + timedelta(days=6))
        case Period.MONTH:
            last = calendar.monthrange(day.year, day.month)[1]
            return Span(first=day.replace(day=1), last=day.replace(day=last))
        case Period.YEAR:
            return Span(first=date(day.year, 1, 1), last=date(day.year, 12, 31))


def previous_of(period: Period, span: Span) -> Span:
    """Return the period of the same kind just before one.

    Args:
        period: The kind of period.
        span: A period of that kind.

    Returns:
        The period before it.
    """
    return period_of(period, span.first - timedelta(days=1))


def periods_until(period: Period, until: date, count: int) -> list[Span]:
    """Return ``count`` consecutive periods, oldest first, the last one holding ``until``.

    Args:
        period: The kind of period.
        until: A day of the last period.
        count: How many periods (at least one).

    Returns:
        The periods.
    """
    spans = [period_of(period, until)]
    while len(spans) < count:
        spans.append(previous_of(period, spans[-1]))
    return spans[::-1]


def months_before(day: date, months: int) -> date:
    """Return the same day of the month ``months`` months earlier (the month's last if shorter).

    Args:
        day: The day.
        months: How many months back.

    Returns:
        The earlier day.
    """
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


@dataclass(frozen=True, slots=True, kw_only=True)
class Retention:
    """How long daily counts are kept: a whole number of months, counted back from today."""

    months: int = DEFAULT_RETENTION_MONTHS
    """The months kept, today's included."""

    def __post_init__(self) -> None:
        """Check the number of months.

        Raises:
            InvalidRetentionError: It is not between 1 and ``MAX_RETENTION_MONTHS``.
        """
        if not 1 <= self.months <= MAX_RETENTION_MONTHS:
            message = f"usage counts are kept for 1 to {MAX_RETENTION_MONTHS} months"
            raise InvalidRetentionError(message)

    def first_kept(self, today: date) -> date:
        """Return the first day whose counts are kept; every earlier day's are deleted.

        Args:
            today: Today, in UTC.

        Returns:
            The day ``months`` months before today (13 months: 2025-10-23 on 2026-11-23).
        """
        return months_before(today, self.months)


@dataclass(frozen=True, slots=True, kw_only=True)
class UsagePolicy:
    """What the operator decided about usage counts (configuration, not stored)."""

    people_leaderboard: bool = False
    """Whether the people leaderboard is on. Off: nobody is shown by name to anyone else, not
    even to operators, whatever they opted into."""
    retention: Retention = field(default_factory=Retention)
    """How long daily counts are kept."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageKey:
    """One stored counter: a UTC day, an account, a token, a library and an operation."""

    day: date
    """The UTC day the requests were served on."""
    account: str
    """The account that made them, or ``NO_ACCOUNT``."""
    token: str
    """The API token they carried, or ``NO_TOKEN``."""
    library: str
    """The library they were about (lower-case), or ``NO_LIBRARY``."""
    operation: Operation
    """What they did."""


def counted_library(libraries: Collection[str]) -> str:
    """Return the library an operation is counted to: its one library, or ``NO_LIBRARY``.

    A search or an answer over several libraries (or all of them) counts once, to no library:
    it is in the person's and the instance's totals, and on no library's row.

    Args:
        libraries: The libraries the operation was about, any letter case.

    Returns:
        The one library, lower-case, or ``NO_LIBRARY``.
    """
    distinct = {library.casefold() for library in libraries if library}
    return next(iter(distinct)) if len(distinct) == 1 else NO_LIBRARY


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- an accumulator
class UsageTally:
    """Counts added up in memory until they are written: requests never wait for the database.

    It holds at most ``limit`` distinct counters; a new one past that is dropped and counted in
    ``dropped`` (only while writes keep failing). Everything runs on one event loop, and no
    method awaits, so each call is atomic.
    """

    limit: int = MAX_PENDING_COUNTS
    """Most distinct counters held."""
    counts: dict[UsageKey, int] = field(default_factory=dict)
    """The pending counts, by counter."""
    dropped: int = 0
    """Counts lost since the last ``take``: their counter did not fit."""

    def add(self, key: UsageKey, count: int = 1) -> None:
        """Count requests.

        Args:
            key: The counter.
            count: How many requests.
        """
        if key in self.counts or len(self.counts) < self.limit:
            self.counts[key] = self.counts.get(key, 0) + count
        else:
            self.dropped += count

    def take(self) -> tuple[dict[UsageKey, int], int]:
        """Hand over every pending count, and how many were dropped, and start again empty.

        Returns:
            The pending counts, and the number dropped since the last call.
        """
        taken, dropped = self.counts, self.dropped
        self.counts, self.dropped = {}, 0
        return taken, dropped

    def put_back(self, counts: Mapping[UsageKey, int]) -> None:
        """Put back counts that could not be written, to be written with the next ones.

        Args:
            counts: The counts taken.
        """
        for key, count in counts.items():
            self.add(key, count)


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageSelection:
    """Which stored counts to sum, and by what."""

    first: date
    """The first day."""
    last: date
    """The last day (included)."""
    by: frozenset[Dimension] = frozenset()
    """The columns to sum by; none: one grand total."""
    account: str | None = None
    """Only this account's counts."""
    library: str | None = None
    """Only this library's counts (lower-case)."""
    operation: Operation | None = None
    """Only this operation's counts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageSum:
    """The sum of the stored counts that share the selected columns.

    A column the selection did not sum by is ``None``.
    """

    count: int
    """The sum."""
    day: date | None = None
    """The day."""
    account: str | None = None
    """The account."""
    token: str | None = None
    """The token."""
    library: str | None = None
    """The library."""
    operation: Operation | None = None
    """The operation."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Person:
    """Someone who may be shown by name: they opted in, and the account is enabled."""

    id: str
    """The account ID."""
    username: str
    """The username."""


def ranks(values: Mapping[str, int]) -> dict[str, int]:
    """Rank subjects by value, highest first; equal values share a rank (1, 2, 2, 4).

    A subject with nothing counted (0 or less) has no rank.

    Args:
        values: Each subject's value.

    Returns:
        Each ranked subject's rank.
    """
    ordered = sorted((v, k) for k, v in values.items() if v > 0)
    ordered.reverse()
    ranked: dict[str, int] = {}
    previous: int | None = None
    rank = 0
    for position, (value, subject) in enumerate(ordered, start=1):
        if value != previous:
            rank, previous = position, value
        ranked[subject] = rank
    return ranked


def days(span: Span) -> Iterator[date]:
    """Yield every day of a span, in order.

    Args:
        span: The span.

    Yields:
        Its days.
    """
    day = span.first
    while day <= span.last:
        yield day
        day += timedelta(days=1)
