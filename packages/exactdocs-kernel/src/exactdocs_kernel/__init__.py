"""Shared kernel: the only code every ExactDocs domain may import.

Keep it small, stable and framework-free. It must never import ``exactdocs``.
"""

from exactdocs_kernel.clock import Clock, SystemClock
from exactdocs_kernel.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)
from exactdocs_kernel.notice import NOTICE
from exactdocs_kernel.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursorError,
    Page,
    decode_cursor,
    encode_cursor,
    paginate,
)
from exactdocs_kernel.tags import MAX_TAG_LENGTH, MAX_TAGS, normalize_tag

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "NOTICE",
    "Clock",
    "ConflictError",
    "DomainError",
    "InvalidCursorError",
    "NotFoundError",
    "Page",
    "SystemClock",
    "UnauthenticatedError",
    "ValidationError",
    "decode_cursor",
    "encode_cursor",
    "normalize_tag",
    "paginate",
]
