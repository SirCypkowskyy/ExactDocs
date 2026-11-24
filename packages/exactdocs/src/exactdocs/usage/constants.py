"""Every constant of the usage domain (#510): daily counts, their retention and the leaderboards."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

DEFAULT_RETENTION_MONTHS: Final[int] = 13
"""How many months of daily counts are kept unless the operator sets another number: a year and
the month before it, so a month compares with the same month a year earlier."""

MAX_RETENTION_MONTHS: Final[int] = 120
"""The longest retention an operator may set, in months: per-person usage is monitoring data,
kept only for a bounded time."""

NO_LIBRARY: Final[str] = ""
"""What a count stores as its library when the operation was not about exactly one library (a
search or an answer over several, or all, of them)."""

NO_ACCOUNT: Final[str] = ""
"""What a count stores as its account when no person made the request (a process the owner runs
without a credential)."""

NO_TOKEN: Final[str] = ""
"""What a count stores as its token when the request carried no API token (a browser session,
or an OAuth sign-in over MCP)."""

MAX_PENDING_COUNTS: Final[int] = 100_000
"""Most distinct counters held in memory between two writes; past it, new ones are dropped (and
the drop is reported) instead of exhausting memory while the database cannot be written."""

COUNTS_PER_WRITE: Final[int] = 500
"""Counters upserted per statement when the pending ones are written."""

DEFAULT_PERIODS: Final[Mapping[str, int]] = MappingProxyType(
    {"day": 30, "week": 12, "month": 12, "year": 2}
)
"""How many periods a usage report covers when the request names no number, by period."""

MAX_PERIODS: Final[int] = 400
"""Most periods one usage report covers (400 days is beyond the default retention)."""

DEFAULT_GROUPS: Final[int] = 50
"""Groups (libraries, people or tokens) a usage report lists unless asked for another number."""

MAX_GROUPS: Final[int] = 200
"""Most groups a usage report lists."""

DEFAULT_LEADERBOARD_SIZE: Final[int] = 100
"""Entries a leaderboard lists unless asked for another number: the top ten and ranks 11 to 100."""

MAX_LEADERBOARD_SIZE: Final[int] = 200
"""Most entries a leaderboard lists."""

PEOPLE_LEADERBOARD_OFF: Final[str] = (
    "the people leaderboard is off on this instance; the libraries leaderboard is always on"
)
"""Why a people leaderboard is refused while the operator has it off."""
