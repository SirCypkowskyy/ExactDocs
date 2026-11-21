"""OpenID Connect sign-in provider: discovery, authorization code with PKCE, ID token checks.

Implements ``ports.driven.SignInProvider`` for one configured issuer (ADFS 2016+ included). HTTP
goes through the ``httpx2`` client bootstrap hands in (never Authlib's own client, which needs
``httpx``); Authlib makes the PKCE challenge and joserfc checks the ID token against the
issuer's JWKS. Nothing here logs or raises with a token, a code or the client secret.

What an ID token must satisfy before its claims are believed:

- signed by a key of the issuer's JWKS, with an asymmetric algorithm the issuer advertises
  (``none`` and ``HS*`` never pass, whatever the token's header says);
- ``iss`` equal to the configured issuer (discovery's ``issuer`` must equal it too);
- ``aud`` holding the client ID, and ``azp`` equal to it when present or when ``aud`` names
  several audiences;
- ``exp`` not passed, ``iat`` not in the future and ``nbf`` reached, with ``ID_TOKEN_LEEWAY``,
  each an integer (no boolean, fraction, ``NaN`` or infinity), in a payload that is an object;
- ``nonce`` equal to the attempt's (at sign-in), and ``sub`` present.

The discovery document is cached per process for ``DISCOVERY_TTL``; the JWKS is fetched on the
first sign-in and again when a token names a key it does not hold (rotation), at most once per
``JWKS_REFETCH_INTERVAL``. A token naming no key (no ``kid``) is checked with each key of the
JWKS that fits its algorithm.
"""

import asyncio
import base64
import ipaddress
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx2
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jws, jwt
from joserfc.errors import BadSignatureError, InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet

