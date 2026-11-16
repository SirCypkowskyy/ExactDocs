"""MCP over OAuth: a web host signs a person in through the chosen provider; API tokens still work.

The identity provider is the fake issuer; the OAuth flow is FastMCP's proxy, driven the way a
web host drives it (``mcp_oauth_host``).
"""

import asyncio
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp_oauth import _storage
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.catalog.dtos import CreateLibraryCommand
from exactdocs.identity.dtos import SetUserDisabledCommand
from fake_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIssuer
from mcp_oauth_host import call_tool, connect, fake_issuer, tool_result

PUBLIC = "http://localhost"


def provider(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "oidc",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "allowed_groups": ["docs"],
        **overrides,
    }


@dataclass(slots=True)
class Clock:
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.at


@dataclass(frozen=True, slots=True)
class Instance:
    client: TestClient
    issuer: FakeIssuer
    container: Container
    clock: Clock


def running(
    *, provider_overrides: dict[str, Any] | None = None, **settings: Any
) -> Iterator[Instance]:
    clock = Clock()
    issuer = FakeIssuer(now=clock.now)
    issuer.add_user("u-1", "alice", groups=["docs"])
    issuer.add_user("u-2", "bob", groups=["other"])
    with tempfile.TemporaryDirectory(prefix="exactdocs-") as data_dir, fake_issuer(issuer):
        container = Container.build(
            Settings(
                data_dir=Path(data_dir),
                public_url=PUBLIC,
                auth={"providers": {"corp": provider(**(provider_overrides or {}))}},
                **settings,
            ),
            sign_in=SignInStandIns(clock=clock, transport=issuer.transport()),
        )
        with TestClient(create_app(container), base_url=PUBLIC) as client:
            yield Instance(client=client, issuer=issuer, container=container, clock=clock)


@pytest.fixture
def oauth() -> Iterator[Instance]:
    yield from running(mcp_oauth_provider="corp")


def test_a_host_discovers_the_metadata_at_the_root(oauth: Instance) -> None:
    server = oauth.client.get("/.well-known/oauth-authorization-server")
    resource = oauth.client.get("/.well-known/oauth-protected-resource/mcp")

    assert server.status_code == resource.status_code == 200
    metadata = server.json()
    assert metadata["issuer"].rstrip("/") == PUBLIC
    assert metadata["registration_endpoint"] == f"{PUBLIC}/register"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert resource.json()["authorization_servers"] == [f"{PUBLIC}/"] or resource.json()[
        "authorization_servers"
    ] == [PUBLIC]


def test_a_host_signs_the_person_in_and_calls_a_tool_as_them(oauth: Instance) -> None:
    granted = connect(oauth.client, oauth.issuer, "u-1")

    assert granted.status_code == 200, granted.text
    answer = call_tool(oauth.client, granted.json()["access_token"], "list_libraries")
    assert answer.status_code == 200, answer.text
    assert tool_result(answer)["isError"] is False


def test_a_person_outside_the_allowed_groups_gets_no_working_token(oauth: Instance) -> None:
    granted = connect(oauth.client, oauth.issuer, "u-2")

    # The host is handed a token (the provider signed bob in), but no call works with it.
    token = granted.json()["access_token"]
    assert call_tool(oauth.client, token, "list_libraries").status_code == 401


def sign_alice_in_to_the_web_ui(oauth: Instance) -> None:
    """The web sign-in creates alice's account and links her identity to it."""
    setup = oauth.client.post(
        "/api/v1/setup", json={"username": "ada", "password": "correct horse battery staple"}
    )
    assert setup.status_code == 201, setup.text
    begun = oauth.client.get("/api/v1/auth/corp/start", follow_redirects=False)
    assert begun.status_code == 303, begun.text
    callback = oauth.issuer.authorize(begun.headers["location"], "u-1")
    assert oauth.client.get(callback, follow_redirects=False).status_code == 303
    oauth.client.cookies.clear()


def refresh(oauth: Instance, granted: httpx2.Response) -> str:
    """Trade the host's refresh token for a new access token, as the host does when told 401."""
    client_id = parse_qs(granted.request.content.decode())["client_id"][0]
    renewed = oauth.client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": granted.json()["refresh_token"],
            "client_id": client_id,
        },
    )
    assert renewed.status_code == 200, renewed.text
    return renewed.json()["access_token"]


def test_a_disabled_account_gets_a_401_at_the_next_call_with_the_same_token(
    oauth: Instance,
) -> None:
    sign_alice_in_to_the_web_ui(oauth)
    token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    assert call_tool(oauth.client, token, "list_libraries").status_code == 200

    assert oauth.client.portal is not None
    oauth.client.portal.call(
        oauth.container.identity.set_user_disabled,
        SetUserDisabledCommand(username="alice", disabled=True),
    )

    assert call_tool(oauth.client, token, "list_libraries").status_code == 401


