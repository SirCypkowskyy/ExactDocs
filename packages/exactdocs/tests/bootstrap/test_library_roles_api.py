"""Library roles (ACL-02, #108) enforced over REST and MCP: a role x action matrix.

Every account here is an ordinary user (`ada` is the instance's operator, who is creator of
every library); a role is granted, or claimed as a creator, on `/acme/payments`.
"""

import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from pydantic import SecretStr
from sqlalchemy import text

from app_lifespan import serving
from exactdocs.bootstrap.caller import bind_caller
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.constants import RESOURCE_LIST_TTL
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    CreateLibraryCommand,
    RemoveLibraryCommand,
    StoreManifestCommand,
)
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.identity.dtos import (
    AccountSummary,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    GrantLibraryRoleCommand,
    LibraryRolesQuery,
    RevokeLibraryRoleCommand,
)
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.models import Job, JobId

IMPORTED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LIBRARIES = [
    Library(
        id=LibraryId(f"/acme/{name}"),
        title=name.title(),
        source_url=f"https://git.example.com/acme/{name}.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset(
            Version(
                ref=VersionRef(ref),
                kind=RefKind.TAG if ref.startswith("v") else RefKind.BRANCH,
                commit_sha="a" * 40,
                imported_at=IMPORTED,
            )
            for ref in ("v1.3.0", "main")
        ),
    )
    for name in ("payments", "ledger")
]
HORSE = "correct horse battery staple"
PHRASE = "a long enough passphrase"
LIBRARY = "/acme/payments"
PATH = "/api/v1/libraries/acme/payments"
type LibraryRole = Literal["viewer", "contributor", "admin", "creator"]
ROLES: list[LibraryRole] = ["viewer", "contributor", "admin", "creator"]
NO_ROLE = "no role"


@dataclass(slots=True)
class Instance:
    container: Container
    app: FastAPI
    accounts: dict[str, AccountSummary]

    @asynccontextmanager
    async def signed_in(self, name: str) -> AsyncGenerator[httpx.AsyncClient]:
        """A client with its own cookie jar, signed in as ``name``."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://localhost"
        ) as client:
            password = HORSE if name == "ada" else PHRASE
            response = await client.post(
                "/api/v1/session", json={"username": name, "password": password}
            )
            assert response.status_code == 201, response.text
            yield client

    async def token(self, name: str) -> str:
        grant = await self.container.identity.create_token(
            self.accounts[name], CreateTokenCommand(name="agent")
        )
        return grant.token

    async def give(self, name: str, role: LibraryRole) -> None:
        """Make ``name`` hold ``role`` on the library, the way a real instance gets there."""
        identity = self.container.identity
        if role == "creator":
            await identity.claim_library(
                ClaimLibraryCommand(account_id=self.accounts[name].id, library=LIBRARY)
            )
            return
        await identity.grant_library_role(
            GrantLibraryRoleCommand(
                caller_id=self.accounts["ada"].id,
                library=LIBRARY,
                kind="user",
                subject=name,
                role=role,
            )
        )


@pytest.fixture
async def instance() -> AsyncIterator[Instance]:
    container = Container.build(Settings())
    async with serving(create_app(container)) as app:
        identity = container.identity
        accounts = {
            "ada": await identity.create_first_admin(
                CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
            )
        }
        for name in ("bob", "carol", NO_ROLE.replace(" ", "")):
            accounts[name] = await identity.create_user(
                CreateUserCommand(username=name, password=SecretStr(PHRASE))
            )
        repository = SqliteLibraryRepository(engine=container.engine)
        for library in LIBRARIES:
            await repository.save(library)
        yield Instance(container, app, accounts)


@dataclass(frozen=True, slots=True)
class Action:
    """One thing a caller does, and the lowest role that may."""

    name: str
    needs: LibraryRole
    method: str
    path: str
    options: dict[str, Any]
    reaches_git: bool = False
    """Its allowed form would call the repository's remote: only the refusals are tried."""


