"""The OIDC adapter against an in-process issuer: discovery, PKCE, and every ID token check."""

import base64
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from exactdocs.identity.adapters.driven.oidc import OidcClaimNames, OidcProvider, secure_url
from exactdocs.identity.constants import MAX_PROVIDER_RESPONSE_BYTES
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)
from fake_oidc import (
    CLIENT_ID,
    CLIENT_SECRET,
    ISSUER,
    FakeIssuer,
    hs256_with_public_key,
    signed_by_stranger,
    signed_payload,
    unsigned,
)

REDIRECT = "https://docs.example.com/api/v1/auth/corp/callback"
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


@dataclass(slots=True)
class Clock:
    at: datetime = NOW

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class Setup:
    issuer: FakeIssuer
    provider: OidcProvider
    clock: Clock


@pytest.fixture
async def setup() -> AsyncIterator[Setup]:
    clock = Clock()
    issuer = FakeIssuer(now=clock.now)
    issuer.add_user("u-1", "alice", email="alice@example.com", groups=["payments"])
    async with httpx2.AsyncClient(transport=issuer.transport()) as client:
        provider = OidcProvider(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret=lambda: CLIENT_SECRET,
            redirect_uri=REDIRECT,
            scopes=("openid", "profile", "email", "offline_access"),
            client=client,
            clock=clock,
        )
        yield Setup(issuer=issuer, provider=provider, clock=clock)


async def sign_in(setup: Setup, subject: str = "u-1", *, nonce: str = "n-1", **kw: Any) -> Any:
    verifier = kw.pop("verifier", "v" * 64)
    url = await setup.provider.authorization_url(state="s-1", nonce=nonce, code_verifier=verifier)
    callback = setup.issuer.authorize(url, subject)
    code = parse_qs(urlsplit(callback).query)["code"][0]
    return await setup.provider.exchange(
        code=code,
        code_verifier=kw.pop("exchange_verifier", verifier),
        nonce=kw.pop("expect", nonce),
    )


async def test_the_authorization_url_asks_for_a_code_with_pkce_s256(setup: Setup) -> None:
    verifier = "v" * 64
    url = await setup.provider.authorization_url(state="s", nonce="n", code_verifier=verifier)

    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f"{ISSUER}/authorize?")
    assert query == {
        "response_type": "code",
        "response_mode": "query",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "scope": "openid profile email offline_access",
        "state": "s",
        "nonce": "n",
        "code_challenge": query["code_challenge"],
        "code_challenge_method": "S256",
    }
    assert verifier not in url
    digest = hashlib.sha256(verifier.encode()).digest()  # base64url(sha256(verifier)), unpadded
    assert query["code_challenge"] == base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def test_a_sign_in_returns_the_validated_claims_and_the_refresh_token(setup: Setup) -> None:
    grant = await sign_in(setup)

    assert grant.claims.issuer == ISSUER
    assert grant.claims.subject == "u-1"
    assert grant.claims.username == "alice"
    assert grant.claims.email == "alice@example.com"
    assert grant.claims.groups == frozenset({"payments"})
    assert grant.refresh_token in setup.issuer.refresh_tokens
    [form] = setup.issuer.token_requests
    assert form["grant_type"] == "authorization_code"
    assert "client_secret" not in form  # client_secret_basic, as advertised


async def test_an_id_token_without_a_nonce_is_verified_for_the_mcp_proxy(setup: Setup) -> None:
    user = setup.issuer.users["u-1"]

    claims = await setup.provider.verify_id_token(setup.issuer.id_token(user, nonce=None))

    assert (claims.issuer, claims.subject, claims.username) == (ISSUER, "u-1", "alice")
    assert claims.groups == frozenset({"payments"})


async def test_a_forged_id_token_is_refused_for_the_mcp_proxy(setup: Setup) -> None:
    other = setup.issuer.users["u-1"]
    setup.issuer.tamper = tamper_claims(aud="someone-else")

    with pytest.raises(ExternalSignInFailedError):
        await setup.provider.verify_id_token(setup.issuer.id_token(other, nonce=None))


async def test_the_discovery_is_fetched_once_and_cached(setup: Setup) -> None:
    await sign_in(setup)
    await sign_in(setup)
    assert setup.issuer.discovery_fetches == 1
    assert setup.issuer.jwks_fetches == 1

    setup.clock.at += timedelta(hours=1)
    await sign_in(setup)
    assert setup.issuer.discovery_fetches == 2


async def test_a_wrong_pkce_verifier_is_refused_by_the_issuer(setup: Setup) -> None:
    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup, exchange_verifier="w" * 64)


