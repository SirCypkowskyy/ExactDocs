"""Manifest use cases on in-memory adapters: store, activate, browse, discard, collect."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryLibraryRepository,
    InMemoryManifestRepository,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    CollectGarbageCommand,
    DiscardPendingManifestsCommand,
    GetArticleQuery,
    ListArticlesQuery,
    ResolveVersionQuery,
    StoreManifestCommand,
)
from exactdocs.catalog.errors import (
    ArticleNotFoundError,
    ConflictingContentError,
    DuplicateArticlePathError,
    InvalidArticlePathError,
    InvalidBlobShaError,
    InvalidCommitShaError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
    ManifestOutdatedError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    ManifestState,
    RefKind,
    Version,
    VersionRef,
)
from exactdocs.catalog.module import CatalogModule
from exactdocs_kernel import InvalidCursorError

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class FakeClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


def sha(name: str) -> str:
    return name.ljust(40, "0")


def article(path: str, content: str = "body", **extra: Any) -> ArticleIn:
    return ArticleIn(
        path=path,
        blob_sha=hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest(),
        content_version=1,
        title=path,
        content=content,
        **extra,
    )


def command(
    ref: str, commit: str, *articles: ArticleIn, kind: RefKind = RefKind.BRANCH
) -> StoreManifestCommand:
    return StoreManifestCommand(
        library="/Acme/Payments",
        ref=ref,
        kind=kind,
        commit_sha=sha(commit),
        articles=list(articles),
    )


@dataclass(slots=True)
class World:
    catalog: CatalogModule
    manifests: InMemoryManifestRepository
    clock: FakeClock

    async def active(
        self, ref: str, commit: str, *articles: ArticleIn, kind: RefKind = RefKind.BRANCH
    ) -> str:
        stored = await self.catalog.store_manifest(command(ref, commit, *articles, kind=kind))
        await self.catalog.activate_manifest(
            ActivateManifestCommand(manifest_id=stored.manifest_id)
        )
        return stored.manifest_id


@pytest.fixture
def world() -> World:
    libraries = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId("/acme/payments"),
                title="Payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
                versions=frozenset(
                    {
                        Version(
                            ref=VersionRef("main"),
                            kind=RefKind.BRANCH,
                            commit_sha=sha("a01d"),
                            imported_at=NOW - timedelta(days=9),
                        )
                    }
                ),
            )
        ]
    )
    manifests = InMemoryManifestRepository(libraries)
    clock = FakeClock()
    return World(
        CatalogModule.build(repository=libraries, manifests=manifests, clock=clock),
        manifests,
        clock,
    )


async def test_storing_a_manifest_changes_nothing_for_readers(world: World) -> None:
    await world.active("main", "aaa111", article("guide/install.md", "old"))

    stored = await world.catalog.store_manifest(
        command("main", "bbb222", article("guide/install.md", "new"))
    )

    assert (stored.state, stored.article_count) == (ManifestState.PENDING, 1)
    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", path="guide/install.md")
    )
    assert (read.content, read.commit_sha) == ("old", sha("aaa111"))
    resolved = await world.catalog.resolve_version(ResolveVersionQuery(id="/acme/payments/main"))
    assert resolved.commit_sha == sha("aaa111")


async def test_activating_swaps_content_listing_and_commit_together(world: World) -> None:
    await world.active("main", "aaa111", article("guide/install.md", "old"), article("a.md"))
    stored = await world.catalog.store_manifest(
        command("main", "bbb222", article("guide/install.md", "new"), article("b.md"))
    )

    done = await world.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )

    assert (done.version.ref, done.version.commit_sha, done.version.is_default) == (
        "main",
        sha("bbb222"),
        True,
    )
    listed = await world.catalog.list_articles(
        ListArticlesQuery(library="/acme/payments", ref="main")
    )
    assert (listed.commit_sha, listed.manifest_id) == (sha("bbb222"), stored.manifest_id)
    assert [a.path for a in listed.articles] == ["b.md", "guide/install.md"]
    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="main", path="guide/install.md")
    )
    assert read.content == "new"


async def test_activating_a_new_ref_makes_it_a_version(world: World) -> None:
    await world.active("v1.4.0", "ccc333", article("a.md"), kind=RefKind.TAG)

    resolved = await world.catalog.resolve_version(ResolveVersionQuery(id="/acme/payments"))

    assert (resolved.ref, resolved.kind, resolved.commit_sha) == (
        "v1.4.0",
        RefKind.TAG,
        sha("ccc333"),
    )


async def test_no_ref_means_the_default_version(world: World) -> None:
    await world.active("main", "aaa111", article("a.md", "main branch"))
    await world.active("v1.4.0", "ccc333", article("a.md", "tag"), kind=RefKind.TAG)

    read = await world.catalog.get_article(GetArticleQuery(library="/acme/payments", path="a.md"))
    listed = await world.catalog.list_articles(ListArticlesQuery(library="/acme/payments"))

    assert (read.ref, read.content, listed.ref) == ("v1.4.0", "tag", "v1.4.0")


async def test_an_article_reports_its_metadata_and_size(world: World) -> None:
    await world.active(
        "main",
        "aaa111",
        article("a.md", "héllo", tags=["api"], front_matter={"title": "A", "tags": ["api"]}),
    )

    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="main", path="a.md")
    )

    assert (read.title, read.tags, read.front_matter, read.size) == (
        "a.md",
        ["api"],
        {"title": "A", "tags": ["api"]},
        6,  # bytes, not characters
    )


async def test_articles_are_listed_by_directory_page_by_page(world: World) -> None:
    await world.active(
        "main",
        "aaa111",
        *(
            article(path, path)
            for path in ["z.md", "guide/b.md", "guide/a.md", "guide-old/x.md", "guide/c.md"]
        ),
    )
    ask = ListArticlesQuery(library="/acme/payments", ref="main", path_prefix="guide/", limit=2)

    first = await world.catalog.list_articles(ask)
    second = await world.catalog.list_articles(ask.model_copy(update={"cursor": first.next_cursor}))
    everything = await world.catalog.list_articles(
        ListArticlesQuery(library="/acme/payments", ref="main")
    )

    assert [a.path for a in first.articles] == ["guide/a.md", "guide/b.md"]
    assert [a.path for a in second.articles] == ["guide/c.md"]
    assert second.next_cursor is None  # and "guide-old/x.md" is not inside "guide/"
    assert len(everything.articles) == 5
    assert everything.next_cursor is None


async def test_a_malformed_cursor_is_a_validation_error(world: World) -> None:
    await world.active("main", "aaa111", article("a.md"))

    with pytest.raises(InvalidCursorError):
        await world.catalog.list_articles(
            ListArticlesQuery(library="/acme/payments", ref="main", cursor="!!")
        )


async def test_a_version_without_an_active_manifest_has_no_articles(world: World) -> None:
    await world.catalog.store_manifest(command("main", "bbb222", article("a.md")))

    with pytest.raises(ArticleNotFoundError):
        await world.catalog.list_articles(ListArticlesQuery(library="/acme/payments", ref="main"))
    with pytest.raises(ArticleNotFoundError):
        await world.catalog.get_article(GetArticleQuery(library="/acme/payments", path="a.md"))


async def test_unknown_libraries_versions_and_paths_are_not_found(world: World) -> None:
    await world.active("main", "aaa111", article("a.md"))

    with pytest.raises(LibraryNotFoundError):
        await world.catalog.get_article(GetArticleQuery(library="/vuejs/docs", path="a.md"))
    with pytest.raises(VersionNotFoundError):
        await world.catalog.get_article(
            GetArticleQuery(library="/acme/payments", ref="Main", path="a.md")
        )
    with pytest.raises(ArticleNotFoundError):
        await world.catalog.get_article(
            GetArticleQuery(library="/acme/payments", ref="main", path="b.md")
        )
    with pytest.raises(LibraryNotFoundError):
        await world.catalog.store_manifest(
            command("main", "aaa111").model_copy(update={"library": "/vuejs/docs"})
        )


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        (article("/abs.md"), InvalidArticlePathError),
        (article("a/../b.md"), InvalidArticlePathError),
        (article("a//b.md"), InvalidArticlePathError),
        (article("a.md").model_copy(update={"blob_sha": "XYZ"}), InvalidBlobShaError),
    ],
)
async def test_a_malformed_article_is_rejected_before_anything_is_stored(
    world: World, bad: ArticleIn, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await world.catalog.store_manifest(command("main", "bbb222", bad))
    assert world.manifests.manifests == {}


async def test_a_manifest_needs_a_full_commit_sha_and_unique_paths(world: World) -> None:
    with pytest.raises(InvalidCommitShaError):
        await world.catalog.store_manifest(
            command("main", "bbb222").model_copy(update={"commit_sha": "bbb"})
        )
    with pytest.raises(DuplicateArticlePathError):
        await world.catalog.store_manifest(
            command("main", "bbb222", article("a.md", "1"), article("a.md", "2"))
        )


async def test_activating_again_is_a_replay_and_an_unknown_or_superseded_one_is_refused(
    world: World,
) -> None:
    first = await world.active("main", "aaa111", article("a.md"))
    again = await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=first))
    await world.active("main", "bbb222", article("a.md", "new"))

    assert again.version.commit_sha == sha("aaa111")
    with pytest.raises(ManifestNotPendingError):
        await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=first))
    with pytest.raises(ManifestNotFoundError):
        await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id="nope"))


async def test_an_older_manifest_cannot_replace_a_newer_active_one(world: World) -> None:
    older = await world.catalog.store_manifest(command("main", "aaa111", article("a.md", "old")))
    world.clock.moment = NOW + timedelta(hours=1)
    await world.active("main", "bbb222", article("a.md", "new"))

    with pytest.raises(ManifestOutdatedError):
        await world.catalog.activate_manifest(
            ActivateManifestCommand(manifest_id=older.manifest_id)
        )

    read = await world.catalog.get_article(GetArticleQuery(library="/acme/payments", path="a.md"))
    assert (read.content, read.commit_sha) == ("new", sha("bbb222"))


async def test_the_same_blob_with_different_text_in_one_manifest_is_rejected(world: World) -> None:
    one = article("a.md", "one")
    clash = one.model_copy(update={"path": "b.md", "content": "other"})

    with pytest.raises(ConflictingContentError):
        await world.catalog.store_manifest(command("main", "aaa111", one, clash))
    assert world.manifests.manifests == {}


async def test_the_same_blob_gets_a_fresh_text_under_a_new_content_version(world: World) -> None:
    old = article("a.md", "old body")
    await world.active("v1.3.0", "aaa111", old, kind=RefKind.TAG)
    fixed = old.model_copy(update={"content": "cleaned body", "content_version": 2})
    await world.active("main", "bbb222", fixed)

    on_tag = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="v1.3.0", path="a.md")
    )
    on_main = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="main", path="a.md")
    )

    assert (on_tag.content, on_main.content) == ("old body", "cleaned body")


async def test_discarding_needs_a_filter_and_keeps_what_readers_see(world: World) -> None:
    await world.active("main", "aaa111", article("a.md", "live"))
    one = await world.catalog.store_manifest(command("main", "bbb222", article("a.md", "x")))
    await world.catalog.store_manifest(command("main", "ccc333", article("a.md", "y")))
    world.clock.moment = NOW + timedelta(hours=1)
    await world.catalog.store_manifest(command("main", "ddd444", article("a.md", "z")))

    with pytest.raises(ValueError, match="give a manifest_id"):
        DiscardPendingManifestsCommand()
    by_id = await world.catalog.discard_pending_manifests(
        DiscardPendingManifestsCommand(manifest_id=one.manifest_id)
    )
    by_age = await world.catalog.discard_pending_manifests(
        DiscardPendingManifestsCommand(older_than_seconds=1800)
    )
    other = await world.catalog.discard_pending_manifests(
        DiscardPendingManifestsCommand(library="/acme/ledger")
    )
    by_library = await world.catalog.discard_pending_manifests(
        DiscardPendingManifestsCommand(library="/Acme/Payments")
    )

    assert (by_id.count, by_age.count, other.count, by_library.count) == (1, 1, 0, 1)
    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="main", path="a.md")
    )
    assert read.content == "live"


async def test_a_short_sha_reads_only_the_commit_versions_own_articles(world: World) -> None:
    await world.active("main", "aaa111", article("only-main.md"))
    commit = "fedcba9876".ljust(40, "0")
    stored = await world.catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref=commit[:12],
            kind=RefKind.COMMIT,
            commit_sha=commit,
            articles=[article("only-commit.md")],
        )
    )
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))

    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="fedcba9", path="only-commit.md")
    )

    assert (read.ref, read.commit_sha) == (commit[:12], commit)
    with pytest.raises(ArticleNotFoundError):  # main's article is not in the commit version
        await world.catalog.get_article(
            GetArticleQuery(library="/acme/payments", ref="fedcba9", path="only-main.md")
        )
    with pytest.raises(ArticleNotFoundError):
        await world.catalog.get_article(
            GetArticleQuery(library="/acme/payments", ref="main", path="only-commit.md")
        )


async def test_garbage_is_collected_after_the_grace_period(world: World) -> None:
    await world.active("main", "aaa111", article("a.md", "old"))
    world.clock.moment = NOW + timedelta(days=1)
    await world.active("main", "bbb222", article("a.md", "new"))

    world.clock.moment = NOW + timedelta(days=1, hours=23)
    early = await world.catalog.collect_garbage(CollectGarbageCommand(grace_seconds=2 * 86400))
    world.clock.moment = NOW + timedelta(days=4)
    late = await world.catalog.collect_garbage(CollectGarbageCommand(grace_seconds=2 * 86400))

    assert (early.manifests, early.contents) == (0, 0)
    assert (late.manifests, late.contents) == (1, 1)
