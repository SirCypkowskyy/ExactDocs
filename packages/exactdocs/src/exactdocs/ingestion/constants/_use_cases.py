"""Constants of the use cases: batch sizes, limits and progress."""

import codecs
from typing import Final

from exactdocs.ingestion.constants._models import MAX_IMAGES

MAX_LISTED_REFS: Final[int] = 1000
"""Refs a repository may advertise to be listed."""
MAX_PREVIEW_FILES: Final[int] = 1000
"""Files a repository preview lists."""
SAVE_EVERY_FILES: Final[int] = 100
"""A running import stores its progress at least every this many files (or ``SAVE_EVERY_SECONDS``).
"""
SAVE_EVERY_SECONDS: Final[float] = 0.25
"""A running import stores its progress at least this often (or every ``SAVE_EVERY_FILES``)."""
KNOWN_BATCH: Final[int] = 500
"""Blobs asked about in one call when checking which are already chunked."""
MAX_WANTED_IMAGES: Final[int] = 4 * MAX_IMAGES
"""Distinct image paths looked for per version."""
OUTSIDE_IMAGES_BATCH: Final[int] = 50
"""Image paths outside the selection fetched in one checkout (a batch that is too big is halved)."""
_BOMS: Final[tuple[tuple[bytes, str], ...]] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
"""FF FE 00 00 is also a UTF-16-LE file starting with U+0000; UTF-32 is tried first, and a file that
then fails to decode is reported undecodable, which is right for such a file anyway.
"""
MAX_CONTROL_RATIO: Final[float] = 0.02
"""Share of control characters above which a decoded file is not text."""
_NOT_TEXT: Final[str] = "not text in any supported encoding"
"""Why a file that decodes in no supported encoding is skipped."""
_MAX_DOUBLINGS: Final[int] = 16
"""Most times the wait after failed auto-sync checks doubles."""
