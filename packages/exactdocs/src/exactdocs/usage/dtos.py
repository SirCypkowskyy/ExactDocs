"""Data crossing the usage boundary (into and out of driving ports). Immutable, validated."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.usage.constants import (
    DEFAULT_GROUPS,
    DEFAULT_LEADERBOARD_SIZE,
    MAX_GROUPS,
    MAX_LEADERBOARD_SIZE,
    MAX_PERIODS,
)
from exactdocs.usage.models import Grouping, Metric, Operation, Period, Subject
from exactdocs_kernel import LIBRARY_ID_PATTERN, MAX_NAME


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class RecordUsageCommand(_Dto):
    """Count one request that read, searched or asked: counts only, never what was asked."""

    operation: Operation
    """What the request did."""
    libraries: list[str] = Field(default_factory=list)
    """The libraries it was about: one for a read; several (or none, for all) when a search or an
    answer covered more than one, which then counts to no library."""
    account_id: str | None = None
    """The account that made it; null when no person did."""
    token_id: str | None = None
    """The API token it carried; null for a browser session or an OAuth sign-in."""


class FlushUsageCommand(_Dto):
    """Write the counts added up in memory since the last write."""


class FlushedUsage(_Dto):
    """What a write of the pending counts did."""

    written: int
    """Counters written (each one added to the day's stored count)."""
    dropped: int
    """Counts lost since the last write because too many counters were pending."""


class PruneUsageCommand(_Dto):
    """Delete the daily counts older than the retention."""


class PrunedUsage(_Dto):
    """What a pruning deleted."""

    first_kept: date
    """The first day still kept."""
    deleted: int
    """Stored counters deleted."""


class UsageRange(_Dto):
    """Which periods a usage report covers."""

    period: Period = Period.DAY
    """What each bucket adds up: `day` (UTC), `week` (ISO, Monday first), `month` or `year`."""
    periods: int | None = Field(default=None, ge=1, le=MAX_PERIODS)
    """How many buckets, the last one holding `until`; default 30 days, 12 weeks, 12 months or 2
    years. Counts older than the retention are gone, so older buckets are zeros."""
    until: date | None = None
    """A day of the last bucket (UTC); default today."""
    limit: int = Field(default=DEFAULT_GROUPS, ge=1, le=MAX_GROUPS)
    """How many groups to list, most reads first."""


class UsageStatsQuery(UsageRange):
    """The instance's usage, for operators: totals per period and a breakdown."""

    by: Grouping = Grouping.NONE
    """`library`, `account` (people), `token` (people and their API tokens), or `none`. People
    are named only while the people leaderboard is on and only if they opted in; everyone else
    is summed into one group with `others` set."""
    library: str | None = Field(default=None, pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)
    """Only this library's counts (`/owner/repo`, any letter case)."""


class OwnUsageQuery(UsageRange):
    """The caller's own usage: totals per period and a breakdown."""

    by: Literal["none", "library", "token"] = "none"
    """`library`, `token` (your API tokens; null is your browser sessions), or `none`."""


class AccountUsageQuery(OwnUsageQuery):
    """One account's own usage, as that account asks for it."""

    account_id: str
    """The account, as the caller is signed in."""


class UsageCountsOut(_Dto):
    """How many reads, searches and agent answers were counted."""

    reads: int
    """Articles and chunks read (MCP, REST and the web reader)."""
    searches: int
    """Searches (one library, several or all; `query-docs` included)."""
    answers: int
    """Questions answered by the agent."""


class UsageBucketOut(UsageCountsOut):
    """The counts of one period."""

    start: date
    """The period's first day (UTC)."""
    end: date
    """The period's last day, included (UTC); the current period's may be after today."""


class UsageGroupOut(UsageCountsOut):
    """The counts of one library, person or token over the whole report."""

    library: str | None = None
    """`by=library`: the library ID, lower-case; null for searches and answers over several
    libraries."""
    account_id: str | None = None
    """`by=account` or `token`: the person's account ID; null in the `others` group."""
    username: str | None = None
    """The person's username, next to `account_id`."""
    token_id: str | None = None
    """`by=token`: the API token's ID; null for browser sessions and OAuth sign-ins."""
    others: bool = False
    """`true` for the one group that sums everyone not shown by name (people who did not opt
    in, everyone while the people leaderboard is off, and requests without an account)."""


class UsageStats(_Dto):
    """Counts per period over a range of periods, and a breakdown over the whole range."""

    period: Period
    """What each bucket adds up."""
    since: date
    """The first day covered (UTC)."""
    until: date
    """The last day covered, included (UTC)."""
    by: Grouping
    """What `groups` breaks the counts down by."""
    total: UsageCountsOut
    """Everything counted in the range."""
    series: list[UsageBucketOut]
    """One bucket per period, oldest first, zeros included."""
    groups: list[UsageGroupOut]
    """The breakdown, most reads first (then searches, then answers), at most `limit`; the
    `others` group, when there is one, comes last and is always listed."""
    groups_total: int
    """How many groups there are in all, the `others` group included."""


class LeaderboardQuery(_Dto):
    """A leaderboard: libraries or people ranked by one metric over one period."""

    subject: Subject = Subject.LIBRARIES
    """`libraries` (always on; only libraries you may read) or `people` (only while the
    operator has it on; only people who opted in)."""
    metric: Metric = Metric.READS
    """`reads`, `searches` or `answers`."""
    period: Period = Period.WEEK
    """`day` (UTC), `week` (ISO), `month` or `year`."""
    at: date | None = None
    """A day of the period to rank (UTC); default today, so the current period so far."""
    limit: int = Field(default=DEFAULT_LEADERBOARD_SIZE, ge=1, le=MAX_LEADERBOARD_SIZE)
    """How many entries to list, best first."""


class ViewLeaderboardQuery(LeaderboardQuery):
    """A leaderboard as one account sees it."""

    viewer_id: str | None = None
    """The account asking: its own entry is marked, and given apart when it is not listed."""


class LeaderboardEntryOut(_Dto):
    """One library or person on a leaderboard."""

    rank: int
    """1 for the most; equal values share a rank (1, 2, 2, 4)."""
    previous_rank: int | None
    """The rank in the previous period, among the same subjects; null when it was not ranked
    then (nothing counted)."""
    value: int
    """The metric's count in the period."""
    library: str | None = None
    """`libraries`: the library ID, lower-case."""
    account_id: str | None = None
    """`people`: the account ID."""
    username: str | None = None
    """`people`: the username."""
    you: bool = False
    """`people`: this is the caller."""


class Leaderboard(_Dto):
    """Libraries or people ranked by one metric over one period, with the previous period's rank."""

    subject: Subject
    """What is ranked."""
    metric: Metric
    """What it is ranked by."""
    period: Period
    """The kind of period."""
    start: date
    """The period's first day (UTC)."""
    end: date
    """The period's last day, included (UTC); the current period ends after today."""
    previous_start: date
    """The previous period's first day: what `previous_rank` ranks."""
    previous_end: date
    """The previous period's last day, included."""
    total: int
    """The metric summed over every ranked subject (for each one's share)."""
    ranked: int
    """How many subjects are ranked; `entries` lists the first `limit`."""
    entries: list[LeaderboardEntryOut]
    """The best first; equal values by name."""
    you: LeaderboardEntryOut | None = None
    """`people`: the caller's own entry when it is ranked but beyond `limit`; null otherwise."""


class GetUsageSettingsQuery(_Dto):
    """Read how this instance counts usage."""


class UsageSettingsOut(_Dto):
    """How this instance counts usage: the operator's configuration."""

    people_leaderboard: bool
    """Whether the people leaderboard is on (`EXACTDOCS_USAGE__PEOPLE_LEADERBOARD`). Off, nobody
    is shown by name; on, only people who opted in (`leaderboard_opt_in`)."""
    retention_months: int
    """How many months of daily counts are kept (`EXACTDOCS_USAGE__RETENTION_MONTHS`)."""
