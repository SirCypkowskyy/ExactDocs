"""An OpenID Connect issuer in the test process, for pytest and behave (never a real network).

``FakeIssuer`` serves discovery, a JWKS, an authorize endpoint that approves a scripted user, a
token endpoint that checks the client, the redirect URI and the PKCE verifier (S256) and returns
an ID token signed with a test RSA key, a refresh grant and userinfo. It can rotate its key, stop
issuing refresh tokens, change a user's groups, revoke refresh tokens, go down, and tamper with
the next ID token (``tamper``) for the negative cases. ``transport`` hands it to ExactDocs'
OIDC adapter through ``httpx2.ASGITransport``.
"""

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ISSUER = "https://idp.example.com"
CLIENT_ID = "exactdocs"
CLIENT_SECRET = "client-secret-of-exactdocs"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class FakeUser:
    """A person the issuer knows."""

    subject: str
    username: str | None
    email: str | None = None
    groups: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Code:
    user: FakeUser
    nonce: str
    challenge: str
    method: str
    redirect_uri: str


@dataclass(slots=True)
class FakeIssuer:
    """A scripted OpenID Connect provider."""

    issuer: str = ISSUER
    client_id: str = CLIENT_ID
    client_secret: str = CLIENT_SECRET
    now: Callable[[], datetime] = _now
    users: dict[str, FakeUser] = field(default_factory=dict)
    issue_refresh_tokens: bool = True
    groups_in_id_token: bool = True
    refresh_id_token: bool = True
    down: bool = False
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    discovered_issuer: str | None = None
    userinfo_subject: str | None = None
    """Userinfo answers with this ``sub`` instead of the token owner's (a confused issuer)."""
    tamper: Callable[[dict[str, Any], dict[str, Any]], str | None] | None = None
    """Called with the next ID token's header and claims (to change them in place); returns a
    whole token to send instead, or ``None`` to sign the changed ones."""
    key: RSAKey = field(default_factory=lambda: _rsa_key("k1"))
    old_keys: list[RSAKey] = field(default_factory=list)
    codes: dict[str, _Code] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)
    access_tokens: dict[str, str] = field(default_factory=dict)
    jwks_fetches: int = 0
    discovery_fetches: int = 0
    token_requests: list[dict[str, str]] = field(default_factory=list)

    # ------------------------------------------------------------------ scripting

    def add_user(
        self,
        subject: str,
        username: str | None,
        *,
        email: str | None = None,
        groups: list[str] | None = None,
    ) -> FakeUser:
        user = FakeUser(subject=subject, username=username, email=email, groups=groups or [])
        self.users[subject] = user
        return user

    def rotate_key(self, *, keep_old: bool = False) -> None:
        """Sign with a new key; the JWKS holds only it (and the old one with ``keep_old``)."""
        if keep_old:
            self.old_keys.append(self.key)
        self.key = _rsa_key(f"k{len(self.old_keys) + 2}-{secrets.token_hex(2)}")

    def revoke_refresh_tokens(self, subject: str) -> None:
        for token in [t for t, s in self.refresh_tokens.items() if s == subject]:
            del self.refresh_tokens[token]

    def authorize(self, url: str, subject: str) -> str:
        """Approve ``subject`` at the authorization URL; return the callback URL (path and query).

        Checks what a real issuer would: the client, the redirect URI's presence, PKCE S256.
        """
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert url.startswith(f"{self.issuer}/authorize?"), url
        assert query["client_id"] == self.client_id
        assert query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256"
        assert "openid" in query["scope"].split()
        code = secrets.token_urlsafe(16)
        self.codes[code] = _Code(
            user=self.users[subject],
            nonce=query["nonce"],
            challenge=query["code_challenge"],
            method=query["code_challenge_method"],
            redirect_uri=query["redirect_uri"],
        )
        callback = urlsplit(query["redirect_uri"])
        return f"{callback.path}?{urlencode({'code': code, 'state': query['state']})}"

    def id_token(self, user: FakeUser, *, nonce: str | None) -> str:
        now = int(self.now().timestamp())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "sub": user.subject,
            "aud": self.client_id,
            "iat": now,
            "exp": now + 300,
        }
        if nonce is not None:
            claims["nonce"] = nonce
        if user.username is not None:
            claims["preferred_username"] = user.username
        if user.email is not None:
            claims["email"] = user.email
        if self.groups_in_id_token:
            claims["groups"] = list(user.groups)
        header = {"alg": "RS256", "kid": self.key.kid}
        if self.tamper is not None:
            replaced = self.tamper(header, claims)
            self.tamper = None
            if replaced is not None:
                return replaced
        return jwt.encode(header, claims, self.key)

    # ------------------------------------------------------------------ the app

    @property
    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/.well-known/openid-configuration", self._discovery),
                Route("/jwks", self._jwks),
                Route("/token", self._token, methods=["POST"]),
                Route("/userinfo", self._userinfo),
            ]
        )

    def transport(self) -> httpx2.AsyncBaseTransport:
        return _Transport(issuer=self, inner=httpx2.ASGITransport(app=self.app))

    async def _discovery(self, _: Request) -> Response:
        self.discovery_fetches += 1
        return JSONResponse(
            {
                "issuer": self.discovered_issuer or self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
                "userinfo_endpoint": f"{self.issuer}/userinfo",
                "id_token_signing_alg_values_supported": self.algorithms,
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    async def _jwks(self, _: Request) -> Response:
        self.jwks_fetches += 1
        keys = KeySet([*self.old_keys, self.key])
        return JSONResponse(keys.as_dict(private=False))

    async def _token(self, request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        self.token_requests.append(form)
        if not self._client_ok(request):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if form.get("grant_type") == "authorization_code":
            return self._code_grant(form)
        if form.get("grant_type") == "refresh_token":
            subject = self.refresh_tokens.get(form.get("refresh_token", ""))
            if subject is None or subject not in self.users:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            user = self.users[subject]
            body = {"access_token": self._access_token(user), "token_type": "Bearer"}
            if self.refresh_id_token:
                body["id_token"] = self.id_token(user, nonce=None)
            return JSONResponse(body)
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    def _code_grant(self, form: dict[str, str]) -> Response:
        code = self.codes.pop(form.get("code", ""), None)  # single use, like a real issuer
        if code is None or form.get("redirect_uri") != code.redirect_uri:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        verifier = form.get("code_verifier", "")
        digest = hashlib.sha256(verifier.encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != code.challenge:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        user = code.user
        body = {
            "access_token": self._access_token(user),
            "token_type": "Bearer",
            "id_token": self.id_token(user, nonce=code.nonce),
        }
        if self.issue_refresh_tokens:
            refresh = secrets.token_urlsafe(16)
            self.refresh_tokens[refresh] = user.subject
            body["refresh_token"] = refresh
        return JSONResponse(body)

    async def _userinfo(self, request: Request) -> Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        subject = self.access_tokens.get(token)
        if subject is None:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        user = self.users[subject]
        info: dict[str, Any] = {
            "sub": self.userinfo_subject or user.subject,
            "groups": list(user.groups),
        }
        if user.username is not None:
            info["preferred_username"] = user.username
        return JSONResponse(info)

    def _client_ok(self, request: Request) -> bool:
        header = request.headers.get("authorization", "")
        if not header.startswith("Basic "):
            return False
        pair = base64.b64decode(header.removeprefix("Basic ")).decode()
        return pair == f"{self.client_id}:{self.client_secret}"

    def _access_token(self, user: FakeUser) -> str:
        token = secrets.token_urlsafe(16)
        self.access_tokens[token] = user.subject
        return token


@dataclass(slots=True)
class _Transport(httpx2.AsyncBaseTransport):
    """The fake issuer's app; a connection error while it is ``down``."""

    issuer: FakeIssuer
    inner: httpx2.ASGITransport

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.issuer.down:
            message = "the identity provider is down"
            raise httpx2.ConnectError(message, request=request)
        return await self.inner.handle_async_request(request)


def _rsa_key(kid: str) -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig", "alg": "RS256"})


def hs256_with_public_key(issuer: FakeIssuer) -> Callable[[dict[str, Any], dict[str, Any]], str]:
    """A tamper that MACs the token with HS256, the issuer's public key PEM as the secret.

    The classic key-confusion attack: a verifier that lets the token choose the algorithm would
    check the MAC with the public key it holds. Built by hand: joserfc refuses to make it.
    """

    def tamper(header: dict[str, Any], claims: dict[str, Any]) -> str:
        signing_input = f"{_part({**header, 'alg': 'HS256'})}.{_part(claims)}"
        secret = issuer.key.as_pem(private=False)
        mac = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"

    return tamper


def _part(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unsigned(header: dict[str, Any], claims: dict[str, Any]) -> str:
    """A tamper that sends the token with ``alg: none`` and no signature."""
    return f"{_part({**header, 'alg': 'none'})}.{_part(claims)}."


def signed_by_stranger(header: dict[str, Any], claims: dict[str, Any]) -> str:
    """A tamper that signs with a key the issuer never published, under its own ``kid``."""
    return jwt.encode(header, claims, _rsa_key(str(header["kid"])))
