"""Usage counts over REST and MCP (#510): what is counted, who may read the reports, and how."""

import hashlib
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr
from sqlalchemy import text

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings, UsageSettings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.identity.dtos import (
    AccountSummary,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    GrantLibraryRoleCommand,
    InterfacePreferences,
    SavePreferencesCommand,
)
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

HORSE = "correct horse battery staple"
PHRASE = "a long enough passphrase"
ACME, BETA = "/acme/docs", "/acme/beta"
ARTICLES = ["guide/install.md", "guide/retry.md"]
SECRET_QUERY = "zebra unicorn quokka"  # appears nowhere but in the requests
IMPORTED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _library(library: str) -> Library:
    return Library(
        id=LibraryId(library),
        title=library.rsplit("/", 1)[-1].title(),
        source_url=f"https://git.example.com{library}.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset(
            {
                Version(
                    ref=VersionRef("v1.0.0"),
                    kind=RefKind.TAG,
                    commit_sha="a" * 40,
                    imported_at=IMPORTED,
                )
            }
        ),
    )


async def _publish(container: Container, library: str) -> None:
    def sha(path: str) -> str:
        return hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest()

    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=library,
            ref="v1.0.0",
            kind="tag",
            commit_sha="a" * 40,
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=sha(path),
                    content_version=1,
                    title=path,
                    tags=[],
                    content=f"# {path}\n\nRetry the payment.",
                )
                for path in ARTICLES
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=library,
            ref="v1.0.0",
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=path,
                    blob_sha=sha(path),
                    chunks=[
                        ChunkIn(
                            heading_path=[path],
                            occurrence_index=0,
                            content=f"# {path}\n\nRetry the payment.",
                            content_hash="h",
                            anchor="h",
                        )
                    ],
                )
                for path in ARTICLES
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