def test_a_group_change_at_the_provider_is_seen_only_when_the_id_token_is_renewed(
    oauth: Instance,
) -> None:
    granted = connect(oauth.client, oauth.issuer, "u-1")
    token = granted.json()["access_token"]
    oauth.issuer.add_user("u-1", "alice", groups=["other"])  # alice leaves the group

    # The ID token the proxy holds still says "docs": nothing changes until it is renewed.
    assert call_tool(oauth.client, token, "list_libraries").status_code == 200

    oauth.clock.at += timedelta(minutes=10)  # the ID token (5 minutes in the fake) has expired
    assert call_tool(oauth.client, token, "list_libraries").status_code == 401

    # The host renews with its refresh token; the provider now says "other": no working token.
    renewed = refresh(oauth, granted)
    assert call_tool(oauth.client, renewed, "list_libraries").status_code == 401


def test_a_host_recovers_from_an_expired_id_token_with_its_refresh_token(oauth: Instance) -> None:
    granted = connect(oauth.client, oauth.issuer, "u-1")
    oauth.clock.at += timedelta(minutes=10)
    assert (
        call_tool(oauth.client, granted.json()["access_token"], "list_libraries").status_code == 401
    )

    renewed = refresh(oauth, granted)

    answer = call_tool(oauth.client, renewed, "list_libraries")
    assert answer.status_code == 200, answer.text


def test_api_tokens_keep_working_next_to_oauth(oauth: Instance) -> None:
    password = "correct horse battery staple"
    setup = oauth.client.post("/api/v1/setup", json={"username": "ada", "password": password})
    assert setup.status_code == 201, setup.text
    login = oauth.client.post("/api/v1/session", json={"username": "ada", "password": password})
    assert login.status_code == 201, login.text
    created = oauth.client.post("/api/v1/tokens", json={"name": "cli"})
    assert created.status_code == 201, created.text
    oauth.client.cookies.clear()

    answer = call_tool(oauth.client, created.json()["token"], "list_libraries")

    assert answer.status_code == 200, answer.text
    assert tool_result(answer)["isError"] is False


def test_without_a_credential_the_endpoint_answers_401_and_names_the_metadata(
    oauth: Instance,
) -> None:
    answer = call_tool(oauth.client, None, "list_libraries")

    assert answer.status_code == 401
    assert "oauth-protected-resource" in answer.headers["www-authenticate"]


def test_a_garbage_bearer_token_is_refused(oauth: Instance) -> None:
    assert call_tool(oauth.client, "not-a-token", "list_libraries").status_code == 401


def test_the_host_allowlist_still_applies_to_the_oauth_routes(oauth: Instance) -> None:
    answer = oauth.client.get(
        "/.well-known/oauth-authorization-server", headers={"host": "evil.example.net"}
    )

    assert answer.status_code in {400, 403, 421}


def test_the_oauth_state_lives_under_the_data_directory(oauth: Instance) -> None:
    connect(oauth.client, oauth.issuer, "u-1")

    stored = list((oauth.container.settings.data_dir / "mcp-oauth").rglob("*"))
    assert stored


def test_without_a_chosen_provider_there_is_no_oauth() -> None:
    for instance in running():
        assert instance.client.get("/.well-known/oauth-authorization-server").status_code == 404
        assert call_tool(instance.client, None, "list_libraries").status_code == 401


def test_the_chosen_provider_must_be_configured() -> None:
    with pytest.raises(ValueError, match="not a configured sign-in provider"):
        Settings(public_url=PUBLIC, mcp_oauth_provider="nope")


def test_the_chosen_provider_needs_a_client_secret() -> None:
    with pytest.raises(ValueError, match="needs a client secret"):
        Settings(
            public_url=PUBLIC,
            auth={"providers": {"corp": provider(client_secret=None)}},
            mcp_oauth_provider="corp",
        )


def test_a_rotated_client_secret_removes_the_state_kept_under_the_old_one() -> None:
    with tempfile.TemporaryDirectory(prefix="exactdocs-") as data_dir:
        root = Path(data_dir) / "mcp-oauth"
        first = _storage(root, "first-secret-first-secret")
        second = _storage(root, "second-secret-second-secret")

        assert first is not None
        assert second is not None
        assert len(list(root.iterdir())) == 1


