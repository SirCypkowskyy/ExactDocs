"""`[auth].default_library_role`: every account reads every library that is not private."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import SecretStr, ValidationError

from app_lifespan import serving
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.identity.dtos import (
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    MarkLibraryPrivateCommand,
)

PHRASE = "a long enough passphrase"
PAYMENTS, LEDGER = "/acme/payments", "/acme/ledger"


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


@pytest.mark.parametrize("source", ["toml", "environment"])
def test_the_default_role_is_read_from_the_file_or_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    assert Settings().auth.default_library_role is None
    if source == "toml":
        config = tmp_path / "exactdocs.toml"
        config.write_text('[auth]\ndefault_library_role = "viewer"\n')
        monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))
    else:
        monkeypatch.setenv("EXACTDOCS_AUTH__DEFAULT_LIBRARY_ROLE", "viewer")

    assert Settings().auth.default_library_role == "viewer"


@pytest.mark.parametrize("role", ["contributor", "admin", "creator", "Viewer", ""])
def test_a_default_role_other_than_viewer_stops_the_server(role: str) -> None:
    with pytest.raises(ValidationError, match="only 'viewer' can be given to every account"):
        Settings.model_validate({"auth": {"default_library_role": role}})


@pytest.fixture
async def instance() -> AsyncIterator[tuple[Container, FastAPI, str]]:
    settings = Settings.model_validate(
        {"auth": {"default_library_role": "viewer", "library_creation": {}}}
    )
    container = Container.build(settings)
    async with serving(create_app(container)) as app:
        identity = container.identity
        await identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(PHRASE))
        )
        bob = await identity.create_user(
            CreateUserCommand(username="bob", password=SecretStr(PHRASE))
        )
        repository = SqliteLibraryRepository(engine=container.engine)
        for library in (PAYMENTS, LEDGER):
            await repository.save(
                Library(
                    id=LibraryId(library),
                    title=library,
                    source_url=f"https://git.example.com{library}.git",
                    host=HostKind.GIT,
                    default_branch=VersionRef("main"),
                )
            )
        await identity.mark_library_private(MarkLibraryPrivateCommand(library=LEDGER, private=True))
        token = await identity.create_token(bob, CreateTokenCommand(name="agent"))
        yield container, app, token.token


async def test_an_account_with_no_grant_reads_over_mcp_and_rest_and_changes_nothing(
    instance: tuple[Container, FastAPI, str],
) -> None:
    _container, app, token = instance

    async with mcp_client(app, token) as agent:
        tools = {tool.name for tool in await agent.list_tools()}
        listed = str((await agent.call_tool("list_libraries", {})).content)
        found = await agent.call_tool(
            "search_docs", {"library": PAYMENTS, "query": "retry"}, raise_on_error=False
        )

    assert not tools & {"add_docs", "import_status"}
    assert PAYMENTS in listed
    assert LEDGER not in listed  # private: the default role never reaches it
    assert "forbidden" not in str(found.content)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
        headers={"authorization": f"Bearer {token}"},
    ) as client:
        read = await client.get("/api/v1/libraries/acme/payments")
        rename = await client.patch("/api/v1/libraries/acme/payments", json={"title": "X"})
        sync = await client.post("/api/v1/libraries/acme/payments/sync")
        private = await client.get("/api/v1/libraries/acme/ledger")

    assert read.status_code == 200, read.text
    assert (rename.status_code, rename.json()["error"]) == (403, "forbidden")
    assert (sync.status_code, sync.json()["error"]) == (403, "forbidden")
    assert private.status_code in {403, 404}
