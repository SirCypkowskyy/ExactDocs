"""Identity use cases. Each one satisfies a driving port structurally, without inheriting it."""

from dataclasses import dataclass
from uuid import uuid7

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    SetupState,
)
from exactdocs.identity.errors import (
    AlreadySetUpError,
    InvalidCredentialsError,
    InvalidUsernameError,
)
from exactdocs.identity.models import Account, AccountId, Role, Username
from exactdocs.identity.ports.driven import AccountRepository, PasswordHasher
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True)
class GetSetupStateUseCase:
    """Implements ``ports.driving.GetSetupState``."""

    repository: AccountRepository

    async def __call__(self) -> SetupState:
        """Report that setup is required until the first account exists."""
        return SetupState(setup_required=not await self.repository.any_exists())


@dataclass(frozen=True, slots=True)
class CreateFirstAdminUseCase:
    """Implements ``ports.driving.CreateFirstAdmin``."""

    repository: AccountRepository
    hasher: PasswordHasher
    clock: Clock

    async def __call__(self, command: CreateFirstAdminCommand) -> AccountSummary:
        """Create the admin, or raise ``AlreadySetUpError`` when an account exists."""
        if await self.repository.any_exists():
            raise AlreadySetUpError  # cheap early exit; `add_first` below is the atomic check
        username = Username(command.username)
        account = Account(
            id=AccountId(uuid7().hex),
            username=username,
            password_hash=await self.hasher.hash(command.password.get_secret_value()),
            role=Role.ADMIN,
            created_at=self.clock.now(),
        )
        if not await self.repository.add_first(account):
            raise AlreadySetUpError
        return AccountSummary.from_model(account)


@dataclass(frozen=True, slots=True)
class AuthenticateUseCase:
    """Implements ``ports.driving.Authenticate``."""

    repository: AccountRepository
    hasher: PasswordHasher

    async def __call__(self, query: AuthenticateQuery) -> AccountSummary:
        """Return the account when the password matches; the same error for every failure."""
        password = query.password.get_secret_value()
        try:
            account = await self.repository.get(Username(query.username))
        except InvalidUsernameError:
            account = None
        if account is None:
            # Spend the same time as a real check, so response time does not reveal which
            # usernames exist.
            await self.hasher.hash(password)
            raise InvalidCredentialsError
        if not await self.hasher.verify(account.password_hash, password):
            raise InvalidCredentialsError
        return AccountSummary.from_model(account)
