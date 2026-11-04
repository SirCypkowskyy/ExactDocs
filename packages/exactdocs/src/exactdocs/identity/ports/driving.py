"""Driving (primary) ports: what the outside world may ask identity to do."""

from typing import Protocol

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    ResetPasswordCommand,
    SessionGrant,
    SessionState,
    SetupState,
)


class GetSetupState(Protocol):
    """Tell whether the instance still waits for its first admin."""

    async def __call__(self) -> SetupState:
        """Run the use case."""
        ...


class CreateFirstAdmin(Protocol):
    """Create the first admin; raises ``AlreadySetUpError`` once any account exists."""

    async def __call__(self, command: CreateFirstAdminCommand) -> AccountSummary:
        """Run the use case."""
        ...


class Authenticate(Protocol):
    """Check a username and password; raises ``InvalidCredentialsError`` on any mismatch."""

    async def __call__(self, query: AuthenticateQuery) -> AccountSummary:
        """Run the use case."""
        ...


class SignIn(Protocol):
    """Check credentials and start a session; raises ``InvalidCredentialsError`` on a mismatch."""

    async def __call__(
        self, query: AuthenticateQuery, previous_token: str | None = None
    ) -> SessionGrant:
        """Run the use case; ``previous_token`` (the caller's current session) is ended."""
        ...


class SignOut(Protocol):
    """End the session behind a token. Unknown or ended sessions are not an error."""

    async def __call__(self, token: str) -> None:
        """Run the use case."""
        ...


class IdentifyCaller(Protocol):
    """Who a session token belongs to; raises ``NotSignedInError`` when it is absent or no good."""

    async def __call__(self, token: str | None) -> AccountSummary:
        """Run the use case."""
        ...


class GetSessionState(Protocol):
    """Tell whether setup is due, nobody is signed in, or the token's owner is."""

    async def __call__(self, token: str | None) -> SessionState:
        """Run the use case."""
        ...


class ResetPassword(Protocol):
    """Set a new password and end every session of the account; ``UnknownAccountError`` if none."""

    async def __call__(self, command: ResetPasswordCommand) -> None:
        """Run the use case."""
        ...
