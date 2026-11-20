"""Driving (primary) ports: what the outside world may ask identity to do."""

from typing import Protocol

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    DropLibraryGrantsCommand,
    ExternalSignInResult,
    ExternalSignInStart,
    ExternalTokenIdentity,
    FinishExternalSignInCommand,
    GrantLibraryRoleCommand,
    LibraryCreationQuery,
    LibraryGrants,
    LibraryRoles,
    LibraryRolesQuery,
    ListLibraryGrantsQuery,
    LoginForTokenCommand,
    PasswordReset,
    ResetPasswordCommand,
    RevalidationReport,
    RevokeLibraryRoleCommand,
    SessionGrant,
    SessionState,
    SetupState,
    SetUserDisabledCommand,
    StartExternalSignInCommand,
    TokenGrant,
    TokenList,
    UserList,
    UserSummary,
)


class GetSetupState(Protocol):
    """Tell whether the instance still waits for its first admin."""

    async def __call__(self) -> SetupState:
        """Run the use case.

        Returns:
            Whether setup is still required.
        """
        ...


class CreateFirstAdmin(Protocol):
    """Create the first admin; raises ``AlreadySetUpError`` once any account exists."""

    async def __call__(self, command: CreateFirstAdminCommand) -> AccountSummary:
        """Run the use case.

        Args:
            command: The first admin's username and password.

        Returns:
            The new account.
        """
        ...


class Authenticate(Protocol):
    """Check a username and password; raises ``InvalidCredentialsError`` on any mismatch.

    Raises ``SignInThrottledError`` without checking the password after too many failures from
    the ``client`` address (the caller's IP, when known) or for the username.
    """

    async def __call__(
        self, query: AuthenticateQuery, *, client: str | None = None
    ) -> AccountSummary:
        """Run the use case.

        Args:
            query: The username and password.
            client: The caller's address, when known, for the sign-in throttle.

        Returns:
            The account the credentials belong to.
        """
        ...


class SignIn(Protocol):
    """Check credentials and start a session; raises ``InvalidCredentialsError`` on a mismatch."""

    async def __call__(
        self,
        query: AuthenticateQuery,
        previous_token: str | None = None,
        *,
        client: str | None = None,
    ) -> SessionGrant:
        """Run the use case; ``previous_token`` (the caller's current session) is ended.

        Args:
            query: The username and password.
            previous_token: The caller's current session token, if any.
            client: The caller's address, for the sign-in throttle (see ``Authenticate``).

        Returns:
            The new session, with its secret token.
        """
        ...


class SignOut(Protocol):
    """End the session behind a token. Unknown or ended sessions are not an error."""

    async def __call__(self, token: str) -> None:
        """Run the use case.

        Args:
            token: The session token.
        """
        ...


class IdentifyCaller(Protocol):
    """Who a session token belongs to; raises ``NotSignedInError`` when it is absent or no good."""

    async def __call__(self, token: str | None) -> AccountSummary:
        """Run the use case.

        Args:
            token: The session token, or ``None`` when the request carried none.

        Returns:
            The signed-in account.
        """
        ...


class IdentifyAccessCaller(Protocol):
    """Who a Cloudflare Access token signs in; raises ``NotSignedInError`` when nobody.

    Off (``NotSignedInError`` for every token) unless Cloudflare Access is configured.
    """

    async def __call__(self, assertion: str | None) -> AccountSummary:
        """Run the use case.

        Args:
            assertion: The Access application token, or ``None`` when the request carried none.

        Returns:
            The account the token's person or service token is linked to.
        """
        ...


class GetSessionState(Protocol):
    """Tell whether setup is due, nobody is signed in, or the token's owner is."""

    async def __call__(
        self, token: str | None, access_assertion: str | None = None
    ) -> SessionState:
        """Run the use case.

        Args:
            token: The session token, or ``None`` when the request carried none.
            access_assertion: The Cloudflare Access token, used when no session signs anyone in.

        Returns:
            The setup and sign-in state.
        """
        ...


