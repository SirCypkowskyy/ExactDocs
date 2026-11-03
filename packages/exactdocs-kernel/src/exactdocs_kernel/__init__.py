"""Shared kernel: the only code every ExactDocs domain may import.

Keep it small, stable and framework-free. It must never import ``exactdocs``.
"""

from exactdocs_kernel.clock import Clock, SystemClock
from exactdocs_kernel.errors import ConflictError, DomainError, NotFoundError, ValidationError

__all__ = [
    "Clock",
    "ConflictError",
    "DomainError",
    "NotFoundError",
    "SystemClock",
    "ValidationError",
]
