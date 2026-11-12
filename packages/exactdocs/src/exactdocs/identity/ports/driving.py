"""Driving (primary) ports: what the outside world may ask identity to do."""

from typing import Protocol

from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    LoginForTokenCommand,
    PasswordReset,
    ResetPasswordCommand,
    SessionGrant,
    SessionState,
    SetupState,
    TokenGrant,
    TokenList,
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


class GetSessionState(Protocol):
    """Tell whether setup is due, nobody is signed in, or the token's owner is."""

    async def __call__(self, token: str | None) -> SessionState:
        """Run the use case.

        Args:
            token: The session token, or ``None`` when the request carried none.

        Returns:
            The setup and sign-in state.
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
