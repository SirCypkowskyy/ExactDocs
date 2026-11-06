"""Editing a library's settings in the catalog, and re-tagging what its versions serve."""

import hashlib

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    ArticleTags,
    GetArticleQuery,
    GetLibraryQuery,
    GetVersionTagsQuery,
    SetImportedTagsCommand,
    SetLibrarySettingsCommand,
    SetManualTagsCommand,
    StoreManifestCommand,
    TagRuleIn,
)
from exactdocs.catalog.errors import (
    InvalidSettingsError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ChunkingConfig,
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    RefKind,
)
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/payments"
CHUNKING = ChunkingConfig(split_level=3)


def sha(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


def article(path: str, *tags: str, front_matter: dict | None = None) -> ArticleIn:
    return ArticleIn(
        path=path,
        blob_sha=sha(path),
        content_version=1,
        title=path,
        tags=list(tags),
        front_matter=front_matter or {},
        content=f"# {path}",
    )


@pytest.fixture
def catalog() -> CatalogModule:
    libraries = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="Payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                settings=LibrarySettings(include_paths=("docs/",), chunking=CHUNKING),
            )
        ]
    )
    manifests = InMemoryManifestRepository(libraries)
    return CatalogModule.build(
        repository=libraries,
        manifests=manifests,
        imported_tags=InMemoryImportedTags(manifests),
        stored_articles=InMemoryStoredArticles(manifests),
    )


async def publish(catalog: CatalogModule, ref: str, *articles: ArticleIn) -> str:
    stored = await catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY, ref=ref, kind=RefKind.TAG, commit_sha=sha(ref), articles=list(articles)
        )
    )
    await catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))
    return stored.manifest_id


async def test_settings_replace_paths_and_tag_rules_and_keep_chunking(catalog):
    detail = await catalog.set_library_settings(
        SetLibrarySettingsCommand(
            id=LIBRARY,
            include_paths=["guide/"],
            exclude_paths=["guide/old/**"],
            tag_rules=[TagRuleIn(pattern="guide/api/**", tag="api")],
        )
    )

    stored = await catalog.get_library(GetLibraryQuery(id=LIBRARY))
    assert detail.settings == stored.settings
    assert stored.settings.include_paths == ["guide/"]
    assert stored.settings.exclude_paths == ["guide/old/**"]
    assert [(r.pattern, r.tag) for r in stored.settings.tag_rules] == [("guide/api/**", "api")]
    assert stored.settings.chunking.split_level == CHUNKING.split_level


async def test_settings_of_an_unknown_library_are_refused(catalog):
    with pytest.raises(LibraryNotFoundError):
        await catalog.set_library_settings(SetLibrarySettingsCommand(id="/acme/nope"))


async def test_a_tag_that_cannot_be_one_is_refused(catalog):
    with pytest.raises(InvalidSettingsError):
        await catalog.set_library_settings(
            SetLibrarySettingsCommand(id=LIBRARY, tag_rules=[TagRuleIn(pattern="a", tag="a b")])
        )


async def test_version_tags_list_every_article_with_its_tag_sources(catalog, monkeypatch):
    monkeypatch.setattr("exactdocs.catalog.use_cases.TAG_SOURCE_PAGE", 2)  # several pages
    manifest_id = await publish(
        catalog,
        "v1",
        article("docs/a.md", "auth", front_matter={"tags": ["Auth"]}),
        article("docs/b.md"),
        article("docs/c.md", "x"),
    )
    await catalog.set_manual_tags(
        SetManualTagsCommand(library=LIBRARY, path="docs/b.md", tags=["m"])
    )

    found = await catalog.get_version_tags(GetVersionTagsQuery(library=LIBRARY, ref="v1"))

    assert found.manifest_id == manifest_id
    assert [(a.path, a.front_matter, a.tags) for a in found.articles] == [
        ("docs/a.md", {"tags": ["Auth"]}, ["auth"]),
        ("docs/b.md", {}, []),  # manual tags are not imported ones
        ("docs/c.md", {}, ["x"]),
    ]


async def test_version_tags_need_an_exact_known_ref(catalog):
    await publish(catalog, "v1.0.0", article("docs/a.md"))

    with pytest.raises(VersionNotFoundError):
        await catalog.get_version_tags(GetVersionTagsQuery(library=LIBRARY, ref="v1"))
    with pytest.raises(LibraryNotFoundError):
        await catalog.get_version_tags(GetVersionTagsQuery(library="/acme/nope", ref="v1.0.0"))


async def test_imported_tags_are_replaced_and_listings_see_them_with_manual_ones(catalog):
    manifest_id = await publish(catalog, "v1", article("docs/a.md", "old"), article("docs/b.md"))
    await catalog.set_manual_tags(
        SetManualTagsCommand(library=LIBRARY, path="docs/a.md", tags=["m"])
    )

    retagged = await catalog.set_imported_tags(
        SetImportedTagsCommand(
            manifest_id=manifest_id,
            articles=[
                ArticleTags(path="docs/a.md", tags=["new"]),
                ArticleTags(path="x.md", tags=[]),
            ],
        )
    )

    assert [(a.path, a.tags) for a in retagged.articles] == [("docs/a.md", ["new", "m"])]
    shown = await catalog.get_article(GetArticleQuery(library=LIBRARY, ref="v1", path="docs/a.md"))
    assert shown.tags == ["new", "m"]


async def test_imported_tags_of_an_unknown_manifest_are_refused(catalog):
    with pytest.raises(ManifestNotFoundError):
        await catalog.set_imported_tags(SetImportedTagsCommand(manifest_id="nope", articles=[]))
