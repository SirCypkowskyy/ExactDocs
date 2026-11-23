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
    MAX_OFFSET,
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
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    SealedTextUnreadableError,
    UnauthenticatedError,
    ValidationError,
)
from exactdocs_kernel.listing import (
    InvalidFilterError,
    InvalidSortError,
    Sort,
    SortValue,
    decode_sort_cursor,
    encode_sort_cursor,
    is_after,
    like_pattern,
    parse_sort,
    sorted_page,
)
from exactdocs_kernel.pagination import (
    CursorWithOffsetError,
    InvalidCursorError,
    Page,
    decode_cursor,
    encode_cursor,
    page_offset,
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
    "MAX_OFFSET",
    "MAX_PATH",
    "MAX_TAGS",
    "MAX_TAG_INPUT",
    "MAX_TAG_LENGTH",
    "NOTICE",
    "TOOL_HINTS",
    "BusyError",
    "Clock",
    "ConflictError",
    "CursorWithOffsetError",
    "DomainError",
    "ForbiddenError",
    "InvalidCursorError",
    "InvalidFilterError",
    "InvalidSortError",
    "NotFoundError",
    "Page",
    "RateLimitedError",
    "SealedTextUnreadableError",
    "Sort",
    "SortValue",
    "SystemClock",
    "UnauthenticatedError",
    "ValidationError",
    "decode_cursor",
    "decode_sort_cursor",
    "encode_cursor",
    "encode_sort_cursor",
    "is_after",
    "like_pattern",
    "normalize_tag",
    "page_offset",
    "paginate",
    "parse_sort",
    "section_link",
    "sorted_page",
]
