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


class BusyError(DomainError):
    """Too many of this kind of request are running: try again shortly."""

    code = "busy"


class UnauthenticatedError(DomainError):
    """The caller is not signed in, or the credentials they gave are wrong."""

    code = "unauthenticated"
