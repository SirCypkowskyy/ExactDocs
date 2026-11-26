"""OAuth2 authorization-code provider with PKCE and authenticated userinfo claims."""

import base64
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx2
from authlib.oauth2.rfc7636 import create_s256_code_challenge

from exactdocs.identity.constants import (
    MAX_PROVIDER_RESPONSE_BYTES,
    OAUTH_CLIENT_BASIC,
    OAUTH_CLIENT_POST,
)
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)
from exactdocs.identity.models import ExternalClaims, ExternalGrant
from exactdocs_kernel import redact_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuth2ClaimNames:
    """Configurable userinfo claim names, including nested dotted paths."""

    subject: str = "sub"
    """The stable, nonempty string identifier."""
    username: str = "preferred_username"
    """The display username, used only for initial account creation."""
    email: str = "email"
    """The email claim."""
    groups: str = "groups"
    """The string or list of group names."""
    roles: str | None = None
    """The string or list of role values; ``None`` reads none."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuth2Provider:
    """One OAuth2 provider; opaque tokens are vouched for by its userinfo endpoint."""

    issuer: str
    """Configured stable linking namespace."""
    authorization_endpoint: str
    """Where users approve authorization."""
    token_endpoint: str
    """Where codes and refresh tokens are exchanged."""
    userinfo_endpoint: str
    """Where the token owner's claims are read."""
    client_id: str
    """The registered client ID."""
    client_secret: Callable[[], str | None] = field(repr=False)
    """Reads the client secret at each exchange."""
    redirect_uri: str
    """The registered browser callback."""
    scopes: tuple[str, ...]
    """The requested scopes, including offline_access for generic OAuth2."""
    client: httpx2.AsyncClient = field(repr=False)
    """The bootstrap-owned client with bounded timeout and no redirects."""
    claims: OAuth2ClaimNames = field(default_factory=OAuth2ClaimNames)
    """Where the stable subject and other claims are found."""
    client_auth_method: str = OAUTH_CLIENT_BASIC
    """Client authentication; GitHub requires client_secret_post."""

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """Build a state-bound PKCE S256 authorization URL.

        Args:
            state: The server's browser-bound random state.
            nonce: Unused by OAuth2; retained for the shared provider interface.
            code_verifier: The secret PKCE verifier.

        Returns:
            The complete authorization URL.
        """
        del nonce  # OAuth2 has no ID-token nonce; state and PKCE bind the browser flow.
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "code_challenge": create_s256_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        separator = "&" if urlsplit(self.authorization_endpoint).query else "?"
        return f"{self.authorization_endpoint}{separator}{urlencode(params)}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        """Exchange the browser code and read its owner's claims.

        Args:
            code: The single-use authorization code.
            code_verifier: The browser attempt's verifier.
            nonce: Unused by OAuth2.

        Returns:
            Verified claims and the refresh credential, if supplied.

        Raises:
            ExternalSignInFailedError: The code was refused or no access token was supplied.
        """
        del nonce
        status, body = await self.token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self.redirect_uri,
            }
        )
        if status != HTTPStatus.OK or body.get("error") is not None:
            raise ExternalSignInFailedError
        access = text(body, "access_token")
        if access is None:
            raise ExternalSignInFailedError
        return ExternalGrant(
            claims=await self.verify_id_token(access), refresh_token=text(body, "refresh_token")
        )

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        """Verify an opaque access token through authenticated userinfo (shared port name).

        Args:
            id_token: The OAuth2 access token, never a self-asserted claim payload.

        Returns:
            The provider's current identity and groups.

        Raises:
            ProviderAccessRevokedError: The provider refuses the credential.
            ProviderUnavailableError: Userinfo is unavailable or malformed.
            ExternalSignInFailedError: No stable string subject is present.
        """
        status, _, info = await request_json(
            self.client,
            "GET",
            self.userinfo_endpoint,
            headers={"Authorization": f"Bearer {id_token}", "Accept": "application/json"},
        )
        if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise ProviderAccessRevokedError
        if status != HTTPStatus.OK or not isinstance(info, dict):
            raise ProviderUnavailableError
        subject = claim(info, self.claims.subject)
        if not isinstance(subject, str) or not subject.strip():
            raise ExternalSignInFailedError
        username, email = claim(info, self.claims.username), claim(info, self.claims.email)
        return ExternalClaims(
            issuer=self.issuer,
            subject=subject,
            username=username if isinstance(username, str) and username.strip() else None,
            email=email if isinstance(email, str) and email.strip() else None,
            groups=claim_strings(claim(info, self.claims.groups)),
            roles=frozenset()
            if self.claims.roles is None
            else claim_strings(claim(info, self.claims.roles)),
        )

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        """Refresh the credential and reread current claims, refusing identity substitution.

        Args:
            refresh_token: The unsealed stored refresh token.
            subject: The stable identifier that must remain unchanged.

        Returns:
            Current claims and the rotated or original refresh credential.

        Raises:
            ProviderAccessRevokedError: The refresh grant was revoked.
            ProviderUnavailableError: The client or provider is unavailable.
            ExternalSignInFailedError: The refreshed identity changed or token is missing.
        """
        status, body = await self.token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        if body.get("error") == "invalid_grant":
            raise ProviderAccessRevokedError
        if status != HTTPStatus.OK or body.get("error") is not None:
            raise ProviderUnavailableError
        access = text(body, "access_token")
        if access is None:
            raise ExternalSignInFailedError
        claims = await self.verify_id_token(access)
        if claims.subject != subject:
            raise ExternalSignInFailedError
        return ExternalGrant(
            claims=claims, refresh_token=text(body, "refresh_token") or refresh_token
        )

    async def token_request(self, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
        """Send a code or refresh grant using the configured client authentication.

        Args:
            form: The grant parameters.

        Returns:
            HTTP status and the token response object, including OAuth errors.

        Raises:
            ProviderUnavailableError: An outage or malformed answer.
        """
        headers = {"Accept": "application/json"}
        form = {**form, "client_id": self.client_id}
        if secret := self.client_secret():
            if self.client_auth_method == OAUTH_CLIENT_POST:
                form["client_secret"] = secret
            else:
                pair = f"{quote(self.client_id, safe='')}:{quote(secret, safe='')}"
                headers["Authorization"] = f"Basic {base64.b64encode(pair.encode()).decode()}"
        status, _, body = await request_json(
            self.client, "POST", self.token_endpoint, data=form, headers=headers
        )
        if status not in {
            HTTPStatus.OK,
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.UNAUTHORIZED,
        } or not isinstance(body, dict):
            raise ProviderUnavailableError
        return status, body


async def request_json(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,  # ruff: ignore[any-type]
) -> tuple[int, httpx2.Headers, Any]:
    """Read one bounded provider JSON response without following redirects.

    Args:
        client: Bootstrap's timeout-bound client.
        method: The HTTP method.
        url: A configured endpoint, never a URL from provider pagination.
        **kwargs: Request headers and form data.

    Returns:
        Status, headers, and the parsed JSON value (None for non-JSON error responses).

    Raises:
        ProviderUnavailableError: Network failure, oversized body, or malformed success.
    """
    try:
        async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
            content = await _read_capped(response)
            status, headers = response.status_code, response.headers
    except httpx2.HTTPError as error:
        # The transport's text names a proxy that failed and the host (#538).
        host = httpx2.URL(url).host
        logger.warning(
            "%s cannot be reached (%s: %s)", host, type(error).__name__, redact_url(str(error))
        )
        raise ProviderUnavailableError from None
    try:
        return status, headers, json.loads(content)
    except ValueError:
        if status == HTTPStatus.OK:
            raise ProviderUnavailableError from None
        return status, headers, None


async def _read_capped(response: httpx2.Response) -> bytes:
    """Read a response while enforcing the shared decoded body limit.

    Args:
        response: The streamed provider response.

    Returns:
        Its bounded bytes.

    Raises:
        ProviderUnavailableError: The body is too large.
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ProviderUnavailableError
    content = bytearray()
    async for chunk in response.aiter_bytes():
        content += chunk
        if len(content) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderUnavailableError
    return bytes(content)


def claim(claims: Mapping[str, Any], path: str) -> object:
    """Read a literal claim name first, then a dotted nested path.

    Args:
        claims: The authenticated claims object.
        path: The configured field path.

    Returns:
        The value, or None if absent.
    """
    if path in claims:
        return claims[path]
    value: object = claims
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def text(body: Mapping[str, Any], name: str) -> str | None:
    """Read a nonempty string value.

    Args:
        body: A provider response object.
        name: The field name.

    Returns:
        The string, or None.
    """
    value = body.get(name)
    return value if isinstance(value, str) and value else None


def claim_strings(value: object) -> frozenset[str]:
    """Read a claim that holds one name or a list of names (groups, roles).

    Args:
        value: The claim's value.

    Returns:
        Its nonempty strings; empty for anything else.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str) and item)
