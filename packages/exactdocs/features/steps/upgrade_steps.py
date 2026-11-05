"""Steps for upgrades (a database left by the previous release) and ``exactdocs reindex``."""

import asyncio
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import alembic_config, open_database
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driving.http import SESSION_COOKIE
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from steps.http_steps import DEMO_COOKIE, OfflineGit, store_demo_catalog
from steps.search_steps import LIBRARY, import_versions

# The newest stable release and the schema revision it ships (its Alembic head). Move both on when
# a release is tagged (docs/releasing.md). CI also runs that release itself from PyPI on a data
# directory and starts this build on it (deploy/upgrade_check.py); this scenario is the in-process
# half: the data is written now, then the schema is taken back to that revision.
PREVIOUS_RELEASE, PREVIOUS_REVISION = "v0.2.0", "a1c9e4d7b352"
CLI = "from exactdocs.bootstrap.cli import main; main()"
QUERY = "retry_policy"


def _client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(Container.build(settings, remote=OfflineGit(GitCli.locate()))),
        base_url="http://localhost",
        cookies={SESSION_COOKIE: DEMO_COOKIE},
    )


def _served(client: TestClient) -> dict[str, object]:
    """What a client sees of the fixture library: the list, a version's articles, one, a search."""
    owner_repo = LIBRARY
    answers = {
        "libraries": client.get("/api/v1/libraries"),
        "articles": client.get(f"/api/v1/libraries{owner_repo}/articles", params={"ref": "v1.4.0"}),
        "article": client.get(
            f"/api/v1/libraries{owner_repo}/article",
            params={"ref": "v1.4.0", "path": "docs/reference/naming.md"},
        ),
        "search": client.get(
            f"/api/v1/libraries{owner_repo}/search", params={"ref": "v1.4.0", "q": QUERY}
        ),
    }
    for name, response in answers.items():
        assert response.status_code == HTTPStatus.OK, (name, response.status_code, response.text)
    return {name: response.json() for name, response in answers.items()}


def _downgrade(connection: Connection, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


async def _take_schema_back(settings: Settings, revision: str) -> None:
    engine = open_database(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, revision)
    finally:
        await engine.dispose()


@given("an instance with libraries created by the previous release")
def step_previous_release(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.stack = stack
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir)
    asyncio.run(store_demo_catalog(context.settings))
    asyncio.run(import_versions(context, ["v1.3.0", "v1.4.0"]))
    with _client(context.settings) as client:
        context.served_before = _served(client)
    asyncio.run(_take_schema_back(context.settings, PREVIOUS_REVISION))


@when("the new release starts")
def step_new_release(context: Context) -> None:
    context.client = context.stack.enter_context(_client(context.settings))


@then("the database is migrated and the libraries are served unchanged")
def step_migrated(context: Context) -> None:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    health = context.client.get("/api/health").json()
    assert health["schema_revision"] == head != PREVIOUS_REVISION, health
    assert not health["reindex_required"], health
    assert _served(context.client) == context.served_before


def _search(context: Context) -> list[str]:
    response = context.client.get(
        f"/api/v1/libraries{LIBRARY}/search", params={"ref": "v1.4.0", "q": QUERY}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return [r["chunk_id"] for r in response.json()["results"]]


async def _age_index(settings: Settings) -> None:
    """Record an older format, as an index an earlier release built would carry."""
    engine = open_database(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE retrieval_search_format SET format = 1"))
    finally:
        await engine.dispose()


@when('the operator runs "exactdocs reindex"')
def step_reindex(context: Context) -> None:
    asyncio.run(_age_index(context.settings))
    assert context.client.get("/api/health").json()["reindex_required"]
    context.searched_before = _search(context)
    assert context.searched_before
    env = {**os.environ, "EXACTDOCS_DATA_DIR": str(context.settings.data_dir)}
    env.pop("EXACTDOCS_DATABASE_URL", None)
    process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, "reindex"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    context.searched_during = []
    deadline = time.monotonic() + 120
    while process.poll() is None and time.monotonic() < deadline:
        context.searched_during.append(_search(context))  # the server answers meanwhile
    context.reindex_out, context.reindex_err = process.communicate(timeout=60)
    context.reindex_code = process.returncode


@then("a new index is built while the old one keeps answering, then swapped")
def step_swapped(context: Context) -> None:
    assert context.reindex_code == 0, context.reindex_err
    assert "Search index rebuilt in format" in context.reindex_out, context.reindex_out
    assert "was format 1" in context.reindex_out, context.reindex_out
    assert context.searched_during, "no search ran while reindex did"
    assert all(found == context.searched_before for found in context.searched_during)
    assert _search(context) == context.searched_before
    health = context.client.get("/api/health").json()
    assert not health["reindex_required"], health
