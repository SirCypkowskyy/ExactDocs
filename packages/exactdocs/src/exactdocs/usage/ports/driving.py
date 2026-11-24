"""Driving (primary) ports: what the outside world may ask the usage domain to do."""

from typing import Protocol

from exactdocs.usage.dtos import (
    AccountUsageQuery,
    FlushedUsage,
    FlushUsageCommand,
    GetUsageSettingsQuery,
    Leaderboard,
    PrunedUsage,
    PruneUsageCommand,
    RecordUsageCommand,
    UsageSettingsOut,
    UsageStats,
    UsageStatsQuery,
    ViewLeaderboardQuery,
)


class RecordUsage(Protocol):
    """Count one read, search or answer, in memory: the request never waits for the database."""

    async def __call__(self, command: RecordUsageCommand) -> None:
        """Run the use case.

        Args:
            command: What the request did, about which libraries, and who made it.
        """
        ...


class FlushUsage(Protocol):
    """Write the counts added up in memory; those that fail to write are kept for next time."""

    async def __call__(self, command: FlushUsageCommand) -> FlushedUsage:
        """Run the use case.

        Args:
            command: Nothing to choose.

        Returns:
            How many counters were written, and how many counts were dropped meanwhile.
        """
        ...


class PruneUsage(Protocol):
    """Delete the daily counts older than the retention (the nightly upkeep runs it)."""

    async def __call__(self, command: PruneUsageCommand) -> PrunedUsage:
        """Run the use case.

        Args:
            command: Nothing to choose.

        Returns:
            The first day kept and how many counters were deleted.
        """
        ...


class GetUsageStats(Protocol):
    """The instance's usage per period, with a breakdown (operators).

    People are named only while the people leaderboard is on and only when they opted in; the
    others are summed into one group.
    """

    async def __call__(self, query: UsageStatsQuery) -> UsageStats:
        """Run the use case.

        Args:
            query: The periods, the breakdown and an optional library.

        Returns:
            The counts per period and per group.
        """
        ...


class GetAccountUsage(Protocol):
    """One account's own usage per period, with a breakdown by library or token."""

    async def __call__(self, query: AccountUsageQuery) -> UsageStats:
        """Run the use case.

        Args:
            query: The account, the periods and the breakdown.

        Returns:
            Its counts per period and per group.
        """
        ...


class GetLeaderboard(Protocol):
    """Libraries or people ranked by one metric over one period, with the previous rank.

    Libraries: only those the viewer may read. People: only while the operator has the board
    on (``PeopleLeaderboardOffError`` otherwise), and only people who opted in.
    """

    async def __call__(self, query: ViewLeaderboardQuery) -> Leaderboard:
        """Run the use case.

        Args:
            query: The subject, metric, period and the account viewing.

        Returns:
            The ranked entries.
        """
        ...


class GetUsageSettings(Protocol):
    """How this instance counts usage: whether the people leaderboard is on, the retention."""

    async def __call__(self, query: GetUsageSettingsQuery) -> UsageSettingsOut:
        """Run the use case.

        Args:
            query: Nothing to choose.

        Returns:
            The settings.
        """
        ...