@dataclass(slots=True)
class Instance:
    container: Container
    app: FastAPI
    accounts: dict[str, AccountSummary]

    @asynccontextmanager
    async def client(self, name: str | None = None) -> AsyncGenerator[httpx.AsyncClient]:
        """A client with its own cookie jar, signed in as ``name`` (none: signed out)."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://localhost"
        ) as client:
            if name is not None:
                password = HORSE if name == "ada" else PHRASE
                response = await client.post(
                    "/api/v1/session", json={"username": name, "password": password}
                )
                assert response.status_code == 201, response.text
            yield client

    async def token(self, name: str) -> tuple[str, str]:
        grant = await self.container.identity.create_token(
            self.accounts[name], CreateTokenCommand(name="agent")
        )
        return grant.id, grant.token

    async def opt_in(self, name: str) -> None:
        defaults = InterfacePreferences.model_validate(
            {
                "theme": "system",
                "contrast": "standard",
                "text_scale": 100,
                "text_spacing": "standard",
                "motion": "system",
                "font": "default",
                "underline_links": False,
                "large_targets": False,
                "language": "system",
                "library_logos": True,
                "leaderboard_opt_in": True,
            }
        )
        await self.container.identity.save_preferences(
            SavePreferencesCommand(account_id=self.accounts[name].id, preferences=defaults)
        )

    async def rows(self) -> list[dict[str, Any]]:
        async with self.container.engine.connect() as connection:
            found = await connection.execute(text("SELECT * FROM usage_daily_counts"))
            return [dict(row) for row in found.mappings()]


@asynccontextmanager
async def _instance(settings: Settings) -> AsyncGenerator[Instance]:
    container = Container.build(settings)
    async with serving(create_app(container)) as app:
        identity = container.identity
        ada = await identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        accounts = {"ada": ada}
        for name in ("alice", "bob"):
            accounts[name] = await identity.create_user(
                CreateUserCommand(username=name, password=SecretStr(PHRASE))
            )
        repository = SqliteLibraryRepository(engine=container.engine)
        for library in (ACME, BETA):
            await repository.save(_library(library))
            await _publish(container, library)
            for name in ("alice", "bob"):
                await identity.grant_library_role(
                    GrantLibraryRoleCommand(
                        caller_id=ada.id, library=library, kind="user", subject=name, role="viewer"
                    )
                )
        yield Instance(container, app, accounts)


@pytest.fixture
async def instance() -> AsyncIterator[Instance]:
    async with _instance(Settings()) as made:
        yield made


@pytest.fixture
async def people_board() -> AsyncIterator[Instance]:
    async with _instance(Settings(usage=UsageSettings(people_leaderboard=True))) as made:
        yield made


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


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


# --- what is counted


async def test_mcp_reads_and_searches_are_counted_to_the_token_account_and_library(
    instance: Instance,
) -> None:
    token_id, token = await instance.token("alice")
    async with mcp_client(instance.app, token) as agent:
        for path in ARTICLES:
            await agent.call_tool("read_article", {"library": ACME, "path": path})
        await agent.call_tool("search_docs", {"library": ACME, "query": SECRET_QUERY})
        await agent.call_tool(
            "query-docs", {"libraryId": ACME, "query": f"{SECRET_QUERY} how do I retry?"}
        )
        # A read that fails is not counted.
        await agent.call_tool(
            "read_article", {"library": ACME, "path": "missing.md"}, raise_on_error=False
        )

    async with instance.client("alice") as alice:
        by_token = (await alice.get("/api/v1/account/usage", params={"by": "token"})).json()
        by_library = (await alice.get("/api/v1/account/usage", params={"by": "library"})).json()

    assert by_token["total"] == {"reads": 2, "searches": 2, "answers": 0}
    assert [(g["token_id"], g["reads"], g["searches"]) for g in by_token["groups"]] == [
        (token_id, 2, 2)
    ]
    assert [(g["library"], g["reads"]) for g in by_library["groups"]] == [(ACME, 2)]
    assert by_token["series"][-1] == {
        "start": _today(),
        "end": _today(),
        "reads": 2,
        "searches": 2,
        "answers": 0,
    }
    alice_id = instance.accounts["alice"].id
    assert sorted(
        (r["account_id"], r["token_id"], r["library"], r["operation"], r["requests"])
        for r in await instance.rows()
    ) == [(alice_id, token_id, ACME, "read", 2), (alice_id, token_id, ACME, "search", 2)]


async def test_only_counts_are_stored_never_a_query_a_path_or_content(instance: Instance) -> None:
    _, token = await instance.token("alice")
    async with mcp_client(instance.app, token) as agent:
        await agent.call_tool("read_article", {"library": ACME, "path": ARTICLES[0]})
        await agent.call_tool("search_docs", {"library": ACME, "query": SECRET_QUERY})
    async with instance.client("alice") as alice:
        await alice.get(f"/api/v1/libraries{ACME}/search", params={"q": SECRET_QUERY})
        await alice.get("/api/v1/account/usage")  # writes the pending counts

    rows = await instance.rows()
    assert rows
    assert set(rows[0]) == {"day", "account_id", "token_id", "library", "operation", "requests"}
    stored = repr(rows)
    for word in [*SECRET_QUERY.split(), "guide", "install", "Retry", "payment"]:
        assert word not in stored


async def test_rest_reads_searches_and_multi_library_searches_are_counted(
    instance: Instance,
) -> None:
    async with instance.client("bob") as bob:
        read = await bob.get(f"/api/v1/libraries{ACME}/article", params={"path": ARTICLES[0]})
        assert read.status_code == 200, read.text
        searched = await bob.get(f"/api/v1/libraries{BETA}/search", params={"q": "retry"})
        assert searched.status_code == 200, searched.text
        everywhere = await bob.get("/api/v1/search", params={"q": "retry"})
        assert everywhere.status_code == 200, everywhere.text
        missing = await bob.get(f"/api/v1/libraries{ACME}/article", params={"path": "nope.md"})
        assert missing.status_code == 404

        usage = (await bob.get("/api/v1/account/usage", params={"by": "library"})).json()

    assert usage["total"] == {"reads": 1, "searches": 2, "answers": 0}
    assert sorted(((g["library"] or ""), g["reads"], g["searches"]) for g in usage["groups"]) == [
        ("", 0, 1),
        (BETA, 0, 1),
        (ACME, 1, 0),
    ]
    # A session carries no API token: its counts are on no token.
    by_token = [r["token_id"] for r in await instance.rows()]
    assert set(by_token) == {""}


# --- who may read the reports


async def test_the_instance_usage_is_for_signed_in_operators_only(instance: Instance) -> None:
    _, admin_token = await instance.token("ada")
    async with instance.client("alice") as alice:
        await alice.get(f"/api/v1/libraries{ACME}/article", params={"path": ARTICLES[0]})
        refused = await alice.get("/api/v1/stats/usage")
    async with instance.client() as anonymous:
        signed_out = await anonymous.get("/api/v1/stats/usage")
        with_token = await anonymous.get(
            "/api/v1/stats/usage", headers={"authorization": f"Bearer {admin_token}"}
        )
    async with instance.client("ada") as ada:
        allowed = await ada.get("/api/v1/stats/usage", params={"by": "account"})

    assert (refused.status_code, refused.json()["error"]) == (403, "forbidden")
    assert signed_out.status_code == 401
    assert with_token.status_code == 401  # like /users: a session, never an API token
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["total"]["reads"] == 1
    # The people board is off: nobody is named, alice's read is in the others' group.
    assert body["groups"] == [
        {
            "reads": 1,
            "searches": 0,
            "answers": 0,
            "library": None,
            "account_id": None,
            "username": None,
            "token_id": None,
            "others": True,
        }
    ]


async def test_own_usage_is_only_the_callers(instance: Instance) -> None:
    async with instance.client("alice") as alice:
        await alice.get(f"/api/v1/libraries{ACME}/article", params={"path": ARTICLES[0]})
    _, bobs = await instance.token("bob")
    async with instance.client() as agent:
        headers = {"authorization": f"Bearer {bobs}"}
        own = await agent.get("/api/v1/account/usage", headers=headers)
        other = await agent.get(
            "/api/v1/account/usage",
            params={"account_id": instance.accounts["alice"].id},
            headers=headers,
        )
        by_person = await agent.get(
            "/api/v1/account/usage", params={"by": "account"}, headers=headers
        )

    assert own.status_code == 200, own.text
    assert own.json()["total"] == {"reads": 0, "searches": 0, "answers": 0}
    assert other.status_code == 422  # there is no asking for someone else's
    assert by_person.status_code == 422


async def test_a_report_range_is_validated(instance: Instance) -> None:
    async with instance.client("ada") as ada:
        too_many = await ada.get("/api/v1/stats/usage", params={"periods": 401})
        bad_period = await ada.get("/api/v1/stats/usage", params={"period": "hour"})
        months = await ada.get(
            "/api/v1/stats/usage", params={"period": "month", "periods": 3, "until": "2026-02-10"}
        )

    assert too_many.status_code == 422
    assert bad_period.status_code == 422
    assert [b["start"] for b in months.json()["series"]] == [
        "2025-12-01",
        "2026-01-01",
        "2026-02-01",
    ]
    assert months.json()["until"] == "2026-02-28"


# --- leaderboards and the settings


async def test_the_libraries_leaderboard_ranks_by_reads_with_the_previous_week(
    instance: Instance,
) -> None:
    today = datetime.now(UTC).date()
    last_week = (today - timedelta(days=7)).isoformat()
    async with instance.container.engine.begin() as connection:
        for library, count in [(ACME, 1), (BETA, 9)]:
            await connection.execute(
                text(
                    "INSERT INTO usage_daily_counts"
                    " (day, account_id, token_id, library, operation, requests)"
                    " VALUES (:day, :account, '', :library, 'read', :count)"
                ),
                {
                    "day": last_week,
                    "account": instance.accounts["bob"].id,
                    "library": library,
                    "count": count,
                },
            )
    async with instance.client("alice") as alice:
        for path in ARTICLES:
            await alice.get(f"/api/v1/libraries{ACME}/article", params={"path": path})
        board = await alice.get("/api/v1/stats/leaderboard", params={"period": "week"})
        people = await alice.get("/api/v1/stats/leaderboard", params={"subject": "people"})

    assert board.status_code == 200, board.text
    body = board.json()
    assert (body["subject"], body["metric"], body["period"]) == ("libraries", "reads", "week")
    assert [(e["library"], e["rank"], e["previous_rank"], e["value"]) for e in body["entries"]] == [
        (ACME, 1, 2, 2)
    ]
    assert (people.status_code, people.json()["error"]) == (403, "people_leaderboard_off")


async def test_the_people_leaderboard_lists_only_people_who_opted_in(
    people_board: Instance,
) -> None:
    await people_board.opt_in("alice")
    for name, reads in [("alice", 1), ("bob", 2)]:
        async with people_board.client(name) as client:
            for _ in range(reads):
                await client.get(f"/api/v1/libraries{ACME}/article", params={"path": ARTICLES[0]})
    bob_id = people_board.accounts["bob"].id

    async with people_board.client("bob") as bob:
        as_bob = (await bob.get("/api/v1/stats/leaderboard", params={"subject": "people"})).json()
    async with people_board.client("alice") as alice:
        as_alice = await alice.get(
            "/api/v1/stats/leaderboard", params={"subject": "people", "period": "day"}
        )
    async with people_board.client("ada") as ada:
        operator = (await ada.get("/api/v1/stats/usage", params={"by": "account"})).json()
        settings = (await ada.get("/api/v1/stats/settings")).json()

    assert [(e["username"], e["rank"], e["you"]) for e in as_alice.json()["entries"]] == [
        ("alice", 1, True)
    ]
    assert [e["username"] for e in as_bob["entries"]] == ["alice"]
    assert bob_id not in str(as_bob) + as_alice.text
    assert [(g["username"], g["reads"], g["others"]) for g in operator["groups"]] == [
        ("alice", 1, False),
        (None, 2, True),
    ]
    assert bob_id not in str(operator)
    assert settings == {"people_leaderboard": True, "retention_months": 13}


async def test_the_settings_say_the_people_board_is_off_by_default(instance: Instance) -> None:
    async with instance.client("bob") as bob:
        settings = await bob.get("/api/v1/stats/settings")
    async with instance.client() as anonymous:
        signed_out = await anonymous.get("/api/v1/stats/settings")

    assert settings.json() == {"people_leaderboard": False, "retention_months": 13}
    assert signed_out.status_code == 401


async def test_the_openapi_document_describes_the_usage_operations(instance: Instance) -> None:
    async with instance.client() as client:
        spec: dict[str, Any] = (await client.get("/api/v1/openapi.json")).json()

    operations = {
        path: spec["paths"][f"/api/v1{path}"]["get"]
        for path in ("/stats/usage", "/account/usage", "/stats/leaderboard", "/stats/settings")
    }
    assert {path: op["operationId"] for path, op in operations.items()} == {
        "/stats/usage": "usage-get_usage_stats",
        "/account/usage": "usage-get_account_usage",
        "/stats/leaderboard": "usage-get_leaderboard",
        "/stats/settings": "usage-get_usage_settings",
    }
    assert operations["/stats/usage"]["security"] == [{"SessionCookie": []}]
    params = {p["name"]: p for p in operations["/stats/leaderboard"]["parameters"]}
    assert set(params) == {"subject", "metric", "period", "at", "limit"}


async def test_the_nightly_upkeep_deletes_the_counts_older_than_the_retention(
    instance: Instance,
) -> None:
    today = datetime.now(UTC).date()
    async with instance.container.engine.begin() as connection:
        for day in (today - timedelta(days=500), today - timedelta(days=10)):
            await connection.execute(
                text(
                    "INSERT INTO usage_daily_counts"
                    " (day, account_id, token_id, library, operation, requests)"
                    " VALUES (:day, '', '', '', 'read', 1)"
                ),
                {"day": day.isoformat()},
            )

    await instance.container.nightly()

    assert [row["day"] for row in await instance.rows()] == [
        (today - timedelta(days=10)).isoformat()
    ]
