"""MCP adapter for identity: API tokens and OAuth ID tokens as the bearer credential of HTTP."""

import logging

from fastmcp.server.auth import AccessToken, TokenVerifier

from exactdocs.identity.errors import InvalidTokenError
from exactdocs.identity.ports.driving import IdentifyExternalToken, IdentifyToken
from exactdocs_kernel import DomainError

logger = logging.getLogger(__name__)


class ApiTokenVerifier(TokenVerifier):
    """Accept ``Authorization: Bearer <API token>`` on ``/mcp``; the token acts as its account.

    Only the HTTP transport asks for it: stdio and in-process clients are not authenticated
    (the process owner already has the data directory).
    """

    def __init__(self, *, identify_token: IdentifyToken) -> None:
        """Create the verifier.

        Args:
            identify_token: The driving port that resolves an API token to its account.
        """
        super().__init__()
        self._identify_token = identify_token

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access of the token's account, or ``None`` (a 401) for a bad token.

        Args:
            token: The bearer token of the request.

        Returns:
            The access of the token's account, or ``None`` when the token is no good.
        """
        try:
            account = await self._identify_token(token)
        except InvalidTokenError:
            return None
        return AccessToken(
            token="",  # the secret is not kept in the request-scoped auth object
            client_id=account.id,
            scopes=[],
            claims={"username": account.username, "role": account.role},
        )


class ExternalTokenVerifier(TokenVerifier):
    """Check the ID token the MCP OAuth proxy holds for a host, at every request.

    The proxy (FastMCP's ``OIDCProxy``) runs the OAuth flow with the host and the provider, and
    asks this verifier to vouch for the provider's ID token before each call. The provider's
    adapter validates the token and its policy admits the person (the same allowed groups as at
    the web sign-in), so a person who lost their group is refused at the next call.
    """

    def __init__(self, *, provider: str, identify_external_token: IdentifyExternalToken) -> None:
        """Create the verifier.

        Args:
            provider: The name of the sign-in provider the proxy signs people in through.
            identify_external_token: The driving port that resolves its ID token to who it
                acts as.
        """
        super().__init__()
        self._provider = provider
        self._identify = identify_external_token

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access of the token's owner, or ``None`` (a 401) when it is refused.

        Args:
            token: The provider's ID token.

        Returns:
            The access of whoever the token acts as, or ``None`` when the token is no good, the
            person is not admitted, their account is disabled or the provider cannot be reached.
        """
        try:
            caller = await self._identify(self._provider, token)
        except DomainError as error:
            logger.info("MCP OAuth token refused (%s)", error.code)
            return None
        return AccessToken(
            token="",  # the secret is not kept in the request-scoped auth object
            client_id=caller.id,
            scopes=[],
            claims={"username": caller.username, "role": caller.role},
        )
