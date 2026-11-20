"""Only verified, request-local OAuth identities may supplement library role resolution."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI, Request
from fastmcp.server.auth import AccessToken

from exactdocs.bootstrap import caller
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import _protected_router
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driving.mcp import ApiTokenVerifier
from exactdocs.identity.dtos import AccountSummary, ApiTokenIdentity, ExternalTokenIdentity


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
    async def identify(token: str) -> ApiTokenIdentity:
        assert "external_identity" in token
        return ApiTokenIdentity(id="api-account", username="alice", role="user", token_id="api")

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


@pytest.mark.parametrize("as_json", [False, True])
def test_api_scope_only_accepts_the_verified_typed_principal(
    monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    principal = ApiTokenIdentity(
        id="api-account", username="bob", role="admin", token_id="a", library_ids={"/acme/docs"}
    )
    token = AccessToken(
        token="",
        client_id=principal.id,
        scopes=[],
        claims={"api_identity": principal.model_dump(mode="json") if as_json else principal},
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_api_identity() == (None if as_json else principal)


async def test_a_bound_rest_session_cannot_inherit_same_account_mcp_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = AccessToken(
        token="", client_id="corp:u-1", scopes=[], claims={"external_identity": identity()}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)

    async def request() -> None:
        caller.bind_caller("corp:u-1")
        assert caller.current_external_identity() is None
        assert caller.current_api_identity() is None

    await asyncio.create_task(request())


@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "concurrent"])
async def test_protected_asgi_requests_restore_parent_caller_context(outcome: str) -> None:

    container = Container.build(Settings())
    principal = ApiTokenIdentity(
        id="api", username="api", role="user", token_id="selected", library_ids=set()
    )

    async def authenticate(request: Request) -> AccountSummary:
        return (
            principal
            if request.headers.get("authorization")
            else AccountSummary(id="session", username="session", role="user")
        )

    router = _protected_router(container, authenticate)
    entered = asyncio.Event()
    release = asyncio.Event()

    @router.get("/inspect")
    async def inspect(request: Request) -> dict[str, str | None]:
        if request.query_params.get("wait"):
            entered.set()
            await release.wait()
        if outcome == "error":
            message = "endpoint failed"
            raise RuntimeError(message)
        api_identity = caller.current_api_identity()
        return {
            "account": caller.current_account_id(),
            "token": None if api_identity is None else api_identity.token_id,
        }

    app = FastAPI()
    app.include_router(router)
    binding = caller.bind_caller("parent")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            if outcome in {"cancel", "concurrent"}:

                async def scoped_request() -> httpx.Response:
                    try:
                        return await client.get(
                            "/inspect?wait=1", headers={"authorization": "Bearer token"}
                        )
                    finally:
                        assert caller.current_account_id() == "parent"
                        assert caller.current_api_identity() is None

                task = asyncio.create_task(scoped_request())
                await asyncio.wait_for(entered.wait(), 5)
                assert (await client.get("/inspect")).json() == {
                    "account": "session",
                    "token": None,
                }
                if outcome == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    assert (await asyncio.wait_for(task, 5)).json() == {
                        "account": "api",
                        "token": "selected",
                    }
            elif outcome == "error":
                with pytest.raises(RuntimeError, match="endpoint failed"):
                    await client.get("/inspect", headers={"authorization": "Bearer token"})
            else:
                first = await client.get("/inspect", headers={"authorization": "Bearer token"})
                assert first.json() == {"account": "api", "token": "selected"}
                assert (await client.get("/inspect")).json() == {
                    "account": "session",
                    "token": None,
                }
            assert caller.current_account_id() == "parent"
            assert caller.current_api_identity() is None
    finally:
        caller.reset_caller(binding)
        await container.engine.dispose()


def test_api_scope_cannot_claim_another_account(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = ApiTokenIdentity(
        id="other", username="other", role="admin", token_id="other", library_ids=set()
    )
    token = AccessToken(
        token="", client_id="account", scopes=[], claims={"api_identity": principal}
    )
    monkeypatch.setattr(caller, "get_access_token", lambda: token)
    assert caller.current_api_identity() is None
