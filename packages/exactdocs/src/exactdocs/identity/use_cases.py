"""Identity use cases. Each one satisfies a driving port structurally, without inheriting it."""

import hmac
import logging
import math
import secrets
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid7

from pydantic import SecretStr

from exactdocs.identity.constants import (
    ABSOLUTE_TIMEOUT,
    ACCESS_DISPLAY_NAME,
    ACCESS_LINK_LIFETIME,
    ACCESS_LINK_REFRESH,
    ACCESS_LOG_ACTION,
    ACCESS_PROVIDER,
    ACCOUNT_PAGE,
    CODE_VERIFIER_BYTES,
    GRANT_SORT_FIELDS,
    IDLE_TIMEOUT,
    MAX_TOKENS_PER_ACCOUNT,
    PREFIX_SHOWN,
    RESERVED_IN_USERNAME,
    REVALIDATION_BATCH,
    REVALIDATION_LEASE,
    SIGN_IN_ATTEMPT_LIFETIME,
    SIGN_IN_SECRET_BYTES,
    TOKEN_BYTES,
    TOKEN_SORT_FIELDS,
    TOUCH_INTERVAL,
    USER_SORT_FIELDS,
    VALUE_PREFIX,
)
from exactdocs.identity.dtos import (
    AccessEventSummary,
    AccessLogPage,
    AccountPreferences,
    AccountProvider,
    AccountProviders,
    AccountSummary,
    ApiTokenIdentity,
    AuthenticateQuery,
    ChangePasswordCommand,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    DropLibraryGrantsCommand,
    ExternalSignInResult,
    ExternalSignInStart,
    ExternalTokenIdentity,
    FinishExternalSignInCommand,
    GetPreferencesQuery,
    GrantLibraryRoleCommand,
    LeaderboardPeople,
    LeaderboardPeopleQuery,
    LeaderboardPerson,
    LibraryCreationQuery,
    LibraryGrantList,
    LibraryGrants,
    LibraryGrantSummary,
    LibraryRoles,
    LibraryRolesQuery,
    ListAccessLogQuery,
    ListLibraryAccessLogQuery,
    ListLibraryGrantsQuery,
    LoginForTokenCommand,
    PasswordReset,
    ProviderIconFile,
    ResetPasswordCommand,
    RevalidationReport,
    RevokeLibraryRoleCommand,
    SavePreferencesCommand,
    SessionGrant,
    SessionState,
    SetupState,
    SetUserDisabledCommand,
    SignInProviderSummary,
    StartAccountLinkCommand,
    StartExternalSignInCommand,
    ThrottleReset,
    TokenGrant,
    TokenList,
    TokenListQuery,
    TokenSummary,
    TransferLibraryCommand,
    UserList,
    UserListQuery,
    UserSummary,
)
from exactdocs.identity.errors import (
    AccessAssertionRefusedError,
    AccountDisabledError,
    AlreadySetUpError,
    ExternalAccountError,
    ExternalSignInFailedError,
    IdentityLinkedElsewhereError,
    InvalidCredentialsError,
    InvalidGrantError,
    InvalidTokenError,
    InvalidTokenExpiryError,
    InvalidUsernameError,
    LastOperatorError,
    LastSignInMethodError,
    LibraryRoleRequiredError,
    LinkRefusedError,
    NoLinkedAccountError,
    NoProviderIconError,
    NotAllowedError,
    NotAnOperatorError,
    NotSetUpError,
    NotSignedInError,
    ProviderAccessRevokedError,
    ProviderAlreadyLinkedError,
    ProviderNotLinkedError,
    ProviderUnavailableError,
    ReservedUsernameError,
    SignInCancelledError,
    SignInThrottledError,
    TooManyTokensError,
    UnknownAccountError,
    UnknownGrantError,
    UnknownSignInProviderError,
    UnknownTokenError,
    UsernameTakenError,
    UsernameUnavailableError,
    WrongPasswordError,
)
from exactdocs.identity.models import (
    AccessChange,
    AccessClaims,
    AccessEvent,
    AccessLogFilter,
    AccessPolicy,
    Account,
    AccountId,
    ApiToken,
    ExternalGrant,
    ExternalIdentity,
    LibraryCreationPolicy,
    LibraryGrant,
    LibraryRole,
    Role,
    Session,
    SignInAttempt,
    SignInPolicy,
    SubjectKind,
    Username,
    access_username_candidates,
    address_key,
    effective_role,
    hash_token,
    known_sign_in_key,
    safe_return_to,
    username_candidates,
)
from exactdocs.identity.ports.driven import (
    AccessAssertionVerifier,
    AccessLog,
    AccountRepository,
    ExternalIdentityRepository,
    FailedSignInLog,
    LibraryGrantRepository,
    PasswordHasher,
    PreferencesRepository,
    SecretBox,
    SessionRepository,
    SignInAttemptRepository,
    SignInProvider,
    TokenRepository,
)
from exactdocs.identity.ports.driving import (
    Authenticate,
    CreateToken,
    IdentifyAccessCaller,
    IdentifyCaller,
)
from exactdocs_kernel import (
    Clock,
    DomainError,
    SealedTextUnreadableError,
    decode_cursor,
    encode_cursor,
    page_offset,
    parse_sort,
    sorted_page,
)


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
        if account is None or account.password_hash is None:
            # Spend the same time as a real check, so response time does not reveal which
            # usernames exist, nor which sign in through an identity provider (no password).
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
        return await _start_session(self.sessions, self.clock, account, previous_token)


async def _start_session(
    sessions: SessionRepository,
    clock: Clock,
    account: AccountSummary,
    previous_token: str | None,
) -> SessionGrant:
    """Start a session for an account whose sign-in just succeeded (password or provider).

    The session the request arrived with (``previous_token``) is deleted, so signing in again
    does not leave a stale row behind, and expired sessions are pruned.

    Args:
        sessions: Where browser sessions are stored.
        clock: The current time.
        account: The account signing in.
        previous_token: The caller's current session token, if any.

    Returns:
        The new session, with its secret token.
    """
    now = clock.now()
    if previous_token:
        await sessions.delete(hash_token(previous_token))
    await sessions.delete_expired(
        idle_before=now - IDLE_TIMEOUT, created_before=now - ABSOLUTE_TIMEOUT
    )
    token = secrets.token_urlsafe(TOKEN_BYTES)  # a new one every time: no session fixation
    await sessions.add(
        Session(
            token_hash=hash_token(token),
            account_id=AccountId(account.id),
            created_at=now,
            last_used_at=now,
        )
    )
    return SessionGrant(
        token=SecretStr(token), account=account, max_age=int(ABSOLUTE_TIMEOUT.total_seconds())
    )