from exactdocs.identity.constants import (
    _BAD_REQUEST,
    _SUCCESS,
    _UNAUTHORIZED,
    ASYMMETRIC_ALGORITHMS,
    DISCOVERY_TTL,
    ID_TOKEN_LEEWAY,
    JWKS_REFETCH_INTERVAL,
    MAX_PROVIDER_RESPONSE_BYTES,
    NUMERIC_DATE_CLAIMS,
    SIGNING_KEY_TYPES,
)
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)
from exactdocs.identity.models import ExternalClaims, ExternalGrant
from exactdocs_kernel import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class OidcClaimNames:
    """Where the person's username, email and groups are among the claims (dotted paths)."""

    username: str = "preferred_username"
    """The username claim (ADFS: ``upn`` or ``unique_name``)."""
    email: str = "email"
    """The email claim; its local part names an account when there is no username."""
    groups: str = "groups"
    """The groups claim, a dotted path (Keycloak: ``realm_access.roles``; ADFS: ``group``)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Discovery:
    """The parts of the issuer's discovery document this adapter uses."""

    authorization_endpoint: str
    """Where the browser signs in."""
    token_endpoint: str
    """Where codes and refresh tokens are exchanged."""
    jwks_uri: str
    """The issuer's signing keys."""
    userinfo_endpoint: str | None
    """The claims of an access token's owner, if the issuer has the endpoint."""
    algorithms: frozenset[str]
    """The asymmetric ID token algorithms the issuer advertises (and this adapter accepts)."""
    basic_auth: bool
    """Whether the token endpoint takes ``client_secret_basic`` (else ``client_secret_post``)."""
    fetched_at: datetime
    """When the document was fetched."""


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- per-process caches
class OidcProvider:
    """Implements ``ports.driven.SignInProvider`` for one OpenID Connect issuer."""

    issuer: str
    """The configured issuer, compared exactly with discovery's ``issuer`` and tokens' ``iss``."""
    client_id: str
    """The client ID registered at the issuer."""
    client_secret: Callable[[], str | None] = field(repr=False)
    """Reads the client secret at each call (``None`` for a public client)."""
    redirect_uri: str
    """``<public URL>/api/v1/auth/<name>/callback``, as registered at the issuer."""
    scopes: tuple[str, ...]
    """The scopes asked for (``openid`` always among them)."""
    claims: OidcClaimNames = field(default_factory=OidcClaimNames)
    """Where the username, email and groups are."""
    client: httpx2.AsyncClient = field(repr=False)
    """The HTTP client (bootstrap's, with its timeout; tests hand in a fake issuer's)."""
    clock: Clock
    """The current time: cache ages and the ID token's times."""
    _discovery: _Discovery | None = field(default=None, init=False, repr=False)
    """The cached discovery document."""
    _keys: KeySet | None = field(default=None, init=False, repr=False)
    """The cached JWKS."""
    _keys_fetched_at: datetime | None = field(default=None, init=False, repr=False)
    """When the JWKS was last fetched."""
    _fetching: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    """One fetch of the discovery document or the JWKS at a time."""

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        """Return the issuer's authorization URL for a code flow with PKCE S256.

        Args:
            state: Comes back unchanged with the code.
            nonce: Must come back in the ID token.
            code_verifier: The attempt's PKCE verifier (only its S256 challenge is sent).

        Returns:
            The URL, with ``response_mode=query`` so the callback is a top-level GET.
        """
        discovery = await self._discover()
        params = {
            "response_type": "code",
            "response_mode": "query",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": create_s256_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        separator = "&" if urlsplit(discovery.authorization_endpoint).query else "?"
        return f"{discovery.authorization_endpoint}{separator}{urlencode(params)}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        """Trade the code for tokens, validate the ID token and read the claims.

        Args:
            code: The authorization code.
            code_verifier: The attempt's PKCE verifier.
            nonce: The attempt's nonce.

        Returns:
            The validated claims and the refresh token, if the issuer sent one.

        Raises:
            ExternalSignInFailedError: The issuer refused the code, or sent no ID token.
        """
        discovery = await self._discover()
        status, body = await self._token_request(
            discovery,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        if status in {_BAD_REQUEST, _UNAUTHORIZED}:
            logger.info("OIDC %s refused the authorization code (%s)", self.issuer, _error(body))
            raise ExternalSignInFailedError
        id_token = body.get("id_token")
        if not isinstance(id_token, str):
            logger.info("OIDC %s sent no ID token", self.issuer)
            raise ExternalSignInFailedError
        claims = await self._validate(id_token, discovery, nonce=nonce)
        claims = await self._with_userinfo(claims, discovery, body.get("access_token"))
        return ExternalGrant(
            claims=self._external(claims), refresh_token=_text(body, "refresh_token")
        )

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        """Validate an ID token of this issuer (no nonce) and read its claims.

        Args:
            id_token: The ID token.

        Returns:
            The validated claims: subject, username, email and groups (from the token only).
        """
        return self._external(await self._validate(id_token, await self._discover(), nonce=None))

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        """Refresh the tokens and read the person's claims again.

        A new ID token, when the issuer sends one, is validated like the first (without the
        nonce); the claims it lacks (often the groups) come from userinfo.

        Args:
            refresh_token: The stored refresh token.
            subject: Whom it belongs to.

        Returns:
            The current claims, and the refresh token to keep (a rotated one, or the same).

        Raises:
            ProviderAccessRevokedError: The issuer refused the refresh token (``invalid_grant``).
            ProviderUnavailableError: The issuer refused the client, or offers no way to read
                the claims again.
            ExternalSignInFailedError: The new claims belong to someone else.
        """
        discovery = await self._discover()
        status, body = await self._token_request(
            discovery, {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        if status in {_BAD_REQUEST, _UNAUTHORIZED}:
            error = _error(body)
            logger.info("OIDC %s refused a refresh token (%s)", self.issuer, error)
            if error == "invalid_grant":
                raise ProviderAccessRevokedError
            raise ProviderUnavailableError  # the client's own setup: not the person's fault
        claims: dict[str, Any] = {}
        if isinstance(id_token := body.get("id_token"), str):
            claims = await self._validate(id_token, discovery, nonce=None)
        elif discovery.userinfo_endpoint is None:
            logger.warning("OIDC %s sent no ID token on refresh and has no userinfo", self.issuer)
            raise ProviderUnavailableError
        claims = await self._with_userinfo(
            claims or {"sub": subject}, discovery, body.get("access_token"), force=not claims
        )
        if claims.get("sub") != subject:
            logger.warning("OIDC %s refreshed the claims of another subject", self.issuer)
            raise ExternalSignInFailedError
        return ExternalGrant(
            claims=self._external(claims),
            refresh_token=_text(body, "refresh_token") or refresh_token,
        )

    def _external(self, claims: Mapping[str, Any]) -> ExternalClaims:
        """Map validated claims to the domain's terms.

        Args:
            claims: The validated claims.

        Returns:
            The issuer, subject, username, email and groups.
        """
        groups = _claim(claims, self.claims.groups)
        if isinstance(groups, str):
            groups = [groups]
        username = _claim(claims, self.claims.username)
        email = _claim(claims, self.claims.email)
        return ExternalClaims(
            issuer=self.issuer,
            subject=str(claims["sub"]),
            username=username if isinstance(username, str) and username.strip() else None,
            email=email if isinstance(email, str) and email.strip() else None,
            groups=frozenset(g for g in groups if isinstance(g, str) and g)
            if isinstance(groups, list)
            else frozenset(),
        )

    async def _with_userinfo(
        self,
        claims: dict[str, Any],
        discovery: _Discovery,
        access_token: object,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Fill in the claims the ID token lacks from the userinfo endpoint.

        Asked only when the groups or the username are missing (or ``force``), when the issuer
        has the endpoint and sent an access token. Userinfo's ``sub`` must be the ID token's
        (OIDC Core 5.3.2); the ID token's own claims win.

        Args:
            claims: The ID token's validated claims.
            discovery: The issuer's discovery document.
            access_token: The access token from the token response.
            force: Ask even when nothing seems missing (a refresh without an ID token).

        Returns:
            The claims, completed.

        Raises:
            ExternalSignInFailedError: Userinfo describes another subject.
            ProviderUnavailableError: Userinfo was needed and could not be read.
        """
        missing = force or any(
            _claim(claims, path) is None for path in (self.claims.groups, self.claims.username)
        )
        if not missing or discovery.userinfo_endpoint is None:
            return claims
        if not isinstance(access_token, str):
            if force:
                raise ProviderUnavailableError
            return claims
        status, info = await self._request(
            "GET",
            discovery.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if status not in _SUCCESS:
            logger.warning("OIDC %s userinfo answered %s", self.issuer, status)
            raise ProviderUnavailableError
        if info.get("sub") != claims.get("sub"):
            logger.warning("OIDC %s userinfo describes another subject", self.issuer)
            raise ExternalSignInFailedError
        return {**info, **claims}

    async def _validate(
        self, token: str, discovery: _Discovery, *, nonce: str | None
    ) -> dict[str, Any]:
        """Check the ID token's signature and claims (see the module docstring).

        Args:
            token: The compact JWT.
            discovery: The issuer's discovery document.
            nonce: The attempt's nonce; ``None`` on a refresh, where none is expected.

        Returns:
            The token's claims.

        Raises:
            ExternalSignInFailedError: Any check fails.
        """
        claims = await self._decode(token, sorted(discovery.algorithms))
        for name in NUMERIC_DATE_CLAIMS:
            # An integer only: joserfc 1.7.7 takes ``true`` as 1 and an ``exp`` of ``1e999``
            # (infinite) as a token that never expires; NaN compares false with everything.
            if name in claims and type(claims[name]) is not int:
                logger.info("OIDC %s: ID token refused (%s is not an integer)", self.issuer, name)
                raise ExternalSignInFailedError
        options: dict[str, Any] = {
            "iss": {"essential": True, "value": self.issuer},
            "sub": {"essential": True},
            "aud": {"essential": True, "value": self.client_id},
            "exp": {"essential": True},
            "iat": {"essential": True},
        }
        if nonce is not None:
            options["nonce"] = {"essential": True, "value": nonce}
        registry = jwt.JWTClaimsRegistry(
            now=lambda: int(self.clock.now().timestamp()),
            leeway=int(ID_TOKEN_LEEWAY.total_seconds()),
            **options,
        )
        try:
            registry.validate(claims)
        except JoseError as error:
            # The error names the failed check, never the token's content.
            logger.info("OIDC %s: ID token refused (%s)", self.issuer, type(error).__name__)
            raise ExternalSignInFailedError from None
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        azp = claims.get("azp")
        if (len(audiences) > 1 or azp is not None) and azp != self.client_id:
            logger.info("OIDC %s: ID token refused (azp is not this client)", self.issuer)
            raise ExternalSignInFailedError
        return claims

    async def _decode(self, token: str, algorithms: list[str]) -> dict[str, Any]:
        """Check the ID token's signature against the issuer's keys and return its claims.

        A token naming a key the cached JWKS does not hold fetches the JWKS again once (the
        issuer may have rotated its keys), within ``JWKS_REFETCH_INTERVAL``. A token naming no
        key is tried against each key that fits its algorithm (``_verify``); when none verifies
        it, the JWKS is fetched again the same way.

        Args:
            token: The compact JWT.
            algorithms: The algorithms accepted (asymmetric, advertised by the issuer).

        Returns:
            The claims, not checked yet.

        Raises:
            ExternalSignInFailedError: The token is malformed, signed with another algorithm,
                by an unknown key, or not by the key it names.
        """
        keys = await self._keyset(refetch=False)
        try:
            try:
                decoded = _verify(token, keys, algorithms)
            except InvalidKeyIdError:
                keys = await self._keyset(refetch=True)
                decoded = _verify(token, keys, algorithms)
        except (JoseError, ValueError, TypeError) as error:
            logger.info("OIDC %s: ID token refused (%s)", self.issuer, type(error).__name__)
            raise ExternalSignInFailedError from None
        # JSON that is not an object is no claims set (``dict`` would even turn a list of pairs
        # into one); joserfc 1.7.7 does not refuse it.
        claims: object = decoded.claims
        if not isinstance(claims, dict):
            logger.info("OIDC %s: ID token refused (the payload is not an object)", self.issuer)
            raise ExternalSignInFailedError
        return claims

    async def _keyset(self, *, refetch: bool) -> KeySet:
        """Return the issuer's keys, fetching them first when there are none yet.

        ``refetch`` (a token named an unknown key) fetches them again, unless they were fetched
        within ``JWKS_REFETCH_INTERVAL``; then the cached keys are returned and the token fails.

        Args:
            refetch: Fetch again (key rotation), within the rate limit.

        Returns:
            The keys.

        Raises:
            ProviderUnavailableError: The JWKS cannot be fetched.
        """
        async with self._fetching:
            now = self.clock.now()
            recent = (
                self._keys_fetched_at is not None
                and now - self._keys_fetched_at < JWKS_REFETCH_INTERVAL
            )
            if self._keys is not None and (not refetch or recent):
                return self._keys
            discovery = await self._discover(locked=True)
            status, body = await self._request("GET", discovery.jwks_uri)
            self._keys_fetched_at = now  # a failed fetch counts too: no storm on a broken issuer
            if status not in _SUCCESS:
                logger.warning("OIDC %s: JWKS answered %s", self.issuer, status)
                raise ProviderUnavailableError
            self._keys = _signing_keys(body, self.issuer)
            return self._keys

    async def _discover(self, *, locked: bool = False) -> _Discovery:
        """Return the issuer's discovery document, fetched at most once per ``DISCOVERY_TTL``.

        Args:
            locked: The caller holds ``_fetching`` already.

        Returns:
            The parts of the document this adapter uses.
        """
        cached = self._discovery
        if cached is not None and self.clock.now() - cached.fetched_at < DISCOVERY_TTL:
            return cached
        if locked:
            return await self._fetch_discovery()
        async with self._fetching:
            cached = self._discovery
            if cached is not None and self.clock.now() - cached.fetched_at < DISCOVERY_TTL:
                return cached
            return await self._fetch_discovery()

    async def _fetch_discovery(self) -> _Discovery:
        """Fetch and check the discovery document (the caller holds ``_fetching``).

        Returns:
            The parts of the document this adapter uses.

        Raises:
            ProviderUnavailableError: The document cannot be read, names another issuer, lacks
                an endpoint, points to an endpoint that is not HTTPS, or advertises no
                asymmetric ID token algorithm.
        """
        url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
        status, body = await self._request("GET", url)
        if status not in _SUCCESS:
            logger.warning("OIDC %s: discovery answered %s", self.issuer, status)
            raise ProviderUnavailableError
        if body.get("issuer") != self.issuer:
            logger.warning("OIDC %s: discovery names another issuer", self.issuer)
            raise ProviderUnavailableError
        endpoints = {
            name: body.get(name)
            for name in ("authorization_endpoint", "token_endpoint", "jwks_uri")
        }
        userinfo = body.get("userinfo_endpoint")
        urls = [*endpoints.values(), *([userinfo] if userinfo is not None else [])]
        if not all(isinstance(u, str) and secure_url(u) for u in urls):
            logger.warning("OIDC %s: discovery lacks an endpoint, or one is not HTTPS", self.issuer)
            raise ProviderUnavailableError
        advertised = body.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = ASYMMETRIC_ALGORITHMS.intersection(a for a in advertised if isinstance(a, str))
        if not algorithms:
            logger.warning("OIDC %s: no asymmetric ID token algorithm advertised", self.issuer)
            raise ProviderUnavailableError
        methods = body.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        self._discovery = _Discovery(
            authorization_endpoint=str(endpoints["authorization_endpoint"]),
            token_endpoint=str(endpoints["token_endpoint"]),
            jwks_uri=str(endpoints["jwks_uri"]),
            userinfo_endpoint=userinfo,
            algorithms=frozenset(algorithms),
            basic_auth="client_secret_basic" in methods,
            fetched_at=self.clock.now(),
        )
        return self._discovery

    async def _token_request(
        self, discovery: _Discovery, form: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        """POST to the token endpoint with the client's authentication.

        Args:
            discovery: The issuer's discovery document.
            form: The grant's parameters.

        Returns:
            The status and the JSON body (``400``/``401`` are returned for the caller to judge).

        Raises:
            ProviderUnavailableError: Any other status that is not a success.
        """
        headers = {"Accept": "application/json"}
        form = {**form, "client_id": self.client_id}
        if secret := self.client_secret():
            if discovery.basic_auth:
                pair = f"{quote(self.client_id, safe='')}:{quote(secret, safe='')}"
                headers["Authorization"] = f"Basic {base64.b64encode(pair.encode()).decode()}"
            else:
                form["client_secret"] = secret
        status, body = await self._request(
            "POST", discovery.token_endpoint, data=form, headers=headers
        )
        if status in _SUCCESS or status in {_BAD_REQUEST, _UNAUTHORIZED}:
            return status, body
        logger.warning("OIDC %s: token endpoint answered %s", self.issuer, status)
        raise ProviderUnavailableError

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:  # ruff: ignore[any-type]
        """Send one request and read its JSON object.

        Args:
            method: The HTTP method.
            url: The URL.
            **kwargs: Passed on to ``httpx2.AsyncClient.request`` (form data, headers).

        Returns:
            The status and the body's JSON object (empty for an answer that is not one, unless
            the request succeeded).

        Raises:
            ProviderUnavailableError: The issuer cannot be reached, answers too much, or
                answers a success that is not a JSON object.
        """
        try:
            async with self.client.stream(
                method, url, follow_redirects=False, **kwargs
            ) as response:
                status = response.status_code
                content = await self._read_capped(response)
        except httpx2.HTTPError as error:
            logger.warning("OIDC %s cannot be reached (%s)", self.issuer, type(error).__name__)
            raise ProviderUnavailableError from None
        try:
            body = json.loads(content)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            if status in _SUCCESS:
                logger.warning("OIDC %s answered something that is not JSON", self.issuer)
                raise ProviderUnavailableError
            body = {}
        return status, body

    async def _read_capped(self, response: httpx2.Response) -> bytes:
        """Read the body while it stays within ``MAX_PROVIDER_RESPONSE_BYTES``.

        The limit is checked as the body arrives (decoded, so a compressed bomb counts at its
        real size), never after it was buffered whole: the rest is not read.

        Args:
            response: The streamed response.

        Returns:
            The body.

        Raises:
            ProviderUnavailableError: The body (or its declared length) exceeds the limit.
        """
        declared = response.headers.get("content-length", "")
        content = bytearray()
        if not (declared.isdigit() and int(declared) > MAX_PROVIDER_RESPONSE_BYTES):
            async for chunk in response.aiter_bytes():
                content += chunk
                if len(content) > MAX_PROVIDER_RESPONSE_BYTES:
                    break
            else:
                return bytes(content)
        logger.warning(
            "OIDC %s answered more than %d bytes", self.issuer, MAX_PROVIDER_RESPONSE_BYTES
        )
        raise ProviderUnavailableError


def secure_url(url: str) -> bool:
    """Whether an issuer or endpoint URL may be used: HTTPS, or HTTP on a loopback host.

    Args:
        url: The URL.

    Returns:
        ``True`` for ``https://...``, and for ``http://`` to ``localhost`` or a loopback IP
        (development only).
    """
    parts = urlsplit(url)
    if not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    if parts.scheme != "http":
        return False
    if parts.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return False


def _verify(token: str, keys: KeySet, algorithms: list[str]) -> jwt.Token:
    """Check the token's signature with the key it names, or with each key that fits.

    joserfc picks the key by ``kid``, and with several keys refuses a token without one. Such a
    token is tried against every key of the type its (accepted) algorithm signs with, whose own
    ``alg``, if it has one, is that algorithm; the first that verifies it wins.

    Args:
        token: The compact JWT.
        keys: The issuer's keys.
        algorithms: The algorithms accepted.

    Returns:
        The decoded token, its claims not checked yet.

    Raises:
        InvalidKeyIdError: The token names an unknown key, or names none and no key verifies it.

    joserfc's own errors (a malformed token, a wrong signature) pass through to the caller.
    """
    header = jws.extract_compact(token.encode()).protected
    alg = header.get("alg")
    if "kid" in header or len(keys.keys) <= 1 or alg not in algorithms:
        return jwt.decode(token, keys, algorithms=algorithms)
    kty = SIGNING_KEY_TYPES.get(str(alg)[:2])
    for key in keys.keys:
        if key.key_type != kty or key.get("alg", alg) != alg:
            continue
        try:
            return jwt.decode(token, key, algorithms=[str(alg)])
        except BadSignatureError:
            continue
    raise InvalidKeyIdError


def _signing_keys(body: Mapping[str, Any], issuer: str) -> KeySet:
    """Import the JWKS's signature keys (never encryption keys, never a shared secret).

    Args:
        body: The JWKS document.
        issuer: The issuer, for the log.

    Returns:
        The keys.

    Raises:
        ProviderUnavailableError: The JWKS holds no usable signature key.
    """
    keys = body.get("keys")
    usable = [
        key
        for key in (keys if isinstance(keys, list) else [])
        if isinstance(key, dict) and key.get("use", "sig") == "sig" and key.get("kty") != "oct"
    ]
    try:
        return KeySet.import_key_set({"keys": usable})
    except (JoseError, ValueError, TypeError) as error:
        logger.warning("OIDC %s: the JWKS cannot be read (%s)", issuer, type(error).__name__)
        raise ProviderUnavailableError from None


def _claim(claims: Mapping[str, Any], path: str) -> object:
    """Return the claim at a dotted path (``realm_access.roles``), or ``None``.

    A claim whose own name holds a dot (``https://example.com/groups``) is found as it is first.

    Args:
        claims: The claims.
        path: The claim's name, or a dotted path through nested objects.

    Returns:
        The value, or ``None`` when it is missing.
    """
    if path in claims:
        return claims[path]
    value: object = claims
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _text(body: Mapping[str, Any], name: str) -> str | None:
    """Return a non-empty text field of a JSON object, or ``None``.

    Args:
        body: The object.
        name: The field.

    Returns:
        The text, or ``None``.
    """
    value = body.get(name)
    return value if isinstance(value, str) and value else None


def _error(body: Mapping[str, Any]) -> str:
    """Return the OAuth error code of a refused request, for the log (never its description).

    Args:
        body: The error response.

    Returns:
        The ``error`` code, or ``unknown``; at most 64 characters.
    """
    error = body.get("error")
    return error[:64] if isinstance(error, str) else "unknown"
