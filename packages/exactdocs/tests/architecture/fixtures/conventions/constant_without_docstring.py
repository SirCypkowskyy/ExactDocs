"""Constants without an attribute docstring, checked as `constants/_limits.py`."""

from typing import Final

PAGE_SIZE: Final[int] = 20  # expect: constant-without-docstring
TIMEOUT: Final[float] = 2.5  # expect: constant-without-docstring
# A comment is not a docstring.
RETRIES: Final[int] = 3  # expect: constant-without-docstring
