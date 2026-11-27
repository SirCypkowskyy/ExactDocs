"""Opaque OAuth2 token verification and refresh against a scripted issuer."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from exactdocs.identity.adapters.driven.oauth2 import OAuth2ClaimNames, OAuth2Provider
from exactdocs.identity.errors import (
    ExternalSignInFailedError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
)


def provider(
    client: httpx2.AsyncClient, *, claims: OAuth2ClaimNames | None = None
) -> OAuth2Provider:
    return OAuth2Provider(
        issuer="https://idp.example.com:8443",
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        userinfo_endpoint="https://idp.example.com/userinfo",
        client_id="exactdocs",
        client_secret=lambda: "secret",
        redirect_uri="https://docs.example.com/callback",
        scopes=("offline_access",),
        client=client,
        claims=claims or OAuth2ClaimNames(),
    )


async def test_authorization_is_bound_with_state_and_s256() -> None:
    async with httpx2.AsyncClient() as client:
        query = parse_qs(
            urlsplit(
                await provider(client).authorization_url(
                    state="state", nonce="nonce", code_verifier="v" * 64
                )
            ).query
        )
    assert query["state"] == ["state"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["offline_access"]
    assert "code_verifier" not in query


async def test_exchange_maps_nested_subject_groups_and_seals_only_refresh_credential() -> None:
    requests = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/token":
            assert "code_verifier=v" in request.content.decode()
            return httpx2.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        assert request.headers["authorization"] == "Bearer access"
        return httpx2.Response(
            200, json={"person": {"id": "123", "name": "alice", "roles": ["payments"]}}
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        grant = await provider(
            client,
            claims=OAuth2ClaimNames(
                subject="person.id", username="person.name", groups="person.roles"
            ),
        ).exchange(code="code", code_verifier="v", nonce="n")
    assert grant.claims.subject == "123"
    assert grant.claims.username == "alice"
    assert grant.claims.groups == {"payments"}
    assert grant.claims.issuer == "https://idp.example.com:8443"
    assert grant.refresh_token == "refresh"
    assert len(requests) == 2


@pytest.mark.parametrize("subject", [None, "", 123, True, [], {}])
async def test_invalid_subject_is_refused(subject: object) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"sub": subject}))
    ) as client:
        with pytest.raises(ExternalSignInFailedError):
            await provider(client).verify_id_token("access")


async def test_refresh_rejects_substitution_and_preserves_rotating_refresh_token() -> None:
    subject = "123"

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/token":
            return httpx2.Response(200, json={"access_token": "access", "refresh_token": "rotated"})
        return httpx2.Response(200, json={"sub": subject})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        assert (await provider(client).refresh("old", subject="123")).refresh_token == "rotated"
        subject = "456"
        with pytest.raises(ExternalSignInFailedError):
            await provider(client).refresh("old", subject="123")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (400, {"error": "invalid_grant"}, ProviderAccessRevokedError),
        (401, {"error": "invalid_client"}, ProviderUnavailableError),
        (503, {}, ProviderUnavailableError),
    ],
)
async def test_refresh_error_classification(
    status: int, body: dict, error: type[Exception]
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(status, json=body))
    ) as client:
        with pytest.raises(error):
            await provider(client).refresh("old", subject="123")


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_opaque_token_revokes_access(status: int) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(status, json={}))
    ) as client:
        with pytest.raises(ProviderAccessRevokedError):
            await provider(client).verify_id_token("access")


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json=[]),
        httpx2.Response(302, headers={"location": "https://evil.example"}),
        httpx2.Response(200, content=b"x" * 1_100_000),
    ],
)
async def test_unusable_userinfo_fails_closed(response: httpx2.Response) -> None:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: response)) as client:
        with pytest.raises(ProviderUnavailableError):
            await provider(client).verify_id_token("access")


async def test_a_role_claim_is_read_from_userinfo_beside_the_groups() -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/token":
            return httpx2.Response(200, json={"access_token": "access"})
        return httpx2.Response(
            200, json={"sub": "1", "groups": ["staff"], "app": {"roles": "ExactDocs.Admin"}}
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        grant = await provider(client, claims=OAuth2ClaimNames(roles="app.roles")).exchange(
            code="code", code_verifier="v", nonce="n"
        )
        plain = await provider(client).verify_id_token("access")

    assert grant.claims.roles == {"ExactDocs.Admin"}
    assert grant.claims.groups == {"staff"}
    assert plain.roles == frozenset()
