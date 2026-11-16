"""Only verified, request-local OAuth identities may supplement library role resolution."""

import asyncio

import pytest
from fastmcp.server.auth import AccessToken

from exactdocs.bootstrap import caller
from exactdocs.identity.adapters.driving.mcp import ApiTokenVerifier
from exactdocs.identity.dtos import AccountSummary, ExternalTokenIdentity


def identity(account_id: str = "corp:u-1") -> ExternalTokenIdentity:
    return ExternalTokenIdentity(
        account=AccountSummary(id=account_id, username="alice", role="admin"),
        groups=frozenset({"docs"}),
        linked=False,
    )


@pytest.mark.parametrize("as_json", [False, True])
def test_only_the_verifiers_typed_object_is_a_trusted_oauth_identity(
    monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    principal = identity()
    token = AccessToken(
        token="",
        client_id=principal.account.id,
        scopes=[],
        claims={"external_identity": principal.model_dump(mode="json") if as_json else principal},
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_external_identity() == (None if as_json else principal)


def test_an_external_identity_cannot_claim_another_token_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="", client_id="another-account", scopes=[], claims={"external_identity": identity()}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_external_identity() is None


async def test_a_bound_rest_caller_cannot_inherit_another_oauth_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="", client_id="corp:u-1", scopes=[], claims={"external_identity": identity()}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)

    async def request() -> None:
        caller.bind_caller("another-account")
        assert caller.current_external_identity() is None

    await asyncio.create_task(request())


async def test_api_token_verification_does_not_turn_json_claims_into_an_oauth_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def identify(token: str) -> AccountSummary:
        assert "external_identity" in token
        return AccountSummary(id="api-account", username="alice", role="user")

    token = await ApiTokenVerifier(identify_token=identify).verify_token(
        '{"external_identity":{"account":{"id":"api-account","role":"admin"},"groups":["docs"]}}'
    )
    assert token is not None
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_external_identity() is None


def test_multiauth_preserves_the_original_account_for_library_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="",
        client_id='["trust-source","corp:u-1"]',
        original_client_id="corp:u-1",
        scopes=[],
        claims={"external_identity": identity()},
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_account_id() == "corp:u-1"
    assert caller.current_external_identity() == identity()


def test_json_claims_cannot_replace_the_original_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="", client_id="api-account", scopes=[], claims={"original_client_id": "ada"}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_account_id() == "api-account"
