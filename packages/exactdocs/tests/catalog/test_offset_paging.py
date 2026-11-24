"""Jumping to any page of the catalog's lists (#509): libraries, versions and articles."""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    ListArticlesQuery,
    ListLibrariesQuery,
    ListVersionsQuery,
    StoreManifestCommand,
)
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.catalog.module import CatalogModule
from exactdocs_kernel import MAX_OFFSET, CursorWithOffsetError

type Page = tuple[list[Any], str | None, int]
type Fetch = Callable[[CatalogModule, dict[str, Any]], Awaitable[Page]]


def version(ref: str, kind: RefKind, hour: int) -> Version:
    sha = hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest()
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=ref.ljust(40, "0") if kind is RefKind.COMMIT else sha,
        imported_at=datetime(2026, 11, 4, hour, tzinfo=UTC),
    )


def library(name: str, *versions: Version) -> Library:
    return Library(
        id=LibraryId(f"/acme/{name}"),
        title=name.title(),
        source_url=f"https://github.com/acme/{name}",
        host=HostKind.GITHUB,
        default_branch=VersionRef("main"),
        versions=frozenset(versions),
    )


def article(path: str, size: int) -> ArticleIn:
    return ArticleIn(
        path=path,
        blob_sha=hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest(),
        content_version=1,
        title=path,
        content="x" * size,
    )


@pytest.fixture
async def catalog() -> CatalogModule:
    repository = InMemoryLibraryRepository.of(
        [
            library(
                "payments",
                *(version(f"v1.{n}.0", RefKind.TAG, 10 + n % 3) for n in range(6)),
                version("main", RefKind.BRANCH, 11),
                version("next", RefKind.BRANCH, 12),
                version("1234abc1", RefKind.COMMIT, 9),
            ),
            *(library(name, version("main", RefKind.BRANCH, 8)) for name in ("ledger", "audit")),
            library("billing", version("main", RefKind.BRANCH, 8), version("v2", RefKind.TAG, 8)),
            library("empty"),
            library("notes"),
        ]
    )
    manifests = InMemoryManifestRepository(libraries=repository)
    catalog = CatalogModule.build(
        repository=repository,
        manifests=manifests,
        imported_tags=InMemoryImportedTags(repository=manifests),
        copier=InMemoryManifestCopier(repository=manifests),
        stored_articles=InMemoryStoredArticles(repository=manifests),
    )
    paths = ["guide/a.md", "guide/b.md", "api/c.md", "guide/d.md", "e.md", "guide/f.md"]
    stored = await catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref="main",
            kind=RefKind.BRANCH,
            commit_sha="c" * 40,
            # sizes repeat, so the path breaks ties
            articles=[article(path, size=n % 3 + 1) for n, path in enumerate(paths)],
        )
    )
    await catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))
    return catalog


async def libraries(catalog: CatalogModule, query: dict[str, Any]) -> Page:
    page = await catalog.list_libraries(
        ListLibrariesQuery.model_validate({"sort": "-version_count", **query})
    )
    return [lib.id for lib in page.libraries], page.next_cursor, page.total


async def versions(catalog: CatalogModule, query: dict[str, Any]) -> Page:
    page = await catalog.list_versions(
        ListVersionsQuery.model_validate(
            {"id": "/acme/payments", "kind": ["tag", "branch"], "sort": "-imported_at", **query}
        )
    )
    return [v.ref for v in page.versions], page.next_cursor, page.total


async def articles(catalog: CatalogModule, query: dict[str, Any]) -> Page:
    page = await catalog.list_articles(
        ListArticlesQuery.model_validate(
            {"library": "/acme/payments", "ref": "main", "q": "GUIDE", "sort": "-size", **query}
        )
    )
    return [a.path for a in page.articles], page.next_cursor, page.total


LISTS = [
    pytest.param(libraries, id="libraries"),
    pytest.param(versions, id="versions"),
    pytest.param(articles, id="articles"),
]


async def cursor_walk(catalog: CatalogModule, fetch: Fetch) -> list[Any]:
    found, cursor = [], None
    while True:
        items, cursor, _ = await fetch(catalog, {"limit": 2, "cursor": cursor})
        found += items
        if cursor is None:
            return found


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_at_an_offset_is_the_slice_of_the_cursor_walk(
    catalog: CatalogModule, fetch: Fetch
) -> None:
    walked = await cursor_walk(catalog, fetch)
    assert len(walked) > 3

    for offset in range(len(walked) + 2):
        items, next_cursor, total = await fetch(catalog, {"limit": 3, "offset": offset})

        assert items == walked[offset : offset + 3], offset
        assert total == len(walked)
        assert (next_cursor is None) == (offset + 3 >= len(walked))


@pytest.mark.parametrize("fetch", LISTS)
async def test_the_cursor_of_a_page_at_an_offset_goes_on_from_its_last_item(
    catalog: CatalogModule, fetch: Fetch
) -> None:
    walked = await cursor_walk(catalog, fetch)
    _, next_cursor, _ = await fetch(catalog, {"limit": 2, "offset": 1})

    items, _, _ = await fetch(catalog, {"limit": 2, "cursor": next_cursor})

    assert items == walked[3:5]


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_after_a_cursor_and_at_an_offset_is_refused(
    catalog: CatalogModule, fetch: Fetch
) -> None:
    _, cursor, _ = await fetch(catalog, {"limit": 1})

    with pytest.raises(CursorWithOffsetError):
        await fetch(catalog, {"limit": 1, "cursor": cursor, "offset": 0})


@pytest.mark.parametrize("fetch", LISTS)
@pytest.mark.parametrize("offset", [-1, MAX_OFFSET + 1])
async def test_an_offset_out_of_bounds_is_refused(
    catalog: CatalogModule, fetch: Fetch, offset: int
) -> None:
    with pytest.raises(ValidationError, match="offset"):
        await fetch(catalog, {"offset": offset})
