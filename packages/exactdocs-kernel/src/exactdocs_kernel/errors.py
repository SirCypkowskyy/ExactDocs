"""Error vocabulary shared by all domains.

Driving adapters translate these into transport errors (HTTP status codes, MCP tool errors)
in one place, so domains never import a web framework to signal failure.
"""


class DomainError(Exception):
    """Base class for expected, business-level failures."""

    code: str = "domain_error"


class NotFoundError(DomainError):
    """The requested thing does not exist (or is not visible to the caller)."""

    code = "not_found"


class ConflictError(DomainError):
    """The request conflicts with the current state."""

    code = "conflict"


class ValidationError(DomainError):
    """The request is well-formed but violates a business rule."""

    code = "validation_error"


class UnauthenticatedError(DomainError):
    """The caller is not signed in, or the credentials they gave are wrong."""

    code = "unauthenticated"


class RateLimitedError(DomainError):
    """The caller asked too often; it may try again after ``retry_after`` seconds."""

    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = max(1, retry_after)
