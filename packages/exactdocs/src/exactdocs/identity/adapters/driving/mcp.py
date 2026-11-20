"""MCP adapter for identity: API tokens, OAuth ID tokens and Cloudflare Access tokens on HTTP."""

import logging
from dataclasses import dataclass

from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from exactdocs.identity.constants import ACCESS_ASSERTION_HEADER, ACCESS_COOKIE
from exactdocs.identity.errors import InvalidTokenError, NotSignedInError
from exactdocs.identity.ports.driving import (
    IdentifyAccessCaller,
    IdentifyExternalToken,
    IdentifyToken,
)
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
    """Check the provider credential the MCP OAuth proxy holds for a host, at every request.

    The proxy runs the OAuth flow with the host and the provider, and asks this verifier to
    vouch for an OIDC ID token or an opaque OAuth2/GitHub access token before each call.
    The provider adapter verifies the token and applies the web sign-in membership policy.
    Disabled accounts are refused at the next call. OIDC group loss takes effect when the ID
    token expires and is renewed; opaque access tokens read current userinfo and memberships
    on every request.
    """

    def __init__(self, *, provider: str, identify_external_token: IdentifyExternalToken) -> None:
        """Create the verifier.

        Args:
            provider: The name of the sign-in provider the proxy signs people in through.
            identify_external_token: The driving port that resolves the provider credential
                to who it acts as.
        """
        super().__init__()
        self._provider = provider
        self._identify = identify_external_token

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access of the token's owner, or ``None`` (a 401) when it is refused.

        Args:
            token: The provider's ID token or opaque access token.

        Returns:
            The access of whoever the token acts as, or ``None`` when the token is no good, the
            person is not admitted, their account is disabled or the provider cannot be reached.
        """
        try:
            identity = await self._identify(self._provider, token)
        except DomainError as error:
            logger.info("MCP OAuth token refused (%s)", error.code)
            return None
        caller = identity.account
        return AccessToken(
            token="",
            client_id=caller.id,
            scopes=[],
            claims={
                "username": caller.username,
                "role": caller.role,
                "external_identity": identity,
            },
        )


class AccessTokenVerifier(TokenVerifier):
    """Accept a Cloudflare Access application token as the bearer credential of ``/mcp``.

    ``AccessAssertionAsBearer`` puts the request's Access token there when the client sent no
    ``Authorization`` of its own; the token then acts as the account its person or service token
    is linked to. It is tried after every other verifier, so an API token or an OAuth bearer the
    client sent is never displaced.
    """

    def __init__(self, *, identify_access: IdentifyAccessCaller) -> None:
        """Create the verifier.

        Args:
            identify_access: The driving port that resolves an Access token to its account.
        """
        super().__init__()
        self._identify_access = identify_access

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access of the token's account, or ``None`` (a 401) when it is refused.

        Args:
            token: The Access application token.

        Returns:
            The access of the linked account, or ``None`` when the token signs nobody in.
        """
        try:
            account = await self._identify_access(token)
        except NotSignedInError:
            return None
        return AccessToken(
            token="",
            client_id=account.id,
            scopes=[],
            claims={"username": account.username, "role": account.role},
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessAssertionAsBearer:
    """ASGI wrapper of ``/mcp``: the Cloudflare Access token becomes the bearer credential.

    Only when the request has no ``Authorization`` header: an explicit API token or OAuth bearer
    always wins. The token comes from the ``Cf-Access-Jwt-Assertion`` header, else the
    ``CF_Authorization`` cookie; ``AccessTokenVerifier`` checks it like any bearer.
    """

    app: ASGIApp
    """FastMCP's Streamable HTTP app."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the request, with the Access token as its bearer when it has none.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope["type"] == "http":
            connection = HTTPConnection(scope)
            assertion = connection.headers.get(ACCESS_ASSERTION_HEADER) or connection.cookies.get(
                ACCESS_COOKIE
            )
            if assertion and "authorization" not in connection.headers:
                bearer = (b"authorization", f"Bearer {assertion}".encode("latin-1", "replace"))
                scope = {**scope, "headers": [*scope["headers"], bearer]}
        await self.app(scope, receive, send)
