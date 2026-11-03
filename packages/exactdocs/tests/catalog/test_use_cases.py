import pytest

from exactdocs.catalog.adapters.driven.memory import InMemoryLibraryRepository
from exactdocs.catalog.dtos import GetLibraryQuery, ListLibrariesQuery
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import Library, LibraryName, Version
from exactdocs.catalog.module import CatalogModule
from exactdocs.catalog.ports import LibraryRepository


@pytest.fixture
def catalog() -> CatalogModule:
    repository: LibraryRepository = InMemoryLibraryRepository.of(
        [
            Library(
                name=LibraryName("react"), versions=frozenset({Version("19.1"), Version("18.3")})
            ),
            Library(name=LibraryName("fastapi"), versions=frozenset({Version("0.115")})),
        ]
    )
    return CatalogModule.build(repository=repository)


async def test_lists_libraries_sorted_by_name_with_sorted_versions(catalog: CatalogModule) -> None:
    result = await catalog.list_libraries(ListLibrariesQuery())

    assert [(lib.name, lib.versions) for lib in result.libraries] == [
        ("fastapi", ["0.115"]),
        ("react", ["18.3", "19.1"]),
    ]


async def test_get_library_raises_for_unknown_name(catalog: CatalogModule) -> None:
    with pytest.raises(LibraryNotFoundError):
        await catalog.get_library(GetLibraryQuery(name="vue"))


def test_version_is_an_exact_filter() -> None:
    library = Library(name=LibraryName("react"), versions=frozenset({Version("19.1")}))

    assert library.has_version(Version("19.1"))
    assert not library.has_version(Version("19"))


async def test_libraries_are_listed_page_by_page_with_an_opaque_cursor(
    catalog: CatalogModule,
) -> None:
    first = await catalog.list_libraries(ListLibrariesQuery(limit=1))
    second = await catalog.list_libraries(ListLibrariesQuery(limit=1, cursor=first.next_cursor))

    assert [lib.name for lib in first.libraries] == ["fastapi"]
    assert [lib.name for lib in second.libraries] == ["react"]
    assert second.next_cursor is None
