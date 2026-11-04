"""Identity use cases. Each one satisfies a driving port structurally, without inheriting it."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid7

from pydantic import SecretStr

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    ResetPasswordCommand,
    SessionGrant,
    SessionState,
    SetupState,
)
from exactdocs.identity.errors import (
    AlreadySetUpError,
    InvalidCredentialsError,
    InvalidUsernameError,
    NotSignedInError,
    UnknownAccountError,
)
from exactdocs.identity.models import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    Account,
    AccountId,
    Role,
    Session,
    Username,
    hash_token,
)
from exactdocs.identity.ports.driven import AccountRepository, PasswordHasher, SessionRepository
from exactdocs.identity.ports.driving import Authenticate, IdentifyCaller
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


TOKEN_BYTES = 32  # 256 bits of randomness
# Using a session only writes `last_used_at` when it is older than this: a read-only request
# should not cost a database write each time, and it is tiny next to the 7-day idle timeout.
# Consequence: idle expiry is accurate to this interval, not to the second.
TOUCH_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class SignInUseCase:
    """Implements ``ports.driving.SignIn``."""

    authenticate: Authenticate
    sessions: SessionRepository
    clock: Clock

    async def __call__(
        self, query: AuthenticateQuery, previous_token: str | None = None
    ) -> SessionGrant:
        """Start a session for the account the credentials belong to.

        The session the request arrived with (``previous_token``) is deleted, so signing in
        again does not leave a stale row behind.
        """
        account = await self.authenticate(query)
        now = self.clock.now()
        if previous_token:
            await self.sessions.delete(hash_token(previous_token))
        await self.sessions.delete_expired(
            idle_before=now - IDLE_TIMEOUT, created_before=now - ABSOLUTE_TIMEOUT
        )
        token = secrets.token_urlsafe(TOKEN_BYTES)  # a new one every time: no session fixation
        await self.sessions.add(
            Session(
                token_hash=hash_token(token),
                account_id=AccountId(account.id),
                created_at=now,
                last_used_at=now,
            )
        )
        return SessionGrant(
            token=SecretStr(token),
            account=account,
            max_age=int(ABSOLUTE_TIMEOUT.total_seconds()),
        )


@dataclass(frozen=True, slots=True)
class SignOutUseCase:
    """Implements ``ports.driving.SignOut``."""

    sessions: SessionRepository

    async def __call__(self, token: str) -> None:
        """Delete the session on the server, so a copied cookie stops working too."""
        await self.sessions.delete(hash_token(token))


@dataclass(frozen=True, slots=True)
class IdentifyCallerUseCase:
    """Implements ``ports.driving.IdentifyCaller``."""

    sessions: SessionRepository
    accounts: AccountRepository
    clock: Clock

    async def __call__(self, token: str | None) -> AccountSummary:
        """Return the owner of a live session, or raise ``NotSignedInError``."""
        if not token:
            raise NotSignedInError
        token_hash = hash_token(token)
        # The lookup compares hashes of random tokens, so there is no secret to learn from its
        # timing: an attacker cannot steer which hash a guess produces.
        session = await self.sessions.get(token_hash)
        if session is None:
            raise NotSignedInError
        now = self.clock.now()
        account = (
            None if session.is_expired(now) else await self.accounts.get_by_id(session.account_id)
        )
        if account is None:
            await self.sessions.delete(token_hash)  # expired, or its account is gone
            raise NotSignedInError
        if now - session.last_used_at >= TOUCH_INTERVAL:
            await self.sessions.touch(token_hash, now)
        return AccountSummary.from_model(account)


@dataclass(frozen=True, slots=True)
class GetSessionStateUseCase:
    """Implements ``ports.driving.GetSessionState``."""

    accounts: AccountRepository
    identify_caller: IdentifyCaller

    async def __call__(self, token: str | None) -> SessionState:
        """Report the setup, signed-out or signed-in state for the token."""
        if not await self.accounts.any_exists():
            return SessionState(state="setup_required")
        try:
            account = await self.identify_caller(token)
        except NotSignedInError:
            return SessionState(state="signed_out")
        return SessionState(state="signed_in", account=account)


@dataclass(frozen=True, slots=True)
class ResetPasswordUseCase:
    """Implements ``ports.driving.ResetPassword``."""

    accounts: AccountRepository
    sessions: SessionRepository
    hasher: PasswordHasher

    async def __call__(self, command: ResetPasswordCommand) -> None:
        """Set the new password, then end all the account's sessions.

        In this order, so nobody can sign in with the old password once the sessions are gone.
        """
        try:
            account = await self.accounts.get(Username(command.username))
        except InvalidUsernameError:
            account = None
        if account is None:
            raise UnknownAccountError
        password_hash = await self.hasher.hash(command.password.get_secret_value())
        await self.accounts.set_password_hash(account.id, password_hash)
        await self.sessions.delete_for_account(account.id)
