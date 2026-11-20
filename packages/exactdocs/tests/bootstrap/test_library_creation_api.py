"""Configured creation permission across REST, catalog and verified OAuth requests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app_lifespan import serving
from exactdocs.bootstrap.bridges import IdentityAccessPolicy
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import CreateLibraryCommand
from exactdocs.catalog.errors import LibraryCreationDeniedError
from exactdocs.catalog.use_cases import CreateLibraryUseCase
from exactdocs.identity.dtos import (
    AccountSummary,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    ExternalTokenIdentity,
    LibraryRolesQuery,
)
from exactdocs.ingestion.models import RemoteRef, RemoteRefs

PHRASE = "a sufficiently long passphrase"
URL = "https://github.com/acme/new-library"
LIBRARY = "/acme/new-library"


@dataclass
class Remote:
    asked: int = 0

    async def host_key_fingerprint(self, repository):
        del repository

    async def list_refs(self, *args, **kwargs):
        del args, kwargs
        self.asked += 1
        return RemoteRefs(
            default_branch="main", refs=(RemoteRef(name="refs/heads/main", sha="a" * 40),)
        )


@asynccontextmanager
async def instance(tmp_path: Path, mode: str) -> AsyncGenerator[tuple]:
    # Create accounts first so the operator can configure their stable IDs, just as on deployment.
    settings = Settings(data_dir=tmp_path)
    setup = Container.build(settings)
    async with setup.running(jobs=False):
        admin = await setup.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(PHRASE))
        )
        bob = await setup.identity.create_user(
            CreateUserCommand(username="bob", password=SecretStr(PHRASE))
        )
        if mode == "group":
            async with setup.engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO identity_account_groups (account_id, name) "
                        "VALUES (:id, 'corp:docs')"
                    ),
                    {"id": bob.id},
                )
    config = (
        None
        if mode == "omitted"
        else {
            "users": [bob.id] if mode == "user" else [],
            "groups": ["corp:docs"] if mode == "group" else [],
        }
    )
    remote = Remote()
    container = Container.build(
        Settings(data_dir=tmp_path, auth={"library_creation": config}), remote=remote
    )
    async with (
        serving(create_app(container)) as app,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        yield container, client, admin, bob, remote


@pytest.mark.parametrize("credential", ["session", "token"])
@pytest.mark.parametrize("mode", ["empty", "user", "group", "omitted", "admin"])
async def test_rest_creation_permission_and_owner(tmp_path: Path, mode: str, credential: str):
    async with instance(tmp_path, mode) as (container, client, admin, bob, remote):
        account = admin if mode == "admin" else bob
        if credential == "session":
            response = await client.post(
                "/api/v1/session", json={"username": account.username, "password": PHRASE}
            )
            assert response.status_code == HTTPStatus.CREATED
        else:
            grant = await container.identity.create_token(account, CreateTokenCommand(name="test"))
            client.headers["authorization"] = f"Bearer {grant.token}"
        response = await client.post(
            "/api/v1/libraries", json={"url": URL, "include_paths": ["docs/**"]}
        )
        if mode == "empty":
            assert response.status_code == HTTPStatus.FORBIDDEN, response.text
            assert remote.asked == 0
            async with container.engine.connect() as connection:
                for statement in (
                    "SELECT count(*) FROM catalog_libraries",
                    "SELECT count(*) FROM identity_library_grants",
                    "SELECT count(*) FROM ingestion_jobs",
                    "SELECT count(*) FROM ingestion_library_credentials",
                ):
                    assert (await connection.execute(text(statement))).scalar() == 0
        else:
            assert response.status_code == HTTPStatus.CREATED, response.text
            roles = await container.identity.resolve_library_roles(
                LibraryRolesQuery(account_id=account.id, libraries=[LIBRARY])
            )
            assert roles.roles == {LIBRARY: "creator"}


async def test_allowed_creator_cannot_overwrite_inaccessible_existing_id(tmp_path: Path):
    async with instance(tmp_path, "user") as (container, client, _admin, bob, remote):
        await container.catalog.create_library(
            CreateLibraryCommand(id=LIBRARY, title="Original", source_url=URL, host="github")
        )
        grant = await container.identity.create_token(bob, CreateTokenCommand(name="test"))
        client.headers["authorization"] = f"Bearer {grant.token}"
        response = await client.post("/api/v1/libraries", json={"url": URL})
        assert response.status_code == HTTPStatus.CONFLICT, response.text
        assert remote.asked == 0
        async with container.engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT title FROM catalog_libraries"))
            ).scalar() == "Original"


async def test_sources_apply_denies_creation_before_git_and_context7(tmp_path: Path):
    async with instance(tmp_path, "empty") as (container, client, _admin, bob, remote):
        grant = await container.identity.create_token(bob, CreateTokenCommand(name="test"))
        client.headers["authorization"] = f"Bearer {grant.token}"
        response = await client.post(
            "/api/v1/sources/apply",
            json={"sources": {"version": 1, "libraries": [{"url": URL, "refs": ["main"]}]}},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN, response.text
        assert remote.asked == 0


@pytest.mark.parametrize("allowed", [True, False])
async def test_verified_principal_creation_and_ownership_through_bridge(
    tmp_path: Path, allowed: bool
):
    async with instance(tmp_path, "group") as (container, _client, _admin, bob, _remote):
        principal = ExternalTokenIdentity(
            account=AccountSummary(id=bob.id, username="bob", role="user"),
            groups=frozenset({"corp:docs"} if allowed else set()),
            linked=True,
        )
        # The bridge captures callables during assembly, so replace context sources on its field.
        creation_case = container.catalog.create_library
        assert isinstance(creation_case, CreateLibraryUseCase)
        policy = creation_case.access
        assert isinstance(policy, IdentityAccessPolicy)

        use_case = replace(
            creation_case,
            access=replace(policy, caller=lambda: bob.id, external_identity=lambda: principal),
        )
        command = CreateLibraryCommand(id=LIBRARY, title="New", source_url=URL, host="github")
        if not allowed:
            with pytest.raises(LibraryCreationDeniedError):
                await use_case(command)
        else:
            await use_case(command)
            roles = await container.identity.resolve_library_roles(
                LibraryRolesQuery(
                    account_id=bob.id, libraries=[LIBRARY], external_identity=principal
                )
            )
            assert roles.roles == {LIBRARY: "creator"}


@pytest.mark.parametrize("source", ["toml", "environment"])
def test_creation_settings_distinguish_absent_and_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
):
    assert Settings().auth.library_creation is None
    if source == "toml":
        config = tmp_path / "exactdocs.toml"
        config.write_text("[auth.library_creation]\n")
        monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))
    else:
        monkeypatch.setenv("EXACTDOCS_AUTH__LIBRARY_CREATION", "{}")
    creation = Settings().auth.library_creation
    assert creation is not None
    assert creation.users == creation.groups == frozenset()


def test_creation_settings_read_stable_users_and_mapped_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = tmp_path / "exactdocs.toml"
    config.write_text(
        "[auth.library_creation]\n"
        'users = ["stable-user-id", "corp:subject-1"]\n'
        'groups = ["corp:docs"]\n'
    )
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))
    monkeypatch.setenv("EXACTDOCS_AUTH__LIBRARY_CREATION__GROUPS", '["corp:editors"]')
    creation = Settings().auth.library_creation
    assert creation is not None
    assert creation.users == frozenset({"stable-user-id", "corp:subject-1"})
    assert creation.groups == frozenset({"corp:editors"})


async def test_library_reader_can_inspect_access_without_creation_permission(tmp_path: Path):
    async with instance(tmp_path, "empty") as (container, client, _admin, bob, _remote):
        await container.catalog.create_library(
            CreateLibraryCommand(id=LIBRARY, title="Original", source_url=URL, host="github")
        )
        await container.identity.claim_library(
            ClaimLibraryCommand(account_id=bob.id, library=LIBRARY)
        )
        token = await container.identity.create_token(bob, CreateTokenCommand(name="test"))
        client.headers["authorization"] = f"Bearer {token.token}"
        response = await client.get("/api/v1/libraries/acme/new-library/access")
        assert response.status_code == HTTPStatus.OK, response.text


@pytest.mark.parametrize("mode", ["admin", "user", "empty"])
@pytest.mark.parametrize("selection", [None, [], [LIBRARY], ["/acme/other"]])
async def test_token_library_selection_intersects_creation_policy(
    tmp_path: Path, mode: str, selection: list[str] | None
) -> None:
    async with instance(tmp_path, mode) as (container, client, admin, bob, remote):
        account = admin if mode == "admin" else bob
        grant = await container.identity.create_token(
            account, CreateTokenCommand(name="scoped", library_ids=selection)
        )
        identity = await container.identity.identify_token(grant.token)
        creation = container.catalog.create_library
        assert isinstance(creation, CreateLibraryUseCase)
        policy = creation.access
        assert isinstance(policy, IdentityAccessPolicy)
        scoped = replace(policy, caller=lambda: account.id, api_identity=lambda: identity)
        assert await scoped.can_create() is (mode != "empty" and selection is None)
        client.headers["authorization"] = f"Bearer {grant.token}"
        response = await client.post(
            "/api/v1/libraries", json={"url": URL, "include_paths": ["docs/**"]}
        )
        allowed = mode != "empty" and (selection is None or LIBRARY in selection)
        if allowed:
            assert response.status_code == HTTPStatus.CREATED, response.text
            assert remote.asked == 1
        else:
            assert response.status_code == HTTPStatus.FORBIDDEN, response.text
            assert response.json()["error"] == "library_creation_denied"
            assert remote.asked == 0
