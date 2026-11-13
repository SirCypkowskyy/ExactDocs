"""Identity use cases. Each one satisfies a driving port structurally, without inheriting it."""

import logging
import math
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import uuid7

from pydantic import SecretStr

from exactdocs.identity.constants import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    MAX_TOKENS_PER_ACCOUNT,
    PREFIX_SHOWN,
    RESERVED_IN_USERNAME,
    TOKEN_BYTES,
    TOUCH_INTERVAL,
    VALUE_PREFIX,
)
from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    LoginForTokenCommand,
    PasswordReset,
    ResetPasswordCommand,
    SessionGrant,
    SessionState,
    SetupState,
    SetUserDisabledCommand,
    ThrottleReset,
    TokenGrant,
    TokenList,
    TokenSummary,
    UserList,
    UserSummary,
)
from exactdocs.identity.errors import (
    AlreadySetUpError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidTokenExpiryError,
    InvalidUsernameError,
    LastOperatorError,
    NotSetUpError,
    NotSignedInError,
    ReservedUsernameError,
    SignInThrottledError,
    TooManyTokensError,
    UnknownAccountError,
    UnknownTokenError,
    UsernameTakenError,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ApiToken,
    Role,
    Session,
    Username,
    address_key,
    hash_token,
    known_sign_in_key,
)
from exactdocs.identity.ports.driven import (
    AccountRepository,
    FailedSignInLog,
    PasswordHasher,
    SessionRepository,
    TokenRepository,
)
from exactdocs.identity.ports.driving import Authenticate, CreateToken, IdentifyCaller
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSetupStateUseCase:
    """Implements ``ports.driving.GetSetupState``."""

    repository: AccountRepository
    """Where accounts are stored."""

    async def __call__(self) -> SetupState:
        """Report that setup is required until the first account exists.

        Returns:
            Whether setup is still required.
        """
        return SetupState(setup_required=not await self.repository.any_exists())


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateFirstAdminUseCase:
    """Implements ``ports.driving.CreateFirstAdmin``."""

    repository: AccountRepository
    """Where accounts are stored."""
    hasher: PasswordHasher
    """The password hasher."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: CreateFirstAdminCommand) -> AccountSummary:
        """Create the admin, or raise ``AlreadySetUpError`` when an account exists.

        Args:
            command: The first admin's username and password.

        Returns:
            The new account.

        Raises:
            AlreadySetUpError: An account exists already.
        """
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


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticateUseCase:
    """Implements ``ports.driving.Authenticate``.

    The one place a password is checked, so every way to sign in shares the throttle: attempts
    are counted per client address and per username, and once either is past
    ``FREE_FAILURES`` the next attempt must wait (``SignInThrottledError``), doubling each time.
    Each attempt is counted before its password is checked, in the same atomic step as the
    check (``FailedSignInLog.charge``), so attempts made at the same time get no more guesses
    than attempts made one by one. A refused attempt is not counted and its password is not
    checked; a right password takes its own attempt back.

    An address that has signed into a username before (``REMEMBER_SIGN_INS_FOR``) is not held
    to that username's count, only to its own: others' failures for the username cannot lock
    its owner out of a machine they already use.
    """

    repository: AccountRepository
    """Where accounts are stored."""
    hasher: PasswordHasher
    """The password hasher."""
    failures: FailedSignInLog
    """The sign-in throttle's counts."""
    clock: Clock
    """The current time."""

    async def __call__(
        self, query: AuthenticateQuery, *, client: str | None = None
    ) -> AccountSummary:
        """Return the account when the password matches; the same error for every failure.

        Args:
            query: The username and password.
            client: The caller's address, when known.

        Returns:
            The account the credentials belong to.

        Raises:
            SignInThrottledError: Too many recent failures from the address or for the username.
            InvalidCredentialsError: The username is unknown or the password is wrong.
        """
        password = query.password.get_secret_value()
        try:
            username: Username | None = Username(query.username)
        except InvalidUsernameError:
            username = None
        address = address_key(client) if client else None
        known = known_sign_in_key(username, address) if username and address else None
        now = self.clock.now()
        trusted = known is not None and await self.failures.signed_in_before(known, now)
        keys = [
            *([address] if address else []),
            *([f"username:{username}"] if username and not trusted else []),
        ]
        wait = await self.failures.charge(keys, now)
        if wait > timedelta(0):
            raise SignInThrottledError(math.ceil(wait.total_seconds()))
        account = await self.repository.get(username) if username else None
        if account is None:
            # Spend the same time as a real check, so response time does not reveal which
            # usernames exist.
            await self.hasher.hash(password)
            raise InvalidCredentialsError
        if not await self.hasher.verify(account.password_hash, password):
            raise InvalidCredentialsError
        if account.is_disabled:
            # Checked after the password, with the same error and the attempt still counted, so
            # the answer tells nobody whether the account exists, is disabled or the password
            # is wrong.
            raise InvalidCredentialsError
        # The account's own count starts over; the address only gets this attempt back (its
        # wait is not restarted), so one good password does not buy an address a fresh round of
        # guesses at others.
        # A busy throttle skips this (and logs it): the owner then waits out the count, as before.
        await self.failures.forget(f"username:{username}")
        if address and known:
            await self.failures.refund(address, now)
            await self.failures.remember_sign_in(known, self.clock.now())
        return AccountSummary.from_model(account)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInUseCase:
    """Implements ``ports.driving.SignIn``."""

    authenticate: Authenticate
    """Checks the credentials, under the sign-in throttle."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    clock: Clock
    """The current time."""

    async def __call__(
        self,
        query: AuthenticateQuery,
        previous_token: str | None = None,
        *,
        client: str | None = None,
    ) -> SessionGrant:
        """Start a session for the account the credentials belong to.

        The session the request arrived with (``previous_token``) is deleted, so signing in
        again does not leave a stale row behind. ``client`` is the caller's address, for the
        sign-in throttle.

        Args:
            query: The username and password.
            previous_token: The caller's current session token, if any.
            client: The caller's address, when known.

        Returns:
            The new session, with its secret token.
        """
        account = await self.authenticate(query, client=client)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class SignOutUseCase:
    """Implements ``ports.driving.SignOut``."""

    sessions: SessionRepository
    """Where browser sessions are stored."""

    async def __call__(self, token: str) -> None:
        """Delete the session on the server, so a copied cookie stops working too.

        Args:
            token: The session token.
        """
        await self.sessions.delete(hash_token(token))


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentifyCallerUseCase:
    """Implements ``ports.driving.IdentifyCaller``."""

    sessions: SessionRepository
    """Where browser sessions are stored."""
    accounts: AccountRepository
    """Where accounts are stored."""
    clock: Clock
    """The current time."""

    async def __call__(self, token: str | None) -> AccountSummary:
        """Return the owner of a live session, or raise ``NotSignedInError``.

        Args:
            token: The session token, or ``None`` when the request carried none.

        Returns:
            The signed-in account.

        Raises:
            NotSignedInError: No token, or its session is unknown, expired or of a deleted or
                disabled account.
        """
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
        if account is None or account.is_disabled:
            # Expired, or its account is gone or disabled. Disabling deletes the account's
            # sessions already; this also refuses one a sign-in racing the disable created.
            await self.sessions.delete(token_hash)
            raise NotSignedInError
        if now - session.last_used_at >= TOUCH_INTERVAL:
            await self.sessions.touch(token_hash, now)
        return AccountSummary.from_model(account)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSessionStateUseCase:
    """Implements ``ports.driving.GetSessionState``."""

    accounts: AccountRepository
    """Where accounts are stored."""
    identify_caller: IdentifyCaller
    """Resolves the session token."""

    async def __call__(self, token: str | None) -> SessionState:
        """Report the setup, signed-out or signed-in state for the token.

        Args:
            token: The session token, or ``None`` when the request carried none.

        Returns:
            The setup and sign-in state.
        """
        if not await self.accounts.any_exists():
            return SessionState(state="setup_required")
        try:
            account = await self.identify_caller(token)
        except NotSignedInError:
            return SessionState(state="signed_out")
        return SessionState(state="signed_in", account=account)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResetPasswordUseCase:
    """Implements ``ports.driving.ResetPassword``."""

    accounts: AccountRepository
    """Where accounts are stored."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    tokens: TokenRepository
    """Where API tokens are stored."""
    hasher: PasswordHasher
    """The password hasher."""
    failures: FailedSignInLog
    """The sign-in throttle; the account's username count and the addresses it remembers for the
    username are dropped once the password is set."""

    async def __call__(self, command: ResetPasswordCommand) -> PasswordReset:
        """Set the new password, then end all the account's sessions and revoke its API tokens.

        A reset is the recovery after a compromise, so nothing issued before it may survive.

        In this order, so nobody can sign in with the old password once the sessions are gone.
        Last, the username's throttle count is dropped, so the owner can sign in with the new
        password straight away, and so is every address remembered for the username (an address
        that signed in with the old password would otherwise go on skipping the username's
        count). The CLI has no client address, so none of them is kept. The client addresses'
        counts and other usernames' counts and remembered sign-ins stay. This only reaches other
        processes when the log is shared (the database-backed log, on PostgreSQL); an in-memory
        log belongs to the process that runs the reset.

        By then the reset itself is done, so a throttle that is busy or fails does not undo or
        fail it: the result says so (``throttle``, the worse of the two steps), and running the
        reset again is safe. An unknown account is refused with ``UnknownAccountError``.

        Args:
            command: The account (its username or id) and its new password.

        Returns:
            The account, and what became of its username's throttle count and remembered
            sign-ins.
        """
        account = await _find_account(
            self.accounts, account_id=command.id, username=command.username
        )
        password_hash = await self.hasher.hash(command.password.get_secret_value())
        await self.accounts.set_password_hash(account.id, password_hash)
        await self.sessions.delete_for_account(account.id)
        await self.tokens.delete_for_account(account.id)
        throttle = await _clear_throttle(self.failures, str(account.username))
        return PasswordReset(account=AccountSummary.from_model(account), throttle=throttle)


