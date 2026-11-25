"""Cloudflare Access application tokens: checked against the team's published keys.

Implements ``ports.driven.AccessAssertionVerifier`` for one team and application. HTTP goes
through the ``httpx2`` client bootstrap hands in; joserfc checks the JWT. Nothing here logs or
raises with a token.

What an Access token must satisfy before its claims are believed:

- an RS256 signature by a key of ``<team_domain>/cdn-cgi/access/certs`` (``none``, ``HS*`` and
  every other algorithm never pass, whatever the token's header says);
- ``iss`` equal to the team domain, and ``aud`` holding one of the configured audience tags;
- ``exp`` not passed and ``nbf`` reached (``iat`` not in the future), with
  ``ACCESS_TOKEN_LEEWAY``, each an integer, in a payload that is an object.

The certs are fetched on the first token and again when a token names a key they do not hold
(Cloudflare rotates its keys), at most once per ``ACCESS_CERTS_REFETCH_INTERVAL``.
"""

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NoReturn

import httpx2
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet

from exactdocs.identity.constants import (
    _SUCCESS,
    ACCESS_ALGORITHMS,
    ACCESS_CERTS_PATH,
    ACCESS_CERTS_REFETCH_INTERVAL,
    ACCESS_TOKEN_LEEWAY,
    MAX_ACCESS_CERTS_BYTES,
    MAX_ACCESS_TOKEN_LENGTH,
    NUMERIC_DATE_CLAIMS,
)
from exactdocs.identity.errors import AccessAssertionRefusedError, ProviderUnavailableError
from exactdocs.identity.models import AccessClaims
from exactdocs_kernel import Clock, redact_url

logger = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- per-process cache
class CloudflareAccessVerifier:
    """Implements ``ports.driven.AccessAssertionVerifier`` for one Access team and application."""

    team_domain: str
    """``https://<team>.cloudflareaccess.com``, without a trailing slash: the tokens' issuer."""
    audiences: frozenset[str]
    """The Access application's AUD tags; a token must name one of them."""
    client: httpx2.AsyncClient = field(repr=False)
    """The HTTP client (bootstrap's, with its timeout; tests hand in a fake team's)."""
    clock: Clock
    """The current time: the token's times and the certs' age."""
    _keys: KeySet | None = field(default=None, init=False, repr=False)
    """The cached certs."""
    _keys_fetched_at: datetime | None = field(default=None, init=False, repr=False)
    """When the certs were last fetched."""
    _fetching: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """One fetch of the certs at a time."""

    async def verify(self, assertion: str) -> AccessClaims:
        """Validate an Access application token and return who it is about.

        A token that is malformed, too long, not signed by a key of the team, or whose issuer,
        audience or times do not check out raises ``AccessAssertionRefusedError``; certs that
        cannot be fetched raise ``ProviderUnavailableError``.

        Args:
            assertion: The compact JWT.

        Returns:
            The person (``email``, ``sub``) or service token (``common_name``) it names.
        """
        if len(assertion) > MAX_ACCESS_TOKEN_LENGTH:
            self._refuse("too long")
        claims = await self._decode(assertion)
        for name in NUMERIC_DATE_CLAIMS:
            # An integer only: joserfc takes ``true`` as 1 and ``1e999`` as a token that never
            # expires.
            if name in claims and type(claims[name]) is not int:
                self._refuse(f"{name} is not an integer")
        registry = jwt.JWTClaimsRegistry(
            now=lambda: int(self.clock.now().timestamp()),
            leeway=int(ACCESS_TOKEN_LEEWAY.total_seconds()),
            iss={"essential": True, "value": self.team_domain},
            aud={"essential": True, "values": sorted(self.audiences)},
            exp={"essential": True},
        )
        try:
            registry.validate(claims)
        except JoseError as error:
            self._refuse(type(error).__name__)  # names the failed check, never the content
        return AccessClaims(
            issuer=self.team_domain,
            subject=_text(claims, "sub") or "",
            email=_text(claims, "email"),
            common_name=_text(claims, "common_name"),
        )

    def _refuse(self, reason: str) -> NoReturn:
        """Log why a token is refused (never the token) and refuse it.

        Args:
            reason: The failed check.

        Raises:
            AccessAssertionRefusedError: Always.
        """
        logger.info("Cloudflare Access %s: token refused (%s)", self.team_domain, reason)
        raise AccessAssertionRefusedError

    async def _decode(self, token: str) -> dict[str, Any]:
        """Check the token's signature against the team's keys and return its claims.

        A token naming a key the cached certs do not hold fetches them again once (rotation),
        within ``ACCESS_CERTS_REFETCH_INTERVAL``.

        A token that is malformed, signed with another algorithm, by an unknown key or not by
        the key it names is refused (``_refuse``).

        Args:
            token: The compact JWT.

        Returns:
            The claims, not checked yet.
        """
        algorithms = list(ACCESS_ALGORITHMS)
        keys = await self._keyset(refetch=False)
        try:
            try:
                decoded = jwt.decode(token, keys, algorithms=algorithms)
            except InvalidKeyIdError:
                keys = await self._keyset(refetch=True)
                decoded = jwt.decode(token, keys, algorithms=algorithms)
        except (JoseError, ValueError, TypeError) as error:
            self._refuse(type(error).__name__)
        claims: object = decoded.claims
        if not isinstance(claims, dict):
            self._refuse("the payload is not an object")
        return claims

    async def _keyset(self, *, refetch: bool) -> KeySet:
        """Return the team's keys, fetching them first when there are none yet.

        ``refetch`` (a token named an unknown key) fetches them again, unless they were fetched
        within ``ACCESS_CERTS_REFETCH_INTERVAL``; then the cached keys are returned.

        Args:
            refetch: Fetch again (key rotation), within the rate limit.

        Returns:
            The keys (``ProviderUnavailableError`` when the certs cannot be fetched or read).
        """
        async with self._fetching:
            now = self.clock.now()
            recent = (
                self._keys_fetched_at is not None
                and now - self._keys_fetched_at < ACCESS_CERTS_REFETCH_INTERVAL
            )
            if self._keys is not None and (not refetch or recent):
                return self._keys
            self._keys_fetched_at = now  # a failed fetch counts too: no storm on a broken team
            body = await self._fetch_certs()
            self._keys = _signing_keys(body.get("keys"), self.team_domain)
            return self._keys

    async def _fetch_certs(self) -> Mapping[str, Any]:
        """Fetch the team's certs document.

        Returns:
            The JSON object.

        Raises:
            ProviderUnavailableError: The team cannot be reached, answers an error, too much,
                or something that is not a JSON object.
        """
        url = f"{self.team_domain}{ACCESS_CERTS_PATH}"
        try:
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                status, content = response.status_code, await _read_capped(response)
        except httpx2.HTTPError as error:
            logger.warning(
                "Cloudflare Access %s cannot be reached (%s: %s)",
                self.team_domain,
                type(error).__name__,
                redact_url(str(error)),
            )
            raise ProviderUnavailableError from None
        if status not in _SUCCESS or content is None:
            logger.warning("Cloudflare Access %s: certs answered %s", self.team_domain, status)
            raise ProviderUnavailableError
        try:
            body = json.loads(content)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            logger.warning("Cloudflare Access %s: certs are not a JSON object", self.team_domain)
            raise ProviderUnavailableError
        return body


