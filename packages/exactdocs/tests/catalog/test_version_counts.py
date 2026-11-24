"""Article counts on the version and library lists (#513), on in-memory adapters."""

import hashlib
from dataclasses import dataclass

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryArticleCounts,
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    ListLibrariesQuery,
    ListVersionsQuery,
    StoreManifestCommand,
)
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/payments"


def _article(path: str) -> ArticleIn:
    return ArticleIn(
        path=path,
        blob_sha=hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest(),
        content_version=1,
        title=path,
        content=f"# {path}",
    )


@dataclass(slots=True)
class World:
    catalog: CatalogModule

    async def store(self, ref: str, articles: int, *, library: str = LIBRARY) -> str:
        stored = await self.catalog.store_manifest(
            StoreManifestCommand(
                library=library,
                ref=ref,
                kind=RefKind.TAG,
                commit_sha=hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest(),
                articles=[_article(f"docs/{ref}/{n}.md") for n in range(articles)],
            )
        )
        return stored.manifest_id

    async def import_version(self, ref: str, articles: int, *, library: str = LIBRARY) -> None:
        manifest_id = await self.store(ref, articles, library=library)
        await self.catalog.activate_manifest(ActivateManifestCommand(manifest_id=manifest_id))


@pytest.fixture(params=["adapter", "scan"])
def world(request: pytest.FixtureRequest) -> World:
    """A catalog counting through ``InMemoryArticleCounts``, or through the module's scan."""
    libraries = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(library),
                title=library,
                source_url=f"https://github.com{library}",
                host=HostKind.GITHUB,
            )
            for library in (LIBRARY, "/acme/empty")
        ]
    )
    manifests = InMemoryManifestRepository(libraries=libraries)
    counts = InMemoryArticleCounts(manifests=manifests) if request.param == "adapter" else None
    catalog = CatalogModule.build(
        repository=libraries,
        manifests=manifests,
        imported_tags=InMemoryImportedTags(repository=manifests),
        copier=InMemoryManifestCopier(repository=manifests),
        stored_articles=InMemoryStoredArticles(repository=manifests),
        article_counts=counts,
    )
    return World(catalog=catalog)


async def test_each_listed_version_carries_its_active_manifests_article_count(
    world: World,
) -> None:
    await world.import_version("v1.0.0", 3)
    await world.import_version("v2.0.0", 5)
    await world.store("v2.0.0", 9)  # pending: not served yet, so not counted

    listed = await world.catalog.list_versions(ListVersionsQuery(id=LIBRARY))

    assert [(v.ref, v.articles) for v in listed.versions] == [("v1.0.0", 3), ("v2.0.0", 5)]
    # The chunk counts are retrieval's: the catalog alone leaves them at 0.
    assert {(v.chunks, v.embedded_chunks) for v in listed.versions} == {(0, 0)}


async def test_the_counts_follow_the_page(world: World) -> None:
    for n in range(1, 6):
        await world.import_version(f"v{n}.0.0", n)

    listed = await world.catalog.list_versions(ListVersionsQuery(id=LIBRARY, limit=2, sort="-ref"))

    assert [(v.ref, v.articles) for v in listed.versions] == [("v5.0.0", 5), ("v4.0.0", 4)]


async def test_a_library_carries_its_default_versions_article_count_and_0_without_one(
    world: World,
) -> None:
    await world.import_version("v1.0.0", 3)
    await world.import_version("v2.0.0", 5)  # the newest tag: the default version

    listed = await world.catalog.list_libraries(ListLibrariesQuery())

    assert [(lib.id, lib.default_version, lib.article_count) for lib in listed.libraries] == [
        ("/acme/empty", None, 0),
        (LIBRARY, "v2.0.0", 5),
    ]


async def test_the_counts_are_in_the_serialized_lists(world: World) -> None:
    await world.import_version("v1.0.0", 2)

    versions = await world.catalog.list_versions(ListVersionsQuery(id=LIBRARY))
    libraries = await world.catalog.list_libraries(ListLibrariesQuery())

    (version,) = versions.model_dump(mode="json")["versions"]
    assert {k: version[k] for k in ("articles", "chunks", "embedded_chunks")} == {
        "articles": 2,
        "chunks": 0,
        "embedded_chunks": 0,
    }
    assert [lib["article_count"] for lib in libraries.model_dump(mode="json")["libraries"]] == [
        0,
        2,
    ]
