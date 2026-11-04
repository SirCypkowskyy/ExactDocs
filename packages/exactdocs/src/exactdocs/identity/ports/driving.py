"""Driving (primary) ports: what the outside world may ask identity to do."""

from typing import Protocol

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
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
