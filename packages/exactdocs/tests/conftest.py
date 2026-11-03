from collections.abc import Generator
from pathlib import Path

import pytest
from fixture_repo import DocsRepo, served

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import Library, LibraryName, Version

DEMO_LIBRARIES = [
    Library(name=LibraryName("/fastapi/fastapi"), versions=frozenset({Version("0.115")})),
    Library(name=LibraryName("/reactjs/react.dev"), versions=frozenset({Version("19.1")})),
]


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real data directory: every test starts on an empty one."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EXACTDOCS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("EXACTDOCS_DATABASE_URL", raising=False)
    return data_dir


@pytest.fixture
async def demo_catalog() -> None:
    """Store the demo libraries in the data directory, as an earlier run of the app would have."""
    container = Container.build(Settings())
    async with container.running():
        repository = SqliteLibraryRepository(container.engine)
        for library in DEMO_LIBRARIES:
            await repository.save(library)


@pytest.fixture(scope="session")
def docs_repo(tmp_path_factory: pytest.TempPathFactory) -> Generator[DocsRepo]:
    """The fixture docs repository, built once per run.

    Yields:
        The repository path and its ``file://`` and HTTP URLs.
    """
    with served(tmp_path_factory.mktemp("fixtures")) as repo:
        yield repo
