"""Shared kernel: the only code every ExactDocs domain may import.

Keep it small, stable and framework-free. It must never import ``exactdocs``.
"""

from exactdocs_kernel.clock import Clock, SystemClock
from exactdocs_kernel.constants import (
    DEFAULT_LIMIT,
    LIBRARY_ID_PATTERN,
    MAX_CURSOR,
    MAX_LIMIT,
    MAX_NAME,
    MAX_PATH,
    MAX_TAG_INPUT,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    NOTICE,
    TOOL_HINTS,
)
from exactdocs_kernel.errors import (
    BusyError,
    ConflictError,
    DomainError,
    NotFoundError,
    RateLimitedError,
    SealedTextUnreadableError,
    UnauthenticatedError,
    ValidationError,
)
from exactdocs_kernel.pagination import (
    InvalidCursorError,
    Page,
    decode_cursor,
    encode_cursor,
    paginate,
)
from exactdocs_kernel.source_link import section_link
from exactdocs_kernel.tags import normalize_tag

__all__ = [
    "DEFAULT_LIMIT",
    "LIBRARY_ID_PATTERN",
    "MAX_CURSOR",
    "MAX_LIMIT",
    "MAX_NAME",
    "MAX_PATH",
    "MAX_TAGS",
    "MAX_TAG_INPUT",
    "MAX_TAG_LENGTH",
    "NOTICE",
    "TOOL_HINTS",
    "BusyError",
    "Clock",
    "ConflictError",
    "DomainError",
    "InvalidCursorError",
    "NotFoundError",
    "Page",
    "RateLimitedError",
    "SealedTextUnreadableError",
    "SystemClock",
    "UnauthenticatedError",
    "ValidationError",
    "decode_cursor",
    "encode_cursor",
    "normalize_tag",
    "paginate",
    "section_link",
]
