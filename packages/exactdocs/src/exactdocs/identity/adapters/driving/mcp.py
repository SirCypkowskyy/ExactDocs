"""MCP adapter for identity: API tokens as the bearer credential of the HTTP transport."""

from fastmcp.server.auth import AccessToken, TokenVerifier

from exactdocs.identity.errors import InvalidTokenError
from exactdocs.identity.ports.driving import IdentifyToken


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