ACTIONS = [
    Action("read the library", "viewer", "GET", PATH, {}),
    Action("list its articles", "viewer", "GET", f"{PATH}/articles", {}),
    Action("search it", "viewer", "GET", f"{PATH}/search", {"params": {"q": "retry"}}),
    Action("outline an article", "viewer", "GET", f"{PATH}/outline", {"params": {"path": "a.md"}}),
    Action("list its jobs", "viewer", "GET", f"{PATH}/jobs", {}),
    Action("read its schedule", "viewer", "GET", f"{PATH}/auto-sync", {}),
    Action("read its retrieval settings", "viewer", "GET", f"{PATH}/retrieval", {}),
    Action(
        "tag an article",
        "contributor",
        "PUT",
        f"{PATH}/tags",
        {"params": {"path": "a.md"}, "json": {"tags": ["x"]}},
    ),
    Action("sync it", "contributor", "POST", f"{PATH}/sync", {}, reaches_git=True),
    Action(
        "add a version",
        "contributor",
        "POST",
        f"{PATH}/versions",
        {"json": {"ref": "v1.5.0"}},
        reaches_git=True,
    ),
    Action(
        "reimport a version",
        "contributor",
        "POST",
        f"{PATH}/versions/reimport",
        {"json": {"ref": "v1.4.0"}},
        reaches_git=True,
    ),
    Action("change its paths", "admin", "PUT", f"{PATH}/settings", {"json": {}}),
    Action("rename it", "admin", "PATCH", PATH, {"json": {"title": "Payments SDK"}}),
    Action(
        "pin its default version",
        "admin",
        "PUT",
        f"{PATH}/default-version",
        {"json": {"ref": "v1.3.0"}},
    ),
    Action(
        "set its retrieval mode", "admin", "PUT", f"{PATH}/retrieval", {"json": {"mode": "bm25"}}
    ),
    Action("schedule its syncs", "admin", "PUT", f"{PATH}/auto-sync", {"json": {"keep_last": 3}}),
    Action("stop its schedule", "admin", "DELETE", f"{PATH}/auto-sync", {}),
    Action("remove a version", "admin", "DELETE", f"{PATH}/versions/v1.3.0", {}),
    Action("remove it", "creator", "DELETE", PATH, {}),
    Action("list who may do what", "admin", "GET", f"{PATH}/grants", {}),
]


def needs_more(role: LibraryRole | None, needed: LibraryRole) -> bool:
    """Whether ``role`` (``None``: no role) is below ``needed``."""
    return role is None or ROLES.index(role) < ROLES.index(needed)


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.name)
async def test_every_action_asks_for_its_role(instance: Instance, action: Action) -> None:
    """Below the role an action needs it is a 403; at the role (and above) it is not."""
    for role in [None, *ROLES]:
        name = "bob" if role is None else "carol"
        if role is not None:
            await instance.give(name, role)
        async with instance.signed_in(name) as client:
            if role is not None and not needs_more(role, action.needs) and action.reaches_git:
                return  # the refusal side is done; the allowed side would call the network
            response = await client.request(action.method, action.path, **action.options)
        refused = response.status_code == (404 if role is None else 403)
        assert refused is needs_more(role, action.needs), (
            action.name,
            role,
            response.status_code,
            response.text,
        )
        if refused:
            assert response.json()["error"] == ("not_found" if role is None else "forbidden")


async def test_a_viewer_reads_and_searches_but_changing_its_paths_is_refused(
    instance: Instance,
) -> None:
    await instance.give("bob", "viewer")
    async with instance.signed_in("bob") as bob:
        assert (await bob.get(PATH)).status_code == 200
        assert (await bob.get(f"{PATH}/search", params={"q": "retry"})).status_code != 403

        changed = await bob.put(f"{PATH}/settings", json={"include_paths": ["docs/"]})

    assert (changed.status_code, changed.json()["error"]) == (403, "forbidden")
    async with instance.signed_in("ada") as ada:
        assert (await ada.get(PATH)).json()["settings"]["include_paths"] == []


async def test_a_role_without_a_grant_leaves_the_library_unreadable_and_unlisted(
    instance: Instance,
) -> None:
    await instance.give("bob", "viewer")
    async with instance.signed_in("carol") as carol, instance.signed_in("bob") as bob:
        assert (await carol.get(PATH)).status_code == 404
        assert (await carol.get("/api/v1/libraries")).json()["libraries"] == []
        listed = (await bob.get("/api/v1/libraries")).json()["libraries"]
        assert [library["id"] for library in listed] == [LIBRARY]


