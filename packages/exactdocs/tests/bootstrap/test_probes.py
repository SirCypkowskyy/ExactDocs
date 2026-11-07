"""Liveness and readiness probes: unauthenticated, and only readiness follows the database."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from exactdocs import __version__
from exactdocs.bootstrap.constants import (
    HEALTH_ALIAS_PATH,
    LIVENESS_PATH,
    PROBE_PATHS,
    READINESS_PATH,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings


@pytest.fixture
def database_dir(tmp_path: Path) -> Path:
    """Folder holding nothing but the database, so a test can take it away.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The folder.
    """
    return tmp_path / "database"


@pytest.fixture
def container(tmp_path: Path, database_dir: Path) -> Container:
    """A fresh instance (no account yet) whose database sits in ``database_dir``.

    Args:
        tmp_path: The test's temporary directory, used as data directory.
        database_dir: Where the database file goes.

    Returns:
        The container.
    """
    url = f"sqlite:///{(database_dir / 'exactdocs.db').as_posix()}"
    return Container.build(Settings(data_dir=tmp_path, database_url=url))


@pytest.fixture
async def anonymous(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """A client with no cookie and no token, like an orchestrator.

    Args:
        container: The instance to serve.

    Yields:
        The client.
    """
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        yield client


async def _make_unreachable(container: Container, database_dir: Path) -> None:
    """Remove the database and close the pooled connections, so no connection can be made.

    Args:
        container: The running instance.
        database_dir: The folder of its database.
    """
    shutil.rmtree(database_dir)
    await container.engine.dispose()


async def test_liveness_answers_without_sign_in_before_setup(
    anonymous: httpx.AsyncClient,
) -> None:
    response = await anonymous.get(LIVENESS_PATH)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["version"], body["database_reachable"]) == (
        "ok",
        __version__,
        True,
    )
    assert body["schema_revision"]


async def test_the_old_health_path_is_an_alias_of_liveness(anonymous: httpx.AsyncClient) -> None:
    alias = await anonymous.get(HEALTH_ALIAS_PATH)
    liveness = await anonymous.get(LIVENESS_PATH)

    assert alias.status_code == liveness.status_code == 200
    assert alias.json() == liveness.json()


async def test_readiness_answers_ready_without_sign_in(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.get(READINESS_PATH)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reason": None}


async def test_an_unreachable_database_is_not_ready_but_alive(
    anonymous: httpx.AsyncClient, container: Container, database_dir: Path
) -> None:
    await _make_unreachable(container, database_dir)

    readiness = await anonymous.get(READINESS_PATH)
    liveness = await anonymous.get(LIVENESS_PATH)
    alias = await anonymous.get(HEALTH_ALIAS_PATH)

    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"
    assert readiness.json()["reason"]
    assert str(database_dir) not in readiness.text  # unauthenticated: no paths
    assert liveness.status_code == alias.status_code == 200
    body = liveness.json()
    assert (body["status"], body["database_reachable"], body["schema_revision"]) == (
        "ok",
        False,
        None,
    )
    assert (body["search_index_format"], body["reindex_required"]) == (None, False)


async def test_probes_still_check_the_host(anonymous: httpx.AsyncClient) -> None:
    for path in sorted(PROBE_PATHS):
        response = await anonymous.get(path, headers={"host": "evil.example"})
        assert response.status_code == 400, path