async def _find_account(
    accounts: AccountRepository, *, account_id: str | None, username: str | None
) -> Account:
    """Return the account an operator named, by its id or by its username.

    Args:
        accounts: Where accounts are stored.
        account_id: The account's id, when it is named that way.
        username: The account's username, when it is named that way.

    Returns:
        The account.

    Raises:
        UnknownAccountError: No account has that id or username.
    """
    account: Account | None = None
    if account_id is not None:
        account = await accounts.get_by_id(AccountId(account_id))
    elif username is not None:
        try:
            account = await accounts.get(Username(username))
        except InvalidUsernameError:
            account = None
    if account is None:
        raise UnknownAccountError
    return account


async def _clear_throttle(failures: FailedSignInLog, username: str) -> ThrottleReset:
    """Drop a username's sign-in throttle count and every address remembered for it.

    The client addresses' own counts and other usernames' stay. A throttle that is busy or
    fails does not raise: the result says so (the worse of the two steps), and clearing again
    is safe.

    Args:
        failures: The sign-in throttle.
        username: The (normalised) username.

    Returns:
        ``cleared``, ``busy`` (the log skipped a step) or ``failed`` (a step raised).
    """
    count = await _forget_throttle(
        lambda: failures.forget(f"username:{username}"), "a username's count was not reset"
    )
    remembered = await _forget_throttle(
        lambda: failures.forget_remembered(username),
        "a username's remembered sign-ins were not forgotten",
    )
    # The worse of the two: either one left undone is worth a warning.
    outcomes = {count, remembered}
    return "failed" if "failed" in outcomes else "busy" if "busy" in outcomes else "cleared"


