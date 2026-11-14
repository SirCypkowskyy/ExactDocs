"""Other domains read article titles by path, one query per batch (RET-01's embedding input)."""

import hashlib
from collections.abc import AsyncIterator

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryArticleTitles,
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ArticleIn, GetArticleTitlesQuery, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, VersionRef
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/docs"


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def catalog(request: pytest.FixtureRequest) -> AsyncIterator[CatalogModule]:
    """The catalog in memory and on each SQL database.

    Yields:
        The catalog module.
    """
    library = Library(
        id=LibraryId(LIBRARY),
        title="Docs",
        source_url="https://github.com/acme/docs",
        host=HostKind.GITHUB,
        default_branch=VersionRef("main"),
    )
    if request.param == "memory":
        libraries = InMemoryLibraryRepository(libraries={library.id: library})
        manifests = InMemoryManifestRepository(libraries=libraries)
        yield CatalogModule.build(
            repository=libraries,
            manifests=manifests,
            imported_tags=InMemoryImportedTags(repository=manifests),
            copier=InMemoryManifestCopier(repository=manifests),
            stored_articles=InMemoryStoredArticles(repository=manifests),
            article_titles=InMemoryArticleTitles(repository=manifests),
        )
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        await SqliteLibraryRepository(engine=container.engine).save(library)
        yield container.catalog


def _article(path: str, title: str) -> ArticleIn:
    blob = hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest()
    return ArticleIn(
        path=path, blob_sha=blob, content_version=1, title=title, tags=[], content="# T\n\nText."
    )


async def test_titles_are_read_by_path_from_one_manifest(catalog: CatalogModule) -> None:
    stored = await catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref="v1",
            kind=RefKind.TAG,
            commit_sha="a" * 40,
            articles=[_article("docs/a.md", "Alpha"), _article("docs/b.md", "Beta")],
        )
    )

    found = await catalog.get_article_titles(
        GetArticleTitlesQuery(manifest_id=stored.manifest_id, paths=["docs/b.md", "docs/zz.md"])
    )
    unknown = await catalog.get_article_titles(
        GetArticleTitlesQuery(manifest_id="gone", paths=["docs/a.md"])
    )

    assert found.titles == {"docs/b.md": "Beta"}
    assert unknown.titles == {}
