"""REST adapter of the usage domain (#510): usage reports, leaderboards and their settings."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from exactdocs.usage.dtos import (
    AccountUsageQuery,
    GetUsageSettingsQuery,
    Leaderboard,
    LeaderboardQuery,
    OwnUsageQuery,
    UsageSettingsOut,
    UsageStats,
    UsageStatsQuery,
    ViewLeaderboardQuery,
)
from exactdocs.usage.ports.driving import (
    GetAccountUsage,
    GetLeaderboard,
    GetUsageSettings,
    GetUsageStats,
)


def build_router(
    *,
    get_usage_stats: GetUsageStats,
    get_account_usage: GetAccountUsage,
    get_leaderboard: GetLeaderboard,
    get_usage_settings: GetUsageSettings,
    caller: Callable[..., Awaitable[str]],
    require_operator: Callable[..., Awaitable[None]],
) -> APIRouter:
    """Expose ``/stats/usage``, ``/stats/leaderboard``, ``/stats/settings`` and ``/account/usage``.

    Every route needs a caller (a session or an API token); ``/stats/usage`` only lets an
    operator through.

    Args:
        get_usage_stats: The instance's usage per period and group.
        get_account_usage: The caller's own usage.
        get_leaderboard: Libraries or people ranked over a period.
        get_usage_settings: Whether the people leaderboard is on, and the retention.
        caller: The dependency naming the account of the request.
        require_operator: The dependency that lets only an operator through (403 otherwise).

    Returns:
        The router.
    """
    router = APIRouter(tags=["usage"])
    account = Annotated[str, Depends(caller)]

    @router.get("/stats/usage", name="get_usage_stats", dependencies=[Depends(require_operator)])
    async def usage_stats(query: Annotated[UsageStatsQuery, Query()]) -> UsageStats:
        """Report the instance's reads, searches and agent answers per period. Operators only.

        `series` has one bucket per `period` (UTC days, ISO weeks, months or years; `periods`
        of them, the last holding `until`), zeros included; `groups` breaks the whole range
        down `by` library, person (`account`) or person and API token (`token`). Only counts
        are kept, never what was read or asked. People are named only while the people
        leaderboard is on (`GET /stats/settings`) and only if they opted in
        (`leaderboard_opt_in`); everyone else is summed into one group with `others: true`.
        A search or an answer over several libraries counts to no library (`library: null`).

        Args:
            query: The periods, the breakdown and an optional library.

        Returns:
            The counts per period and per group.
        """
        return await get_usage_stats(query)

    @router.get("/account/usage", name="get_account_usage")
    async def own_usage(who: account, query: Annotated[OwnUsageQuery, Query()]) -> UsageStats:
        """Report your own reads, searches and agent answers per period.

        The same shape as `GET /stats/usage`, over your account only, broken down by library or
        by API token (`token_id: null` is your browser sessions and OAuth sign-ins).

        Args:
            who: The caller.
            query: The periods and the breakdown.

        Returns:
            Your counts per period and per group.
        """
        return await get_account_usage(
            AccountUsageQuery(account_id=who, **query.model_dump(exclude_unset=True))
        )

    @router.get("/stats/leaderboard", name="get_leaderboard")
    async def leaderboard(who: account, query: Annotated[LeaderboardQuery, Query()]) -> Leaderboard:
        """Rank libraries or people by reads, searches or agent answers over a period.

        `period` is the UTC day, ISO week, month or year holding `at` (default today, so the
        current period so far); each entry has its rank in the previous period among the same
        subjects (`previous_rank`, null when it had none). `libraries` ranks only libraries you
        may read. `people` is 403 `people_leaderboard_off` unless the operator turned the
        people leaderboard on, and ranks only people who opted in (`leaderboard_opt_in` in
        `PUT /account/preferences`); your own entry is marked `you`, and given in `you` when
        it is ranked beyond `limit`.

        Args:
            who: The caller.
            query: The subject, metric, period and how many entries.

        Returns:
            The ranked entries.
        """
        return await get_leaderboard(
            ViewLeaderboardQuery(viewer_id=who, **query.model_dump(exclude_unset=True))
        )

    @router.get("/stats/settings", name="get_usage_settings")
    async def usage_settings() -> UsageSettingsOut:
        """Say whether the people leaderboard is on and how long daily counts are kept.

        Both are the operator's configuration (`EXACTDOCS_USAGE__PEOPLE_LEADERBOARD`,
        `EXACTDOCS_USAGE__RETENTION_MONTHS`).

        Returns:
            The settings.
        """
        return await get_usage_settings(GetUsageSettingsQuery())

    return router