def tamper_claims(**changes: Any) -> Callable[[dict[str, Any], dict[str, Any]], None]:
    def tamper(_: dict[str, Any], claims: dict[str, Any]) -> None:
        for name, value in changes.items():
            if value is None:
                claims.pop(name, None)
            else:
                claims[name] = value

    return tamper


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(tamper_claims(iss="https://evil.example.com"), id="wrong iss"),
        pytest.param(tamper_claims(aud="someone-else"), id="wrong aud"),
        pytest.param(tamper_claims(aud=["someone-else", "another"]), id="aud list without us"),
        pytest.param(tamper_claims(aud=[CLIENT_ID, "another"]), id="several aud, no azp"),
        pytest.param(
            tamper_claims(aud=[CLIENT_ID, "another"], azp="another"), id="several aud, azp other"
        ),
        pytest.param(tamper_claims(azp="another"), id="azp of another client"),
        pytest.param(tamper_claims(exp=int(NOW.timestamp()) - 61), id="expired"),
        pytest.param(tamper_claims(iat=int(NOW.timestamp()) + 61), id="iat in the future"),
        pytest.param(tamper_claims(nbf=int(NOW.timestamp()) + 61), id="not yet valid"),
        pytest.param(tamper_claims(exp=None), id="no exp"),
        pytest.param(tamper_claims(iat=None), id="no iat"),
        pytest.param(tamper_claims(sub=None), id="no sub"),
        pytest.param(tamper_claims(nonce=None), id="no nonce"),
        pytest.param(tamper_claims(nonce="another"), id="wrong nonce"),
        pytest.param(unsigned, id="alg none"),
        pytest.param(signed_by_stranger, id="signed by a key not in the JWKS"),
        pytest.param(lambda header, claims: f"{header}.{claims}", id="not a JWT"),
    ],
)
async def test_an_id_token_that_fails_a_check_is_refused(
    setup: Setup, tamper: Callable[[dict[str, Any], dict[str, Any]], str | None]
) -> None:
    setup.issuer.tamper = tamper

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)


def with_raw(name: str, raw: str) -> Callable[[dict[str, Any]], str]:
    """Render the claims as JSON with ``name``'s value written as ``raw``, unparsed."""

    def render(claims: dict[str, Any]) -> str:
        return json.dumps({**claims, name: "@RAW@"}).replace('"@RAW@"', raw)

    return render


IN_AN_HOUR = int(NOW.timestamp()) + 3600


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(with_raw("exp", "1e999"), id="exp infinite"),
        pytest.param(with_raw("exp", "Infinity"), id="exp Infinity"),
        pytest.param(with_raw("exp", "NaN"), id="exp NaN"),
        pytest.param(with_raw("exp", f"{IN_AN_HOUR}.5"), id="exp a float"),
        pytest.param(with_raw("exp", "true"), id="exp a boolean"),
        pytest.param(with_raw("exp", f'"{IN_AN_HOUR}"'), id="exp a string"),
        pytest.param(with_raw("iat", "true"), id="iat a boolean"),
        pytest.param(with_raw("iat", "-Infinity"), id="iat -Infinity"),
        pytest.param(with_raw("iat", "NaN"), id="iat NaN"),
        pytest.param(with_raw("nbf", "false"), id="nbf a boolean"),
        pytest.param(with_raw("nbf", "-1e999"), id="nbf minus infinite"),
        pytest.param(with_raw("nbf", "NaN"), id="nbf NaN"),
        pytest.param(lambda claims: json.dumps(list(claims.items())), id="payload pairs"),
        pytest.param(lambda claims: json.dumps([claims]), id="payload a list"),
        pytest.param(lambda _: '"a string"', id="payload a string"),
        pytest.param(lambda _: "null", id="payload null"),
    ],
)
async def test_a_signed_id_token_with_malformed_claims_is_refused(
    setup: Setup, render: Callable[[dict[str, Any]], str]
) -> None:
    """NumericDates must be integers and the payload an object, whatever joserfc accepts."""
    setup.issuer.tamper = signed_payload(setup.issuer, render)

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)


async def test_a_signed_payload_rendered_as_is_passes_when_well_formed(setup: Setup) -> None:
    """The raw signer above is not what makes those tokens fail."""
    setup.issuer.tamper = signed_payload(setup.issuer, json.dumps)

    assert (await sign_in(setup)).claims.subject == "u-1"


async def test_hs256_with_the_public_key_as_secret_is_refused(setup: Setup) -> None:
    setup.issuer.tamper = hs256_with_public_key(setup.issuer)

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)


