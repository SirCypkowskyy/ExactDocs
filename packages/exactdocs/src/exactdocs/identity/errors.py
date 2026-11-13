from exactdocs_kernel import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)


class InvalidUsernameError(ValidationError):
    """A username is blank, too long or contains whitespace or control characters."""

    code = "invalid_username"

    def __init__(self, max_length: int) -> None:
        """Create the error.

        Args:
            max_length: The most characters allowed, for the message.
        """
        super().__init__(
            f"username must be 1 to {max_length} characters, "
            "without whitespace or control characters"
        )


class AlreadySetUpError(ConflictError):
    """The first admin exists, so the setup is over."""

    code = "already_set_up"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the instance is already set up: an account exists")


class InvalidCredentialsError(UnauthenticatedError):
    """Wrong password or unknown user; deliberately the same error for both."""

    code = "invalid_credentials"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("invalid username or password")


class NotSignedInError(UnauthenticatedError):
    """No session, or one that is unknown, expired or ended; deliberately not told apart."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("sign in to use this")


class UnknownAccountError(NotFoundError):
    """No account has this username or id. Only operators (command line, users page) learn this."""

    code = "unknown_account"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no account has this username")


class ReservedUsernameError(ValidationError):
    """A new username holds a sequence the sign-in throttle uses in its own keys."""

    code = "invalid_username"

    def __init__(self, reserved: str) -> None:
        """Create the error.

        Args:
            reserved: The sequence that is not allowed, for the message.
        """
        super().__init__(f"a username may not contain {reserved!r}")


class UsernameTakenError(ConflictError):
    """Another account already has this username (compared case-insensitively)."""

    code = "username_taken"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("another account already has this username")


class NotSetUpError(ConflictError):
    """No account exists yet: the first one is the admin, made by the setup, not a user."""

    code = "not_set_up"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "the instance is not set up: create the first admin first (exactdocs admin create)"
        )


class LastOperatorError(ConflictError):
    """Disabling this account would leave no enabled admin to manage the others."""

    code = "last_operator"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the last enabled admin cannot be disabled")


class NotAnOperatorError(ForbiddenError):
    """The caller is signed in, but only an admin manages accounts."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("only an admin manages user accounts")


class InvalidTokenNameError(ValidationError):
    """A token name is blank or too long."""

    code = "invalid_token_name"

    def __init__(self, max_length: int) -> None:
        """Create the error.

        Args:
            max_length: The most characters allowed, for the message.
        """
        super().__init__(f"token name must be 1 to {max_length} characters")


class InvalidTokenExpiryError(ValidationError):
    """A token would expire before it exists."""

    code = "invalid_token_expiry"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("a token must expire in the future")


class TooManyTokensError(ConflictError):
    """The account already holds the most tokens it may."""

    code = "too_many_tokens"

    def __init__(self, limit: int) -> None:
        """Create the error.

        Args:
            limit: The most tokens an account may hold, for the message.
        """
        super().__init__(f"an account may hold at most {limit} API tokens; revoke one first")


class InvalidTokenError(UnauthenticatedError):
    """An API token that is unknown, expired or revoked; deliberately not told apart."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the API token is invalid, expired or revoked")


class UnknownTokenError(NotFoundError):
    """No token of the caller has this id."""

    code = "unknown_token"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no such token")


class SignInThrottledError(RateLimitedError):
    """Too many failed sign-ins from this address or for this username; the password is unchecked.

    Deliberately says neither which of the two it is nor whether the username exists.
    """

    def __init__(self, retry_after: int) -> None:
        """Create the error.

        Args:
            retry_after: Seconds until the next attempt may go ahead.
        """
        super().__init__(
            f"too many failed sign-ins; try again in {retry_after} seconds", retry_after
        )
