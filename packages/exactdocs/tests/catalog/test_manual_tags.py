"""Manual tags: set per library and path, combined with imported tags, carried across renames."""

import hashlib

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ApplyManualTagsCommand,
    ArticleIn,
    GetArticleQuery,
    ListArticlesQuery,
    ListTagsQuery,
    ManualTagsOut,
    RenameIn,
    ReplaceRenamesCommand,
    SetManualTagsCommand,
    StoreManifestCommand,
    TagFilter,
)
from exactdocs.catalog.errors import (
    InvalidArticlePathError,
    InvalidManualTagsError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    ManifestEntry,
    ManualTag,
    ManualTags,
    RefKind,
)
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/payments"


def article(path: str, *tags: str) -> ArticleIn:
    return ArticleIn(
        path=path,
        blob_sha=hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest(),
        content_version=1,
        title=path,
        tags=list(tags),
        content=f"# {path}",
    )


def rename(from_ref: str, old: str, new: str) -> RenameIn:
    return RenameIn(from_ref=from_ref, old_path=old, new_path=new, similarity=90)


@pytest.fixture
def catalog() -> CatalogModule:
    libraries = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="Payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
            )
        ]
    )
    return CatalogModule.build(
        repository=libraries,
        manifests=(written := InMemoryManifestRepository(libraries=libraries)),
        imported_tags=InMemoryImportedTags(repository=written),
        copier=InMemoryManifestCopier(repository=written),
        stored_articles=InMemoryStoredArticles(repository=written),
    )


async def store(
    catalog: CatalogModule,
    ref: str,
    *articles: ArticleIn,
    renames: tuple[RenameIn, ...] = (),
    kind: RefKind = RefKind.TAG,
) -> str:
    stored = await catalog.store_manifest(
        StoreManifestCommand(
            library=LIBRARY,
            ref=ref,
            kind=kind,
            commit_sha=hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest(),
            articles=list(articles),
            renames=list(renames),
        )
    )
    return stored.manifest_id


async def publish(
    catalog: CatalogModule,
    ref: str,
    *articles: ArticleIn,
    renames: tuple[RenameIn, ...] = (),
    kind: RefKind = RefKind.TAG,
) -> str:
    """Store, apply manual tags and activate, as an import does."""
    manifest_id = await store(catalog, ref, *articles, renames=renames, kind=kind)
    await catalog.apply_manual_tags(ApplyManualTagsCommand(manifest_id=manifest_id))
    await catalog.activate_manifest(ActivateManifestCommand(manifest_id=manifest_id))
    return manifest_id


async def tag(catalog: CatalogModule, path: str, *tags: str) -> ManualTagsOut:
    return await catalog.set_manual_tags(
        SetManualTagsCommand(library=LIBRARY, path=path, tags=list(tags))
    )


async def tags_of(catalog: CatalogModule, ref: str, path: str) -> tuple[list[str], list[str]]:
    """Every tag of the article, and the manual ones (whatever path they were set on)."""
    found = await catalog.get_article(GetArticleQuery(library=LIBRARY, ref=ref, path=path))
    return found.tags, sorted({t.tag for t in found.manual_tags})


async def origins_of(catalog: CatalogModule, ref: str, path: str) -> list[tuple[str, str]]:
    """The article's manual tags with the path each was set on."""
    found = await catalog.get_article(GetArticleQuery(library=LIBRARY, ref=ref, path=path))
    return [(t.tag, t.path) for t in found.manual_tags]


def test_manual_tags_are_normalized_sorted_and_deduplicated() -> None:
    assert ManualTags.of("a.md", [" Onboarding ", "API", "api"]).tags == ("api", "onboarding")


@pytest.mark.parametrize("tags", [["#!?"], [""], [f"t{i}" for i in range(21)]])
def test_a_value_that_is_no_tag_or_too_many_is_refused(tags: list[str]) -> None:
    with pytest.raises(InvalidManualTagsError):
        ManualTags.of("a.md", tags)


@pytest.mark.parametrize("path", ["", "../a.md", "a//b.md", "./a.md"])
def test_a_path_outside_the_repository_is_refused(path: str) -> None:
    with pytest.raises(InvalidArticlePathError):
        ManualTags.of(path, ["x"])


def test_an_entry_shows_imported_tags_first_then_the_manual_ones_it_lacks() -> None:
    entry = ManifestEntry(
        path="a.md",
        blob_sha="a" * 40,
        content_version=1,
        title="A",
        tags=("guide", "api"),
        manual_tags=(
            ManualTag(tag="api", path="a.md"),
            ManualTag(tag="onboarding", path="a.md"),
            ManualTag(tag="onboarding", path="old.md"),
        ),
    )

    assert entry.all_tags == ("guide", "api", "onboarding")


