"""Shared kernel: the only code every ExactDocs domain may import.

Keep it small, stable and framework-free. It must never import ``exactdocs``.
"""

from exactdocs_kernel.clock import Clock, SystemClock
from exactdocs_kernel.errors import ConflictError, DomainError, NotFoundError, ValidationError
from exactdocs_kernel.pagination import DEFAULT_LIMIT, MAX_LIMIT, InvalidCursorError, Page, paginate

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "Clock",
    "ConflictError",
    "DomainError",
    "InvalidCursorError",
    "NotFoundError",
    "Page",
    "SystemClock",
    "ValidationError",
    "paginate",
]