class ListUsers(Protocol):
    """Every local account, for an operator."""

    async def __call__(self) -> UserList:
        """Run the use case.

        Returns:
            The accounts, oldest first.
        """
        ...


class CreateUser(Protocol):
    """Create a further local account (operators only; there is no self-signup).

    Raises ``NotSetUpError`` before the first admin exists, ``UsernameTakenError`` for a taken
    name and ``ReservedUsernameError`` for a name the sign-in throttle needs for itself.
    """

    async def __call__(self, command: CreateUserCommand) -> UserSummary:
        """Run the use case.

        Args:
            command: The new account's username, password and role.

        Returns:
            The new account.
        """
        ...


class SetUserDisabled(Protocol):
    """Disable an account, ending its sessions and revoking its tokens, or enable it again.

    Raises ``UnknownAccountError`` when there is no such account, and ``LastOperatorError``
    rather than disable the last enabled admin.
    """

    async def __call__(self, command: SetUserDisabledCommand) -> UserSummary:
        """Run the use case.

        Args:
            command: The account, and whether to disable or enable it.

        Returns:
            The account as it is now.
        """
        ...


class ResetPassword(Protocol):
    """Set a new password and end every session of the account; ``UnknownAccountError`` if none."""

    async def __call__(self, command: ResetPasswordCommand) -> PasswordReset:
        """Run the use case.

        Args:
            command: The username and the new password.

        Returns:
            The account, and whether its username's sign-in throttle count and remembered
            sign-ins were cleared.
        """
        ...


class CreateToken(Protocol):
    """Mint an API token for an account; the secret is in the result and nowhere else."""

    async def __call__(self, account: AccountSummary, command: CreateTokenCommand) -> TokenGrant:
        """Run the use case; ``InvalidTokenExpiryError`` if ``expires_at`` is not in the future.

        Args:
            account: The account the token acts as.
            command: The token's name and expiry.

        Returns:
            The new token, with its secret.
        """
        ...


class LoginForToken(Protocol):
    """Check credentials and mint a named API token; no session is started."""

    async def __call__(
        self, command: LoginForTokenCommand, *, client: str | None = None
    ) -> TokenGrant:
        """Run the use case; ``InvalidCredentialsError`` on any mismatch.

        Args:
            command: The credentials and the new token's name and expiry.
            client: The caller's address, for the sign-in throttle (see ``Authenticate``).

        Returns:
            The new token, with its secret.
        """
        ...


class ListTokens(Protocol):
    """The account's tokens, never their secrets."""

    async def __call__(self, account: AccountSummary) -> TokenList:
        """Run the use case.

        Args:
            account: The account whose tokens to list.

        Returns:
            The tokens, newest first.
        """
        ...


class RevokeToken(Protocol):
    """Delete one of the account's tokens; ``UnknownTokenError`` when it has none by this id."""

    async def __call__(self, account: AccountSummary, token_id: str) -> None:
        """Run the use case.

        Args:
            account: The account that owns the token.
            token_id: The token's id.
        """
        ...


class IdentifyToken(Protocol):
    """Who an API token acts as; raises ``InvalidTokenError`` when it is no good."""

    async def __call__(self, token: str) -> AccountSummary:
        """Run the use case.

        Args:
            token: The API token's secret.

        Returns:
            The account the token acts as.
        """
        ...


class IdentifyExternalToken(Protocol):
    """Who an ID token of a sign-in provider acts as (MCP's OAuth); nothing is stored.

    Raises ``UnknownSignInProviderError`` for a name that is not configured,
    ``ExternalSignInFailedError`` for a token the provider does not vouch for,
    ``NotAllowedError`` for a person in no allowed group and ``AccountDisabledError``.
    """

    async def __call__(self, provider: str, token: str) -> ExternalTokenIdentity:
        """Run the use case.

        Args:
            provider: The provider's name.
            token: The ID token.

        Returns:
            The linked account, or, for a person who never signed in to the web UI, a caller
            named ``<provider>:<subject>`` that no account backs, and their verified groups.
        """
        ...