async def test_hs256_is_refused_even_when_the_issuer_advertises_it(setup: Setup) -> None:
    setup.issuer.algorithms = ["HS256", "RS256"]
    setup.issuer.tamper = hs256_with_public_key(setup.issuer)

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)


async def test_an_issuer_with_only_symmetric_algorithms_is_not_used(setup: Setup) -> None:
    setup.issuer.algorithms = ["HS256", "none"]

    with pytest.raises(ProviderUnavailableError):
        await setup.provider.authorization_url(state="s", nonce="n", code_verifier="v" * 64)


async def test_the_times_allow_sixty_seconds_of_skew(setup: Setup) -> None:
    setup.issuer.tamper = tamper_claims(
        exp=int(NOW.timestamp()) - 59, iat=int(NOW.timestamp()) + 59
    )

    assert (await sign_in(setup)).claims.subject == "u-1"


async def test_several_audiences_pass_when_azp_is_this_client(setup: Setup) -> None:
    setup.issuer.tamper = tamper_claims(aud=[CLIENT_ID, "api"], azp=CLIENT_ID)

    assert (await sign_in(setup)).claims.subject == "u-1"


async def test_a_rotated_key_is_fetched_once_and_then_trusted(setup: Setup) -> None:
    await sign_in(setup)
    setup.clock.at += timedelta(minutes=1)
    setup.issuer.rotate_key()

    assert (await sign_in(setup)).claims.subject == "u-1"
    assert (await sign_in(setup)).claims.subject == "u-1"
    assert setup.issuer.jwks_fetches == 2


async def test_unknown_keys_fetch_the_jwks_at_most_once_a_minute(setup: Setup) -> None:
    await sign_in(setup)
    for _ in range(5):  # a storm of tokens naming keys nobody published, within the minute
        setup.issuer.tamper = made_up_kid
        with pytest.raises(ExternalSignInFailedError):
            await sign_in(setup)
    assert setup.issuer.jwks_fetches == 1

    setup.clock.at += timedelta(minutes=1)
    for _ in range(5):  # the next minute: one refetch, whatever the storm
        setup.issuer.tamper = made_up_kid
        with pytest.raises(ExternalSignInFailedError):
            await sign_in(setup)
    assert setup.issuer.jwks_fetches == 2

    setup.issuer.rotate_key()  # within that minute the new key is not fetched yet
    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)
    setup.clock.at += timedelta(minutes=1)
    assert (await sign_in(setup)).claims.subject == "u-1"
    assert setup.issuer.jwks_fetches == 3


def no_kid(header: dict[str, Any], _: dict[str, Any]) -> None:
    del header["kid"]


async def test_a_token_without_a_kid_is_checked_with_each_fitting_key(setup: Setup) -> None:
    """Several keys in the JWKS (a rollover): the one that verifies the token is used."""
    setup.issuer.rotate_key(keep_old=True)
    setup.issuer.tamper = no_kid

    assert (await sign_in(setup)).claims.subject == "u-1"
    assert setup.issuer.jwks_fetches == 1  # found among the cached keys, no refetch


async def test_a_token_without_a_kid_signed_by_the_older_key_is_accepted(setup: Setup) -> None:
    old = setup.issuer.key
    setup.issuer.rotate_key(keep_old=True)
    setup.issuer.tamper = lambda header, claims: jwt.encode(
        {k: v for k, v in header.items() if k != "kid"}, claims, old
    )

    assert (await sign_in(setup)).claims.subject == "u-1"


async def test_a_token_without_a_kid_that_no_key_verifies_is_refused(setup: Setup) -> None:
    setup.issuer.rotate_key(keep_old=True)
    await sign_in(setup)
    setup.clock.at += timedelta(minutes=1)
    stranger = RSAKey.generate_key(2048)
    setup.issuer.tamper = lambda _, claims: jwt.encode({"alg": "RS256"}, claims, stranger)

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)
    assert setup.issuer.jwks_fetches == 2  # one refetch, as for an unknown kid


def made_up_kid(header: dict[str, Any], _: dict[str, Any]) -> None:
    header["kid"] = "made-up"


async def test_a_discovery_naming_another_issuer_is_not_used(setup: Setup) -> None:
    setup.issuer.discovered_issuer = f"{ISSUER}/"

    with pytest.raises(ProviderUnavailableError):
        await sign_in(setup)


async def test_an_issuer_that_is_down_is_unavailable(setup: Setup) -> None:
    setup.issuer.down = True

    with pytest.raises(ProviderUnavailableError):
        await setup.provider.authorization_url(state="s", nonce="n", code_verifier="v" * 64)


