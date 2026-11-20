"""The Cloudflare Access verifier: what a token must satisfy before its claims are believed.

The team is ``fake_cf_access.FakeAccess`` (a local RSA key, its certs served in process): no
network, no real Cloudflare.
"""

import base64
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import OctKey

from exactdocs.identity.adapters.driven.cloudflare_access import CloudflareAccessVerifier
from exactdocs.identity.constants import ACCESS_CERTS_REFETCH_INTERVAL, MAX_ACCESS_TOKEN_LENGTH
from exactdocs.identity.errors import AccessAssertionRefusedError, ProviderUnavailableError
from exactdocs.identity.models import AccessClaims
from fake_cf_access import AUDIENCE, TEAM_DOMAIN, FakeAccess, signed_by_stranger

START = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


@dataclass(slots=True)
class Clock:
    at: datetime = START

    def now(self) -> datetime:
        return self.at


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def access(clock: Clock) -> FakeAccess:
    return FakeAccess(now=clock.now)


@pytest.fixture
async def verifier(access: FakeAccess, clock: Clock) -> CloudflareAccessVerifier:
    client = httpx2.AsyncClient(transport=access.transport())
    return CloudflareAccessVerifier(
        team_domain=TEAM_DOMAIN,
        audiences=frozenset({AUDIENCE, "another-app"}),
        client=client,
        clock=clock,
    )


async def test_a_person_is_named_by_email_and_subject(
    verifier: CloudflareAccessVerifier, access: FakeAccess
) -> None:
    claims = await verifier.verify(access.person("alice@example.com", "s-1"))

    assert claims == AccessClaims(issuer=TEAM_DOMAIN, subject="s-1", email="alice@example.com")


async def test_a_service_token_is_named_by_its_client_id(
    verifier: CloudflareAccessVerifier, access: FakeAccess
) -> None:
    claims = await verifier.verify(access.service("abc.access"))

    assert claims == AccessClaims(issuer=TEAM_DOMAIN, subject="", common_name="abc.access")


async def test_any_configured_audience_is_accepted(
    verifier: CloudflareAccessVerifier, access: FakeAccess
) -> None:
    claims = await verifier.verify(access.person("a@example.com", aud="another-app"))

    assert claims.email == "a@example.com"


def _now(access: FakeAccess) -> int:
    return int(access.now().timestamp())


def _unsigned(claims: dict[str, object]) -> str:
    def part(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


@pytest.mark.parametrize(
    "forge",
    [
        pytest.param(
            lambda a: signed_by_stranger(a, {"email": "m@example.com", "sub": "m"}),
            id="unknown key",
        ),
        pytest.param(lambda a: a.person("m@example.com", aud=["other"]), id="other audience"),
        pytest.param(lambda a: a.person("m@example.com", aud=None), id="no audience"),
        pytest.param(
            lambda a: a.person("m@example.com", iss="https://evil.cloudflareaccess.com"),
            id="other issuer",
        ),
        pytest.param(lambda a: a.person("m@example.com", exp=_now(a) - 120), id="expired"),
        pytest.param(lambda a: a.person("m@example.com", exp=None), id="no expiry"),
        pytest.param(lambda a: a.person("m@example.com", nbf=_now(a) + 3600), id="not yet valid"),
        pytest.param(lambda a: a.person("m@example.com", iat=_now(a) + 3600), id="issued later"),
        pytest.param(lambda a: a.person("m@example.com", exp=True), id="boolean expiry"),
        pytest.param(lambda a: a.person("m@example.com", exp=1e999), id="infinite expiry"),
        pytest.param(
            lambda _: _unsigned({"email": "m@example.com", "sub": "m", "aud": [AUDIENCE]}),
            id="alg none",
        ),
        pytest.param(lambda _: "not.a.jwt", id="malformed"),
        pytest.param(lambda _: "x" * (MAX_ACCESS_TOKEN_LENGTH + 1), id="too long"),
    ],
)
async def test_a_token_that_does_not_check_out_is_refused(
    verifier: CloudflareAccessVerifier, access: FakeAccess, forge, caplog: pytest.LogCaptureFixture
) -> None:
    token = forge(access)
    caplog.set_level(logging.INFO)

    with pytest.raises(AccessAssertionRefusedError):
        await verifier.verify(token)

    assert token not in caplog.text  # the reason is logged, never the token


async def test_a_token_macd_with_the_public_key_is_refused(
    verifier: CloudflareAccessVerifier, access: FakeAccess
) -> None:
    """HS256 with the team's public key as the secret (algorithm confusion)."""
    public = json.dumps(access.key.as_dict(private=False)).encode()
    claims = {
        "email": "m@example.com",
        "sub": "m",
        "aud": [AUDIENCE],
        "iss": TEAM_DOMAIN,
        "exp": _now(access) + 600,
    }
    token = jwt.encode({"alg": "HS256", "kid": access.key.kid}, claims, OctKey.import_key(public))

    with pytest.raises(AccessAssertionRefusedError):
        await verifier.verify(token)


async def test_the_certs_are_cached(verifier: CloudflareAccessVerifier, access: FakeAccess) -> None:
    for _ in range(3):
        await verifier.verify(access.person("a@example.com"))

    assert access.certs_fetches == 1


async def test_a_rotated_key_fetches_the_certs_again(
    verifier: CloudflareAccessVerifier, access: FakeAccess, clock: Clock
) -> None:
    await verifier.verify(access.person("a@example.com"))
    clock.at += ACCESS_CERTS_REFETCH_INTERVAL
    access.rotate_key()

    claims = await verifier.verify(access.person("a@example.com"))

    assert (claims.email, access.certs_fetches) == ("a@example.com", 2)


async def test_unknown_keys_cannot_flood_the_team_domain(
    verifier: CloudflareAccessVerifier, access: FakeAccess, clock: Clock
) -> None:
    await verifier.verify(access.person("a@example.com"))
    access.rotate_key()
    clock.at += timedelta(seconds=1)

    for _ in range(5):
        with pytest.raises(AccessAssertionRefusedError):
            await verifier.verify(access.person("a@example.com"))
    assert access.certs_fetches == 1  # fetched within the interval: no refetch, however many

    clock.at += ACCESS_CERTS_REFETCH_INTERVAL
    for _ in range(5):
        await verifier.verify(access.person("a@example.com"))
    assert access.certs_fetches == 2  # then one refetch, which finds the new key


async def test_unreachable_certs_are_reported_as_unavailable(
    verifier: CloudflareAccessVerifier, access: FakeAccess
) -> None:
    access.down = True

    with pytest.raises(ProviderUnavailableError):
        await verifier.verify(access.person("a@example.com"))


async def test_certs_without_an_rsa_key_are_unusable(clock: Clock, access: FakeAccess) -> None:
    def answer(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"keys": [{"kty": "oct", "k": "c2VjcmV0"}]})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(answer))
    verifier = CloudflareAccessVerifier(
        team_domain=TEAM_DOMAIN, audiences=frozenset({AUDIENCE}), client=client, clock=clock
    )

    with pytest.raises(ProviderUnavailableError):
        await verifier.verify(access.person("a@example.com"))
