"""The usage domain, wired: its driving ports built from the driven adapters bootstrap picks."""

from dataclasses import dataclass
from typing import Self

from exactdocs.usage.models import UsagePolicy, UsageTally
from exactdocs.usage.ports.driven import LibraryAccess, People, UsageCounts
from exactdocs.usage.ports.driving import (
    FlushUsage,
    GetAccountUsage,
    GetLeaderboard,
    GetUsageSettings,
    GetUsageStats,
    PruneUsage,
    RecordUsage,
)
from exactdocs.usage.use_cases import (
    FlushUsageUseCase,
    GetAccountUsageUseCase,
    GetLeaderboardUseCase,
    GetUsageSettingsUseCase,
    GetUsageStatsUseCase,
    PruneUsageUseCase,
    RecordUsageUseCase,
    UsageReports,
)
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageModule:
    """Every use case of the usage domain (#510), wired."""

    record_usage: RecordUsage
    """Count a read, search or answer in memory."""
    flush_usage: FlushUsage
    """Write the counts added up in memory."""
    prune_usage: PruneUsage
    """Delete the counts older than the retention."""
    get_usage_stats: GetUsageStats
    """The instance's usage per period and per group (operators)."""
    get_account_usage: GetAccountUsage
    """An account's own usage per period and per group."""
    get_leaderboard: GetLeaderboard
    """Libraries or people ranked over a period, with the previous rank."""
    get_usage_settings: GetUsageSettings
    """Whether the people leaderboard is on, and the retention."""

    @classmethod
    def build(
        cls,
        *,
        counts: UsageCounts,
        people: People,
        libraries: LibraryAccess,
        clock: Clock,
        policy: UsagePolicy | None = None,
        tally: UsageTally | None = None,
    ) -> Self:
        """Wire the use cases.

        Args:
            counts: Where the daily counts are stored.
            people: Who may be shown by name (identity).
            libraries: Which libraries the caller may read (identity's library roles).
            clock: The current time: the UTC day a request counts to.
            policy: Whether the people leaderboard is on, and the retention; default off and 13
                months.
            tally: Where counts wait to be written; a new, empty one by default.

        Returns:
            The module.
        """
        policy = policy or UsagePolicy()
        tally = UsageTally() if tally is None else tally
        flush = FlushUsageUseCase(tally=tally, counts=counts)
        reports = UsageReports(counts=counts, flush=flush, clock=clock)
        return cls(
            record_usage=RecordUsageUseCase(tally=tally, clock=clock),
            flush_usage=flush,
            prune_usage=PruneUsageUseCase(counts=counts, policy=policy, clock=clock),
            get_usage_stats=GetUsageStatsUseCase(reports=reports, people=people, policy=policy),
            get_account_usage=GetAccountUsageUseCase(reports=reports),
            get_leaderboard=GetLeaderboardUseCase(
                reports=reports, people=people, libraries=libraries, policy=policy
            ),
            get_usage_settings=GetUsageSettingsUseCase(policy=policy),
        )
