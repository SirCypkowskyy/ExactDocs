"""MCP over OAuth: a web host signs a person in through the chosen provider; API tokens still work.

The identity provider is the fake issuer; the OAuth flow is FastMCP's proxy, driven the way a
web host drives it (``mcp_oauth_host``).
"""

import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
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


@dataclass(frozen=True, slots=True)
class Instance:
    client: TestClient
    issuer: FakeIssuer
    container: Container


def running(**settings: Any) -> Iterator[Instance]:
    issuer = FakeIssuer()
    issuer.add_user("u-1", "alice", groups=["docs"])
    issuer.add_user("u-2", "bob", groups=["other"])
    with tempfile.TemporaryDirectory(prefix="exactdocs-") as data_dir, fake_issuer(issuer):
        container = Container.build(
            Settings(
                data_dir=Path(data_dir),
                public_url=PUBLIC,
                auth={"providers": {"corp": provider()}},
                **settings,
            ),
            sign_in=SignInStandIns(transport=issuer.transport()),
        )
        with TestClient(create_app(container), base_url=PUBLIC) as client:
            yield Instance(client=client, issuer=issuer, container=container)


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
