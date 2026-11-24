"""Errors of the usage domain (#510)."""

from exactdocs.usage.constants import PEOPLE_LEADERBOARD_OFF
from exactdocs_kernel import ForbiddenError, ValidationError


class PeopleLeaderboardOffError(ForbiddenError):
    """A people leaderboard was asked for while the operator has it off."""

    code = "people_leaderboard_off"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(PEOPLE_LEADERBOARD_OFF)


class InvalidRetentionError(ValidationError):
    """A retention that is not a whole number of months the domain keeps counts for."""

    code = "invalid_retention"

    def __init__(self, reason: str) -> None:
        """Create the error.

        Args:
            reason: What the retention must be.
        """
        super().__init__(reason)
