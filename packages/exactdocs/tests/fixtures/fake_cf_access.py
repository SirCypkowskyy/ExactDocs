"""A Cloudflare Access team in the test process, for pytest and behave (never a real network).

``FakeAccess`` serves ``/cdn-cgi/access/certs`` (the team's JWKS, in Cloudflare's shape) and signs
application tokens with a locally generated RSA key: a person's (``email`` and ``sub``) or a
service token's (``common_name``, empty ``sub``). Keyword arguments change any claim for the
negative cases; ``signed_by_stranger`` signs with a key the team does not publish. ``transport``
hands it to ExactDocs' Access verifier through ``httpx2.ASGITransport``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

TEAM_DOMAIN = "https://team.cloudflareaccess.com"
AUDIENCE = "aud-123"
CERTS_PATH = "/cdn-cgi/access/certs"
LIFETIME = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


def rsa_key(kid: str) -> RSAKey:
    """A fresh RS256 signing key."""
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig", "alg": "RS256"})


@dataclass(slots=True)
class FakeAccess:
    """A scripted Cloudflare Access team."""

    team_domain: str = TEAM_DOMAIN
    audience: str = AUDIENCE
    now: Callable[[], datetime] = _now
    key: RSAKey = field(default_factory=lambda: rsa_key("cf1"))
    certs_fetches: int = 0
    down: bool = False

    def rotate_key(self) -> None:
        """Sign with a new key from now on (the old one is no longer published)."""
        self.key = rsa_key(f"cf{self.certs_fetches + 2}")

    def person(self, email: str, subject: str | None = None, **changes: Any) -> str:
        """An application token for a person who passed Access."""
        claims = {"email": email, "sub": subject or f"sub-{email}", "type": "app"}
        return self.token(claims, **changes)

    def service(self, common_name: str, **changes: Any) -> str:
        """An application token for a service token (its client ID in ``common_name``)."""
        return self.token({"common_name": common_name, "sub": "", "type": "app"}, **changes)

    def token(self, claims: dict[str, Any], *, key: RSAKey | None = None, **changes: Any) -> str:
        """Sign ``claims`` plus the standard ones; ``changes`` override any of them."""
        issued = int(self.now().timestamp())
        payload: dict[str, Any] = {
            "aud": [self.audience],
            "iss": self.team_domain,
            "iat": issued,
            "nbf": issued,
            "exp": issued + int(LIFETIME.total_seconds()),
            **claims,
            **changes,
        }
        payload = {name: value for name, value in payload.items() if value is not None}
        signer = key or self.key
        header = {"alg": "RS256", "kid": signer.kid, "typ": "JWT"}
        return jwt.encode(header, payload, signer)

    @property
    def app(self) -> Starlette:
        return Starlette(routes=[Route(CERTS_PATH, self._certs)])

    def transport(self) -> httpx2.AsyncBaseTransport:
        return _Transport(access=self, inner=httpx2.ASGITransport(app=self.app))

    async def _certs(self, _: Request) -> Response:
        self.certs_fetches += 1
        keys = KeySet([self.key]).as_dict(private=False)
        return JSONResponse({**keys, "public_cert": {"kid": self.key.kid, "cert": "unused"}})


@dataclass(slots=True)
class _Transport(httpx2.AsyncBaseTransport):
    """The fake team's app; a connection error while it is ``down``."""

    access: FakeAccess
    inner: httpx2.ASGITransport

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.access.down:
            message = "Cloudflare Access is down"
            raise httpx2.ConnectError(message, request=request)
        return await self.inner.handle_async_request(request)


def signed_by_stranger(access: FakeAccess, claims: dict[str, Any]) -> str:
    """A token like the team's, signed by a key the team does not publish (same ``kid``)."""
    stranger = RSAKey.generate_key(
        2048, parameters={"kid": access.key.kid or "cf1", "use": "sig", "alg": "RS256"}
    )
    return access.token(claims, key=stranger)
