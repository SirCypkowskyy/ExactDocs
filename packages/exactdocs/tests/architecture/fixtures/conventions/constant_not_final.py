"""Constants without a `Final[...]` type, checked as a `constants.py`."""

from typing import Final

PAGE_SIZE = 20  # expect: constant-not-final
"""Items per page."""
TIMEOUT: float = 2.5  # expect: constant-not-final
"""Seconds to wait."""
RETRIES: Final = 3  # expect: constant-not-final
"""`Final` without the type."""