def _signing_keys(keys: object, team_domain: str) -> KeySet:
    """Import the certs' RSA signature keys (never a shared secret, never another type).

    Args:
        keys: The certs document's ``keys``.
        team_domain: The team, for the log.

    Returns:
        The keys.

    Raises:
        ProviderUnavailableError: The certs hold no usable key.
    """
    usable = [
        key
        for key in (keys if isinstance(keys, list) else [])
        if isinstance(key, dict) and key.get("use", "sig") == "sig" and key.get("kty") == "RSA"
    ]
    try:
        imported = KeySet.import_key_set({"keys": usable})
    except (JoseError, ValueError, TypeError) as error:
        logger.warning(
            "Cloudflare Access %s: the certs cannot be read (%s)", team_domain, type(error).__name__
        )
        raise ProviderUnavailableError from None
    if not imported.keys:
        logger.warning("Cloudflare Access %s: the certs hold no RSA signing key", team_domain)
        raise ProviderUnavailableError
    return imported


async def _read_capped(response: httpx2.Response) -> bytes | None:
    """Read the body while it stays within ``MAX_ACCESS_CERTS_BYTES``.

    Args:
        response: The streamed response.

    Returns:
        The body; ``None`` when it (or its declared length) exceeds the limit, unread to the end.
    """
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_ACCESS_CERTS_BYTES:
        return None
    content = bytearray()
    async for chunk in response.aiter_bytes():
        content += chunk
        if len(content) > MAX_ACCESS_CERTS_BYTES:
            return None
    return bytes(content)


def _text(claims: Mapping[str, Any], name: str) -> str | None:
    """Return a non-empty text claim, or ``None``.

    Args:
        claims: The claims.
        name: The claim.

    Returns:
        The text, or ``None``.
    """
    value = claims.get(name)
    return value if isinstance(value, str) and value else None