def test_reaching_merges_the_tags_of_every_path_an_article_came_from() -> None:
    reached = ManualTags.reaching(
        {"c.md": {"b.md", "a.md"}}, {"a.md": ("x",), "b.md": ("y",), "z.md": ("z",)}
    )

    assert reached == {
        "c.md": (ManualTag(tag="x", path="a.md"), ManualTag(tag="y", path="b.md")),
        "a.md": (ManualTag(tag="x", path="a.md"),),
        "b.md": (ManualTag(tag="y", path="b.md"),),
        "z.md": (ManualTag(tag="z", path="z.md"),),
    }


def test_reaching_keeps_a_tag_once_for_each_path_it_was_set_on() -> None:
    reached = ManualTags.reaching({"b.md": {"a.md"}}, {"a.md": ("x",), "b.md": ("x", "y")})

    assert reached["b.md"] == (
        ManualTag(tag="x", path="a.md"),
        ManualTag(tag="x", path="b.md"),
        ManualTag(tag="y", path="b.md"),
    )


async def test_a_manual_tag_applies_to_every_version_and_combines_with_imported_tags(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1.3.0", article("guide/setup.md", "guide"), article("other.md"))
    await publish(catalog, "v1.4.0", article("guide/setup.md", "guide"))

    stored = await tag(catalog, "guide/setup.md", "Onboarding")

    assert stored.tags == ["onboarding"]
    for ref in ("v1.3.0", "v1.4.0"):
        assert await tags_of(catalog, ref, "guide/setup.md") == (
            ["guide", "onboarding"],
            ["onboarding"],
        )
    assert await tags_of(catalog, "v1.3.0", "other.md") == ([], [])


async def test_the_answer_names_each_touched_article_with_all_its_tags(
    catalog: CatalogModule,
) -> None:
    v13 = await publish(catalog, "v1.3.0", article("guide/setup.md", "guide"), article("b.md"))

    stored = await tag(catalog, "guide/setup.md", "onboarding")

    assert [(r.manifest_id, [(a.path, a.tags) for a in r.articles]) for r in stored.retagged] == [
        (v13, [("guide/setup.md", ["guide", "onboarding"])])
    ]


async def test_a_manual_tag_follows_a_rename_into_later_versions_only(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1.3.0", article("guide/setup.md"))
    await tag(catalog, "guide/setup.md", "onboarding")

    renamed = (rename("v1.3.0", "guide/setup.md", "guide/install.md"),)
    await publish(catalog, "v1.4.0", article("guide/install.md"), renames=renamed)

    assert await tags_of(catalog, "v1.4.0", "guide/install.md") == (
        ["onboarding"],
        ["onboarding"],
    )
    await tag(catalog, "guide/install.md", "later")
    # The new name's tag does not travel back to the old version.
    assert await tags_of(catalog, "v1.3.0", "guide/setup.md") == (
        ["onboarding"],
        ["onboarding"],
    )
    assert (await tags_of(catalog, "v1.4.0", "guide/install.md"))[1] == ["later", "onboarding"]


async def test_an_inherited_manual_tag_names_the_path_it_is_removed_on(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1.3.0", article("a.md"))
    await tag(catalog, "a.md", "x")
    await publish(catalog, "v1.4.0", article("b.md"), renames=(rename("v1.3.0", "a.md", "b.md"),))

    await tag(catalog, "b.md", "y")
    assert await origins_of(catalog, "v1.4.0", "b.md") == [("x", "a.md"), ("y", "b.md")]

    await tag(catalog, "b.md")  # removing on the new name leaves the inherited tag
    assert await origins_of(catalog, "v1.4.0", "b.md") == [("x", "a.md")]

    await tag(catalog, "a.md")  # removing it where it was set clears it everywhere
    assert await origins_of(catalog, "v1.4.0", "b.md") == []
    assert await origins_of(catalog, "v1.3.0", "a.md") == []


async def test_a_manual_tag_follows_renames_across_several_versions(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1", article("a.md"))
    await publish(catalog, "v2", article("b.md"), renames=(rename("v1", "a.md", "b.md"),))
    await publish(catalog, "v3", article("c.md"), renames=(rename("v2", "b.md", "c.md"),))

    await tag(catalog, "a.md", "kept")

    assert await origins_of(catalog, "v3", "c.md") == [("kept", "a.md")]


async def test_a_branch_rename_map_already_chained_is_not_followed_again(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "main", article("a.md"), kind=RefKind.BRANCH)
    await tag(catalog, "old.md", "kept")
    renamed = (rename("main", "old.md", "a.md"),)

    await publish(catalog, "main", article("a.md"), renames=renamed, kind=RefKind.BRANCH)

    assert (await tags_of(catalog, "main", "a.md"))[1] == ["kept"]


async def test_removing_manual_tags_brings_back_exactly_the_imported_ones(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1", article("a.md", "api"))
    await tag(catalog, "a.md", "api", "onboarding")

    removed = await tag(catalog, "a.md")

    assert removed.tags == []
    assert await tags_of(catalog, "v1", "a.md") == (["api"], [])
    assert [[(a.path, a.tags) for a in r.articles] for r in removed.retagged] == [
        [("a.md", ["api"])]
    ]


async def test_listings_and_tag_counts_see_manual_tags(catalog: CatalogModule) -> None:
    await publish(catalog, "v1", article("a.md"), article("b.md", "api"))
    await tag(catalog, "a.md", "onboarding")

    listed = await catalog.list_articles(
        ListArticlesQuery(library=LIBRARY, ref="v1", tag_filter=TagFilter(tags=["onboarding"]))
    )
    counted = await catalog.list_tags(ListTagsQuery(library=LIBRARY, ref="v1"))

    assert [a.path for a in listed.articles] == ["a.md"]
    assert listed.articles[0].tags == ["onboarding"]
    assert sorted((t.tag, t.count) for t in counted.tags) == [("api", 1), ("onboarding", 1)]


async def test_a_pending_manifest_is_tagged_too_and_applying_again_changes_nothing(
    catalog: CatalogModule,
) -> None:
    pending = await store(catalog, "v1", article("a.md"))

    stored = await tag(catalog, "a.md", "onboarding")
    again = await catalog.apply_manual_tags(ApplyManualTagsCommand(manifest_id=pending))
    await catalog.activate_manifest(ActivateManifestCommand(manifest_id=pending))

    assert [r.manifest_id for r in stored.retagged] == [pending]
    assert [(a.path, a.tags) for a in again.articles] == [("a.md", ["onboarding"])]
    assert (await tags_of(catalog, "v1", "a.md"))[1] == ["onboarding"]


async def test_tagging_a_path_no_version_has_touches_nothing(catalog: CatalogModule) -> None:
    await publish(catalog, "v1", article("a.md"))

    stored = await tag(catalog, "missing.md", "x")

    assert stored.tags == ["x"]
    assert stored.retagged == []


async def test_new_renames_of_a_version_let_manual_tags_follow_them(
    catalog: CatalogModule,
) -> None:
    await publish(catalog, "v1.4.0", article("guide/install.md"), article("other.md"))
    await tag(catalog, "guide/setup.md", "legacy")
    await tag(catalog, "other.md", "kept")

    retagged = await catalog.replace_renames(
        ReplaceRenamesCommand(
            library=LIBRARY,
            ref="v1.4.0",
            renames=[rename("v1.3.0", "guide/setup.md", "guide/install.md")],
        )
    )

    (only,) = retagged.retagged
    assert only.manifest_id == retagged.manifest_id
    assert {(a.path, tuple(a.tags)) for a in only.articles} == {
        ("guide/install.md", ("legacy",)),
        ("other.md", ("kept",)),
    }
    assert await origins_of(catalog, "v1.4.0", "guide/install.md") == [("legacy", "guide/setup.md")]

    retagged = await catalog.replace_renames(
        ReplaceRenamesCommand(library=LIBRARY, ref="v1.4.0", renames=[])
    )

    (only,) = retagged.retagged
    assert ("guide/install.md", ()) in {(a.path, tuple(a.tags)) for a in only.articles}
    assert await origins_of(catalog, "v1.4.0", "guide/install.md") == []


async def test_new_renames_of_a_version_reach_the_versions_after_it(
    catalog: CatalogModule,
) -> None:
    newer = await publish(catalog, "v1.4.0", article("install.md"))
    newest = await publish(
        catalog,
        "v1.5.0",
        article("guide.md"),
        renames=(rename("v1.4.0", "install.md", "guide.md"),),
    )
    await tag(catalog, "setup.md", "legacy")
    await publish(catalog, "v1.3.0", article("setup.md"))

    replaced = await catalog.replace_renames(
        ReplaceRenamesCommand(
            library=LIBRARY,
            ref="v1.4.0",
            renames=[rename("v1.3.0", "setup.md", "install.md")],
        )
    )

    assert await origins_of(catalog, "v1.4.0", "install.md") == [("legacy", "setup.md")]
    assert await origins_of(catalog, "v1.5.0", "guide.md") == [("legacy", "setup.md")]
    retagged = {m.manifest_id: {a.path: a.tags for a in m.articles} for m in replaced.retagged}
    assert replaced.manifest_id == newer
    assert retagged[newer] == {"install.md": ["legacy"]}
    assert retagged[newest] == {"guide.md": ["legacy"]}


async def test_renames_of_an_unknown_library_or_version_are_not_found(
    catalog: CatalogModule,
) -> None:
    with pytest.raises(LibraryNotFoundError):
        await catalog.replace_renames(
            ReplaceRenamesCommand(library="/acme/nope", ref="v1", renames=[])
        )
    await store(catalog, "v1", article("a.md"))  # pending only: nothing is served yet
    with pytest.raises(VersionNotFoundError):
        await catalog.replace_renames(ReplaceRenamesCommand(library=LIBRARY, ref="v1", renames=[]))


async def test_an_unknown_library_or_manifest_is_not_found(catalog: CatalogModule) -> None:
    with pytest.raises(LibraryNotFoundError):
        await catalog.set_manual_tags(
            SetManualTagsCommand(library="/acme/nope", path="a.md", tags=["x"])
        )
    with pytest.raises(ManifestNotFoundError):
        await catalog.apply_manual_tags(ApplyManualTagsCommand(manifest_id="nope"))
