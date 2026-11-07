"""Constants defined outside a constants module."""

from typing import Final, NewType

PAGE_SIZE: Final[int] = 20  # expect: constant-outside-constants
"""Items per page."""
_TIMEOUT: Final[float] = 2.5  # expect: constant-outside-constants
"""Seconds to wait."""
retries: Final[int] = 3  # expect: constant-outside-constants
"""Lower-case, but `Final` makes it a constant."""
__all__ = ["PAGE_SIZE"]
logger_name = "not a constant: lower case and not Final"
LOW, HIGH = 1, 9  # expect: constant-outside-constants
"""Several at once are constants, too."""
UserId = NewType("UserId", str)
"""A type, not a constant."""
FIRST = SECOND = 1  # expect: constant-outside-constants
"""Chained: both names are constants."""
try:
    TRIED: Final[int] = 1  # expect: constant-outside-constants
    """Defined in a module-level try block."""
except ImportError:
    TRIED_TOO: Final[int] = 2  # expect: constant-outside-constants
    """Defined in its handler."""
if FIRST:
    BRANCHED: Final[int] = 3  # expect: constant-outside-constants
    """Defined in a module-level if block."""
