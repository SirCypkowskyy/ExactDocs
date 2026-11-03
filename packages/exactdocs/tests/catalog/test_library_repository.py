"""Adapter contract: every ``LibraryRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator

import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import InMemoryLibraryRepository
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import Library, LibraryName, Version
from exactdocs.catalog.ports import LibraryRepository

REACT = Library(
    name=LibraryName("/reactjs/react.dev"), versions=frozenset({Version("19.1"), Version("18.3")})
)
FASTAPI = Library(name=LibraryName("/fastapi/fastapi"), versions=frozenset({Version("0.115")}))


@pytest.fixture(params=["memory", "sqlite"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[LibraryRepository]:
    if request.param == "memory":
        yield InMemoryLibraryRepository()
        return
    container = Container.build(Settings())
    async with container.running():
        yield SqliteLibraryRepository(container.engine)


async def test_starts_empty(repository: LibraryRepository) -> None:
    assert await repository.list_all() == ()
    assert await repository.get(REACT.name) is None


async def test_saved_library_is_returned_by_name_and_listed(repository: LibraryRepository) -> None:
    await repository.save(REACT)
    await repository.save(FASTAPI)

    assert await repository.get(REACT.name) == REACT
    assert set(await repository.list_all()) == {REACT, FASTAPI}


async def test_get_needs_the_exact_name(repository: LibraryRepository) -> None:
    await repository.save(REACT)

    assert await repository.get(LibraryName("/reactjs/react")) is None


async def test_saving_again_replaces_the_versions(repository: LibraryRepository) -> None:
    await repository.save(REACT)
    newer = Library(name=REACT.name, versions=frozenset({Version("19.2")}))

    await repository.save(newer)

    assert await repository.get(REACT.name) == newer
    assert await repository.list_all() == (newer,)


async def test_a_library_without_versions_is_kept(repository: LibraryRepository) -> None:
    bare = Library(name=LibraryName("/vuejs/docs"))

    await repository.save(bare)

    assert await repository.get(bare.name) == bare
