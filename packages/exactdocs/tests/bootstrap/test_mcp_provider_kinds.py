"""Full OAuthProxy host flows for opaque OAuth2 and GitHub Enterprise tokens."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import SignInStandIns
from exactdocs.catalog.dtos import CreateLibraryCommand
from exactdocs.identity.dtos import SetUserDisabledCommand
from fake_github import FakeGithub
from fake_oauth2 import FakeOAuth2
from fake_oidc import CLIENT_ID, CLIENT_SECRET
from mcp_oauth_host import call_tool, connect, fake_issuer, tool_result


@contextmanager
def running(tmp_path: Path, fake, config: dict[str, Any]):
    with fake_issuer(fake, oidc=False):
        container = Container.build(
            Settings(
                data_dir=tmp_path,
                public_url="http://localhost",
                mcp_oauth_provider="corp",
                auth={
                    "providers": {
                        "corp": {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **config}
                    }
                },
            ),
            sign_in=SignInStandIns(transport=fake.transport()),
        )
        with TestClient(create_app(container), base_url="http://localhost") as client:
            yield client, container


def test_generic_oauth2_host_uses_userinfo_and_lost_group_is_refused(tmp_path: Path) -> None:
    fake = FakeOAuth2()
    fake.add_user("123", "alice", groups=["docs"])
    config = {
        "kind": "oauth2",
        "authorization_url": f"{fake.issuer}/authorize",
        "token_url": f"{fake.issuer}/token",
        "userinfo_url": f"{fake.issuer}/userinfo",
        "allowed_groups": ["docs"],
    }
    with running(tmp_path, fake, config) as (client, _):
        token = connect(client, fake, "123", scope="offline_access")
        assert token.status_code == 200, token.text
        bearer = token.json()["access_token"]
        assert not tool_result(call_tool(client, bearer, "list_libraries")).get("isError")
        fake.users["123"].groups.clear()
        assert call_tool(client, bearer, "list_libraries").status_code == 401


@pytest.mark.parametrize(
    ("base", "override", "api"),
    [
        ("https://github.com", None, "https://api.github.com"),
        ("https://github.example.com", None, "https://github.example.com/api/v3"),
        ("https://acme.ghe.com", None, "https://api.acme.ghe.com"),
        (
            "https://github.example.com",
            "https://custom.example.com/api",
            "https://custom.example.com/api",
        ),
    ],
)
def test_github_host_and_per_request_membership(
    tmp_path: Path, base: str, override: str | None, api: str
) -> None:
    fake = FakeGithub(issuer=base, api_url=api)
    fake.add_user("123", "alice")
    config = {"kind": "github", "base_url": base, "allowed_teams": ["acme/docs-readers"]}
    if override:
        config["api_url"] = override
    with running(tmp_path, fake, config) as (client, _):
        token = connect(client, fake, "123", scope="read:user read:org")
        assert token.status_code == 200, token.text
        bearer = token.json()["access_token"]
        assert not tool_result(call_tool(client, bearer, "list_libraries")).get("isError")
        fake.teams.clear()
        assert call_tool(client, bearer, "list_libraries").status_code == 401


@pytest.mark.parametrize("restriction", ["app", "sso", "team"])
def test_ghe_membership_refusal_never_opens_a_tool(tmp_path: Path, restriction: str) -> None:
    fake = FakeGithub(issuer="https://github.example.com")
    fake.add_user("123", "bob")
    if restriction == "team":
        fake.teams.clear()
    else:
        fake.restricted = restriction
    with running(
        tmp_path,
        fake,
        {"kind": "github", "base_url": fake.issuer, "allowed_teams": ["acme/docs-readers"]},
    ) as (client, _):
        token = connect(client, fake, "123", scope="read:user read:org")
        # A credential received before the first resource check must never open a tool.
        bearer = token.json().get("access_token") if token.status_code == 200 else None
        assert call_tool(client, bearer, "list_libraries").status_code == 401


@pytest.mark.parametrize("kind", ["oauth2", "github"])
def test_opaque_linked_identity_keeps_user_grants_and_api_tokens(tmp_path: Path, kind: str) -> None:
    fake = FakeGithub() if kind == "github" else FakeOAuth2()
    fake.add_user("123", "alice", groups=["docs"])
    config = (
        {"kind": kind, "base_url": fake.issuer, "allowed_teams": ["acme/docs-readers"]}
        if kind == "github"
        else {
            "kind": kind,
            "authorization_url": f"{fake.issuer}/authorize",
            "token_url": f"{fake.issuer}/token",
            "userinfo_url": f"{fake.issuer}/userinfo",
            "allowed_groups": ["docs"],
        }
    )
    with running(tmp_path, fake, config) as (client, container):
        admin = {"username": "ada", "password": "correct horse battery staple"}
        assert client.post("/api/v1/setup", json=admin).status_code == 201
        started = client.get("/api/v1/auth/corp/start", follow_redirects=False)
        callback = fake.authorize(started.headers["location"], "123")
        assert client.get(callback, follow_redirects=False).status_code == 303
        assert client.post("/api/v1/session", json=admin).status_code == 201
        api = client.post("/api/v1/tokens", json={"name": "cli"}).json()["token"]
        assert client.portal is not None
        client.portal.call(
            container.catalog.create_library,
            CreateLibraryCommand(
                id="/acme/docs",
                title="Docs",
                source_url="https://example.com/docs.git",
                default_branch="main",
                host="git",
            ),
        )
        granted = client.put(
            "/api/v1/libraries/acme/docs/grants",
            json={"kind": "user", "subject": "alice", "role": "viewer"},
        )
        assert granted.status_code == 200, granted.text
        scope = "read:user read:org" if kind == "github" else "offline_access"
        bearer = connect(client, fake, "123", scope=scope).json()["access_token"]
        for credential in (api, bearer):
            result = tool_result(call_tool(client, credential, "list_libraries"))
            assert [item["id"] for item in result["structuredContent"]["libraries"]] == [
                "/acme/docs"
            ]
        client.portal.call(
            container.identity.set_user_disabled,
            SetUserDisabledCommand(username="alice", disabled=True),
        )
        assert call_tool(client, bearer, "list_libraries").status_code == 401
        assert call_tool(client, api, "list_libraries").status_code == 200


@pytest.mark.parametrize("kind", ["oauth2", "github"])
def test_token_library_scopes_and_opaque_oauth_callers_stay_apart(
    tmp_path: Path, kind: str
) -> None:
    fake = FakeGithub() if kind == "github" else FakeOAuth2()
    fake.add_user("123", "alice", groups=["docs"])
    config = (
        {"kind": kind, "base_url": fake.issuer, "allowed_teams": ["acme/docs-readers"]}
        if kind == "github"
        else {
            "kind": kind,
            "authorization_url": f"{fake.issuer}/authorize",
            "token_url": f"{fake.issuer}/token",
            "userinfo_url": f"{fake.issuer}/userinfo",
            "allowed_groups": ["docs"],
        }
    )
    with running(tmp_path, fake, config) as (client, container):
        admin = {"username": "ada", "password": "correct horse battery staple"}
        assert client.post("/api/v1/setup", json=admin).status_code == 201
        started = client.get("/api/v1/auth/corp/start", follow_redirects=False)
        callback = fake.authorize(started.headers["location"], "123")
        assert client.get(callback, follow_redirects=False).status_code == 303
        assert client.post("/api/v1/session", json=admin).status_code == 201
        assert client.portal is not None
        for library in ("/acme/docs", "/acme/api"):
            client.portal.call(
                container.catalog.create_library,
                CreateLibraryCommand(
                    id=library,
                    title=library,
                    source_url="https://example.com/docs.git",
                    default_branch="main",
                    host="git",
                ),
            )
            granted = client.put(
                f"/api/v1/libraries{library}/grants",
                json={"kind": "user", "subject": "alice", "role": "viewer"},
            )
            assert granted.status_code == 200, granted.text
        scoped = client.post(
            "/api/v1/tokens", json={"name": "docs only", "library_ids": ["/acme/docs"]}
        ).json()["token"]
        scope = "read:user read:org" if kind == "github" else "offline_access"
        bearer = connect(client, fake, "123", scope=scope).json()["access_token"]

        def listed(credential: str) -> list[str]:
            result = tool_result(call_tool(client, credential, "list_libraries"))
            return sorted(item["id"] for item in result["structuredContent"]["libraries"])

        # The selection narrows only that API token; the OAuth caller keeps its user's grants.
        assert listed(scoped) == ["/acme/docs"]
        assert listed(bearer) == ["/acme/api", "/acme/docs"]
        assert listed(scoped) == ["/acme/docs"]
