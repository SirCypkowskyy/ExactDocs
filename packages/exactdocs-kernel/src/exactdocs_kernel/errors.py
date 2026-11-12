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
    """Too many of this kind of request are running: try again shortly.

    ``retry_after`` is a hint in whole seconds (an HTTP adapter sends it as ``Retry-After``).
    """

    code = "busy"

    def __init__(self, detail: str, *, retry_after: int = 1) -> None:
        """Create the error.

        Args:
            detail: What is busy, for the caller.
            retry_after: Seconds to wait before trying again; raised to at least 1.
        """
        super().__init__(detail)
        self.retry_after = max(1, retry_after)


class UnauthenticatedError(DomainError):
    """The caller is not signed in, or the credentials they gave are wrong."""

    code = "unauthenticated"


class RateLimitedError(DomainError):
    """The caller asked too often; it may try again after ``retry_after`` seconds."""

    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        """Create the error.

        Args:
            message: What was refused, for the caller.
            retry_after: Seconds to wait before trying again; raised to at least 1.
        """
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class SealedTextUnreadableError(Exception):
    """A sealed text does not open: another secret key or purpose sealed it, or it was altered.

    Raised by the instance's secret box, which every domain reaches through its own ``SecretBox``
    port. It is not a ``DomainError`` and never reaches a client: the adapter that opened the text
    translates it into its own domain's error (ingestion's vault: ``CredentialsRequiredError``).
    """
