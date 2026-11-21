"""The `ai_enabled` filter of the libraries list becomes the IDs the catalog lists or skips."""

from dataclasses import dataclass, field

from exactdocs.bootstrap.library_filters import ListLibrariesByAi
from exactdocs.catalog.dtos import LibraryList, ListLibrariesQuery

OFF = frozenset({"/acme/off"})


@dataclass
class _Catalog:
    calls: list[tuple[frozenset[str] | None, frozenset[str]]] = field(default_factory=list)

    async def __call__(
        self,
        query: ListLibrariesQuery,
        *,
        only: frozenset[str] | None = None,
        without: frozenset[str] = frozenset(),
    ) -> LibraryList:
        del query
        self.calls.append((only, without))
        return LibraryList(libraries=[], next_cursor=None, total=0)


class _Settings:
    async def ai_disabled(self) -> frozenset[str]:
        return OFF


async def _run(ai_enabled: bool | None) -> tuple[frozenset[str] | None, frozenset[str]]:
    catalog = _Catalog()
    await ListLibrariesByAi(list_libraries=catalog, settings=_Settings())(  # ty: ignore[invalid-argument-type]
        ListLibrariesQuery(ai_enabled=ai_enabled)
    )
    return catalog.calls[0]


async def test_without_the_filter_the_catalog_lists_everything() -> None:
    assert await _run(None) == (None, frozenset())


async def test_ai_on_skips_the_libraries_with_ai_off() -> None:
    assert await _run(True) == (None, OFF)


async def test_ai_off_lists_only_the_libraries_with_ai_off() -> None:
    assert await _run(False) == (OFF, frozenset())