async def test_a_search_across_libraries_reaches_only_the_readable_ones(
    instance: Instance,
) -> None:
    async with instance.signed_in("carol") as carol:
        response = await carol.get("/api/v1/search", params={"q": "retry"})

    assert response.status_code == 200
    assert response.json()["libraries"] == []


async def test_a_grant_to_a_group_gives_its_members_the_role(instance: Instance) -> None:
    async with instance.container.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO identity_account_groups (account_id, name) VALUES (:id, :name)"),
            {"id": instance.accounts["carol"].id, "name": "corp:payments"},
        )
    async with instance.signed_in("ada") as ada:
        granted = await ada.put(
            f"{PATH}/grants",
            json={"kind": "group", "subject": "corp:payments", "role": "contributor"},
        )
    assert granted.status_code == 200, granted.text

    async with instance.signed_in("carol") as carol:
        assert (await carol.get(PATH)).status_code == 200
        assert (await carol.patch(PATH, json={"title": "x"})).status_code == 403
        tagged = await carol.put(f"{PATH}/tags", params={"path": "a.md"}, json={"tags": ["x"]})
        assert tagged.status_code != 403


async def test_grants_are_given_listed_and_revoked_over_rest(instance: Instance) -> None:
    async with instance.signed_in("ada") as ada, instance.signed_in("bob") as bob:
        assert (await bob.get(PATH)).status_code == 404

        await ada.put(f"{PATH}/grants", json={"kind": "user", "subject": "bob", "role": "viewer"})
        assert (await bob.get(PATH)).status_code == 200
        listed = await ada.get(f"{PATH}/grants")
        assert listed.json() == {"grants": [{"kind": "user", "subject": "bob", "role": "viewer"}]}

        revoked = await ada.delete(f"{PATH}/grants/user/bob")
        assert revoked.json() == {"grants": []}
        assert (await bob.get(PATH)).status_code == 404
        missing = await ada.delete(f"{PATH}/grants/user/bob")
        assert (missing.status_code, missing.json()["error"]) == (404, "unknown_grant")
        unknown = await ada.put(
            f"{PATH}/grants", json={"kind": "user", "subject": "zed", "role": "viewer"}
        )
        assert (unknown.status_code, unknown.json()["error"]) == (404, "unknown_account")
        creator = await ada.put(
            f"{PATH}/grants", json={"kind": "user", "subject": "bob", "role": "creator"}
        )
        assert creator.status_code == 422


async def test_the_operator_manages_every_library_as_its_creator(instance: Instance) -> None:
    async with instance.signed_in("ada") as ada:
        assert (await ada.patch(PATH, json={"title": "Payments SDK"})).status_code == 200
        listed = (await ada.get("/api/v1/libraries")).json()["libraries"]
        assert {library["id"] for library in listed} == {d.id.value for d in LIBRARIES}


async def test_a_new_library_is_created_by_its_caller_and_removing_it_drops_its_grants(
    instance: Instance,
) -> None:
    catalog, identity = instance.container.catalog, instance.container.identity
    bob, carol = instance.accounts["bob"], instance.accounts["carol"]
    new = "/acme/ledger-two"
    await identity.grant_library_role(
        GrantLibraryRoleCommand(
            caller_id=instance.accounts["ada"].id,
            library=new,
            kind="user",
            subject="carol",
            role="viewer",
        )
    )  # left by an earlier library of this ID

    bind_caller(bob.id)  # what the REST dependency and the MCP token do for a request
    await catalog.create_library(
        CreateLibraryCommand(
            id=new, title="Ledger two", source_url="https://example.com/a/b.git", host="git"
        )
    )

    async def role(account: AccountSummary) -> str | None:
        found = await identity.resolve_library_roles(
            LibraryRolesQuery(account_id=account.id, libraries=[new])
        )
        return found.roles.get(new)

    assert (await role(bob), await role(carol)) == ("creator", None)
    await catalog.remove_library(RemoveLibraryCommand(library=new))
    assert await role(bob) is None


