"""Driven (secondary) ports: what the usage domain needs from infrastructure and other domains."""

from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Protocol

from exactdocs.usage.models import Person, UsageKey, UsageSelection, UsageSum


class UsageCounts(Protocol):
    """The stored daily counts: one number per day, account, token, library and operation."""

    async def add(self, counts: Mapping[UsageKey, int]) -> None:
        """Add counts to the stored ones, creating the counters that do not exist yet.

        All of them or none: a failure leaves the stored counts as they were.

        Args:
            counts: How many to add to each counter.
        """
        ...

    async def sums(self, selection: UsageSelection) -> Sequence[UsageSum]:
        """Sum the stored counts of a range of days by the selected columns.

        Args:
            selection: The days, the columns to sum by and the filters.

        Returns:
            One sum per distinct value of the selected columns that has counts, in no order.
        """
        ...

    async def prune(self, before: date) -> int:
        """Delete every count of a day before the given one.

        Args:
            before: The first day kept.

        Returns:
            How many counters were deleted.
        """
        ...


class People(Protocol):
    """Who may be shown by name (identity's accounts and their ``leaderboard_opt_in``)."""

    async def shown(self, account_ids: Collection[str]) -> Sequence[Person]:
        """Return the accounts among these that may be shown by name, with their usernames.

        Args:
            account_ids: The accounts asked about.

        Returns:
            Those that exist, are enabled and opted in.
        """
        ...


class LibraryAccess(Protocol):
    """Which libraries the caller of the current request may read (identity's library roles)."""

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Return the libraries among these that the caller may read.

        Args:
            libraries: Library IDs, lower-case.

        Returns:
            The lower-case IDs the caller may read.
        """
        ...