async def _external_access_ended(
    externals: ExternalIdentityRepository, account: Account, now: datetime
) -> bool:
    """Whether an external account's access has ended (``access_until`` passed, or no link).

    A local account's access never ends this way.

    Args:
        externals: The links of external identities.
        account: The account.
        now: The current time.

    Returns:
        ``True`` for an external account without access at ``now``.
    """
    if not account.is_external:
        return False
    link = await externals.get_for_account(account.id)
    return link is None or not link.has_access(now)


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
    """Implements ``ports.driving.IdentifyCaller``.

    For an external account (no password) it reads the account's link too: one more query per
    request, on purpose. It is what makes access end at ``access_until`` even when no
    revalidation runs (fail closed); do not cache it or skip it to save the query.
    """

    sessions: SessionRepository
    """Where browser sessions are stored."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external accounts, whose access ends at their ``access_until``."""
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
                disabled account, or of an external account whose access has ended.
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
        if (
            account is None
            or account.is_disabled
            or await _external_access_ended(self.externals, account, now)
        ):
            # Expired, or its account is gone or disabled. Disabling deletes the account's
            # sessions already; this also refuses one a sign-in racing the disable created.
            # An external account whose access ended (lost membership, no check within the
            # grace) fails closed here even when no revalidation ran.
            await self.sessions.delete(token_hash)
            raise NotSignedInError
        if now - session.last_used_at >= TOUCH_INTERVAL:
            await self.sessions.touch(token_hash, now)
        return AccountSummary.from_model(account)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetSessionStateUseCase:
    """Implements ``ports.driving.GetSessionState``.

    A live session cookie wins; without one, a Cloudflare Access token signs its owner in (when
    Access is configured), and the state says so, with where to sign out of Access.
    """

    accounts: AccountRepository
    """Where accounts are stored."""
    identify_caller: IdentifyCaller
    """Resolves the session token."""
    policies: Mapping[str, SignInPolicy] = field(default_factory=dict)
    """The configured identity providers, offered on the sign-in page."""
    identify_access: IdentifyAccessCaller | None = None
    """Resolves a Cloudflare Access token; ``None`` while Access is not configured."""
    access_sign_out_url: str | None = None
    """Where the browser signs out of Cloudflare Access."""

    async def __call__(
        self, token: str | None, access_assertion: str | None = None
    ) -> SessionState:
        """Report the setup, signed-out or signed-in state for the token.

        Args:
            token: The session token, or ``None`` when the request carried none.
            access_assertion: The Cloudflare Access token, used when no session signs anyone in.

        Returns:
            The setup and sign-in state, with the identity providers one may sign in with.
        """
        if not await self.accounts.any_exists():
            return SessionState(state="setup_required")  # the first admin is always local
        providers = [SignInProviderSummary.from_model(p) for p in self.policies.values()]
        try:
            account = await self.identify_caller(token)
        except NotSignedInError:
            pass
        else:
            return SessionState(
                state="signed_in", account=account, providers=providers, source="session"
            )
        if self.identify_access is not None and access_assertion:
            try:
                account = await self.identify_access(access_assertion)
            except NotSignedInError:
                pass
            else:
                return SessionState(
                    state="signed_in",
                    account=account,
                    providers=providers,
                    source="cloudflare_access",
                    sign_out_url=self.access_sign_out_url,
                )
        return SessionState(state="signed_out", providers=providers)


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentifyAccessCallerUseCase:
    """Implements ``ports.driving.IdentifyAccessCaller``.

    The verifier checks the token (signature by the team's keys, issuer, audience, times). A
    person reaches the account linked to (team domain, Access ``sub``); a first visit creates it
    when ``auto_create_users`` is on, never taking over an existing account by name. The role
    follows ``admin_emails`` at every visit. A service token acts as the existing account its
    client ID is mapped to. Every refusal is logged without the token and answers
    ``NotSignedInError``, so the request falls back to the other credentials (or none).

    A visit writes the account's link only when it is older than ``ACCESS_LINK_REFRESH`` or the
    role changed: its ``access_until`` (``ACCESS_LINK_LIFETIME`` ahead) keeps the account's
    sessions and API tokens working that long after its owner last came through Access.
    """

    verifier: AccessAssertionVerifier | None
    """Checks the token; ``None`` while Cloudflare Access is not configured (all refused)."""
    policy: AccessPolicy | None
    """Who Access signs in, and as which account."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external identities to accounts."""
    clock: Clock
    """The current time."""

    async def __call__(self, assertion: str | None) -> AccountSummary:
        """Return the account the Access token signs in, or raise ``NotSignedInError``.

        Args:
            assertion: The Access application token, or ``None`` when the request carried none.

        Returns:
            The account, with its role as of now.

        Raises:
            NotSignedInError: Access is not configured, the token is missing or refused, or it
                names nobody with a usable account.
        """
        if not assertion or self.verifier is None or self.policy is None:
            raise NotSignedInError
        try:
            claims = await self.verifier.verify(assertion)
        except AccessAssertionRefusedError, ProviderUnavailableError:
            raise NotSignedInError from None
        if claims.common_name:
            account = await self._service_account(self.policy, claims.common_name)
        else:
            account = await self._person(self.policy, claims)
        if account is None:
            raise NotSignedInError
        return AccountSummary.from_model(account)

    async def _service_account(self, policy: AccessPolicy, client_id: str) -> Account | None:
        """Return the account a service token is mapped to, if it may be used.

        Args:
            policy: The Access policy.
            client_id: The service token's client ID (``common_name``).

        Returns:
            The account; ``None`` when the token is not mapped, or its account is missing,
            disabled or an external account whose access ended.
        """
        username = policy.service_tokens.get(client_id)
        if username is None:
            logger.info(
                "Cloudflare Access: service token %r is not mapped to an account", client_id
            )
            return None
        account = await self.accounts.get(username)
        if account is None:
            logger.warning(
                "Cloudflare Access: service token %r is mapped to %r, which does not exist",
                client_id,
                username.value,
            )
            return None
        if account.is_disabled or await _external_access_ended(
            self.externals, account, self.clock.now()
        ):
            logger.info("Cloudflare Access: the account of service token %r is disabled", client_id)
            return None
        return account

    async def _person(self, policy: AccessPolicy, claims: AccessClaims) -> Account | None:
        """Return the account of the person the token names, creating it on a first visit.

        Args:
            policy: The Access policy.
            claims: The checked claims.

        Returns:
            The account, with its role as of now; ``None`` when the token names no person, the
            account is disabled or gone, or a first visit may not (or cannot) create one.
        """
        if not claims.subject or not claims.email:
            logger.info("Cloudflare Access: a token names neither a person nor a service token")
            return None
        now = self.clock.now()
        role = policy.role_for(claims.email)
        link = await self.externals.get(policy.team_domain, claims.subject)
        if link is None:
            if not policy.auto_create_users:
                logger.info(
                    "Cloudflare Access: no account is linked to this person and "
                    "auto_create_users is off"
                )
                return None
            return await self._create_account(policy, claims, role, now)
        account = await self.accounts.get_by_id(link.account_id)
        if account is None or account.is_disabled:
            logger.info("Cloudflare Access: the linked account is disabled or gone")
            return None
        if account.role != role or now - link.checked_at >= ACCESS_LINK_REFRESH:
            until = now + ACCESS_LINK_LIFETIME
            await self.externals.record_check(
                replace(
                    link, signed_in_at=now, checked_at=now, next_check_at=until, access_until=until
                ),
                role=role,
                groups=frozenset(),
            )
        return replace(account, role=role)

    async def _create_account(
        self, policy: AccessPolicy, claims: AccessClaims, role: Role, now: datetime
    ) -> Account | None:
        """Create the account of a person's first visit, linked to their Access identity.

        Args:
            policy: The Access policy.
            claims: The checked claims (a person's).
            role: The new account's role.
            now: The current time.

        Returns:
            The new account (or the one a concurrent first visit linked); ``None`` when every
            username it could take is taken.
        """
        email = claims.email or ""
        until = now + ACCESS_LINK_LIFETIME
        identity = ExternalIdentity(
            issuer=policy.team_domain,
            subject=claims.subject,
            account_id=AccountId(""),
            provider=policy.provider,
            signed_in_at=now,
            checked_at=now,
            next_check_at=until,
            access_until=until,
        )
        for username in access_username_candidates(email):
            account = Account(
                id=AccountId(uuid7().hex),
                username=username,
                password_hash=None,
                role=role,
                created_at=now,
            )
            outcome = await self.externals.create_linked_account(
                account, replace(identity, account_id=account.id), frozenset()
            )
            if outcome == "created":
                logger.info("Cloudflare Access: created account %r", username.value)
                return account
            if outcome == "already_linked":
                return await self._person(policy, claims)
        logger.warning("Cloudflare Access: no free username for a person's first visit")
        return None


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

        Raises:
            ExternalAccountError: The account signs in through an identity provider.
        """
        account = await _find_account(
            self.accounts, account_id=command.id, username=command.username
        )
        if account.is_external:
            raise ExternalAccountError  # it signs in through its provider: no password to set
        password_hash = await self.hasher.hash(command.password.get_secret_value())
        await self.accounts.set_password_hash(account.id, password_hash)
        await self.sessions.delete_for_account(account.id)
        await self.tokens.delete_for_account(account.id)
        throttle = await _clear_throttle(self.failures, str(account.username))
        return PasswordReset(account=AccountSummary.from_model(account), throttle=throttle)


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangePasswordUseCase:
    """Implements ``ports.driving.ChangePassword``.

    The current password is checked by ``Authenticate``, so a wrong one costs what a failed
    sign-in costs (the same counts, per client address and per username) and too many of them are
    refused unchecked. Once the new password is stored, every other session of the account ends;
    the one the change was made from stays. API tokens are not touched: they never held the
    password, and the person revokes them on their own page if they may have leaked. Then, as a
    reset does (#322), the username's throttle count and every address remembered for it are
    dropped (those addresses signed in with the old password), and the address the change was
    made from, which knows the new one, is remembered again.
    """

    accounts: AccountRepository
    """Where accounts are stored."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    hasher: PasswordHasher
    """The password hasher."""
    authenticate: Authenticate
    """Checks the current password, under the sign-in throttle."""
    failures: FailedSignInLog
    """The sign-in throttle; the username's count and remembered addresses are dropped."""
    clock: Clock
    """The current time."""

    async def __call__(
        self,
        account: AccountSummary,
        command: ChangePasswordCommand,
        *,
        session_token: str | None = None,
        client: str | None = None,
    ) -> None:
        """Check the current password, store the new one and end the account's other sessions.

        Args:
            account: The signed-in account.
            command: The current password and the new one.
            session_token: The session the change is made from, which stays signed in.
            client: The caller's address, for the sign-in throttle.

        Raises:
            NotSignedInError: The account no longer exists.
            ExternalAccountError: The account has no password (it signs in through a provider).
            WrongPasswordError: The current password is wrong.
        """
        stored = await self.accounts.get_by_id(AccountId(account.id))
        if stored is None:
            raise NotSignedInError
        if stored.is_external:
            raise ExternalAccountError
        query = AuthenticateQuery(username=stored.username.value, password=command.current_password)
        try:
            await self.authenticate(query, client=client)
        except InvalidCredentialsError:
            raise WrongPasswordError from None
        password_hash = await self.hasher.hash(command.new_password.get_secret_value())
        await self.accounts.set_password_hash(stored.id, password_hash)
        await self.sessions.delete_others(
            stored.id, keep=hash_token(session_token) if session_token else None
        )
        username = stored.username.value
        await _clear_throttle(self.failures, username)
        if client:
            known = known_sign_in_key(stored.username, address_key(client))
            await _forget_throttle(
                lambda: _remember(self.failures, known, self.clock.now()),
                "the address the password was changed from is not remembered",
            )


async def _remember(failures: FailedSignInLog, key: str, now: datetime) -> bool:
    """Remember a successful sign-in, in the shape ``_forget_throttle`` reports on.

    Args:
        failures: The sign-in throttle.
        key: The sign-in key (a username at an address).
        now: When it succeeded.

    Returns:
        ``True``: remembering has no busy outcome.
    """
    await failures.remember_sign_in(key, now)
    return True


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


def _contains(text: str, needle: str | None) -> bool:
    """Tell whether a list item passes the text filter ``q``.

    Args:
        text: The item's name.
        needle: The filter; ``None`` or blank lets everything through.

    Returns:
        Whether ``text`` contains ``needle``, in any case.
    """
    return not needle or needle.casefold() in text.casefold()


def _sortable(moment: datetime | None) -> str:
    """Return a time as text that sorts in time order.

    Args:
        moment: The time, or ``None`` (never).

    Returns:
        An ISO 8601 UTC timestamp; empty for ``None``, which sorts first.
    """
    return "" if moment is None else moment.astimezone(UTC).isoformat()


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
    externals: ExternalIdentityRepository
    """The links of external accounts, for their provider and groups."""

    async def __call__(self, query: UserListQuery) -> UserList:
        """List a page of the accounts, disabled ones included, with where each signs in.

        Args:
            query: The filters, the sort and the page.

        Returns:
            The page, its next cursor and how many accounts match.
        """
        sort = parse_sort(query.sort, allowed=USER_SORT_FIELDS, default="created_at")
        links = await self.externals.groups_by_account()
        users = []
        for account in await self.accounts.list_all():
            provider, groups = links.get(account.id, (None, []))
            users.append(UserSummary.from_model(account, provider=provider, groups=groups))
        users = [
            u
            for u in users
            if _contains(u.username, query.q)
            and (query.role is None or u.role in query.role)
            and (query.disabled is None or u.disabled is query.disabled)
        ]
        page = sorted_page(
            users,
            sort=sort,
            key_field="id",
            values={
                "created_at": lambda u: _sortable(u.created_at),
                "username": lambda u: u.username,
                "role": lambda u: u.role,
            },
            key=lambda u: u.id,
            limit=query.limit,
            cursor=query.cursor,
            offset=query.offset,
        )
        return UserList.from_page(page)


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
    externals: ExternalIdentityRepository
    """The links of external accounts: disabling drops their sealed provider tokens."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: SetUserDisabledCommand) -> UserSummary:
        """Disable or enable the account. Doing what is already done is not an error.

        Disabling marks the account first, so a sign-in, a session or a token checked from
        then on is refused; then every session of the account ends and every token is
        revoked, so nothing issued before survives an enable either. Enabling first ends any
        session or token stored while the account was disabled (one that raced the disable),
        then lets the account sign in again, with its password unchanged. An unknown account is
        refused with ``UnknownAccountError``. Disabling an external account also drops its
        sealed provider tokens: nothing checks its memberships any more, and it stays disabled
        whatever its provider says.

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
        if not command.disabled:
            # Nothing can be issued legitimately while the account is disabled; a session or
            # token stored then raced the disable and must not come back to life now.
            await self._end_sessions_and_tokens(account.id)
        if not await self.accounts.set_disabled_at(account.id, disabled_at):
            raise LastOperatorError
        if command.disabled:
            await self._end_sessions_and_tokens(account.id)
            await self.externals.forget_tokens(account.id)
        return UserSummary.from_model(replace(account, disabled_at=disabled_at))

    async def _end_sessions_and_tokens(self, account_id: AccountId) -> None:
        """End every session of the account and revoke every token it holds.

        Args:
            account_id: The account.
        """
        await self.sessions.delete_for_account(account_id)
        await self.tokens.delete_for_account(account_id)


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
            library_ids=command.library_ids,
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
            account,
            CreateTokenCommand(
                name=command.name, expires_at=command.expires_at, library_ids=command.library_ids
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListTokensUseCase:
    """Implements ``ports.driving.ListTokens``."""

    tokens: TokenRepository
    """Where API tokens are stored."""

    async def __call__(self, account: AccountSummary, query: TokenListQuery) -> TokenList:
        """List a page of the account's tokens without their secrets.

        Args:
            account: The account whose tokens to list.
            query: The filters, the sort and the page.

        Returns:
            The page, its next cursor and how many tokens match.
        """
        sort = parse_sort(query.sort, allowed=TOKEN_SORT_FIELDS, default="-created_at")
        found = await self.tokens.list_for_account(AccountId(account.id))
        tokens = [TokenSummary.from_model(t) for t in found if _contains(t.name, query.q)]
        page = sorted_page(
            tokens,
            sort=sort,
            key_field="id",
            values={
                "created_at": lambda t: _sortable(t.created_at),
                "name": lambda t: t.name.casefold(),
                "expires_at": lambda t: _sortable(t.expires_at),
                "last_used_at": lambda t: _sortable(t.last_used_at),
            },
            key=lambda t: t.id,
            limit=query.limit,
            cursor=query.cursor,
            offset=query.offset,
        )
        return TokenList.from_page(page)


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
    """Implements ``ports.driving.IdentifyToken``.

    For an external account (no password) it reads the account's link too: one more query per
    request, on purpose. It is what makes access end at ``access_until`` even when no
    revalidation runs (fail closed); do not cache it or skip it to save the query.
    """

    tokens: TokenRepository
    """Where API tokens are stored."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external accounts, whose tokens are refused once their access ended."""
    clock: Clock
    """The current time."""

    async def __call__(self, token: str) -> ApiTokenIdentity:
        """Return the account the token acts as, or raise ``InvalidTokenError``.

        Args:
            token: The API token's secret.

        Returns:
            The account the token acts as.

        Raises:
            InvalidTokenError: The token is unknown, expired, or its account is gone or disabled,
                or is an external account whose access has ended (until it signs in again).
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
        if (
            account is None
            or account.is_disabled
            or await _external_access_ended(self.externals, account, now)
        ):
            raise InvalidTokenError
        if found.last_used_at is None or now - found.last_used_at >= TOUCH_INTERVAL:
            try:
                await self.tokens.touch(token_hash, now)
            except Exception:  # ruff: ignore[blind-except] - bookkeeping must not break a valid token
                logger.warning("could not record API token use")
        return ApiTokenIdentity(
            **AccountSummary.from_model(account).model_dump(),
            token_id=found.id,
            library_ids=found.library_ids,
        )


def _configured(
    providers: Mapping[str, SignInProvider], policies: Mapping[str, SignInPolicy], name: str
) -> tuple[SignInProvider, SignInPolicy]:
    """Return the configured provider of this name with its policy.

    Args:
        providers: The configured providers, by name.
        policies: Their policies, by name.
        name: The provider's name.

    Returns:
        The provider and its policy.

    Raises:
        UnknownSignInProviderError: No provider of this name is configured.
    """
    provider, policy = providers.get(name), policies.get(name)
    if provider is None or policy is None:
        raise UnknownSignInProviderError
    return provider, policy


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentifyExternalTokenUseCase:
    """Implements ``ports.driving.IdentifyExternalToken``.

    The provider's adapter validates the ID token; the provider's policy then decides, as at a
    web sign-in, whether the person is admitted and with which role. A person linked to an
    account acts as it (a disabled one is refused); anyone else acts as ``<provider>:<subject>``,
    unless the provider creates no accounts (then they are refused). Nothing is created or
    changed: the MCP host's token is checked at every request, so a disabled account loses access
    at the next call; the groups come from the ID token, so a group change shows once the token
    expires and the host renews it. An identity the account's owner linked from Account settings
    only signs in: the account keeps its own role and groups, whatever the provider says.
    """

    providers: Mapping[str, SignInProvider]
    """The configured identity providers, by name."""
    policies: Mapping[str, SignInPolicy]
    """Their policies, by name."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external identities to accounts."""

    async def __call__(self, provider: str, token: str) -> ExternalTokenIdentity:
        """Validate the token and return who it acts as.

        Args:
            provider: The provider's name.
            token: The ID token.

        Returns:
            The caller and signed groups, with the role the policy gives those groups.

        Raises:
            AccountDisabledError: The linked account is disabled.
            ExternalSignInFailedError: The identity links an account that no longer exists.
            NotAllowedError: The provider puts the person in no allowed group.
            NoLinkedAccountError: No account is linked, and the provider creates none.
        """
        adapter, policy = _configured(self.providers, self.policies, provider)
        claims = await adapter.verify_id_token(token)
        link = await self.externals.get(claims.issuer, claims.subject)
        account = None if link is None else await self.accounts.get_by_id(link.account_id)
        if link is not None and account is None:
            raise ExternalSignInFailedError
        if account is not None and account.is_disabled:
            raise AccountDisabledError
        if not policy.admits(claims.groups):
            logger.info("MCP OAuth through %s refused: not in an allowed group", policy.name)
            raise NotAllowedError
        if link is None and not policy.auto_create_users:
            logger.info("MCP OAuth through %s refused: no account is linked", policy.name)
            raise NoLinkedAccountError
        role = policy.role_for(claims.groups).value
        groups = policy.stored_groups(claims.groups)
        if account is not None and link is not None and not link.is_origin:
            # A linked identity only signs in: the account's own role and groups stand.
            role, groups = account.role.value, await self.externals.groups_of(account.id)
        if account is not None:
            caller = AccountSummary(
                id=account.id,
                username=account.username.value,
                role=role,
                has_password=not account.is_external,
            )
        else:
            candidates = username_candidates(claims, policy.name)
            username = candidates[0].value if candidates else claims.subject
            caller = AccountSummary(
                id=f"{policy.name}:{claims.subject}", username=username, role=role
            )
        return ExternalTokenIdentity(account=caller, groups=groups, linked=link is not None)


@dataclass(frozen=True, slots=True, kw_only=True)
class StartExternalSignInUseCase:
    """Implements ``ports.driving.StartExternalSignIn``."""

    providers: Mapping[str, SignInProvider]
    """The configured identity providers, by name."""
    policies: Mapping[str, SignInPolicy]
    """Their policies, by name."""
    attempts: SignInAttemptRepository
    """Where started sign-ins wait for their callback."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: StartExternalSignInCommand) -> ExternalSignInStart:
        """Create a sign-in attempt and return where to send the browser (see ``_begin``).

        Args:
            command: The provider and where to go once signed in.

        Returns:
            The provider's authorization URL and the binding for the browser.
        """
        provider, policy = _configured(self.providers, self.policies, command.provider)
        return await _begin(
            provider,
            policy,
            attempts=self.attempts,
            clock=self.clock,
            return_to=safe_return_to(command.return_to),
        )


async def _begin(
    provider: SignInProvider,
    policy: SignInPolicy,
    *,
    attempts: SignInAttemptRepository,
    clock: Clock,
    return_to: str,
    link_session_hash: str | None = None,
) -> ExternalSignInStart:
    """Store a new attempt (a sign-in, or a link) and return where to send the browser.

    The attempt holds fresh random ``state``, ``nonce`` and PKCE verifier, and is keyed by the
    hash of a random browser binding: the browser gets the binding as a cookie, the provider gets
    only ``state``, ``nonce`` and the verifier's S256 challenge.

    Args:
        provider: The provider's adapter.
        policy: Its policy.
        attempts: Where started attempts wait for their callback.
        clock: The current time.
        return_to: Where the browser goes afterwards (a same-origin path, checked already).
        link_session_hash: For a link, the hash of the session that starts it.

    Returns:
        The provider's authorization URL and the binding for the browser.
    """
    binding = secrets.token_urlsafe(SIGN_IN_SECRET_BYTES)
    attempt = SignInAttempt(
        binding_hash=hash_token(binding),
        provider=policy.name,
        state=secrets.token_urlsafe(SIGN_IN_SECRET_BYTES),
        nonce=secrets.token_urlsafe(SIGN_IN_SECRET_BYTES),
        code_verifier=secrets.token_urlsafe(CODE_VERIFIER_BYTES),
        return_to=return_to,
        created_at=clock.now(),
        link_session_hash=link_session_hash,
    )
    # First the provider (it may be down): nothing is stored for a sign-in that cannot start.
    url = await provider.authorization_url(
        state=attempt.state, nonce=attempt.nonce, code_verifier=attempt.code_verifier
    )
    await attempts.add(attempt, expired_before=attempt.created_at - SIGN_IN_ATTEMPT_LIFETIME)
    return ExternalSignInStart(
        redirect_url=url,
        binding=SecretStr(binding),
        max_age=int(SIGN_IN_ATTEMPT_LIFETIME.total_seconds()),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FinishExternalSignInUseCase:
    """Implements ``ports.driving.FinishExternalSignIn``.

    The callback must come from the browser that started the attempt (its binding cookie), with
    the attempt's ``state``, within ``SIGN_IN_ATTEMPT_LIFETIME``, through the same provider; the
    attempt is taken (deleted) before anything else, so a callback works once at most. Then the
    provider's adapter exchanges the code with the attempt's PKCE verifier and validates the ID
    token (with the attempt's ``nonce``). The identity reaches its account by (issuer, subject)
    only; a first sign-in creates an account, never taking over one by name (unless the provider
    creates no accounts: then an identity no account has linked is refused).

    An attempt started by ``StartAccountLink`` must also come back from the session that started
    it (the caller's session token hashes to the attempt's ``link_session_hash``); the identity is
    then linked to that session's account, and nobody is signed in.
    """

    providers: Mapping[str, SignInProvider]
    """The configured identity providers, by name."""
    policies: Mapping[str, SignInPolicy]
    """Their policies, by name."""
    attempts: SignInAttemptRepository
    """Where started sign-ins wait for their callback."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external identities to accounts."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    identify_caller: IdentifyCaller
    """Resolves the session a link comes back with to its account."""
    box: SecretBox
    """Seals the refresh token before it is stored."""
    clock: Clock
    """The current time."""

    async def __call__(
        self, command: FinishExternalSignInCommand, previous_token: str | None = None
    ) -> ExternalSignInResult:
        """Check the callback, find or create the account and start a session (or link).

        Args:
            command: The callback and the browser's binding.
            previous_token: The caller's current session token, if any.

        Returns:
            The new session (none after a link), and where to send the browser.

        Raises:
            LinkRefusedError: A link was refused, after its attempt was found.
        """
        provider, policy = _configured(self.providers, self.policies, command.provider)
        attempt = await self._take_attempt(command)
        if attempt.link_session_hash is not None:
            try:
                await self._link(provider, policy, attempt, command, previous_token)
            except DomainError as refusal:
                raise LinkRefusedError(refusal, attempt.return_to) from refusal
            return ExternalSignInResult(
                session=None, return_to=attempt.return_to, linked=policy.name
            )
        grant = await _exchange(provider, policy, attempt, command)
        account = await self._account_for(policy, grant)
        session = await _start_session(
            self.sessions, self.clock, AccountSummary.from_model(account), previous_token
        )
        return ExternalSignInResult(session=session, return_to=attempt.return_to)

    async def _link(
        self,
        provider: SignInProvider,
        policy: SignInPolicy,
        attempt: SignInAttempt,
        command: FinishExternalSignInCommand,
        session_token: str | None,
    ) -> None:
        """Link the identity the provider vouches for to the account of the attempt's session.

        Linking an identity that is this account's already changes nothing.

        Args:
            provider: The provider's adapter.
            policy: Its policy.
            attempt: The link's attempt, taken.
            command: The callback.
            session_token: The caller's session token.

        Raises:
            ExternalSignInFailedError: The callback comes from another session (or none).
            NotAllowedError: The provider puts the person in no allowed group.
            IdentityLinkedElsewhereError: The identity is linked to another account.
            ProviderAlreadyLinkedError: The account has another identity of the provider.
        """
        expected = (attempt.link_session_hash or "").encode()
        if not session_token or not hmac.compare_digest(
            hash_token(session_token).encode(), expected
        ):
            logger.info("link through %s refused: the callback is another session's", policy.name)
            raise ExternalSignInFailedError
        account = await self.identify_caller(session_token)
        grant = await _exchange(provider, policy, attempt, command)
        claims = grant.claims
        if not policy.admits(claims.groups):
            logger.info("link through %s refused: not in an allowed group", policy.name)
            raise NotAllowedError
        now = self.clock.now()
        identity = ExternalIdentity(
            issuer=claims.issuer,
            subject=claims.subject,
            account_id=AccountId(account.id),
            provider=policy.name,
            signed_in_at=now,
            checked_at=now,
            next_check_at=now,
            access_until=now,
            linked_at=now,
        )
        outcome = await self.externals.link(identity)
        if outcome == "provider_taken":
            raise ProviderAlreadyLinkedError
        if outcome == "identity_taken":
            existing = await self.externals.get(claims.issuer, claims.subject)
            if existing is None or existing.account_id != account.id:
                raise IdentityLinkedElsewhereError
            logger.info("link through %s: the identity is this account's already", policy.name)
            return
        logger.info("an identity of %s was linked to an account", policy.name)

    async def _take_attempt(self, command: FinishExternalSignInCommand) -> SignInAttempt:
        """Take the browser's attempt and check that this callback belongs to it.

        Args:
            command: The callback and the browser's binding.

        Returns:
            The attempt, now deleted.

        Raises:
            ExternalSignInFailedError: No binding, no attempt for it (never started, or used
                already), another provider, a ``state`` that does not match, or too late.
        """
        if command.binding is None:
            logger.info("external sign-in refused: the browser sent no binding cookie")
            raise ExternalSignInFailedError
        attempt = await self.attempts.take(hash_token(command.binding.get_secret_value()))
        if attempt is None:
            logger.info("external sign-in refused: no attempt for this browser (or used already)")
            raise ExternalSignInFailedError
        state = (command.state or "").encode()
        if (
            attempt.provider != command.provider
            or not hmac.compare_digest(attempt.state.encode(), state)
            or attempt.is_expired(self.clock.now())
        ):
            logger.info("external sign-in refused: provider, state or age does not match")
            raise ExternalSignInFailedError
        return attempt

    async def _account_for(self, policy: SignInPolicy, grant: ExternalGrant) -> Account:
        """Return the account of the identity, after recording this sign-in.

        Args:
            policy: The provider's policy.
            grant: The validated claims and the refresh token.

        Returns:
            The account, with its role as of now.

        Raises:
            ExternalSignInFailedError: The link names an account that does not exist.
            AccountDisabledError: The linked account is disabled.
            NotAllowedError: The provider puts the person in no allowed group (their access, if
                they had any, ends now).
            NoLinkedAccountError: No account is linked, and the provider creates none.
        """
        claims = grant.claims
        now = self.clock.now()
        link = await self.externals.get(claims.issuer, claims.subject)
        account = None if link is None else await self.accounts.get_by_id(link.account_id)
        if link is not None and account is None:  # deleting an account deletes its link
            raise ExternalSignInFailedError
        if account is not None and account.is_disabled:
            raise AccountDisabledError
        if link is not None and account is not None and not link.is_origin:
            return await self._linked_sign_in(policy, link, account, grant, now)
        if link is None and not policy.auto_create_users:
            logger.info("external sign-in through %s refused: no account is linked", policy.name)
            raise NoLinkedAccountError
        if not policy.admits(claims.groups):
            if account is not None:
                await self._end_access(account.id, now)
            logger.info("external sign-in through %s refused: not in an allowed group", policy.name)
            raise NotAllowedError
        role = policy.role_for(claims.groups)
        groups = policy.stored_groups(claims.groups)
        sealed = None if grant.refresh_token is None else self.box.seal(grant.refresh_token)
        identity = ExternalIdentity(
            issuer=claims.issuer,
            subject=claims.subject,
            account_id=AccountId(""),
            provider=policy.name,
            sealed_tokens=sealed,
            signed_in_at=now,
            checked_at=now,
            next_check_at=now + policy.revalidate_every,
            access_until=policy.access_until(now, refreshable=sealed is not None),
        )
        if account is not None:
            await self.externals.record_check(
                replace(identity, account_id=account.id), role=role, groups=groups
            )
            return replace(account, role=role)
        return await self._create_account(policy, grant, identity, role=role, groups=groups)

    async def _linked_sign_in(
        self,
        policy: SignInPolicy,
        link: ExternalIdentity,
        account: Account,
        grant: ExternalGrant,
        now: datetime,
    ) -> Account:
        """Sign in through an identity linked from Account settings: it only opens the door.

        The account keeps its role and groups; an account created through another provider must
        still have access through that one (its origin).

        Args:
            policy: The provider's policy.
            link: The linked identity.
            account: Its account (enabled).
            grant: The validated claims (the refresh token is not kept).
            now: The current time.

        Returns:
            The account, as it is.

        Raises:
            NotAllowedError: The provider puts the person in no allowed group.
            ProviderAccessRevokedError: The account follows another provider, whose access ended.
        """
        if not policy.admits(grant.claims.groups):
            logger.info("external sign-in through %s refused: not in an allowed group", policy.name)
            raise NotAllowedError
        if await _external_access_ended(self.externals, account, now):
            logger.info(
                "sign-in through linked %s refused: the account's access ended", policy.name
            )
            raise ProviderAccessRevokedError
        await self.externals.record_linked_sign_in(link, now)
        return account

    async def _create_account(
        self,
        policy: SignInPolicy,
        grant: ExternalGrant,
        identity: ExternalIdentity,
        *,
        role: Role,
        groups: frozenset[str],
    ) -> Account:
        """Create the account of a first sign-in (just in time), linked to the identity.

        The username comes from the provider (or the email's local part); when another account
        has it, ``<username>@<provider>``. An existing account is never linked by its name.

        Args:
            policy: The provider's policy.
            grant: The validated claims and the refresh token.
            identity: The link to store (its account id is filled in here).
            role: The new account's role.
            groups: The new account's groups.

        Returns:
            The new account; or, when a concurrent first sign-in linked the identity first,
            that one's account.

        Raises:
            UsernameUnavailableError: No usable username, or every candidate is taken.
        """
        candidates = username_candidates(grant.claims, policy.name)
        if not candidates:
            raise UsernameUnavailableError
        for username in candidates:
            account = Account(
                id=AccountId(uuid7().hex),
                username=username,
                password_hash=None,
                role=role,
                created_at=identity.signed_in_at,
            )
            linked = replace(identity, account_id=account.id)
            outcome = await self.externals.create_linked_account(account, linked, groups)
            if outcome == "created":
                return account
            if outcome == "already_linked":
                return await self._account_for(policy, grant)  # the link exists now
        raise UsernameUnavailableError([c.value for c in candidates])

    async def _end_access(self, account_id: AccountId, now: datetime) -> None:
        """End an external account's access now: its sessions go, its tokens are refused.

        Args:
            account_id: The account.
            now: The current time.
        """
        await self.externals.revoke(account_id, now)
        await self.sessions.delete_for_account(account_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProviderIconUseCase:
    """Implements ``ports.driving.GetProviderIcon``."""

    policies: Mapping[str, SignInPolicy]
    """The configured providers' policies, by name (with their icons)."""

    async def __call__(self, provider: str) -> ProviderIconFile:
        """Return the provider's own icon.

        Args:
            provider: The provider's name.

        Returns:
            The icon's type, bytes and version.

        Raises:
            UnknownSignInProviderError: No provider of this name is configured.
            NoProviderIconError: The provider has no icon of its own.
        """
        policy = self.policies.get(provider)
        if policy is None:
            raise UnknownSignInProviderError
        if policy.icon_file is None:
            raise NoProviderIconError
        icon = policy.icon_file
        return ProviderIconFile.model_validate(
            {"media_type": icon.media_type, "content": icon.content, "version": icon.version}
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListAccountProvidersUseCase:
    """Implements ``ports.driving.ListAccountProviders``."""

    policies: Mapping[str, SignInPolicy]
    """The configured providers' policies, by name, in configuration order."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The identities linked to accounts."""

    async def __call__(self, account: AccountSummary) -> AccountProviders:
        """List the configured providers with the account's identities, then the others it has.

        Args:
            account: The signed-in account.

        Returns:
            Whether it has a password, and its providers.

        Raises:
            NotSignedInError: The account no longer exists.
        """
        stored = await self.accounts.get_by_id(AccountId(account.id))
        if stored is None:
            raise NotSignedInError
        return await _account_providers(self.policies, self.externals, stored)


async def _account_providers(
    policies: Mapping[str, SignInPolicy], externals: ExternalIdentityRepository, account: Account
) -> AccountProviders:
    """Describe an account's ways to sign in, for its Account settings.

    Args:
        policies: The configured providers' policies, by name, in configuration order.
        externals: The identities linked to accounts.
        account: The account.

    Returns:
        Whether it has a password, every configured provider with the account's identity of it
        (if any), then the account's identities of providers no longer configured.
    """
    links = {link.provider: link for link in await externals.list_for_account(account.id)}
    shown = []
    for name, policy in policies.items():
        summary = SignInProviderSummary.from_model(policy).model_dump()
        shown.append(_account_provider(summary, links.pop(name, None), configured=True))
    for name, link in sorted(links.items()):
        summary = {
            "name": name,
            "display_name": ACCESS_DISPLAY_NAME if name == ACCESS_PROVIDER else name,
        }
        shown.append(_account_provider(summary, link, configured=False))
    return AccountProviders(has_password=not account.is_external, providers=shown)


def _account_provider(
    summary: Mapping[str, object], link: ExternalIdentity | None, *, configured: bool
) -> AccountProvider:
    """Describe one provider for an account's settings.

    Args:
        summary: The provider as the sign-in page shows it (name, display name, icon).
        link: The account's identity of it, if any.
        configured: Whether the provider is configured (else only its link is left).

    Returns:
        The provider, linked or not, and what may be done with it.
    """
    return AccountProvider.model_validate(
        {
            **summary,
            "configured": configured,
            "linked": link is not None,
            "origin": link is not None and link.is_origin,
            "linked_at": None if link is None else link.linked_at,
            "last_signed_in_at": None if link is None else link.signed_in_at,
            "can_link": configured and link is None,
            "can_unlink": link is not None and _may_unlink(link),
        }
    )


def _may_unlink(link: ExternalIdentity) -> bool:
    """Whether an identity may be unlinked without taking the account's way in with it.

    Only an account without a password has an origin (the identity it was created through): it
    signs in through it and follows it (its role, groups and access), so the origin stays,
    whatever else is linked. Any identity linked from Account settings may go: the password, or
    the origin, stays.

    Args:
        link: The identity to unlink.

    Returns:
        ``True`` unless it is the account's origin.
    """
    return not link.is_origin


@dataclass(frozen=True, slots=True, kw_only=True)
class StartAccountLinkUseCase:
    """Implements ``ports.driving.StartAccountLink``."""

    providers: Mapping[str, SignInProvider]
    """The configured identity providers, by name."""
    policies: Mapping[str, SignInPolicy]
    """Their policies, by name."""
    attempts: SignInAttemptRepository
    """Where started attempts wait for their callback."""
    externals: ExternalIdentityRepository
    """The identities linked to accounts."""
    clock: Clock
    """The current time."""

    async def __call__(
        self, account: AccountSummary, command: StartAccountLinkCommand, session_token: str | None
    ) -> ExternalSignInStart:
        """Store a link attempt bound to the browser and to this session, as a sign-in's.

        Args:
            account: The signed-in account.
            command: The provider and where to come back to (default: Account settings).
            session_token: The session the link is started from.

        Returns:
            The provider's authorization URL and the binding for the browser.

        Raises:
            NotSignedInError: No session to bind the link to (e.g. signed in by Cloudflare
                Access only).
            ProviderAlreadyLinkedError: The account has an identity of the provider already.
        """
        provider, policy = _configured(self.providers, self.policies, command.provider)
        if not session_token:
            raise NotSignedInError
        links = await self.externals.list_for_account(AccountId(account.id))
        if any(link.provider == policy.name for link in links):
            raise ProviderAlreadyLinkedError
        return await _begin(
            provider,
            policy,
            attempts=self.attempts,
            clock=self.clock,
            return_to=safe_return_to(command.return_to or ACCOUNT_PAGE),
            link_session_hash=hash_token(session_token),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UnlinkProviderUseCase:
    """Implements ``ports.driving.UnlinkProvider``.

    Unlinking only removes the identity: the sessions it signed in stay (the account's owner is
    the one unlinking, and the account itself is unchanged).
    """

    policies: Mapping[str, SignInPolicy]
    """The configured providers' policies, by name, in configuration order."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The identities linked to accounts."""

    async def __call__(self, account: AccountSummary, provider: str) -> AccountProviders:
        """Unlink the account's identity of the provider, unless it is the account's way in.

        Args:
            account: The signed-in account.
            provider: The provider's name.

        Returns:
            The account's providers afterwards.

        Raises:
            NotSignedInError: The account no longer exists.
            ProviderNotLinkedError: The account has no identity of the provider.
            LastSignInMethodError: Unlinking it would leave the account no way to sign in.
        """
        stored = await self.accounts.get_by_id(AccountId(account.id))
        if stored is None:
            raise NotSignedInError
        links = await self.externals.list_for_account(stored.id)
        link = next((link for link in links if link.provider == provider), None)
        if link is None:
            raise ProviderNotLinkedError
        if not _may_unlink(link):
            raise LastSignInMethodError
        if not await self.externals.unlink(stored.id, provider):
            raise ProviderNotLinkedError  # unlinked meanwhile
        logger.info("an identity of %s was unlinked from an account", provider)
        return await _account_providers(self.policies, self.externals, stored)


async def _exchange(
    provider: SignInProvider,
    policy: SignInPolicy,
    attempt: SignInAttempt,
    command: FinishExternalSignInCommand,
) -> ExternalGrant:
    """Trade the callback's code for the validated claims, unless the provider answered an error.

    Args:
        provider: The provider's adapter.
        policy: Its policy.
        attempt: The attempt the callback belongs to (its PKCE verifier and nonce).
        command: The callback.

    Returns:
        The claims and the refresh token.

    Raises:
        SignInCancelledError: The provider answered with an error instead of a code.
        ExternalSignInFailedError: No code came back.
    """
    if command.error is not None:
        logger.info("external sign-in through %s: the provider answered an error", policy.name)
        raise SignInCancelledError
    if not command.code:
        raise ExternalSignInFailedError
    return await provider.exchange(
        code=command.code, code_verifier=attempt.code_verifier, nonce=attempt.nonce
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RevalidateExternalAccountsUseCase:
    """Implements ``ports.driving.RevalidateExternalAccounts``.

    Each due link (``next_check_at`` passed, a refresh token stored) is claimed with a lease, so
    processes sharing a database share the work, then refreshed with its provider: still allowed
    moves ``access_until`` forward and refreshes groups and role; a refused token or a lost
    membership ends the account's access and its sessions; an unreachable provider leaves
    ``access_until`` as it is (access ends once it passes, failing closed) and the link is
    tried again after the lease.

    An extension is stored only if the link is still as it was claimed (see
    ``ExternalIdentityRepository.record_revalidation``): a disable, revocation or sign-in that
    happened while the provider answered wins, and the answer is counted as ``superseded``.
    Ending access is not conditional: at worst it ends a session a concurrent sign-in just
    started, which fails closed.
    """

    providers: Mapping[str, SignInProvider]
    """The configured identity providers, by name."""
    policies: Mapping[str, SignInPolicy]
    """Their policies, by name."""
    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external identities to accounts."""
    sessions: SessionRepository
    """Where browser sessions are stored."""
    box: SecretBox
    """Opens the stored refresh tokens and seals rotated ones."""
    clock: Clock
    """The current time."""

    async def __call__(self) -> RevalidationReport:
        """Check every due link, a batch at a time, until none is due.

        Returns:
            How many were extended, revoked and left as they were.
        """
        counts = {"extended": 0, "revoked": 0, "unreachable": 0, "superseded": 0}
        while True:
            now = self.clock.now()
            due = await self.externals.claim_due(
                now, lease_until=now + REVALIDATION_LEASE, limit=REVALIDATION_BATCH
            )
            for link in due:
                try:
                    counts[await self._check(link)] += 1
                except Exception:  # one link must not stop the rest
                    logger.exception("revalidating an external identity failed; retried later")
            if len(due) < REVALIDATION_BATCH:
                return RevalidationReport(**counts)

    async def _check(self, link: ExternalIdentity) -> str:
        """Check one link with its provider and record the outcome.

        Args:
            link: The claimed link.

        Returns:
            ``extended``, ``revoked``, ``unreachable`` or ``superseded``.
        """
        found = await self._refresh(link)
        if found == "unreachable":
            return found
        if found is None:
            return await self._revoke(link)
        policy, grant, refresh_token = found
        claims = grant.claims
        if claims.subject != link.subject or claims.issuer != link.issuer:
            return await self._revoke(link)
        if not policy.admits(claims.groups):
            logger.info("an account left the allowed groups of %s: access ended", policy.name)
            return await self._revoke(link)
        now = self.clock.now()
        stored = await self.externals.record_revalidation(
            link,
            replace(
                link,
                sealed_tokens=self.box.seal(grant.refresh_token or refresh_token),
                checked_at=now,
                next_check_at=now + policy.revalidate_every,
                access_until=policy.access_until(now, refreshable=True),
            ),
            role=policy.role_for(claims.groups),
            groups=policy.stored_groups(claims.groups),
        )
        if not stored:
            # A disable, a revocation or a sign-in changed the link while the provider
            # answered: its state is newer than this answer, so the answer is dropped.
            logger.info("an external identity changed during its revalidation: answer dropped")
            return "superseded"
        return "extended"

    async def _refresh(
        self, link: ExternalIdentity
    ) -> tuple[SignInPolicy, ExternalGrant, str] | Literal["unreachable"] | None:
        """Ask the link's provider for the person's current claims with the stored token.

        Args:
            link: The claimed link.

        Returns:
            The provider's policy, the fresh grant and the refresh token used; ``unreachable``
            when the provider cannot be reached; ``None`` when access must end (the provider is
            no longer configured, the account is disabled or gone, the token does not open or
            the provider refused it).
        """
        provider = self.providers.get(link.provider)
        policy = self.policies.get(link.provider)
        if provider is None or policy is None or link.sealed_tokens is None:
            logger.warning("sign-in provider %r is not configured: access ended", link.provider)
            return None
        account = await self.accounts.get_by_id(link.account_id)
        if account is None or account.is_disabled:
            return None
        try:
            refresh_token = self.box.open(link.sealed_tokens)
        except SealedTextUnreadableError:
            logger.warning("an external identity's refresh token does not open: access ended")
            return None
        try:
            grant = await provider.refresh(refresh_token, subject=link.subject)
        except ProviderUnavailableError:
            logger.warning(
                "sign-in provider %s unreachable; access kept until it ends", policy.name
            )
            return "unreachable"
        except ProviderAccessRevokedError, ExternalSignInFailedError:
            logger.info("sign-in provider %s refused a refresh: access ended", policy.name)
            return None
        return policy, grant, refresh_token

    async def _revoke(self, link: ExternalIdentity) -> str:
        """End the link's access now and the account's sessions.

        Args:
            link: The link.

        Returns:
            ``revoked``.
        """
        await self.externals.revoke(link.account_id, self.clock.now())
        await self.sessions.delete_for_account(link.account_id)
        return "revoked"


async def _library_roles(
    *,
    accounts: AccountRepository,
    externals: ExternalIdentityRepository,
    grants: LibraryGrantRepository,
    account_id: str,
    libraries: Collection[str],
    external_identity: ExternalTokenIdentity | None = None,
) -> dict[str, LibraryRole]:
    """Work out an account's effective role on each library: the highest one it holds.

    An operator is ``creator`` of every library, so a library whose creator is gone, or that
    no grant was ever made on, can still be managed. OAuth requests use only their verified
    token's policy role and mapped groups, without writing them over stored web-account state.
    Disabled accounts, missing linked accounts and unknown ordinary callers hold no roles.

    Args:
        accounts: Where accounts are stored.
        externals: The links of external accounts, for their groups.
        grants: Who holds which role on which library.
        account_id: The account.
        libraries: Library IDs; compared lower-case.
        external_identity: The verified caller and groups of this OAuth request, if any.

    Returns:
        The role on each library the account has one on, by lower-case library ID.
    """
    wanted = {library.casefold() for library in libraries}
    account = await accounts.get_by_id(AccountId(account_id))
    if external_identity is not None:
        if external_identity.account.id != account_id:
            return {}
        if account is None and external_identity.linked:
            return {}
        if account is not None and account.is_disabled:
            return {}
        operator = external_identity.account.role == Role.ADMIN.value
        groups = external_identity.groups
    else:
        if account is None or account.is_disabled:
            return {}
        operator = account.is_operator
        groups = await externals.groups_of(account.id)
    if operator:
        return dict.fromkeys(wanted, LibraryRole.CREATOR)
    held: dict[str, list[LibraryGrant]] = {}
    for grant in await grants.matching(wanted, account_id=AccountId(account_id), groups=groups):
        held.setdefault(grant.library, []).append(grant)
    return {library: role for library, found in held.items() if (role := effective_role(found))}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveLibraryRolesUseCase:
    """Implements ``ports.driving.ResolveLibraryRoles``."""

    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external accounts, for their groups."""
    grants: LibraryGrantRepository
    """Who holds which role on which library."""

    async def __call__(self, query: LibraryRolesQuery) -> LibraryRoles:
        """Return the account's effective role on each library it has one on.

        Args:
            query: The account and the libraries.

        Returns:
            Library ID to role.
        """
        roles = await _library_roles(
            accounts=self.accounts,
            externals=self.externals,
            grants=self.grants,
            account_id=query.account_id,
            libraries=query.libraries,
            external_identity=query.external_identity,
        )
        return LibraryRoles(roles={library: role.value for library, role in roles.items()})


def _access_event(
    clock: Clock,
    library: str,
    actor: str | None,
    change: AccessChange,
    grant: LibraryGrant | None = None,
    previous_role: LibraryRole | None = None,
) -> AccessEvent:
    """Build an access log entry stamped now.

    Args:
        clock: The current time.
        library: The library ID, lower-case.
        actor: The account that made the change; ``None`` for the instance.
        change: What happened.
        grant: The grant given or taken away; ``None`` for a deletion.
        previous_role: The role the subject held before, if any.

    Returns:
        The event, with a new time-ordered ID.
    """
    return AccessEvent(
        id=str(uuid7()),
        library=library,
        at=clock.now(),
        actor=None if actor is None else AccountId(actor),
        change=change,
        kind=None if grant is None else grant.kind,
        subject=None if grant is None else grant.subject,
        role=None if grant is None else grant.role,
        previous_role=previous_role,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimLibraryUseCase:
    """Implements ``ports.driving.ClaimLibrary``."""

    grants: LibraryGrantRepository
    """Who holds which role on which library."""
    log: AccessLog
    """The access log."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: ClaimLibraryCommand) -> None:
        """Make the account the library's creator; grants left on the same ID are dropped.

        Args:
            command: The account and the library.
        """
        library = command.library.casefold()
        await self.grants.claim(library, AccountId(command.account_id))
        creator = LibraryGrant(
            library=library,
            kind=SubjectKind.USER,
            subject=command.account_id,
            role=LibraryRole.CREATOR,
        )
        await self.log.record(
            _access_event(
                self.clock, library, command.account_id, AccessChange.LIBRARY_CREATED, creator
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DropLibraryGrantsUseCase:
    """Implements ``ports.driving.DropLibraryGrants``."""

    grants: LibraryGrantRepository
    """Who holds which role on which library."""
    log: AccessLog
    """The access log."""
    clock: Clock
    """The current time."""

    async def __call__(self, command: DropLibraryGrantsCommand) -> None:
        """Drop every grant on the library and log its deletion.

        Args:
            command: The library and who removed it.
        """
        library = command.library.casefold()
        await self.grants.clear(library)
        await self.log.record(
            _access_event(self.clock, library, command.actor_id, AccessChange.LIBRARY_DELETED)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Sharing:
    """What the three sharing use cases have in common: who may share, and how grants read."""

    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """The links of external accounts, for their groups."""
    grants: LibraryGrantRepository
    """Who holds which role on which library."""
    log: AccessLog
    """The access log."""
    clock: Clock
    """The current time."""

    async def caller_role(self, caller_id: str, library: str) -> LibraryRole:
        """Return the caller's role on the library, if it may share it at all.

        Args:
            caller_id: The account that shares.
            library: The library ID, lower-case.

        Returns:
            The role (``admin`` or ``creator``).

        Raises:
            LibraryRoleRequiredError: The caller is not an ``admin`` of the library.
        """
        roles = await _library_roles(
            accounts=self.accounts,
            externals=self.externals,
            grants=self.grants,
            account_id=caller_id,
            libraries=[library],
        )
        role = roles.get(library)
        if role is None or not role.allows(LibraryRole.ADMIN):
            raise LibraryRoleRequiredError(LibraryRole.ADMIN.value)
        return role

    async def subject_id(self, kind: SubjectKind, subject: str) -> str:
        """Return what a grant stores for a username or a group name.

        Args:
            kind: Whether ``subject`` is a username or a group name.
            subject: The username or group name as the caller gave it.

        Returns:
            The account's ID, or the group name.

        Raises:
            UnknownAccountError: No account has the username.
        """
        if kind is SubjectKind.GROUP:
            return subject
        account = await self.accounts.get(Username(subject))
        if account is None:
            raise UnknownAccountError
        return account.id

    async def listing(self, library: str) -> LibraryGrants:
        """List the library's grants, users by their names.

        Args:
            library: The library ID, lower-case.

        Returns:
            The grants.
        """
        shown = []
        for grant in await self.grants.for_library(library):
            subject = grant.subject
            if grant.kind is SubjectKind.USER:
                account = await self.accounts.get_by_id(AccountId(subject))
                subject = account.username.value if account else subject
            shown.append(LibraryGrantSummary.from_model(grant, subject=subject))
        return LibraryGrants(grants=shown)

    async def record(
        self,
        caller_id: str,
        change: AccessChange,
        grant: LibraryGrant,
        previous_role: LibraryRole | None = None,
    ) -> None:
        """Log a change of the library's grants made by the caller.

        Args:
            caller_id: The account that made it.
            change: What happened.
            grant: The grant given or taken away.
            previous_role: The role the subject held before, if any.
        """
        await self.log.record(
            _access_event(self.clock, grant.library, caller_id, change, grant, previous_role)
        )

    async def log_page(
        self,
        where: AccessLogFilter,
        *,
        limit: int,
        cursor: str | None,
        offset: int | None = None,
    ) -> AccessLogPage:
        """Read a page of the access log, newest first, people by their names.

        Args:
            where: Which events.
            limit: Most events on the page.
            cursor: The ``next_cursor`` of the previous page; ``None`` for the first.
            offset: How many matching events to skip instead of a cursor; ``None``: none.

        Returns:
            The page, its next cursor and how many events match.
        """
        skip = page_offset(cursor=cursor, offset=offset)
        older_than = None if cursor is None else decode_cursor(cursor)
        found = await self.log.newest(where, older_than=older_than, limit=limit + 1, offset=skip)
        events, more = found[:limit], len(found) > limit
        people = {e.actor for e in events if e.actor is not None} | {
            e.subject for e in events if e.kind is SubjectKind.USER and e.subject is not None
        }
        names: dict[str, str] = {}
        for account_id in people:
            account = await self.accounts.get_by_id(AccountId(account_id))
            names[account_id] = account.username.value if account else account_id
        shown = [
            AccessEventSummary.from_model(
                event,
                actor=None if event.actor is None else names[event.actor],
                subject=names[event.subject]
                if event.kind is SubjectKind.USER and event.subject is not None
                else event.subject,
            )
            for event in events
        ]
        return AccessLogPage(
            events=shown,
            next_cursor=encode_cursor(events[-1].id) if more else None,
            total=await self.log.count(where),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GrantLibraryRoleUseCase:
    """Implements ``ports.driving.GrantLibraryRole``."""

    sharing: Sharing
    """Who may share, and how grants read."""

    async def __call__(self, command: GrantLibraryRoleCommand) -> LibraryGrants:
        """Give the user or group the role, if the caller may.

        Args:
            command: The caller, the library, whom to give a role and which.

        Returns:
            The library's grants now.

        Raises:
            LibraryRoleRequiredError: The caller is no ``admin`` of the library, or not its
                ``creator`` while the grant gives or changes an ``admin``'s role.
            InvalidGrantError: The subject is the library's creator.
        """
        library = command.library.casefold()
        caller = await self.sharing.caller_role(command.caller_id, library)
        kind = SubjectKind(command.kind)
        subject = await self.sharing.subject_id(kind, command.subject)
        held = await self.sharing.grants.get(library, kind, subject)
        if held is not None and held.role is LibraryRole.CREATOR:
            msg = "the creator's role is not changed here"
            raise InvalidGrantError(msg)
        wanted = LibraryRole(command.role)
        touches_admin = wanted is LibraryRole.ADMIN or (
            held is not None and held.role is LibraryRole.ADMIN
        )
        if touches_admin and not caller.allows(LibraryRole.CREATOR):
            raise LibraryRoleRequiredError(LibraryRole.CREATOR.value)
        grant = LibraryGrant(library=library, kind=kind, subject=subject, role=wanted)
        await self.sharing.grants.put(grant)
        if held is None or held.role is not wanted:  # the same role again changes nothing
            await self.sharing.record(
                command.caller_id,
                AccessChange.GRANTED,
                grant,
                previous_role=None if held is None else held.role,
            )
        return await self.sharing.listing(library)


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeLibraryRoleUseCase:
    """Implements ``ports.driving.RevokeLibraryRole``."""

    sharing: Sharing
    """Who may share, and how grants read."""

    async def __call__(self, command: RevokeLibraryRoleCommand) -> LibraryGrants:
        """Take the role away, if the caller may.

        Args:
            command: The caller, the library and whose role goes.

        Returns:
            The library's grants now.

        Raises:
            LibraryRoleRequiredError: The caller is no ``admin`` of the library, or not its
                ``creator`` while the role is an ``admin``'s.
            UnknownGrantError: There is no such grant.
            InvalidGrantError: The grant is the creator's.
        """
        library = command.library.casefold()
        caller = await self.sharing.caller_role(command.caller_id, library)
        kind = SubjectKind(command.kind)
        subject = await self.sharing.subject_id(kind, command.subject)
        held = await self.sharing.grants.get(library, kind, subject)
        if held is None:
            raise UnknownGrantError
        if held.role is LibraryRole.CREATOR:
            msg = "the creator's role is not taken away here"
            raise InvalidGrantError(msg)
        if held.role is LibraryRole.ADMIN and not caller.allows(LibraryRole.CREATOR):
            raise LibraryRoleRequiredError(LibraryRole.CREATOR.value)
        if await self.sharing.grants.remove(library, kind, subject):
            await self.sharing.record(command.caller_id, AccessChange.REVOKED, held)
        return await self.sharing.listing(library)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListLibraryGrantsUseCase:
    """Implements ``ports.driving.ListLibraryGrants``."""

    sharing: Sharing
    """Who may share, and how grants read."""

    async def __call__(self, query: ListLibraryGrantsQuery) -> LibraryGrantList:
        """List a page of the library's grants, if the caller is an admin of it.

        The role is checked first: a caller who may not see the grants gets no page and no count.

        Args:
            query: The caller, the library, the filters, the sort and the page.

        Returns:
            The page, its next cursor and how many grants match.
        """
        sort = parse_sort(query.sort, allowed=GRANT_SORT_FIELDS, default="kind")
        library = query.library.casefold()
        caller = await self.sharing.caller_role(query.caller_id, library)
        everyone = (await self.sharing.listing(library)).grants
        grants = [
            g
            for g in everyone
            if _contains(g.subject, query.q)
            and (query.kind is None or g.kind in query.kind)
            and (query.role is None or g.role in query.role)
        ]
        page = sorted_page(
            grants,
            sort=sort,
            key_field="",  # no sort field is unique on its own: every sort pages by its value
            values={
                "kind": lambda g: int(g.kind == SubjectKind.GROUP.value),  # users first
                "subject": lambda g: g.subject.casefold(),
                "role": lambda g: LibraryRole(g.role).rank,
            },
            key=lambda g: f"{g.kind}:{g.subject}",
            limit=query.limit,
            cursor=query.cursor,
            offset=query.offset,
        )
        creator = next((g.subject for g in everyone if g.role == LibraryRole.CREATOR.value), None)
        return LibraryGrantList.from_page(
            page,
            caller_role="creator" if caller.allows(LibraryRole.CREATOR) else "admin",
            creator=creator,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TransferLibraryUseCase:
    """Implements ``ports.driving.TransferLibrary``."""

    sharing: Sharing
    """Who may share, and how grants read."""

    async def __call__(self, command: TransferLibraryCommand) -> LibraryGrants:
        """Make the user the library's creator, and the creator before an ``admin``; log both.

        The access log gets a ``granted`` event per creator before (``admin``, previous role
        ``creator``), then one ``ownership_transferred`` event naming the new creator.

        Args:
            command: The caller, the library and the new creator's username.

        Returns:
            The library's grants now.

        Raises:
            LibraryRoleRequiredError: The caller is not the library's ``creator`` (nor an
                operator).
            InvalidGrantError: The user is already the library's creator.
        """
        library = command.library.casefold()
        caller = await self.sharing.caller_role(command.caller_id, library)
        if not caller.allows(LibraryRole.CREATOR):
            raise LibraryRoleRequiredError(LibraryRole.CREATOR.value)
        new_creator = AccountId(await self.sharing.subject_id(SubjectKind.USER, command.username))
        held = await self.sharing.grants.get(library, SubjectKind.USER, new_creator)
        if held is not None and held.role is LibraryRole.CREATOR:
            msg = f"{command.username} is already the creator of {command.library}"
            raise InvalidGrantError(msg)
        before = await self.sharing.grants.transfer(library, new_creator)
        # One event per account whose role changed: each creator before is now an admin (a role
        # change, logged as one), and the transfer itself names the new creator, recorded last
        # so it reads first in the newest-first log.
        for previous in before:
            await self.sharing.record(
                command.caller_id,
                AccessChange.GRANTED,
                LibraryGrant(
                    library=library,
                    kind=SubjectKind.USER,
                    subject=previous,
                    role=LibraryRole.ADMIN,
                ),
                previous_role=LibraryRole.CREATOR,
            )
        await self.sharing.record(
            command.caller_id,
            AccessChange.OWNERSHIP_TRANSFERRED,
            LibraryGrant(
                library=library,
                kind=SubjectKind.USER,
                subject=new_creator,
                role=LibraryRole.CREATOR,
            ),
            previous_role=None if held is None else held.role,
        )
        return await self.sharing.listing(library)


def _changes(wanted: Collection[str] | None) -> frozenset[AccessChange] | None:
    """Map a filter's change names to the domain's.

    Args:
        wanted: The names, or ``None`` for every change.

    Returns:
        The changes, or ``None`` for every change.
    """
    return None if wanted is None else frozenset(AccessChange(c) for c in wanted)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListLibraryAccessLogUseCase:
    """Implements ``ports.driving.ListLibraryAccessLog``."""

    sharing: Sharing
    """Who may read a library's access, and how the log reads."""

    async def __call__(self, query: ListLibraryAccessLogQuery) -> AccessLogPage:
        """Read a page of the library's access log, if the caller is an admin of it.

        The role is checked first: a caller who may not read the log gets no page and no count.

        Args:
            query: The caller, the library, the filters and the page.

        Returns:
            The page, its next cursor and how many events match.
        """
        library = query.library.casefold()
        await self.sharing.caller_role(query.caller_id, library)
        caller = await self.sharing.accounts.get_by_id(AccountId(query.caller_id))
        since = None
        if caller is None or not caller.is_operator:
            deleted = AccessLogFilter(
                library=library, changes=frozenset({AccessChange.LIBRARY_DELETED})
            )
            last = await self.sharing.log.newest(deleted, older_than=None, limit=1)
            since = last[0].id if last else None
        where = AccessLogFilter(library=library, changes=_changes(query.change), newer_than=since)
        return await self.sharing.log_page(
            where, limit=query.limit, cursor=query.cursor, offset=query.offset
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListAccessLogUseCase:
    """Implements ``ports.driving.ListAccessLog``."""

    sharing: Sharing
    """How the log reads, people by their names."""

    async def __call__(self, query: ListAccessLogQuery) -> AccessLogPage:
        """Read a page of the access log of every library, if the caller is an operator.

        Args:
            query: The caller, the filters and the page.

        Returns:
            The page, its next cursor and how many events match.

        Raises:
            NotAnOperatorError: The caller is not an enabled instance operator.
        """
        caller = await self.sharing.accounts.get_by_id(AccountId(query.caller_id))
        if caller is None or caller.is_disabled or not caller.is_operator:
            raise NotAnOperatorError(ACCESS_LOG_ACTION)
        where = AccessLogFilter(
            library=None if query.library is None else query.library.casefold(),
            changes=_changes(query.change),
        )
        return await self.sharing.log_page(
            where, limit=query.limit, cursor=query.cursor, offset=query.offset
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanCreateLibraryUseCase:
    """Implements ``ports.driving.CanCreateLibrary`` using current trusted identity state."""

    accounts: AccountRepository
    """Where accounts are stored."""
    externals: ExternalIdentityRepository
    """Current stored provider groups for ordinary credentials."""
    policy: LibraryCreationPolicy | None = None
    """None preserves creation by every authenticated caller; empty allows operators only."""

    async def __call__(self, query: LibraryCreationQuery) -> bool:
        """Resolve permission without accepting display names or stale OAuth groups.

        Args:
            query: The stable caller and optional verified OAuth principal.

        Returns:
            Whether the valid caller is an operator or matches the creation policy.
        """
        account = await self.accounts.get_by_id(AccountId(query.account_id))
        principal = query.external_identity
        if principal is not None:
            if principal.account.id != query.account_id:
                return False
            if account is None and principal.linked:
                return False
            if account is not None and account.is_disabled:
                return False
            operator = principal.account.role == Role.ADMIN.value
            groups = principal.groups
        else:
            if account is None or account.is_disabled:
                return False
            operator = account.is_operator
            groups = await self.externals.groups_of(account.id)
        return (
            operator
            or self.policy is None
            or query.account_id in self.policy.users
            or bool(self.policy.groups.intersection(groups))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GetPreferencesUseCase:
    """Implements ``ports.driving.GetPreferences``."""

    preferences: PreferencesRepository
    """Where each account's interface preferences are saved."""

    async def __call__(self, query: GetPreferencesQuery) -> AccountPreferences:
        """Return the account's saved preferences, or the defaults when it saved none.

        Args:
            query: The account.

        Returns:
            Its preferences, and whether it saved them.
        """
        return AccountPreferences.from_model(
            await self.preferences.get(AccountId(query.account_id))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SavePreferencesUseCase:
    """Implements ``ports.driving.SavePreferences``."""

    preferences: PreferencesRepository
    """Where each account's interface preferences are saved."""

    async def __call__(self, command: SavePreferencesCommand) -> AccountPreferences:
        """Save the account's preferences, replacing the ones it had.

        Saving the defaults saves them too: the account then has preferences of its own, which
        win over a browser's on the next sign-in. A save that leaves ``leaderboard_opt_in`` out
        (a client older than it) keeps the account's saved choice, so it neither opts the person
        in nor drops an opt-in it never showed.

        Args:
            command: The account and its new preferences.

        Returns:
            The preferences as saved.
        """
        account_id = AccountId(command.account_id)
        chosen = command.preferences.to_model()
        if "leaderboard_opt_in" not in command.preferences.model_fields_set:
            saved = await self.preferences.get(account_id)
            chosen = replace(
                chosen, leaderboard_opt_in=saved is not None and saved.leaderboard_opt_in
            )
        await self.preferences.put(account_id, chosen)
        return AccountPreferences.from_model(chosen)


@dataclass(frozen=True, slots=True, kw_only=True)
class FindLeaderboardPeopleUseCase:
    """Implements ``ports.driving.FindLeaderboardPeople``."""

    preferences: PreferencesRepository
    """Where each account's interface preferences are saved."""
    accounts: AccountRepository
    """The accounts, for their usernames and whether they are disabled."""

    async def __call__(self, query: LeaderboardPeopleQuery) -> LeaderboardPeople:
        """Return the accounts among those asked about that opted in, exist and are enabled.

        One query finds who opted in; only those accounts are then read, one by one.

        Args:
            query: The accounts asked about.

        Returns:
            Those that may be shown by name, sorted by ID.
        """
        opted = await self.preferences.opted_in({AccountId(i) for i in query.account_ids})
        people = []
        for account_id in sorted(opted):
            account = await self.accounts.get_by_id(account_id)
            if account is not None and not account.is_disabled:
                people.append(LeaderboardPerson(id=account.id, username=str(account.username)))
        return LeaderboardPeople(people=people)
