"""The engine under test: the fixture docs repository, imported for real, behind ``SearchDocs``.

To run the suite on another engine (hybrid retrieval, ParadeDB), add its name to ``ENGINES`` and
build its ``Container`` in ``open_container``: the cases and the assertions do not change.
``postgres_fts`` (PostgreSQL full-text search) runs when ``EXACTDOCS_TEST_POSTGRES_URL`` is set, and
``postgres_fts_c`` runs it again on a database in the ``C`` locale. ``pg_search`` (ParadeDB's BM25)
runs with ``EXACTDOCS_TEST_PG_SEARCH=1`` (a server with the extension, as CI's ParadeDB); the app
chooses it by itself, as in production, and the suite checks that it did.
``hybrid`` is FTS5 fused with sqlite-vec vectors (RRF), every version embedded by the in-process
term-hash stand-in (``offline_embedding``): the fusion must keep every expected section where BM25
puts it. ``hybrid_pg`` is the same on PostgreSQL (full-text search and pgvector), when the server
is set. An engine in ``VECTOR_ENGINES`` always has a vector half, so a case that expects no answer
only asks that nothing of another version comes back (the eval's rule for ``hits: []``).
"""

import asyncio
from collections.abc import AsyncIterator, Generator
from contextlib import ExitStack
from pathlib import Path

import pytest

from databases import ADMIN_URL, PG_SEARCH, SECRET_KEY, postgres_database
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.ports.driving import SearchAllLibraries, SearchDocs
from fixture_import import embed_fixture, import_fixture
from fixture_repo import DocsRepo
from offline_embedding import offline_container

ENGINES = [
    "fts5",
    "hybrid",
    *(["postgres_fts", "postgres_fts_c", "hybrid_pg"] if ADMIN_URL else []),
    *(["pg_search"] if PG_SEARCH else []),
]
VECTOR_ENGINES = frozenset({"hybrid", "hybrid_pg"})
"""Engines with a vector half: the nearest chunks come back even when no word matches."""
SEARCH_ENGINES = {"hybrid": "fts5", "hybrid_pg": "postgres_fts", "postgres_fts_c": "postgres_fts"}
"""The full-text engine the app must choose for an engine under test (by default its own name)."""
_DATABASES: dict[str, str] = {}  # engine -> database URL, for the engines that have one


def open_container(engine: str, data_dir: Path) -> Container:
    """The app's container for ``engine``; every engine shares the import and the search port."""
    assert engine in ENGINES, engine
    if engine in _DATABASES:
        settings = Settings(
            data_dir=data_dir, database_url=_DATABASES[engine], secret_key=SECRET_KEY
        )
    else:
        settings = Settings(data_dir=data_dir)
    if engine in VECTOR_ENGINES:
        return offline_container(settings)
    return Container.build(settings)


async def _import_all(engine: str, data_dir: Path, docs_repo: DocsRepo) -> None:
    container = open_container(engine, data_dir)
    async with container.running(jobs=False):
        state = await container.retrieval.get_search_index_state()
        assert state.engine == SEARCH_ENGINES.get(engine, engine), state  # the app's choice
        await import_fixture(container, docs_repo)
        if engine in VECTOR_ENGINES:
            assert await embed_fixture(container) == 3, "every version is embedded"


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
        if request.param not in {"fts5", "hybrid"}:
            database = postgres_database(
                c_locale=request.param.endswith("_c"), pg_search=request.param == "pg_search"
            )
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


@pytest.fixture
def vector_half(imported: tuple[str, Path]) -> bool:
    """Say whether the engine under test has a vector half (``VECTOR_ENGINES``).

    Returns:
        True for the hybrid engines.
    """
    return imported[0] in VECTOR_ENGINES
