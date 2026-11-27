"""Manifest use cases on in-memory adapters: store, activate, browse, discard, collect."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryArticleTitles,
    InMemoryImportedTags,
    InMemoryInstructionFiles,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.constants import MAX_INSTRUCTION_FILE_CHARS, MAX_RENAME_HOPS
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    CollectGarbageCommand,
    DiscardPendingManifestsCommand,
    GetActiveManifestQuery,
    GetArticleQuery,
    GetInstructionFilesQuery,
    GetLibraryQuery,
    GetManifestStatesQuery,
    InstructionFileIn,
    ListArticlesQuery,
    ListRenamesQuery,
    ListTagsQuery,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RenameDirection,
    RenameIn,
    ReplaceRenamesCommand,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    StoreManifestCommand,
)
from exactdocs.catalog.errors import (
    ArticleNotFoundError,
    ConflictingContentError,
    DuplicateArticlePathError,
    DuplicateRenameError,
    InvalidArticlePathError,
    InvalidBlobShaError,
    InvalidCommitShaError,
    InvalidInstructionFileError,
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
    ManifestOutdatedError,
    RenameLinkMismatchError,
    SelfRenameError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    Manifest,
    ManifestId,
    ManifestInstruction,
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
    manifests = InMemoryManifestRepository(libraries=libraries)
    clock = FakeClock()
    return World(
        CatalogModule.build(
            repository=libraries,
            manifests=manifests,
            clock=clock,
            imported_tags=InMemoryImportedTags(repository=manifests),
            copier=InMemoryManifestCopier(repository=manifests),
            stored_articles=InMemoryStoredArticles(repository=manifests),
            instruction_files=InMemoryInstructionFiles(repository=manifests),
            article_titles=InMemoryArticleTitles(repository=manifests),
        ),
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


async def test_the_active_manifest_of_a_version_is_named_even_when_it_has_no_articles(
    world: World,
) -> None:
    query = GetActiveManifestQuery(library="/acme/payments", ref="main")
    assert (await world.catalog.get_active_manifest(query)).manifest_id is None  # imported, not yet

    empty = await world.active("main", "aaa111")

    assert (await world.catalog.get_active_manifest(query)).manifest_id == empty
    with pytest.raises(VersionNotFoundError):
        await world.catalog.get_active_manifest(
            GetActiveManifestQuery(library="/acme/payments", ref="nope")
        )


async def test_manifest_states_are_reported_by_id_and_unknown_ids_are_left_out(
    world: World,
) -> None:
    active = await world.active("main", "aaa111", article("a.md"))
    pending = await world.catalog.store_manifest(command("main", "bbb222", article("a.md")))

    states = await world.catalog.get_manifest_states(
        GetManifestStatesQuery(manifest_ids=[pending.manifest_id, "nope", active, active])
    )

    assert states.states == {
        pending.manifest_id: ManifestState.PENDING,
        active: ManifestState.ACTIVE,
    }


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


async def test_a_ref_that_names_a_version_but_for_a_leading_v_reads_it_with_a_note(
    world: World,
) -> None:
    # #605: the project tags `1.10.0`, the agent asks for `v1.10.0`
    await world.active("1.10.0", "aaa111", article("a.md", "ten", tags=["guide"]), kind=RefKind.TAG)
    lib = "/acme/payments"
    note = (
        "ref 'v1.10.0' is not imported: read as '1.10.0', the one version it names but for a "
        "leading v."
    )

    listed = await world.catalog.list_articles(ListArticlesQuery(library=lib, ref="v1.10.0"))
    read = await world.catalog.get_article(GetArticleQuery(library=lib, ref="v1.10.0", path="a.md"))
    tags = await world.catalog.list_tags(ListTagsQuery(library=lib, ref="v1.10.0"))
    resolved = await world.catalog.resolve_version(ResolveVersionQuery(id=f"{lib}/v1.10.0"))

    assert (listed.ref, [a.path for a in listed.articles], listed.notes) == (
        "1.10.0",
        ["a.md"],
        [note],
    )
    assert (read.ref, read.content, read.notes) == ("1.10.0", "ten", [note])
    assert (tags.ref, tags.notes) == ("1.10.0", [note])
    assert (resolved.ref, resolved.notes) == ("1.10.0", [note])
    upper = await world.catalog.list_articles(ListArticlesQuery(library=lib, ref="V1.10.0"))
    assert upper.ref == "1.10.0"


async def test_a_ref_read_as_given_has_no_notes(world: World) -> None:
    await world.active("v1.10.0", "aaa111", article("a.md"), kind=RefKind.TAG)

    read = await world.catalog.get_article(
        GetArticleQuery(library="/acme/payments", ref="v1.10.0", path="a.md")
    )

    assert read.notes == []
    assert "notes" not in read.model_dump(mode="json")


async def test_a_ref_matching_two_spellings_is_not_guessed(world: World) -> None:
    await world.active("1.0", "aaa111", article("a.md", "plain"), kind=RefKind.TAG)
    await world.active("V1.0", "bbb222", article("a.md", "upper"), kind=RefKind.TAG)

    with pytest.raises(VersionNotFoundError, match=r"has no version 'v1\.0'"):
        await world.catalog.get_article(
            GetArticleQuery(library="/acme/payments", ref="v1.0", path="a.md")
        )


async def test_a_missing_ref_names_the_versions_newest_first_and_the_default(
    world: World,
) -> None:
    world.clock.moment = NOW - timedelta(days=2)
    await world.active("0.27.0", "aaa111", article("a.md"), kind=RefKind.TAG)
    world.clock.moment = NOW - timedelta(days=1)
    await world.active("1.10.0", "bbb222", article("a.md"), kind=RefKind.TAG)

    with pytest.raises(VersionNotFoundError) as missing:
        await world.catalog.list_articles(ListArticlesQuery(library="/acme/payments", ref="2.0.0"))

    assert str(missing.value) == (
        "library '/acme/payments' has no version '2.0.0'; imported versions "
        "(repository refs, not instructions), newest first: "
        "'1.10.0', '0.27.0', 'main'; default version: '1.10.0'"
    )
    assert missing.value.versions == ("1.10.0", "0.27.0", "main")


async def test_lookups_of_a_stored_ref_stay_exact(world: World) -> None:
    await world.active("1.10.0", "aaa111", article("a.md"), kind=RefKind.TAG)

    with pytest.raises(VersionNotFoundError):
        await world.catalog.get_active_manifest(
            GetActiveManifestQuery(library="/acme/payments", ref="v1.10.0")
        )
    with pytest.raises(VersionNotFoundError):
        await world.catalog.remove_version(
            RemoveVersionCommand(library="/acme/payments", ref="v1.10.0")
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


async def test_removing_a_version_moves_the_default_and_frees_its_unshared_content(
    world: World,
) -> None:
    await world.active(
        "v1.3.0", "a1", article("a.md", "shared"), article("old.md", "old"), kind=RefKind.TAG
    )
    new = await world.active("v1.4.0", "a2", article("a.md", "shared"), kind=RefKind.TAG)
    default = await world.catalog.resolve_version(ResolveVersionQuery(id="/acme/payments"))
    assert default.ref == "v1.4.0"

    removed = await world.catalog.remove_version(
        RemoveVersionCommand(library="/Acme/Payments", ref="v1.4.0")
    )

    assert (removed.ref, removed.manifest_ids, removed.default_ref) == ("v1.4.0", [new], "v1.3.0")
    after = await world.catalog.resolve_version(ResolveVersionQuery(id="/acme/payments"))
    assert after.ref == "v1.3.0"
    with pytest.raises(VersionNotFoundError):
        await world.catalog.resolve_version(ResolveVersionQuery(id="/acme/payments/v1.4.0"))
    collected = await world.catalog.collect_garbage(CollectGarbageCommand())
    assert collected.contents == 0  # v1.3.0 still uses both texts


async def test_removing_the_last_version_leaves_a_library_without_versions(world: World) -> None:
    await world.active("v1.0.0", "a1", article("a.md"), kind=RefKind.TAG)
    await world.catalog.remove_version(RemoveVersionCommand(library="/acme/payments", ref="main"))

    last = await world.catalog.remove_version(
        RemoveVersionCommand(library="/acme/payments", ref="v1.0.0")
    )

    assert last.default_ref is None
    detail = await world.catalog.get_library(GetLibraryQuery(id="/acme/payments"))
    assert (detail.versions, detail.default_version) == ([], None)
    assert (await world.catalog.collect_garbage(CollectGarbageCommand())).contents == 1


async def test_removing_matches_the_ref_exactly_and_names_what_is_missing(world: World) -> None:
    with pytest.raises(VersionNotFoundError):
        await world.catalog.remove_version(
            RemoveVersionCommand(library="/acme/payments", ref="MAIN")
        )
    with pytest.raises(LibraryNotFoundError):
        await world.catalog.remove_version(RemoveVersionCommand(library="/acme/none", ref="main"))
    with pytest.raises(LibraryNotFoundError):
        await world.catalog.remove_library(RemoveLibraryCommand(library="/acme/none"))


async def test_removing_a_library_takes_its_versions_and_manifests(world: World) -> None:
    kept = await world.active("main", "aaa111", article("a.md"))

    removed = await world.catalog.remove_library(RemoveLibraryCommand(library="/Acme/Payments"))

    assert (removed.library, removed.manifest_ids) == ("/acme/payments", [kept])
    with pytest.raises(LibraryNotFoundError):
        await world.catalog.get_library(GetLibraryQuery(id="/acme/payments"))


def renamed(ref: str, commit: str, *renames: RenameIn, kind: RefKind = RefKind.TAG) -> Any:
    stored = command(ref, commit, article("guide/install.md", "new"), kind=kind)
    return stored.model_copy(update={"renames": list(renames)})


SETUP_TO_INSTALL = RenameIn(
    from_ref="v1.3.0", old_path="guide/setup.md", new_path="guide/install.md", similarity=84
)


async def where_did(
    world: World,
    path: str,
    ref: str | None = "v1.4.0",
    direction: RenameDirection = RenameDirection.FORWARD,
) -> Any:
    return await world.catalog.resolve_renamed_path(
        ResolveRenamedPathQuery(library="/Acme/Payments", ref=ref, path=path, direction=direction)
    )


async def test_a_path_renamed_since_the_previous_version_resolves_to_its_new_place(
    world: World,
) -> None:
    stored = await world.catalog.store_manifest(renamed("v1.4.0", "bbb222", SETUP_TO_INSTALL))
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))

    found = await where_did(world, "guide/setup.md")

    assert found is not None
    assert (found.from_ref, found.ref, found.old_path, found.new_path, found.similarity) == (
        "v1.3.0",
        "v1.4.0",
        "guide/setup.md",
        "guide/install.md",
        84,
    )
    assert await where_did(world, "guide/other.md") is None


async def test_a_path_can_be_followed_back_to_where_it_came_from(world: World) -> None:
    stored = await world.catalog.store_manifest(renamed("v1.4.0", "bbb222", SETUP_TO_INSTALL))
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))

    back = await where_did(world, "guide/install.md", direction=RenameDirection.BACK)

    assert back is not None
    assert (back.from_ref, back.old_path, back.new_path) == (
        "v1.3.0",
        "guide/setup.md",
        "guide/install.md",
    )
    assert await where_did(world, "guide/setup.md", direction=RenameDirection.BACK) is None
    assert await where_did(world, "guide/install.md") is None  # forward asks for the old path
    listed = await world.catalog.list_renames(
        ListRenamesQuery(library="/Acme/Payments", ref="v1.4.0")
    )
    assert [(r.old_path, r.new_path) for r in listed.renames] == [
        ("guide/setup.md", "guide/install.md")
    ]


async def test_a_pending_manifests_renames_are_not_visible_and_a_new_import_replaces_them(
    world: World,
) -> None:
    first = await world.catalog.store_manifest(renamed("v1.4.0", "bbb222", SETUP_TO_INSTALL))
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=first.manifest_id))
    await world.catalog.store_manifest(renamed("v1.4.0", "ccc333"))  # pending, none found

    assert await where_did(world, "guide/setup.md") is not None  # the active one speaks

    again = await world.catalog.store_manifest(renamed("v1.4.0", "ccc333"))
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=again.manifest_id))

    assert await where_did(world, "guide/setup.md") is None


async def test_without_a_ref_the_default_version_is_asked(world: World) -> None:
    await world.active("main", "ddd444", article("guide/install.md", "x"))

    assert await where_did(world, "guide/setup.md", ref=None) is None


async def test_an_unknown_version_or_one_without_a_manifest_is_an_error(world: World) -> None:
    with pytest.raises(VersionNotFoundError):
        await where_did(world, "guide/setup.md", ref="v9")
    with pytest.raises(ArticleNotFoundError):  # `main` exists but was never imported here
        await where_did(world, "guide/setup.md", ref="main")


async def test_impossible_renames_are_refused_when_stored(world: World) -> None:
    traversal = SETUP_TO_INSTALL.model_copy(update={"old_path": "../x.md"})
    with pytest.raises(InvalidArticlePathError):
        await world.catalog.store_manifest(renamed("v1.4.0", "bbb222", traversal))
    with pytest.raises(DuplicateRenameError):
        await world.catalog.store_manifest(
            renamed("v1.4.0", "bbb222", SETUP_TO_INSTALL, SETUP_TO_INSTALL)
        )
    with pytest.raises(SelfRenameError):  # a tag compares with an earlier version only
        await world.catalog.store_manifest(
            renamed("v1.4.0", "bbb222", SETUP_TO_INSTALL.model_copy(update={"from_ref": "v1.4.0"}))
        )
    with pytest.raises(ValueError, match="less than or equal to 100"):
        RenameIn(from_ref="v1", old_path="a.md", new_path="b.md", similarity=101)


# ---------------------------------------------------------------- across several versions (#201)


def commit_of(ref: str) -> str:
    return hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest()


async def linked(
    world: World,
    ref: str,
    after: str | None,
    *paths: str,
    renames: tuple[tuple[str, str], ...] = (),
    kind: RefKind = RefKind.TAG,
    similarity: int = 84,
) -> None:
    """Import ``ref`` (its articles at ``paths``) as the version that follows ``after``."""
    stored = command(ref, commit_of(ref), *(article(p, f"{ref} {p}") for p in paths))
    await world.catalog.store_manifest(
        stored.model_copy(
            update={
                "kind": kind,
                "renamed_from": after,
                "renames": [
                    RenameIn(from_ref=after or ref, old_path=o, new_path=n, similarity=similarity)
                    for o, n in renames
                ],
            }
        )
    )
    pending = await world.manifests.list_live(LibraryId("/acme/payments"))
    (manifest,) = [m for m in pending if m.ref == VersionRef(ref) and m.state.value == "pending"]
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=manifest.id))


async def path_in(world: World, path: str, from_ref: str, ref: str) -> str | None:
    found = await world.catalog.resolve_renamed_path(
        ResolveRenamedPathQuery(library="/Acme/Payments", ref=ref, path=path, from_ref=from_ref)
    )
    return None if found is None else found.new_path


async def three_versions(world: World) -> None:
    """v1.2.0, v1.3.0 (nothing moved), v1.4.0 (renamed guide/setup.md), imported in order."""
    await linked(world, "v1.2.0", None, "guide/setup.md", "guide/auth.md")
    await linked(world, "v1.3.0", "v1.2.0", "guide/setup.md", "guide/auth.md")
    await linked(
        world,
        "v1.4.0",
        "v1.3.0",
        "guide/install.md",
        "guide/auth.md",
        renames=(("guide/setup.md", "guide/install.md"),),
    )


async def test_a_path_is_followed_across_a_version_where_nothing_moved(world: World) -> None:
    await three_versions(world)

    found = await world.catalog.resolve_renamed_path(
        ResolveRenamedPathQuery(
            library="/Acme/Payments", ref="v1.4.0", path="guide/setup.md", from_ref="v1.2.0"
        )
    )

    assert found is not None
    assert (found.ref, found.from_ref, found.old_path, found.new_path, found.similarity) == (
        "v1.4.0",
        "v1.2.0",
        "guide/setup.md",
        "guide/install.md",
        84,
    )
    assert await path_in(world, "guide/install.md", "v1.4.0", "v1.2.0") == "guide/setup.md"
    assert await path_in(world, "guide/auth.md", "v1.2.0", "v1.4.0") is None  # did not move
    assert await path_in(world, "guide/setup.md", "v1.2.0", "v1.2.0") is None  # same version


async def test_one_hop_with_from_answers_as_the_one_hop_lookup_did(world: World) -> None:
    await three_versions(world)

    forward = await world.catalog.resolve_renamed_path(
        ResolveRenamedPathQuery(
            library="/Acme/Payments", ref="v1.4.0", path="guide/setup.md", from_ref="v1.3.0"
        )
    )

    assert forward == await where_did(world, "guide/setup.md")
    assert await path_in(world, "guide/install.md", "v1.4.0", "v1.3.0") == "guide/setup.md"


async def test_a_rename_on_every_hop_resolves_to_the_last_name_both_ways(world: World) -> None:
    await linked(world, "v1.0.0", None, "a.md")
    await linked(world, "v1.1.0", "v1.0.0", "b.md", renames=(("a.md", "b.md"),), similarity=90)
    await linked(world, "v1.2.0", "v1.1.0", "c.md", renames=(("b.md", "c.md"),), similarity=70)

    found = await world.catalog.resolve_renamed_path(
        ResolveRenamedPathQuery(
            library="/Acme/Payments", ref="v1.2.0", path="a.md", from_ref="v1.0.0"
        )
    )

    assert found is not None
    assert (found.new_path, found.similarity) == ("c.md", 70)  # the weakest move of the chain
    assert await path_in(world, "c.md", "v1.2.0", "v1.0.0") == "a.md"
    assert await path_in(world, "b.md", "v1.1.0", "v1.2.0") == "c.md"
    assert await path_in(world, "c.md", "v1.2.0", "v1.1.0") == "b.md"


async def test_versions_without_an_import_link_did_not_move(world: World) -> None:
    await three_versions(world)
    # A branch's map is its own (it names the branch itself): it links to no tag.
    await linked(
        world,
        "main",
        "main",
        "guide/install.md",
        renames=(("guide/setup.md", "guide/install.md"),),
        kind=RefKind.BRANCH,
    )
    # A tag whose renames were never detected against anything.
    await linked(world, "v2.0.0", None, "guide/install.md")

    assert await path_in(world, "guide/setup.md", "v1.2.0", "main") is None
    assert await path_in(world, "guide/install.md", "main", "v1.2.0") is None
    assert await path_in(world, "guide/setup.md", "v1.2.0", "v2.0.0") is None
    assert await path_in(world, "guide/install.md", "v2.0.0", "v1.2.0") is None


async def test_a_version_removed_in_between_breaks_the_chain(world: World) -> None:
    await three_versions(world)
    await world.catalog.remove_version(RemoveVersionCommand(library="/Acme/Payments", ref="v1.3.0"))

    assert await path_in(world, "guide/setup.md", "v1.2.0", "v1.4.0") is None
    assert await path_in(world, "guide/install.md", "v1.4.0", "v1.2.0") is None


async def test_a_path_renamed_and_then_dropped_is_not_in_the_later_version(
    world: World,
) -> None:
    await linked(world, "v1.0.0", None, "x.md", "w.md")
    await linked(world, "v1.1.0", "v1.0.0", "y.md", "w.md", renames=(("x.md", "y.md"),))
    await linked(world, "v1.2.0", "v1.1.0", "w.md")  # y.md is gone

    assert await path_in(world, "x.md", "v1.0.0", "v1.1.0") == "y.md"
    assert await path_in(world, "x.md", "v1.0.0", "v1.2.0") is None  # never v1.1.0's path


async def test_renames_of_another_version_than_the_link_are_refused(world: World) -> None:
    await three_versions(world)
    other = SETUP_TO_INSTALL.model_copy(update={"from_ref": "v1.2.0"})

    with pytest.raises(RenameLinkMismatchError):
        await world.catalog.store_manifest(
            renamed("v1.5.0", commit_of("v1.5.0"), other).model_copy(
                update={"renamed_from": "v1.4.0"}
            )
        )
    with pytest.raises(RenameLinkMismatchError):
        await world.catalog.replace_renames(
            ReplaceRenamesCommand(
                library="/Acme/Payments", ref="v1.4.0", renamed_from="v1.3.0", renames=[other]
            )
        )
    found = await world.catalog.resolve_renamed_path(  # the refused map left nothing behind
        ResolveRenamedPathQuery(library="/Acme/Payments", ref="v1.4.0", path="guide/setup.md")
    )
    assert found is not None
    assert found.from_ref == "v1.3.0"


async def test_an_unknown_from_version_is_an_error(world: World) -> None:
    await three_versions(world)

    with pytest.raises(VersionNotFoundError):
        await path_in(world, "guide/setup.md", "v9", "v1.4.0")


async def test_the_walk_is_bounded(world: World) -> None:
    await linked(world, "v1.0.0", None, "a.md")
    previous = "v1.0.0"
    for minor in range(1, MAX_RENAME_HOPS + 2):
        ref = f"v1.{minor}.0"
        await linked(world, ref, previous, "a.md")
        previous = ref
    last = previous

    await world.catalog.store_manifest(
        command("v9.0.0", commit_of("v9.0.0"), article("z.md"), kind=RefKind.TAG).model_copy(
            update={
                "renamed_from": last,
                "renames": [
                    RenameIn(from_ref=last, old_path="a.md", new_path="z.md", similarity=50)
                ],
            }
        )
    )
    (pending,) = [
        m
        for m in await world.manifests.list_live(LibraryId("/acme/payments"))
        if m.state.value == "pending"
    ]
    await world.catalog.activate_manifest(ActivateManifestCommand(manifest_id=pending.id))

    assert await path_in(world, "a.md", "v1.2.0", "v9.0.0") == "z.md"  # within the bound
    assert await path_in(world, "a.md", "v1.0.0", "v9.0.0") is None  # farther than the bound


# ---------------------------------------------------------------- instruction files (RET-08)


async def test_a_manifest_keeps_its_instruction_files_for_other_domains(world: World) -> None:
    stored = await world.catalog.store_manifest(
        command("main", "bbb222", article("guide/install.md")).model_copy(
            update={
                "instructions": [
                    InstructionFileIn(path="guide/CLAUDE.md", content="One H1."),
                    InstructionFileIn(path="AGENTS.md", content="Guides in guide/."),
                ]
            }
        )
    )

    found = await world.catalog.get_instruction_files(
        GetInstructionFilesQuery(manifest_id=stored.manifest_id)
    )
    other = await world.catalog.get_instruction_files(GetInstructionFilesQuery(manifest_id="x"))

    assert [(f.path, f.content) for f in found.files] == [
        ("AGENTS.md", "Guides in guide/."),
        ("guide/CLAUDE.md", "One H1."),
    ]
    assert other.files == []


@pytest.mark.parametrize(
    "paths",
    [["AGENTS.md", "AGENTS.md"], [f"d{i}/AGENTS.md" for i in range(65)]],
    ids=["twice", "too many"],
)
def test_a_manifest_refuses_instruction_files_it_cannot_keep(paths: list[str]) -> None:
    with pytest.raises(InvalidInstructionFileError):
        Manifest(
            id=ManifestId("m"),
            library=LibraryId("/acme/payments"),
            ref=VersionRef("main"),
            kind=RefKind.BRANCH,
            commit_sha=sha("a"),
            created_at=NOW,
            instructions=tuple(ManifestInstruction(path=p, content="a") for p in paths),
        )


def test_an_instruction_file_has_a_bounded_text() -> None:
    with pytest.raises(InvalidInstructionFileError):
        ManifestInstruction(path="AGENTS.md", content="x" * (MAX_INSTRUCTION_FILE_CHARS + 1))


@pytest.mark.parametrize("path", ["../AGENTS.md", ".git/AGENTS.md", "a//AGENTS.md", ""])
def test_an_instruction_file_needs_a_plain_repository_path(path: str) -> None:
    with pytest.raises(InvalidArticlePathError):
        ManifestInstruction(path=path, content="a")
