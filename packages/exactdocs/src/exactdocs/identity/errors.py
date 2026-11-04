from exactdocs_kernel import ConflictError, DomainError, ValidationError


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


class InvalidCredentialsError(DomainError):
    """Wrong password or unknown user; deliberately the same error for both."""

    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("invalid username or password")
