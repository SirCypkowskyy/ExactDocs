from exactdocs_kernel import ConflictError, NotFoundError, UnauthenticatedError, ValidationError


class InvalidUsernameError(ValidationError):
    """A username is blank, too long or contains whitespace or control characters."""

    code = "invalid_username"

    def __init__(self, max_length: int) -> None:
        super().__init__(
            f"username must be 1 to {max_length} characters, "
            "without whitespace or control characters"
        )


class AlreadySetUpError(ConflictError):
    """The first admin exists, so the setup is over."""

    code = "already_set_up"

    def __init__(self) -> None:
        super().__init__("the instance is already set up: an account exists")


class InvalidCredentialsError(UnauthenticatedError):
    """Wrong password or unknown user; deliberately the same error for both."""

    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("invalid username or password")


class NotSignedInError(UnauthenticatedError):
    """No session, or one that is unknown, expired or ended; deliberately not told apart."""

    def __init__(self) -> None:
        super().__init__("sign in to use this")


class UnknownAccountError(NotFoundError):
    """No account has this username. Only operators (the local command line) learn this."""

    code = "unknown_account"

    def __init__(self) -> None:
        super().__init__("no account has this username")


class InvalidTokenNameError(ValidationError):
    """A token name is blank or too long."""

    code = "invalid_token_name"

    def __init__(self, max_length: int) -> None:
        super().__init__(f"token name must be 1 to {max_length} characters")


class InvalidTokenExpiryError(ValidationError):
    """A token would expire before it exists."""

    code = "invalid_token_expiry"

    def __init__(self) -> None:
        super().__init__("a token must expire in the future")


class InvalidTokenError(UnauthenticatedError):
    """An API token that is unknown, expired or revoked; deliberately not told apart."""

    def __init__(self) -> None:
        super().__init__("the API token is invalid, expired or revoked")


class UnknownTokenError(NotFoundError):
    """No token of the caller has this id."""

    code = "unknown_token"

    def __init__(self) -> None:
        super().__init__("no such token")