def shared_library(oauth: Instance, group: str = "docs") -> None:
    client = oauth.client
    assert (
        client.post(
            "/api/v1/setup", json={"username": "ada", "password": "correct horse battery staple"}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/session", json={"username": "ada", "password": "correct horse battery staple"}
        ).status_code
        == 201
    )
    assert client.portal is not None
    client.portal.call(
        oauth.container.catalog.create_library,
        CreateLibraryCommand(
            id="/acme/docs",
            title="Docs",
            source_url="https://example.com/acme/docs.git",
            default_branch="main",
            host="git",
        ),
    )
    granted = client.put(
        "/api/v1/libraries/acme/docs/grants",
        json={"kind": "group", "subject": group, "role": "viewer"},
    )
    assert granted.status_code == 200, granted.text
    client.cookies.clear()


def listed_libraries(oauth: Instance, token: str) -> list[str]:
    response = call_tool(oauth.client, token, "list_libraries")
    assert response.status_code == 200, response.text
    result = tool_result(response)
    assert result["isError"] is False, result
    return [item["id"] for item in result["structuredContent"]["libraries"]]


def test_an_oauth_only_member_reads_libraries_shared_with_their_group(oauth: Instance) -> None:
    shared_library(oauth)
    token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    assert listed_libraries(oauth, token) == ["/acme/docs"]


def test_an_oauth_only_operator_reads_libraries_without_a_group_grant() -> None:
    for oauth in running(
        mcp_oauth_provider="corp", provider_overrides={"admin_groups": ["exactdocs-admins"]}
    ):
        shared_library(oauth, group="other")
        oauth.issuer.add_user("u-1", "alice", groups=["docs", "exactdocs-admins"])
        token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
        assert listed_libraries(oauth, token) == ["/acme/docs"]


def test_an_admitted_oauth_user_without_a_library_role_cannot_read_it(oauth: Instance) -> None:
    shared_library(oauth, group="other")
    token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    assert listed_libraries(oauth, token) == []


def test_a_linked_oauth_caller_uses_the_current_token_groups_not_web_groups(
    oauth: Instance,
) -> None:
    shared_library(oauth, group="readers")
    begun = oauth.client.get("/api/v1/auth/corp/start", follow_redirects=False)
    callback = oauth.issuer.authorize(begun.headers["location"], "u-1")
    assert oauth.client.get(callback, follow_redirects=False).status_code == 303
    oauth.client.cookies.clear()
    oauth.issuer.add_user("u-1", "alice", groups=["docs", "readers"])
    token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    assert listed_libraries(oauth, token) == ["/acme/docs"]
    oauth.issuer.add_user("u-1", "alice", groups=["docs"])
    token = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    assert listed_libraries(oauth, token) == []


def test_concurrent_oauth_requests_keep_their_own_group_memberships(oauth: Instance) -> None:
    shared_library(oauth, group="readers")
    oauth.issuer.add_user("u-1", "alice", groups=["docs", "readers"])
    oauth.issuer.add_user("u-2", "bob", groups=["docs"])
    alice = connect(oauth.client, oauth.issuer, "u-1").json()["access_token"]
    bob = connect(oauth.client, oauth.issuer, "u-2").json()["access_token"]

    async def simultaneous() -> list[list[str]]:
        return list(
            await asyncio.gather(
                asyncio.to_thread(listed_libraries, oauth, alice),
                asyncio.to_thread(listed_libraries, oauth, bob),
            )
        )

    assert asyncio.run(simultaneous()) == [["/acme/docs"], []]


def test_an_api_token_operator_keeps_library_access_when_oauth_is_enabled(oauth: Instance) -> None:
    shared_library(oauth, group="other")
    client = oauth.client
    assert (
        client.post(
            "/api/v1/session", json={"username": "ada", "password": "correct horse battery staple"}
        ).status_code
        == 201
    )
    created = client.post("/api/v1/tokens", json={"name": "cli"})
    assert created.status_code == 201, created.text
    client.cookies.clear()
    assert listed_libraries(oauth, created.json()["token"]) == ["/acme/docs"]


def test_a_linked_oauth_caller_keeps_grants_to_their_web_account(oauth: Instance) -> None:
    shared_library(oauth, group="other")
    client = oauth.client
    begun = client.get("/api/v1/auth/corp/start", follow_redirects=False)
    callback = oauth.issuer.authorize(begun.headers["location"], "u-1")
    assert client.get(callback, follow_redirects=False).status_code == 303
    assert (
        client.post(
            "/api/v1/session", json={"username": "ada", "password": "correct horse battery staple"}
        ).status_code
        == 201
    )
    granted = client.put(
        "/api/v1/libraries/acme/docs/grants",
        json={"kind": "user", "subject": "alice", "role": "viewer"},
    )
    assert granted.status_code == 200, granted.text
    client.cookies.clear()
    token = connect(client, oauth.issuer, "u-1").json()["access_token"]
    assert listed_libraries(oauth, token) == ["/acme/docs"]