async def test_groups_missing_from_the_id_token_come_from_userinfo(setup: Setup) -> None:
    setup.issuer.groups_in_id_token = False

    assert (await sign_in(setup)).claims.groups == frozenset({"payments"})


async def test_userinfo_of_another_subject_is_refused(setup: Setup) -> None:
    setup.issuer.groups_in_id_token = False
    setup.issuer.userinfo_subject = "u-2"

    with pytest.raises(ExternalSignInFailedError):
        await sign_in(setup)


async def test_a_dotted_groups_claim_reads_nested_claims(setup: Setup) -> None:
    setup.provider.claims = OidcClaimNames(groups="realm_access.roles", username="upn")
    setup.issuer.tamper = tamper_claims(realm_access={"roles": ["docs"]}, upn="alice@corp.example")
    setup.issuer.groups_in_id_token = True

    grant = await sign_in(setup)

    assert grant.claims.groups == frozenset({"docs"})
    assert grant.claims.username == "alice@corp.example"


async def test_a_single_group_as_text_is_one_group(setup: Setup) -> None:
    setup.provider.claims = OidcClaimNames(groups="group")  # ADFS sends one group as text
    setup.issuer.tamper = tamper_claims(group="docs-readers")

    assert (await sign_in(setup)).claims.groups == frozenset({"docs-readers"})


async def test_a_refresh_reads_the_current_groups(setup: Setup) -> None:
    grant = await sign_in(setup)
    setup.issuer.users["u-1"].groups = ["ops"]

    refreshed = await setup.provider.refresh(grant.refresh_token, subject="u-1")

    assert refreshed.claims.groups == frozenset({"ops"})
    assert refreshed.refresh_token == grant.refresh_token  # not rotated: the same one is kept


async def test_a_refresh_without_an_id_token_reads_userinfo(setup: Setup) -> None:
    grant = await sign_in(setup)
    setup.issuer.refresh_id_token = False
    setup.issuer.users["u-1"].groups = ["ops"]

    refreshed = await setup.provider.refresh(grant.refresh_token, subject="u-1")

    assert refreshed.claims.groups == frozenset({"ops"})


async def test_a_refresh_of_another_subject_is_refused(setup: Setup) -> None:
    grant = await sign_in(setup)

    with pytest.raises(ExternalSignInFailedError):
        await setup.provider.refresh(grant.refresh_token, subject="u-2")


async def test_a_revoked_refresh_token_is_refused_as_revoked(setup: Setup) -> None:
    grant = await sign_in(setup)
    setup.issuer.revoke_refresh_tokens("u-1")

    with pytest.raises(ProviderAccessRevokedError):
        await setup.provider.refresh(grant.refresh_token, subject="u-1")


async def test_a_refused_client_is_not_blamed_on_the_person(setup: Setup) -> None:
    grant = await sign_in(setup)
    setup.provider.client_secret = lambda: "rotated-without-telling-us"

    with pytest.raises(ProviderUnavailableError):
        await setup.provider.refresh(grant.refresh_token, subject="u-1")


async def test_a_refresh_while_the_issuer_is_down_is_unavailable(setup: Setup) -> None:
    grant = await sign_in(setup)
    setup.issuer.down = True

    with pytest.raises(ProviderUnavailableError):
        await setup.provider.refresh(grant.refresh_token, subject="u-1")


@pytest.mark.parametrize(
    ("url", "secure"),
    [
        ("https://idp.example.com", True),
        ("https://login.microsoftonline.com/tenant/v2.0", True),
        ("http://localhost:8080/realms/x", True),
        ("http://127.0.0.1:8080", True),
        ("http://[::1]:8080", True),
        ("http://idp.example.com", False),
        ("http://10.0.0.1", False),
        ("ftp://idp.example.com", False),
        ("https://", False),
    ],
)
def test_only_https_or_loopback_http_is_used(url: str, secure: bool) -> None:
    assert secure_url(url) is secure


@dataclass(slots=True)
class EndlessBody(httpx2.AsyncByteStream):
    """A body that never ends (no Content-Length), counting what was read and whether closed."""

    sent: int = 0
    closed: bool = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        chunk = b" " * 65536
        while True:
            self.sent += len(chunk)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class EndlessTransport(httpx2.AsyncBaseTransport):
    body: EndlessBody
    length: str | None = None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        headers = {"content-type": "application/json"}
        if self.length is not None:
            headers["content-length"] = self.length
        return httpx2.Response(200, headers=headers, stream=self.body, request=request)