def mcp_client(app: FastAPI, token: str) -> Client[StreamableHttpTransport]:
    """A FastMCP client that talks to the app in-process, over the real HTTP transport."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **extra: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **extra,
        )

    return Client(
        StreamableHttpTransport(
            "http://localhost/mcp",
            headers={"authorization": f"Bearer {token}"},
            httpx_client_factory=factory,
        )
    )


async def test_a_viewer_reads_over_mcp_and_a_caller_without_a_role_is_refused(
    instance: Instance,
) -> None:
    await instance.give("bob", "viewer")
    reads = [
        ("list_articles", {"library": LIBRARY}),
        ("search_docs", {"library": LIBRARY, "query": "retry"}),
    ]
    async with mcp_client(instance.app, await instance.token("bob")) as viewer:
        for tool, arguments in reads:
            # The demo library has nothing imported: it may say so, but never "forbidden".
            result = await viewer.call_tool(tool, arguments, raise_on_error=False)
            assert "forbidden" not in str(result.content), tool
        listed = await viewer.call_tool("list_libraries", {})
        assert LIBRARY in str(listed.content)

    async with mcp_client(instance.app, await instance.token("carol")) as nobody:
        for tool, arguments in reads:
            with pytest.raises(ToolError, match="not_found"):
                await nobody.call_tool(tool, arguments)
        listed = await nobody.call_tool("list_libraries", {})
        assert LIBRARY not in str(listed.content)


async def _publish_plan(container: Container, library: str) -> None:
    """Store and activate ``v1.3.0``, the default version, of ``library``: one article."""
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=library,
            ref="v1.3.0",
            kind="tag",
            commit_sha="a" * 40,
            articles=[
                ArticleIn(
                    path="plan.md",
                    blob_sha="b" * 40,
                    content_version=1,
                    title="Secret plan",
                    tags=[],
                    content="# Secret plan",
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def test_the_resource_list_is_kept_per_caller_not_shared_through_its_cache(
    instance: Instance, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _publish_plan(instance.container, LIBRARY)
    # The list the server built while starting is stale now: let it expire, so that the first
    # caller below builds a list that the 30 s cache then holds for the next ones.
    expired = SimpleNamespace(monotonic=lambda: time.monotonic() + RESOURCE_LIST_TTL + 1)
    monkeypatch.setattr("exactdocs.catalog.adapters.driving.mcp.time", expired)
    wanted = "exactdocs://acme/payments/plan.md?ref=v1.3.0"
    # The cache lives 30 s: the operator lists first, so a shared one would hand it to carol.
    async with mcp_client(instance.app, await instance.token("ada")) as operator:
        assert wanted in {str(r.uri) for r in await operator.list_resources()}

    async with mcp_client(instance.app, await instance.token("carol")) as nobody:
        listed = await nobody.list_resources()
        assert wanted not in {str(r.uri) for r in listed}

    await instance.give("bob", "viewer")
    async with mcp_client(instance.app, await instance.token("bob")) as viewer:
        assert wanted in {str(r.uri) for r in await viewer.list_resources()}


AI_ROUTES = [
    ("GET", "/api/v1/ai/providers", {}),
    ("GET", "/api/v1/ai/providers/corp", {}),
    (
        "PUT",
        "/api/v1/ai/providers/corp",
        {"json": {"kind": "openai-compatible", "base_url": "https://llm.example.com/v1"}},
    ),
    ("DELETE", "/api/v1/ai/providers/corp", {}),
    ("GET", "/api/v1/ai/roles", {}),
    ("GET", "/api/v1/ai/embedding", {}),
    ("GET", "/api/v1/ai/usage", {}),
]


@pytest.mark.parametrize(("method", "path", "options"), AI_ROUTES)
async def test_the_ai_routes_are_for_the_operator_whatever_the_library_roles(
    instance: Instance, method: str, path: str, options: dict[str, Any]
) -> None:
    await instance.give("bob", "creator")  # a role on a library is no reach into the instance
    for name in ("bob", "carol"):
        async with instance.signed_in(name) as client:
            refused = await client.request(method, path, **options)
            assert refused.status_code == 403, (name, refused.text)
            assert refused.json()["error"] == "forbidden"

    async with instance.signed_in("ada") as operator:
        allowed = await operator.request(method, path, **options)
        assert allowed.status_code not in {401, 403}, allowed.text


async def test_two_tokens_of_one_operator_have_distinct_live_resource_scopes(
    instance: Instance,
) -> None:
    for library in (LIBRARY, "/acme/ledger"):
        await _publish_plan(instance.container, library)
    identity = instance.container.identity
    grants = [
        await identity.create_token(
            instance.accounts["ada"], CreateTokenCommand(name="scoped", library_ids=selection)
        )
        for selection in (None, {"/acme/ledger"}, set())
    ]
    wanted = "exactdocs://acme/payments/plan.md?ref=v1.3.0"
    for grant, visible in zip(grants, (True, False, False), strict=True):
        async with mcp_client(instance.app, grant.token) as client:
            assert (wanted in {str(r.uri) for r in await client.list_resources()}) is visible
            listing = await client.call_tool("list_libraries", {})
            assert (LIBRARY in str(listing.content)) is visible
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=instance.app),
            base_url="http://localhost",
            headers={"authorization": f"Bearer {grant.token}"},
        ) as client:
            response = await client.get("/api/v1/libraries")
            assert (LIBRARY in response.text) is visible


async def test_warm_resources_immediately_lose_a_revoked_library_role(instance: Instance) -> None:
    await _publish_plan(instance.container, LIBRARY)
    await instance.give("bob", "viewer")
    secret = await instance.token("bob")
    wanted = "exactdocs://acme/payments/plan.md?ref=v1.3.0"
    async with mcp_client(instance.app, secret) as client:
        assert wanted in {str(r.uri) for r in await client.list_resources()}
        await instance.container.identity.revoke_library_role(
            RevokeLibraryRoleCommand(
                caller_id=instance.accounts["ada"].id, library=LIBRARY, kind="user", subject="bob"
            )
        )
        assert wanted not in {str(r.uri) for r in await client.list_resources()}


@pytest.mark.parametrize(
    ("method", "suffix", "options"),
    [
        ("GET", "", {}),
        ("PATCH", "", {"json": {"title": "hidden"}}),
        ("GET", "/grants", {}),
        ("GET", "/article", {"params": {"path": "plan.md"}}),
        ("GET", "/assets/logo.png", {}),
    ],
)
async def test_scoped_hidden_and_missing_library_errors_have_identical_details(
    instance: Instance, method: str, suffix: str, options: dict[str, Any]
) -> None:
    grant = await instance.container.identity.create_token(
        instance.accounts["ada"], CreateTokenCommand(name="no libraries", library_ids=set())
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=instance.app),
        base_url="http://localhost",
        headers={"authorization": f"Bearer {grant.token}"},
    ) as client:
        hidden = await client.request(method, PATH + suffix, **options)
        missing_path = "/api/v1/libraries/acme/absent"
        missing = await client.request(method, missing_path + suffix, **options)
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json()["error"] == missing.json()["error"] == "not_found"
        assert hidden.text.replace(LIBRARY, "/acme/absent") == missing.text


async def test_hidden_opaque_job_errors_match_missing_jobs(instance: Instance) -> None:
    jobs = SqliteJobRepository(engine=instance.container.engine)
    await jobs.add(
        Job.queued(
            job_id=JobId("hidden"),
            kind=JobKind("import"),
            library=LIBRARY,
            version=None,
            now=IMPORTED,
        )
    )
    grant = await instance.container.identity.create_token(
        instance.accounts["ada"], CreateTokenCommand(name="empty", library_ids=set())
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=instance.app),
        base_url="http://localhost",
        headers={"authorization": f"Bearer {grant.token}"},
    ) as client:
        hidden = await client.get("/api/v1/jobs/hidden")
        missing = await client.get("/api/v1/jobs/missing")
        assert hidden.status_code == missing.status_code == 404
        assert hidden.text.replace("hidden", "missing") == missing.text
        assert LIBRARY not in hidden.text
