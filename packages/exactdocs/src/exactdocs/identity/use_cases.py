"""Identity use cases. Each one satisfies a driving port structurally, without inheriting it."""

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid7

from pydantic import SecretStr

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    LoginForTokenCommand,
    ResetPasswordCommand,
    SessionGrant,
    SessionState,
    SetupState,
    TokenGrant,
    TokenList,
    TokenSummary,
)
from exactdocs.identity.errors import (
    AlreadySetUpError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidTokenExpiryError,
    InvalidUsernameError,
    NotSignedInError,
    TooManyTokensError,
    UnknownAccountError,
    UnknownTokenError,
)
from exactdocs.identity.models import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    PREFIX_SHOWN,
    VALUE_PREFIX,
    Account,
    AccountId,
    ApiToken,
    Role,
    Session,
    Username,
    hash_token,
)
from exactdocs.identity.ports.driven import (
    AccountRepository,
    PasswordHasher,
    SessionRepository,
    TokenRepository,
)
from exactdocs.identity.ports.driving import Authenticate, CreateToken, IdentifyCaller
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


logger = logging.getLogger(__name__)
MAX_TOKENS_PER_ACCOUNT = 50
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
    tokens: TokenRepository
    hasher: PasswordHasher

    async def __call__(self, command: ResetPasswordCommand) -> None:
        """Set the new password, then end all the account's sessions and revoke its API tokens.

        A reset is the recovery after a compromise, so nothing issued before it may survive.

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
        await self.tokens.delete_for_account(account.id)


@dataclass(frozen=True, slots=True)
class CreateTokenUseCase:
    """Implements ``ports.driving.CreateToken``."""

    tokens: TokenRepository
    clock: Clock

    async def __call__(self, account: AccountSummary, command: CreateTokenCommand) -> TokenGrant:
        """Mint a token. Only its hash is stored; the secret is returned this once."""
        now = self.clock.now()
        if command.expires_at is not None and command.expires_at <= now:
            raise InvalidTokenExpiryError
        await self.tokens.delete_expired(now)
        if len(await self.tokens.list_for_account(AccountId(account.id))) >= MAX_TOKENS_PER_ACCOUNT:
            raise TooManyTokensError(MAX_TOKENS_PER_ACCOUNT)
        secret = VALUE_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
        token = ApiToken(
            id=uuid7().hex,
            account_id=AccountId(account.id),
            name=command.name.strip(),
            token_hash=hash_token(secret),
            prefix=secret[:PREFIX_SHOWN],
            created_at=now,
            expires_at=command.expires_at,
        )
        await self.tokens.add(token)
        return TokenGrant(**TokenSummary.from_model(token).model_dump(), token=secret)


@dataclass(frozen=True, slots=True)
class LoginForTokenUseCase:
    """Implements ``ports.driving.LoginForToken``."""

    authenticate: Authenticate
    create_token: CreateToken

    async def __call__(self, command: LoginForTokenCommand) -> TokenGrant:
        """Mint a token for the account the credentials belong to."""
        query = AuthenticateQuery(username=command.username, password=command.password)
        account = await self.authenticate(query)
        return await self.create_token(account, CreateTokenCommand(name=command.name))


@dataclass(frozen=True, slots=True)
class ListTokensUseCase:
    """Implements ``ports.driving.ListTokens``."""

    tokens: TokenRepository

    async def __call__(self, account: AccountSummary) -> TokenList:
        """List the account's tokens without their secrets."""
        found = await self.tokens.list_for_account(AccountId(account.id))
        return TokenList(tokens=[TokenSummary.from_model(t) for t in found])


@dataclass(frozen=True, slots=True)
class RevokeTokenUseCase:
    """Implements ``ports.driving.RevokeToken``."""

    tokens: TokenRepository

    async def __call__(self, account: AccountSummary, token_id: str) -> None:
        """Delete the token, so it stops working at once."""
        if not await self.tokens.delete(AccountId(account.id), token_id):
            raise UnknownTokenError


@dataclass(frozen=True, slots=True)
class IdentifyTokenUseCase:
    """Implements ``ports.driving.IdentifyToken``."""

    tokens: TokenRepository
    accounts: AccountRepository
    clock: Clock

    async def __call__(self, token: str) -> AccountSummary:
        """Return the account the token acts as, or raise ``InvalidTokenError``."""
        token_hash = hash_token(token)
        # Looked up by the hash of a random secret, like sessions: no timing to learn from.
        found = await self.tokens.get(token_hash)
        if found is None:
            raise InvalidTokenError
        now = self.clock.now()
        if found.is_expired(now):
            raise InvalidTokenError
        account = await self.accounts.get_by_id(found.account_id)
        if account is None:
            raise InvalidTokenError
        if found.last_used_at is None or now - found.last_used_at >= TOUCH_INTERVAL:
            try:
                await self.tokens.touch(token_hash, now)
            except Exception:  # ruff: ignore[blind-except] - bookkeeping must not break a valid token
                logger.warning("could not record API token use")
        return AccountSummary.from_model(account)
