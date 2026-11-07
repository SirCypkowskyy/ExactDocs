"""Liveness and readiness probes: unauthenticated, and only readiness follows the database."""

import asyncio
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
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
from exactdocs.bootstrap.database import schema_head
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

LIVENESS = (LIVENESS_PATH, HEALTH_ALIAS_PATH)
"""The liveness probe and its alias."""
FAST_SECONDS = 1.0
"""Kubernetes' default probe timeout: liveness must answer well within it."""
MAX_POOL = 100
"""More connections than any pool here hands out."""
CHECKOUT_SECONDS = 0.5
"""A checkout waiting this long means the pool is drained."""


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


def _has(path: Path) -> bool:
    """Tell whether a path exists.

    Args:
        path: The path.

    Returns:
        Whether it exists.
    """
    return path.exists()


def _files(folder: Path) -> list[str]:
    """List a folder's file names.

    Args:
        folder: The folder.

    Returns:
        The sorted names.
    """
    return sorted(file.name for file in folder.iterdir())


def _remove_database_files(folder: Path) -> None:
    """Delete the database and its WAL files, keeping the folder (a lost or remounted volume).

    Args:
        folder: The database's folder.
    """
    for file in folder.glob("exactdocs.db*"):
        file.unlink()


async def _hold_every_connection(container: Container, stack: AsyncExitStack) -> None:
    """Check out connections until the pool has none left, as a burst of requests could.

    Args:
        container: The instance whose pool to drain.
        stack: Holds the connections until it is closed.
    """
    for _ in range(MAX_POOL):
        try:
            async with asyncio.timeout(CHECKOUT_SECONDS):
                await stack.enter_async_context(container.engine.connect())
        except TimeoutError:
            return
    pytest.fail(f"the pool handed out more than {MAX_POOL} connections")


def _assert_unknown(body: dict[str, object]) -> None:
    """Check a liveness body says it is up but knows nothing of the database.

    Args:
        body: The liveness response body.
    """
    assert (body["status"], body["version"], body["database_reachable"]) == (
        "ok",
        __version__,
        False,
    )
    assert (body["schema_revision"], body["search_index_format"], body["reindex_required"]) == (
        None,
        None,
        None,
    )
    assert body["search_engine"] is None


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
    assert body["schema_revision"] == schema_head()
    assert body["reindex_required"] is False


async def test_the_old_health_path_is_an_alias_of_liveness(anonymous: httpx.AsyncClient) -> None:
    alias = await anonymous.get(HEALTH_ALIAS_PATH)
    liveness = await anonymous.get(LIVENESS_PATH)

    assert alias.status_code == liveness.status_code == 200
    assert alias.json() == liveness.json()


async def test_readiness_answers_ready_without_sign_in(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.get(READINESS_PATH)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reason": None}


@pytest.mark.parametrize("path", sorted(PROBE_PATHS))
async def test_probes_answer_head(anonymous: httpx.AsyncClient, path: str) -> None:
    response = await anonymous.head(path)

    assert response.status_code == 200
    assert not response.content


async def test_an_unreachable_database_is_not_ready_but_alive(
    anonymous: httpx.AsyncClient, container: Container, database_dir: Path
) -> None:
    shutil.rmtree(database_dir)
    await container.engine.dispose()

    readiness = await anonymous.get(READINESS_PATH)

    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"
    assert str(database_dir) not in readiness.text  # unauthenticated: no paths
    for path in LIVENESS:
        liveness = await anonymous.get(path)
        assert liveness.status_code == 200
        _assert_unknown(liveness.json())
    assert not _has(database_dir)


async def test_deleted_database_files_are_not_ready_and_not_recreated(
    anonymous: httpx.AsyncClient, container: Container, database_dir: Path
) -> None:
    await container.engine.dispose()
    _remove_database_files(database_dir)

    readiness = await anonymous.get(READINESS_PATH)
    liveness = await anonymous.get(LIVENESS_PATH)

    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready", "reason": "the database file is missing"}
    assert liveness.status_code == 200
    _assert_unknown(liveness.json())
    assert _has(database_dir)
    assert _files(database_dir) == []  # the probes created no empty database


async def test_a_database_not_at_this_schema_is_not_ready(
    anonymous: httpx.AsyncClient, container: Container
) -> None:
    async with container.engine.begin() as connection:
        await connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'elsewhere'")

    readiness = await anonymous.get(READINESS_PATH)

    assert readiness.status_code == 503
    assert readiness.json()["reason"] == "the database is not at this version's schema"


async def test_liveness_answers_fast_while_every_connection_is_busy(
    anonymous: httpx.AsyncClient, container: Container
) -> None:
    async with AsyncExitStack() as stack:
        await _hold_every_connection(container, stack)
        started = time.monotonic()
        liveness = await anonymous.get(LIVENESS_PATH)
        elapsed = time.monotonic() - started

    assert liveness.status_code == 200
    assert elapsed < FAST_SECONDS
    _assert_unknown(liveness.json())


@pytest.mark.parametrize("path", LIVENESS)
async def test_an_untrusted_host_learns_only_that_it_is_up(
    anonymous: httpx.AsyncClient, path: str
) -> None:
    response = await anonymous.get(path, headers={"host": "10.1.2.3:3000"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_an_untrusted_host_gets_readiness(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.get(READINESS_PATH, headers={"host": "10.1.2.3:3000"})

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "reason": None}


@pytest.mark.parametrize("path", LIVENESS)
async def test_a_trusted_host_gets_the_details(anonymous: httpx.AsyncClient, path: str) -> None:
    response = await anonymous.get(path, headers={"host": "127.0.0.1:3000"})

    assert response.status_code == 200
    assert response.json()["version"] == __version__
    assert response.json()["database_reachable"] is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/session"),
        ("POST", LIVENESS_PATH),
        ("OPTIONS", LIVENESS_PATH),
        ("GET", f"{READINESS_PATH}/"),
        ("GET", f"/{LIVENESS_PATH}"),
    ],
)
async def test_only_exact_probe_requests_skip_the_host_check(
    anonymous: httpx.AsyncClient, method: str, path: str
) -> None:
    # A raw path: httpx would read a leading `//` as a host name.
    url = httpx.URL("http://localhost").copy_with(raw_path=path.encode())
    response = await anonymous.request(method, url, headers={"host": "10.1.2.3:3000"})

    assert response.status_code == 400


async def test_a_query_string_is_still_a_probe(anonymous: httpx.AsyncClient) -> None:
    response = await anonymous.get(LIVENESS_PATH, params={"x": ""}, headers={"host": "10.1.2.3"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