class StartExternalSignIn(Protocol):
    """Start a sign-in through a configured identity provider.

    Raises ``UnknownSignInProviderError`` for a name that is not configured and
    ``ProviderUnavailableError`` when the provider cannot be reached.
    """

    async def __call__(self, command: StartExternalSignInCommand) -> ExternalSignInStart:
        """Run the use case.

        Args:
            command: The provider and where to go once signed in.

        Returns:
            Where to send the browser, and the binding to hand it.
        """
        ...


class FinishExternalSignIn(Protocol):
    """Finish an external sign-in and start a session.

    Refuses with ``ExternalSignInFailedError`` (forged, replayed, expired or invalid),
    ``SignInCancelledError``, ``NotAllowedError``, ``AccountDisabledError``,
    ``UsernameUnavailableError`` or ``ProviderUnavailableError``; no session is created then.
    """

    async def __call__(
        self, command: FinishExternalSignInCommand, previous_token: str | None = None
    ) -> ExternalSignInResult:
        """Run the use case; ``previous_token`` (the caller's current session) is ended.

        Args:
            command: The callback and the browser's binding.
            previous_token: The caller's current session token, if any.

        Returns:
            The new session, and where to send the browser.
        """
        ...


class RevalidateExternalAccounts(Protocol):
    """Check again the memberships of the external identities that are due."""

    async def __call__(self) -> RevalidationReport:
        """Run the use case.

        Returns:
            How many were extended, revoked and left as they were.
        """
        ...


class ResolveLibraryRoles(Protocol):
    """Tell what an account may do with libraries: the highest role granted to it or its groups.

    An instance operator (role ``admin``) is ``creator`` of every library; a disabled or unknown
    account has no role.
    """

    async def __call__(self, query: LibraryRolesQuery) -> LibraryRoles:
        """Run the use case.

        Args:
            query: The account and the libraries.

        Returns:
            Its role on each library it has one on.
        """
        ...


class ClaimLibrary(Protocol):
    """Make an account the creator of a new library, dropping any grant left on its ID."""

    async def __call__(self, command: ClaimLibraryCommand) -> None:
        """Run the use case.

        Args:
            command: The account and the library.
        """
        ...


class DropLibraryGrants(Protocol):
    """Drop every grant on a library that was removed."""

    async def __call__(self, command: DropLibraryGrantsCommand) -> None:
        """Run the use case.

        Args:
            command: The library.
        """
        ...


class GrantLibraryRole(Protocol):
    """Give a user or a group a role on a library.

    Needs the ``admin`` role on it, and the ``creator`` role to give ``admin`` or to change an
    ``admin``'s role (``LibraryRoleRequiredError``). ``UnknownAccountError`` for a username
    nobody has.
    """

    async def __call__(self, command: GrantLibraryRoleCommand) -> LibraryGrants:
        """Run the use case.

        Args:
            command: The caller, the library, whom to give a role and which.

        Returns:
            The library's grants now.
        """
        ...


class RevokeLibraryRole(Protocol):
    """Take a role away from a user or a group; the creator's role stays.

    Needs the ``admin`` role, and the ``creator`` role to take an ``admin``'s. Raises
    ``UnknownGrantError`` when there is no such grant.
    """

    async def __call__(self, command: RevokeLibraryRoleCommand) -> LibraryGrants:
        """Run the use case.

        Args:
            command: The caller, the library and whose role goes.

        Returns:
            The library's grants now.
        """
        ...


class ListLibraryGrants(Protocol):
    """List who holds a role on a library; needs the ``admin`` role on it."""

    async def __call__(self, query: ListLibraryGrantsQuery) -> LibraryGrants:
        """Run the use case.

        Args:
            query: The caller and the library.

        Returns:
            The grants.
        """
        ...


class CanCreateLibrary(Protocol):
    """Resolve the instance-wide library creation permission."""

    async def __call__(self, query: LibraryCreationQuery) -> bool:
        """Resolve the permission from current authenticated identity state.

        Args:
            query: The caller and optional verified OAuth identity.

        Returns:
            Whether the caller may create a library.
        """
        ...
