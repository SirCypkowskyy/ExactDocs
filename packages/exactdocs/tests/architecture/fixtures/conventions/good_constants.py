"""Constants done right, checked as `constants/_limits.py`."""

from datetime import timedelta
import sys
from typing import Final

SESSION_IDLE: Final[timedelta] = timedelta(days=7)
"""Idle time after which a web session expires."""
PAGE_SIZE: Final[int] = 20
"""Items per page."""
_SCALE: Final[float] = 1.5
"""Private to this topic module."""
__all__ = ["PAGE_SIZE", "SESSION_IDLE"]
if sys.platform == "win32":
    SEPARATOR: Final[str] = "\\"
    """Path separator on Windows."""
else:
    SEPARATOR: Final[str] = "/"
    """Path separator elsewhere."""
