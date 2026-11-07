"""The engine under test: the fixture docs repository, imported for real, behind ``SearchDocs``.

To run the suite on another engine (hybrid retrieval, ParadeDB), add its name to ``ENGINES`` and
build its ``Container`` in ``open_container``: the cases and the assertions do not change.
``postgres_fts`` (PostgreSQL full-text search) runs when ``EXACTDOCS_TEST_POSTGRES_URL`` is set, and
``postgres_fts_c`` runs it again on a database in the ``C`` locale.
"""

import asyncio
from collections.abc import AsyncIterator, Generator
from contextlib import ExitStack
from pathlib import Path

import pytest

from databases import ADMIN_URL, SECRET_KEY, postgres_database
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.ports.driving import SearchAllLibraries, SearchDocs
from fixture_import import import_fixture
from fixture_repo import DocsRepo

ENGINES = ["fts5", *(["postgres_fts", "postgres_fts_c"] if ADMIN_URL else [])]
_DATABASES: dict[str, str] = {}  # engine -> database URL, for the engines that have one


def open_container(engine: str, data_dir: Path) -> Container:
    """The app's container for ``engine``; every engine shares the import and the search port."""
    assert engine in ENGINES, engine
    if engine.startswith("postgres_fts"):
        return Container.build(
            Settings(data_dir=data_dir, database_url=_DATABASES[engine], secret_key=SECRET_KEY)
        )
    return Container.build(Settings(data_dir=data_dir))


async def _import_all(engine: str, data_dir: Path, docs_repo: DocsRepo) -> None:
    container = open_container(engine, data_dir)
    async with container.running(jobs=False):
        await import_fixture(container, docs_repo)


@pytest.fixture(scope="session", params=ENGINES)
def imported(
    request: pytest.FixtureRequest, docs_repo: DocsRepo, tmp_path_factory: pytest.TempPathFactory
) -> Generator[tuple[str, Path]]:
    """Import the three versions once per engine; tests reopen the same data directory.

    Yields:
        The engine's name and the data directory holding its imported versions.
    """
    data_dir = tmp_path_factory.mktemp("ranking")
    with ExitStack() as stack:
        if request.param.startswith("postgres_fts"):
            database = postgres_database(c_locale=request.param.endswith("_c"))
            _DATABASES[request.param] = stack.enter_context(database).url
        asyncio.run(_import_all(request.param, data_dir, docs_repo))
        yield request.param, data_dir


@pytest.fixture
async def search_docs(imported: tuple[str, Path]) -> AsyncIterator[SearchDocs]:
    """Open the engine under test.

    Yields:
        Its ``SearchDocs`` driving port.
    """
    engine, data_dir = imported
    container = open_container(engine, data_dir)
    async with container.running(jobs=False):
        yield container.retrieval.search_docs


@pytest.fixture
async def search_all(imported: tuple[str, Path]) -> AsyncIterator[SearchAllLibraries]:
    """Open the engine under test.

    Yields:
        Its ``SearchAllLibraries`` driving port.
    """
    engine, data_dir = imported
    container = open_container(engine, data_dir)
    async with container.running(jobs=False):
        yield container.retrieval.search_all_libraries
