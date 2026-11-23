"""In-memory driven adapters of the usage domain, for tests."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from exactdocs.usage.models import Dimension, Person, UsageKey, UsageSelection, UsageSum


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryUsageCounts:
    """Implements ``ports.driven.UsageCounts``. For tests."""

    counts: dict[UsageKey, int] = field(default_factory=dict)
    """The stored counts, by counter."""

    async def add(self, counts: Mapping[UsageKey, int]) -> None:
        """Add counts to the stored ones (a zero creates no counter, as in SQL).

        Args:
            counts: How many to add to each counter.
        """
        for key, count in counts.items():
            if count:
                self.counts[key] = self.counts.get(key, 0) + count

    async def sums(self, selection: UsageSelection) -> Sequence[UsageSum]:
        """Sum the stored counts of a range of days by the selected columns.

        Args:
            selection: The days, the columns to sum by and the filters.

        Returns:
            One sum per distinct value of the selected columns.
        """
        by = selection.by
        totals: dict[UsageSum, int] = {}
        for key, count in self.counts.items():
            if not _selected(key, selection):
                continue
            group = UsageSum(
                count=0,
                day=key.day if Dimension.DAY in by else None,
                account=key.account if Dimension.ACCOUNT in by else None,
                token=key.token if Dimension.CREDENTIAL in by else None,
                library=key.library if Dimension.LIBRARY in by else None,
                operation=key.operation if Dimension.OPERATION in by else None,
            )
            totals[group] = totals.get(group, 0) + count
        return [replace(group, count=count) for group, count in totals.items() if count]

    async def prune(self, before: date) -> int:
        """Delete every count of a day before the given one.

        Args:
            before: The first day kept.

        Returns:
            How many counters were deleted.
        """
        old = [key for key in self.counts if key.day < before]
        for key in old:
            del self.counts[key]
        return len(old)


def _selected(key: UsageKey, selection: UsageSelection) -> bool:
    """Tell whether a counter falls in a selection's days and filters.

    Args:
        key: The counter.
        selection: The days and filters.

    Returns:
        Whether it is summed.
    """
    return (
        selection.first <= key.day <= selection.last
        and selection.account in {None, key.account}
        and selection.library in {None, key.library}
        and selection.operation in {None, key.operation}
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryPeople:
    """Implements ``ports.driven.People``: the people who opted in, given. For tests."""

    people: Mapping[str, str] = field(default_factory=dict)
    """The usernames of the accounts that may be shown by name, by account ID."""

    async def shown(self, account_ids: Collection[str]) -> Sequence[Person]:
        """Return the given accounts that may be shown by name.

        Args:
            account_ids: The accounts asked about.

        Returns:
            Those among ``people``.
        """
        return [
            Person(id=account, username=self.people[account])
            for account in sorted(account_ids)
            if account in self.people
        ]


@dataclass(frozen=True, slots=True, kw_only=True)
class InMemoryLibraryAccess:
    """Implements ``ports.driven.LibraryAccess`` with a fixed set of readable libraries."""

    readable_libraries: frozenset[str] | None = None
    """The lower-case IDs the caller may read; ``None``: every library."""

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Return the libraries among these that the caller may read.

        Args:
            libraries: Library IDs, lower-case.

        Returns:
            Those it may read.
        """
        allowed = self.readable_libraries
        return frozenset(lib for lib in libraries if allowed is None or lib in allowed)