async def _forget_throttle(forget: Callable[[], Awaitable[bool]], what: str) -> ThrottleReset:
    """Await one of the throttle's forgets, reporting rather than raising a failure.

    Args:
        forget: Starts the forget; called inside the ``try``, so a forget that raises
            before it awaits anything is reported too.
        what: What stays when it fails, for the log.

    Returns:
        ``cleared``, ``busy`` (the log skipped it) or ``failed`` (the log raised).
    """
    try:
        cleared = await forget()
    except Exception as error:  # ruff: ignore[blind-except] - the account changed already
        # No traceback: the change worked, and one would read as if it had not.
        logger.warning("Sign-in throttle failed: %s (%s)", what, type(error).__name__)
        return "failed"
    return "cleared" if cleared else "busy"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListUsersUseCase:
    """Implements ``ports.driving.ListUsers``."""

    accounts: AccountRepository
    """Where accounts are stored."""

    async def __call__(self) -> UserList:
        """List every local account, disabled ones included.

        Returns:
            The accounts, oldest first.
        """
        return UserList(users=[UserSummary.from_model(a) for a in await self.accounts.list_all()])


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateUserUseCase:
    """Implements ``ports.driving.CreateUser``."""

    accounts: AccountRepository
    """Where accounts are stored."""
    hasher: PasswordHasher
    """The password hasher."""
    failures: FailedSignInLog
    """The sign-in throttle; any count the new username collected is dropped."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: CreateUserCommand) -> UserSummary:
        """Create a further local account.

        Only after the setup: the first account must be the admin the setup makes. Once the
        account is stored, the throttle forgets whatever failures were counted against its
        username before it existed, so guesses at a name cannot lock its new owner out.

        Args:
            command: The new account's username, password and role.

        Returns:
            The new account.

        Raises:
            NotSetUpError: No account exists yet.
            ReservedUsernameError: The username holds ``RESERVED_IN_USERNAME``.
            UsernameTakenError: Another account has the username.
        """
        if not await self.accounts.any_exists():
            raise NotSetUpError
        username = Username(command.username)
        if RESERVED_IN_USERNAME in username.value:
            raise ReservedUsernameError(RESERVED_IN_USERNAME)
        if await self.accounts.get(username) is not None:
            raise UsernameTakenError  # cheap early exit; `add` below is the atomic check
        account = Account(
            id=AccountId(uuid7().hex),
            username=username,
            password_hash=await self.hasher.hash(command.password.get_secret_value()),
            role=Role(command.role),
            created_at=self.clock.now(),
        )
        if not await self.accounts.add(account):
            raise UsernameTakenError
        await _clear_throttle(self.failures, username.value)
        return UserSummary.from_model(account)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetUserDisabledUseCase:
    """Implements ``ports.driving.SetUserDisabled``."""

    accounts: AccountRepository
    """Where accounts are stored."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    tokens: TokenRepository
    """Where API tokens are stored."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: SetUserDisabledCommand) -> UserSummary:
        """Disable or enable the account. Doing what is already done is not an error.

        Disabling marks the account first, so a sign-in, a session or a token checked from
        then on is refused; then every session of the account ends and every token is
        revoked, so nothing issued before survives an enable either. Enabling lets the account
        sign in again, with its password unchanged. An unknown account is refused with
        ``UnknownAccountError``.

        Args:
            command: The account (its username or id), and whether to disable or enable it.

        Returns:
            The account as it is now.

        Raises:
            LastOperatorError: The account is the last enabled admin.
        """
        account = await _find_account(
            self.accounts, account_id=command.id, username=command.username
        )
        if command.disabled == account.is_disabled:
            return UserSummary.from_model(account)
        disabled_at = self.clock.now() if command.disabled else None
        if not await self.accounts.set_disabled_at(account.id, disabled_at):
            raise LastOperatorError
        if command.disabled:
            await self.sessions.delete_for_account(account.id)
            await self.tokens.delete_for_account(account.id)
        return UserSummary.from_model(replace(account, disabled_at=disabled_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTokenUseCase:
    """Implements ``ports.driving.CreateToken``."""

    tokens: TokenRepository
    """Where API tokens are stored."""
    clock: Clock
    """The current time."""

    async def __call__(self, account: AccountSummary, command: CreateTokenCommand) -> TokenGrant:
        """Mint a token. Only its hash is stored; the secret is returned this once.

        Args:
            account: The account the token acts as.
            command: The token's name and expiry.

        Returns:
            The new token, with its secret.

        Raises:
            InvalidTokenExpiryError: ``expires_at`` is not in the future.
            TooManyTokensError: The account holds ``MAX_TOKENS_PER_ACCOUNT`` tokens already.
        """
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


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginForTokenUseCase:
    """Implements ``ports.driving.LoginForToken``."""

    authenticate: Authenticate
    """Checks the credentials, under the sign-in throttle."""
    create_token: CreateToken
    """Mints the token."""

    async def __call__(
        self, command: LoginForTokenCommand, *, client: str | None = None
    ) -> TokenGrant:
        """Mint a token for the account the credentials belong to (``client``: see ``SignIn``).

        Args:
            command: The credentials and the new token's name and expiry.
            client: The caller's address, when known.

        Returns:
            The new token, with its secret.
        """
        query = AuthenticateQuery(username=command.username, password=command.password)
        account = await self.authenticate(query, client=client)
        return await self.create_token(
            account, CreateTokenCommand(name=command.name, expires_at=command.expires_at)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListTokensUseCase:
    """Implements ``ports.driving.ListTokens``."""

    tokens: TokenRepository
    """Where API tokens are stored."""

    async def __call__(self, account: AccountSummary) -> TokenList:
        """List the account's tokens without their secrets.

        Args:
            account: The account whose tokens to list.

        Returns:
            The tokens, newest first.
        """
        found = await self.tokens.list_for_account(AccountId(account.id))
        return TokenList(tokens=[TokenSummary.from_model(t) for t in found])


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeTokenUseCase:
    """Implements ``ports.driving.RevokeToken``."""

    tokens: TokenRepository
    """Where API tokens are stored."""

    async def __call__(self, account: AccountSummary, token_id: str) -> None:
        """Delete the token, so it stops working at once.

        Args:
            account: The account that owns the token.
            token_id: The token's id.

        Raises:
            UnknownTokenError: The account has no token by this id.
        """
        if not await self.tokens.delete(AccountId(account.id), token_id):
            raise UnknownTokenError


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentifyTokenUseCase:
    """Implements ``ports.driving.IdentifyToken``."""

    tokens: TokenRepository
    """Where API tokens are stored."""
    accounts: AccountRepository
    """Where accounts are stored."""
    clock: Clock
    """The current time."""

    async def __call__(self, token: str) -> AccountSummary:
        """Return the account the token acts as, or raise ``InvalidTokenError``.

        Args:
            token: The API token's secret.

        Returns:
            The account the token acts as.

        Raises:
            InvalidTokenError: The token is unknown, expired, or its account is gone or disabled.
        """
        token_hash = hash_token(token)
        # Looked up by the hash of a random secret, like sessions: no timing to learn from.
        found = await self.tokens.get(token_hash)
        if found is None:
            raise InvalidTokenError
        now = self.clock.now()
        if found.is_expired(now):
            raise InvalidTokenError
        account = await self.accounts.get_by_id(found.account_id)
        if account is None or account.is_disabled:
            raise InvalidTokenError
        if found.last_used_at is None or now - found.last_used_at >= TOUCH_INTERVAL:
            try:
                await self.tokens.touch(token_hash, now)
            except Exception:  # ruff: ignore[blind-except] - bookkeeping must not break a valid token
                logger.warning("could not record API token use")
        return AccountSummary.from_model(account)