@pytest.mark.parametrize("length", [None, str(MAX_PROVIDER_RESPONSE_BYTES + 1)])
async def test_an_answer_over_the_size_limit_is_refused_while_it_streams(
    length: str | None,
) -> None:
    body = EndlessBody()
    async with httpx2.AsyncClient(transport=EndlessTransport(body, length)) as client:
        provider = OidcProvider(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret=lambda: CLIENT_SECRET,
            redirect_uri=REDIRECT,
            scopes=("openid",),
            client=client,
            clock=Clock(),
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.authorization_url(state="s", nonce="n", code_verifier="v" * 64)

    # Never buffered whole: the read stops one chunk past the limit (or before any, when the
    # declared length is already over it), and the connection is closed.
    assert body.sent <= MAX_PROVIDER_RESPONSE_BYTES + 65536
    if length is not None:
        assert body.sent == 0
    assert body.closed


# ---------------------------------------------------------------- multi-tenant issuers

TENANT = "11111111-2222-3333-4444-555555555555"
OTHER_TENANT = "99999999-8888-7777-6666-555555555555"
TEMPLATE = f"{ISSUER}/{{tenantid}}/v2.0"


@pytest.fixture
async def tenants() -> AsyncIterator[Setup]:
    clock = Clock()
    issuer = FakeIssuer(now=clock.now, discovered_issuer=TEMPLATE, token_issuer=TEMPLATE)
    issuer.add_user("u-1", "alice@contoso.com", tenant=TENANT)
    issuer.add_user("u-2", "bob@fabrikam.com", tenant=OTHER_TENANT)
    async with httpx2.AsyncClient(transport=issuer.transport()) as client:
        provider = OidcProvider(
            issuer=TEMPLATE,
            discovery_url=f"{ISSUER}/.well-known/openid-configuration",
            client_id=CLIENT_ID,
            client_secret=lambda: CLIENT_SECRET,
            redirect_uri=REDIRECT,
            scopes=("openid", "profile", "email", "offline_access"),
            client=client,
            clock=clock,
        )
        yield Setup(issuer=issuer, provider=provider, clock=clock)


async def test_a_multi_tenant_issuer_names_each_persons_tenant(tenants: Setup) -> None:
    alice = await sign_in(tenants, "u-1")
    bob = await sign_in(tenants, "u-2")

    assert alice.claims.issuer == f"{ISSUER}/{TENANT}/v2.0"
    assert bob.claims.issuer == f"{ISSUER}/{OTHER_TENANT}/v2.0"
    assert tenants.issuer.discovery_fetches == 1


async def test_a_token_whose_issuer_is_not_its_tenants_is_refused(tenants: Setup) -> None:
    def other_tid(_: dict[str, Any], claims: dict[str, Any]) -> None:
        claims["tid"] = OTHER_TENANT  # iss still names TENANT

    tenants.issuer.tamper = other_tid
    with pytest.raises(ExternalSignInFailedError):
        await sign_in(tenants, "u-1")


@pytest.mark.parametrize("tid", [None, "contoso.onmicrosoft.com", "../evil", 7])
async def test_a_multi_tenant_token_without_a_tenant_id_is_refused(
    tenants: Setup, tid: object
) -> None:
    def set_tid(_: dict[str, Any], claims: dict[str, Any]) -> None:
        claims["iss"] = TEMPLATE.replace("{tenantid}", str(tid))
        if tid is None:
            claims.pop("tid", None)
        else:
            claims["tid"] = tid

    tenants.issuer.tamper = set_tid
    with pytest.raises(ExternalSignInFailedError):
        await sign_in(tenants, "u-1")


async def test_a_multi_tenant_refresh_needs_an_id_token(tenants: Setup) -> None:
    grant = await sign_in(tenants, "u-1")
    again = await tenants.provider.refresh(grant.refresh_token, subject="u-1")
    assert again.claims.issuer == f"{ISSUER}/{TENANT}/v2.0"

    tenants.issuer.refresh_id_token = False  # userinfo names no tenant
    with pytest.raises(ProviderUnavailableError):
        await tenants.provider.refresh(grant.refresh_token, subject="u-1")


async def test_extra_authorization_params_never_replace_the_flows_own(setup: Setup) -> None:
    provider = setup.provider
    provider.authorization_params = {"access_type": "offline", "state": "forged"}

    url = await provider.authorization_url(state="s-1", nonce="n-1", code_verifier="v" * 64)

    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert (query["access_type"], query["state"]) == ("offline", "s-1")
