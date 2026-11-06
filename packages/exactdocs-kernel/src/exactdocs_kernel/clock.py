from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Driven port for the current time, so time-dependent logic stays testable."""

    def now(self) -> datetime:
        """Return the current, timezone-aware time."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemClock:
    """Real wall clock (UTC)."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)
