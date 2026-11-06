"""Adapter contract: every ``ManifestRepository`` behaves the same, whatever stores the data."""

from collections import UserDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
)
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteImportedTags,
    SqliteLibraryRepository,
    SqliteManifestCopier,
    SqliteManifestRepository,
    article_contents,
)
from exactdocs.catalog.errors import (
    LibraryNotFoundError,
    ManifestNotFoundError,
    ManifestNotPendingError,
    ManifestOutdatedError,
    StoredContentOutdatedError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    ContentKey,
    HostKind,
    Library,
    LibraryId,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestImage,
    ManifestRename,
    ManifestState,
    ManualTag,
    ManualTags,
    RefKind,
    RenameDirection,
    StoredImage,
    TagMatch,
    TagSelection,
    VersionRef,
)
from exactdocs.catalog.ports import (
    ImportedTagWriter,
    LibraryRepository,
    ManifestCopier,
    ManifestRepository,
)

PAYMENTS = Library(
    id=LibraryId("/acme/payments"),
    title="Payments",
    source_url="https://github.com/acme/payments",
    host=HostKind.GITHUB,
    default_branch=VersionRef("main"),
)
T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
INSTALL = "guide/install.md"


def sha(name: str) -> str:
    return name.ljust(40, "0")


def entry(
    path: str, blob: str, *, title: str = "T", tags: tuple[str, ...] = (), version: int = 1
) -> ManifestEntry:
    return ManifestEntry(
        path=path,
        blob_sha=sha(blob),
        content_version=version,
        title=title,
        tags=tags,
        front_matter={"title": title, "nested": {"n": [1, None, "x"]}},
        size=7,
    )


def manifest(
    id_: str,
    ref: str,
    commit: str,
    *entries: ManifestEntry,
    kind: RefKind = RefKind.BRANCH,
    created_at: datetime = T0,
) -> Manifest:
    return Manifest(
        id=ManifestId(id_),
        library=PAYMENTS.id,
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha(commit),
        created_at=created_at,
        entries=entries,
    )


def body(e: ManifestEntry) -> str:
    return f"content of {e.blob_sha[:6]} v{e.content_version}"


def contents(*entries: ManifestEntry) -> dict[ContentKey, str]:
    return {e.content_key: body(e) for e in entries}


@dataclass(frozen=True, slots=True)
class Stores:
    libraries: LibraryRepository
    manifests: ManifestRepository
    count_contents: Callable[[], Awaitable[int]]
    imported_tags: ImportedTagWriter
    copier: ManifestCopier


@pytest.fixture(params=["memory", "sqlite"])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    if request.param == "memory":
        libraries = InMemoryLibraryRepository()
        manifests = InMemoryManifestRepository(libraries)

        async def count() -> int:
            return len(manifests.contents)

        found = Stores(
            libraries,
            manifests,
            count,
            InMemoryImportedTags(manifests),
            InMemoryManifestCopier(manifests),
        )
    else:
        container = Container.build(Settings())
        async with container.running():

            async def count() -> int:
                async with container.engine.connect() as connection:
                    query = select(func.count()).select_from(article_contents)
                    return (await connection.execute(query)).scalar_one()

            found = Stores(
                SqliteLibraryRepository(container.engine),
                SqliteManifestRepository(container.engine),
                count,
                SqliteImportedTags(container.engine),
                SqliteManifestCopier(container.engine),
            )
            await found.libraries.save(PAYMENTS)
            yield found
        return
    await found.libraries.save(PAYMENTS)
    yield found


async def store(stores: Stores, stored: Manifest) -> None:
    await stores.manifests.add(stored, contents(*stored.entries))


async def fetch(manifests: ManifestRepository, id_: str) -> Manifest:
    found = await manifests.get(ManifestId(id_))
    assert found is not None, id_
    return found


async def paths(
    manifests: ManifestRepository,
    id_: str,
    *,
    prefix: str = "",
    after: str | None = None,
    limit: int = 100,
    tags: TagSelection | None = None,
) -> list[str]:
    entries = await manifests.list_entries(
        ManifestId(id_), prefix=prefix, tags=tags or TagSelection(), after=after, limit=limit
    )
    return [e.path for e in entries]


async def discard(
    stores: Stores,
    *,
    manifest_id: str | None = None,
    library: LibraryId | None = None,
    before: datetime | None = None,
) -> int:
    return await stores.manifests.discard_pending(
        manifest_id=None if manifest_id is None else ManifestId(manifest_id),
        library_id=library,
        created_before=before,
    )


async def active_commit(stores: Stores, ref: str) -> str | None:
    found = await stores.manifests.get_active(PAYMENTS.id, VersionRef(ref))
    return found.commit_sha if found else None


async def test_a_stored_manifest_comes_back_pending_with_everything_in_it(stores: Stores) -> None:
    stored = manifest(
        "m1",
        "main",
        "aaa111",
        entry("a/one.md", "b1", title="One", tags=("api", "auth")),
        entry("a/two.md", "b2"),
    )

    await store(stores, stored)

    header = await fetch(stores.manifests, stored.id)
    assert header == replace(stored, entries=())  # reads do not carry the entries
    assert header.state is ManifestState.PENDING
    assert await stores.manifests.list_entries(
        stored.id, prefix="", tags=TagSelection(), after=None, limit=9
    ) == (stored.entries)
    assert await stores.manifests.get(ManifestId("nope")) is None


async def test_get_many_returns_the_known_manifests_and_leaves_unknown_ids_out(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    found = await stores.manifests.get_many([ManifestId(i) for i in ("m1", "m2", "nope")])

    assert {i: m.state for i, m in found.items()} == {
        ManifestId("m1"): ManifestState.ACTIVE,
        ManifestId("m2"): ManifestState.PENDING,
    }
    assert all(m.entries == () for m in found.values())
    assert await stores.manifests.get_many([]) == {}


async def test_get_many_copes_with_more_ids_than_a_query_can_bind(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))

    ids = [ManifestId("m1"), *(ManifestId(f"ghost{i}") for i in range(1200))]

    assert set(await stores.manifests.get_many(ids)) == {ManifestId("m1")}


async def test_get_active_many_returns_active_manifests_only_and_copes_with_many_versions(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "dev", "bbb222", entry(INSTALL, "b2")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)  # "dev" stays pending
    asked = [
        (PAYMENTS.id, VersionRef("main")),
        (PAYMENTS.id, VersionRef("dev")),
        *((PAYMENTS.id, VersionRef(f"ghost{i}")) for i in range(900)),
    ]

    found = await stores.manifests.get_active_many(asked)

    assert {k: m.id for k, m in found.items()} == {(PAYMENTS.id, VersionRef("main")): "m1"}
    assert all(m.entries == () for m in found.values())
    assert await stores.manifests.get_active_many([]) == {}


async def test_a_pending_manifest_is_invisible_until_it_is_activated(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)

    assert article is not None
    assert (article.commit_sha, article.manifest_id) == (sha("aaa111"), "m1")
    assert article.content == body(entry(INSTALL, "b1"))
    assert await active_commit(stores, "main") == sha("aaa111")


async def test_activation_swaps_the_manifest_and_moves_the_version_to_its_commit(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    version = await stores.manifests.activate(ManifestId("m2"), at=T0 + timedelta(hours=1))

    assert (version.ref, version.commit_sha) == (VersionRef("main"), sha("bbb222"))
    assert version.imported_at == T0 + timedelta(hours=1)
    assert await active_commit(stores, "main") == sha("bbb222")
    old = await fetch(stores.manifests, "m1")
    assert (old.state, old.superseded_at) == (ManifestState.SUPERSEDED, T0 + timedelta(hours=1))
    library = await stores.libraries.get(PAYMENTS.id)
    assert library is not None
    assert {(v.ref.value, v.commit_sha) for v in library.versions} == {("main", sha("bbb222"))}


async def test_activation_creates_a_version_that_did_not_exist(stores: Stores) -> None:
    await store(stores, manifest("m1", "v1.4.0", "ccc333", kind=RefKind.TAG))

    await stores.manifests.activate(ManifestId("m1"), at=T0)

    library = await stores.libraries.get(PAYMENTS.id)
    assert library is not None
    (created,) = library.versions
    assert (created.ref.value, created.kind, created.commit_sha) == (
        "v1.4.0",
        RefKind.TAG,
        sha("ccc333"),
    )


async def test_each_version_keeps_its_own_active_manifest(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "next", "bbb222", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    assert await active_commit(stores, "main") == sha("aaa111")
    assert await active_commit(stores, "next") == sha("bbb222")
    assert await active_commit(stores, "Main") is None  # refs are case-sensitive


async def test_a_superseded_or_unknown_manifest_cannot_be_activated(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111"))
    await store(stores, manifest("m2", "main", "bbb222"))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    with pytest.raises(ManifestNotPendingError):  # superseded
        await stores.manifests.activate(ManifestId("m1"), at=T0)
    with pytest.raises(ManifestNotFoundError):
        await stores.manifests.activate(ManifestId("nope"), at=T0)
    assert await active_commit(stores, "main") == sha("bbb222")


async def test_the_same_blob_in_two_versions_is_stored_once(stores: Stores) -> None:
    install = entry(INSTALL, "b1")
    await store(stores, manifest("m1", "v1.3.0", "aaa111", install, kind=RefKind.TAG))
    await store(stores, manifest("m2", "v1.4.0", "bbb222", install, entry("new.md", "b2")))

    assert await stores.count_contents() == 2
    assert await paths(stores.manifests, "m2") == [INSTALL, "new.md"]


async def test_the_same_content_key_keeps_the_first_text(stores: Stores) -> None:
    stored = manifest("m1", "main", "aaa111", entry(INSTALL, "b1"))
    await stores.manifests.add(stored, {(sha("b1"), 1): "first"})
    await stores.manifests.add(replace(stored, id=ManifestId("m2")), {(sha("b1"), 1): "second"})
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)

    assert article is not None
    assert (article.content, await stores.count_contents()) == ("first", 1)


async def test_a_new_content_version_stores_a_fresh_text_next_to_the_old_one(
    stores: Stores,
) -> None:
    # The same blob parsed by a fixed parser: other text, so other content version.
    await store(stores, manifest("m1", "v1.3.0", "aaa111", entry(INSTALL, "b1", version=1)))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b1", version=2)))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    old = await stores.manifests.get_article(PAYMENTS.id, VersionRef("v1.3.0"), INSTALL)
    new = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)

    assert old is not None
    assert new is not None
    assert (old.content, new.content) == (
        body(entry(INSTALL, "b1", version=1)),
        body(entry(INSTALL, "b1", version=2)),
    )
    assert (old.entry.content_version, new.entry.content_version) == (1, 2)
    assert await stores.count_contents() == 2


async def test_an_article_that_is_not_in_the_active_manifest_is_none(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    pending = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    assert pending is None
    assert await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), "other.md") is None
    assert await stores.manifests.get_article(PAYMENTS.id, VersionRef("next"), INSTALL) is None


async def test_discarding_removes_the_matching_pending_manifests_and_nothing_else(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await store(stores, manifest("m3", "main", "ccc333"))
    await store(stores, manifest("m4", "next", "ddd444"))

    assert await discard(stores, manifest_id="m2") == 1
    assert await discard(stores, manifest_id="m1") == 0  # active: not pending
    assert await discard(stores, manifest_id="nope") == 0
    assert await discard(stores, library=PAYMENTS.id) == 2

    assert await stores.manifests.get(ManifestId("m1")) is not None
    assert [await stores.manifests.get(ManifestId(i)) for i in ("m2", "m3", "m4")] == [None] * 3
    assert await active_commit(stores, "main") == sha("aaa111")


async def test_discarding_by_age_leaves_the_imports_still_in_flight(stores: Stores) -> None:
    crashed = manifest("m1", "main", "aaa111", created_at=T0)
    in_flight = manifest("m2", "next", "bbb222", created_at=T0 + timedelta(hours=1))
    await store(stores, crashed)
    await store(stores, in_flight)

    assert await discard(stores, before=T0 + timedelta(minutes=30)) == 1

    assert await stores.manifests.get(ManifestId("m1")) is None
    assert await stores.manifests.get(ManifestId("m2")) is not None
    await stores.manifests.activate(ManifestId("m2"), at=T0 + timedelta(hours=2))  # still works


async def test_discarding_other_libraries_pending_manifests_is_not_possible(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111"))

    assert await discard(stores, library=LibraryId("/acme/ledger")) == 0
    assert await stores.manifests.get(ManifestId("m1")) is not None


async def test_garbage_collection_keeps_recent_superseded_manifests_and_used_contents(
    stores: Stores,
) -> None:
    shared, old_only = entry("shared.md", "b1"), entry("old.md", "b2")
    await store(stores, manifest("m1", "main", "aaa111", shared, old_only))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "bbb222", shared))
    await stores.manifests.activate(ManifestId("m2"), at=T0 + timedelta(days=1))

    young = await stores.manifests.collect_garbage(superseded_before=T0)
    assert (young.manifests, young.contents) == (0, 0)
    assert await stores.manifests.get(ManifestId("m1")) is not None

    old = await stores.manifests.collect_garbage(superseded_before=T0 + timedelta(days=2))
    assert (old.manifests, old.contents) == (1, 1)  # only old.md's blob lost its last user
    assert await stores.manifests.get(ManifestId("m1")) is None
    assert await stores.count_contents() == 1
    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), "shared.md")
    assert article is not None
    assert article.commit_sha == sha("bbb222")


async def test_garbage_collection_never_touches_active_or_pending_manifests(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "bbb222", entry("new.md", "b2")))

    collected = await stores.manifests.collect_garbage(superseded_before=T0 + timedelta(days=99))

    assert (collected.manifests, collected.contents) == (0, 0)
    assert await stores.manifests.get(ManifestId("m2")) is not None
    assert await active_commit(stores, "main") == sha("aaa111")


async def test_discarded_contents_are_collected_once_nothing_uses_them(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await discard(stores, library=PAYMENTS.id)

    collected = await stores.manifests.collect_garbage(superseded_before=T0)

    assert (collected.manifests, collected.contents) == (0, 1)
    assert await stores.count_contents() == 0


async def test_activating_the_active_manifest_again_succeeds_without_changes(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    first = await stores.manifests.activate(ManifestId("m1"), at=T0)

    replay = await stores.manifests.activate(ManifestId("m1"), at=T0 + timedelta(hours=1))

    assert replay == first
    assert (await fetch(stores.manifests, "m1")).state is ManifestState.ACTIVE
    assert await active_commit(stores, "main") == sha("aaa111")


async def test_an_older_pending_manifest_does_not_replace_a_newer_active_one(
    stores: Stores,
) -> None:
    later = T0 + timedelta(hours=1)
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2"), created_at=later))
    await stores.manifests.activate(ManifestId("m2"), at=later)

    with pytest.raises(ManifestOutdatedError):
        await stores.manifests.activate(ManifestId("m1"), at=later)

    assert await active_commit(stores, "main") == sha("bbb222")
    assert (await fetch(stores.manifests, "m1")).state is ManifestState.PENDING
    library = await stores.libraries.get(PAYMENTS.id)
    assert library is not None
    assert {v.commit_sha for v in library.versions} == {sha("bbb222")}


async def test_entries_are_listed_by_directory_in_path_order_page_by_page(stores: Stores) -> None:
    names = ["guide-old/x.md", "guide/b.md", "guide/a.md", "guide/sub/c.md", "guide", "api/z.md"]
    await store(stores, manifest("m1", "main", "aaa111", *(entry(n, "b1") for n in sorted(names))))

    assert await paths(stores.manifests, "m1") == sorted(names)
    assert await paths(stores.manifests, "m1", prefix="guide") == [
        "guide",
        "guide/a.md",
        "guide/b.md",
        "guide/sub/c.md",
    ]
    assert await paths(stores.manifests, "m1", prefix="guide/sub") == ["guide/sub/c.md"]
    assert await paths(stores.manifests, "m1", prefix="gui") == []  # not a directory
    assert await paths(stores.manifests, "m1", prefix="guide", after="guide/a.md", limit=2) == [
        "guide/b.md",
        "guide/sub/c.md",
    ]
    assert await paths(stores.manifests, "m1", limit=1) == ["api/z.md"]
    assert await paths(stores.manifests, "nope") == []


async def test_a_path_that_exists_only_in_another_version_is_not_found(stores: Stores) -> None:
    await store(
        stores,
        manifest(
            "m1",
            "v1.3.0",
            "aaa111",
            entry("only-old.md", "b1"),
            entry(INSTALL, "b2"),
            kind=RefKind.TAG,
        ),
    )
    await store(
        stores,
        manifest(
            "m2",
            "v1.4.0",
            "bbb222",
            entry("only-new.md", "b3"),
            entry(INSTALL, "b4"),
            kind=RefKind.TAG,
        ),
    )
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.activate(ManifestId("m2"), at=T0)
    get = stores.manifests.get_article

    assert await get(PAYMENTS.id, VersionRef("v1.4.0"), "only-old.md") is None
    assert await get(PAYMENTS.id, VersionRef("v1.3.0"), "only-new.md") is None
    old = await get(PAYMENTS.id, VersionRef("v1.3.0"), INSTALL)
    new = await get(PAYMENTS.id, VersionRef("v1.4.0"), INSTALL)
    assert old is not None
    assert new is not None
    assert (old.commit_sha, new.commit_sha) == (sha("aaa111"), sha("bbb222"))
    assert (old.content, new.content) == (body(entry(INSTALL, "b2")), body(entry(INSTALL, "b4")))
    assert await get(PAYMENTS.id, VersionRef("v1.5.0"), INSTALL) is None
    assert await get(LibraryId("/acme/ledger"), VersionRef("v1.4.0"), INSTALL) is None


async def test_saving_a_stale_library_does_not_undo_an_activation(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "v2.0.0", "bbb222", entry(INSTALL, "b2"), kind=RefKind.TAG))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    stale = await stores.libraries.get(PAYMENTS.id)  # an edit starts here (settings, rename)
    assert stale is not None
    await stores.manifests.activate(ManifestId("m2"), at=T0)  # ... an import activates meanwhile

    await stores.libraries.save(replace(stale, title="Renamed"))

    saved = await stores.libraries.get(PAYMENTS.id)
    assert saved is not None
    assert saved.title == "Renamed"
    assert {(v.ref.value, v.commit_sha) for v in saved.versions} == {
        ("main", sha("aaa111")),
        ("v2.0.0", sha("bbb222")),
    }
    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("v2.0.0"), INSTALL)
    assert article is not None


async def test_a_failure_while_the_memory_adapter_swaps_leaves_the_old_manifest_active() -> None:
    libraries = InMemoryLibraryRepository()
    await libraries.save(PAYMENTS)
    manifests = InMemoryManifestRepository(libraries)
    await manifests.add(
        manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {(sha("b1"), 1): "x"}
    )
    await manifests.add(
        manifest("m2", "main", "bbb222", entry(INSTALL, "b2")), {(sha("b2"), 1): "y"}
    )
    await manifests.activate(ManifestId("m1"), at=T0)

    class FailingOnWrite(UserDict[LibraryId, Library]):
        def __setitem__(self, key: LibraryId, item: Library) -> None:
            message = "injected failure"
            raise RuntimeError(message)

    failing = FailingOnWrite()
    failing.data.update(libraries.libraries)
    libraries.libraries = failing  # the last step of the swap fails

    with pytest.raises(RuntimeError, match="injected failure"):
        await manifests.activate(ManifestId("m2"), at=T0)

    assert [(await fetch(manifests, i)).state for i in ("m1", "m2")] == [
        ManifestState.ACTIVE,
        ManifestState.PENDING,
    ]
    article = await manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)
    assert article is not None
    assert article.commit_sha == sha("aaa111")


# ---- SQLite only: what the database itself guarantees


@pytest.fixture
async def sqlite() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running():
        await SqliteLibraryRepository(container.engine).save(PAYMENTS)
        yield container


async def test_sqlite_a_failure_during_activation_leaves_the_previous_manifest_active(
    sqlite: Container,
) -> None:
    manifests = SqliteManifestRepository(sqlite.engine)
    await manifests.add(
        manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {(sha("b1"), 1): "old"}
    )
    await manifests.add(
        manifest("m2", "main", "bbb222", entry(INSTALL, "b2")), {(sha("b2"), 1): "new"}
    )
    await manifests.activate(ManifestId("m1"), at=T0)
    async with sqlite.engine.begin() as connection:  # the last step of the swap fails
        await connection.execute(
            text(
                "CREATE TRIGGER fail_swap BEFORE INSERT ON catalog_library_versions "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        )

    with pytest.raises(IntegrityError, match="injected failure"):
        await manifests.activate(ManifestId("m2"), at=T0 + timedelta(hours=1))

    assert [(await fetch(manifests, i)).state for i in ("m1", "m2")] == [
        ManifestState.ACTIVE,
        ManifestState.PENDING,
    ]
    article = await manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)
    assert article is not None
    assert (article.commit_sha, article.content) == (sha("aaa111"), "old")
    library = await SqliteLibraryRepository(sqlite.engine).get(PAYMENTS.id)
    assert library is not None
    assert {v.commit_sha for v in library.versions} == {sha("aaa111")}


async def test_sqlite_refuses_a_second_active_manifest_for_one_version(sqlite: Container) -> None:
    manifests = SqliteManifestRepository(sqlite.engine)
    await manifests.add(manifest("m1", "main", "aaa111"), {})
    await manifests.add(manifest("m2", "main", "bbb222"), {})
    await manifests.activate(ManifestId("m1"), at=T0)

    async with sqlite.engine.begin() as connection:
        with pytest.raises(IntegrityError, match="UNIQUE"):
            await connection.execute(
                text("UPDATE catalog_manifests SET state = 'active' WHERE id = 'm2'")
            )


async def test_listing_filters_by_tags_before_it_pages(stores: Stores) -> None:
    await store(
        stores,
        manifest(
            "m1",
            "main",
            "aaa111",
            entry("a.md", "b1"),
            entry("b.md", "b2", tags=("api", "auth")),
            entry("c.md", "b3", tags=("api",)),
            entry("d.md", "b4", tags=("adr",)),
            entry("e.md", "b5", tags=("api",)),
        ),
    )
    any_of = TagSelection(frozenset({"api", "adr"}))
    all_of = TagSelection(frozenset({"api", "auth"}), TagMatch.ALL)

    assert await paths(stores.manifests, "m1", tags=any_of) == ["b.md", "c.md", "d.md", "e.md"]
    assert await paths(stores.manifests, "m1", tags=any_of, limit=2, after="b.md") == [
        "c.md",
        "d.md",
    ]
    assert await paths(stores.manifests, "m1", tags=all_of) == ["b.md"]
    assert await paths(stores.manifests, "m1", tags=TagSelection(frozenset({"nope"}))) == []
    assert await paths(stores.manifests, "m1", prefix="a.md", tags=any_of) == []


async def test_only_paths_are_listed_sorted_and_capped_for_suggestions(stores: Stores) -> None:
    names = ["guide/b.md", "api/z.md", "guide/a.md"]
    await store(stores, manifest("m1", "main", "aaa111", *(entry(n, "b1") for n in names)))

    assert list(await stores.manifests.list_paths(ManifestId("m1"), limit=100)) == sorted(names)
    assert list(await stores.manifests.list_paths(ManifestId("m1"), limit=2)) == sorted(names)[:2]
    assert not await stores.manifests.list_paths(ManifestId("none"), limit=100)


async def test_removing_the_pinned_version_clears_the_pin(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "next", "bbb222", entry(INSTALL, "b1"), kind=RefKind.TAG))
    await stores.manifests.activate(ManifestId("m2"), at=T0)
    assert await stores.libraries.pin_default(PAYMENTS.id, VersionRef("next"))

    await stores.manifests.remove_version(PAYMENTS.id, VersionRef("main"))  # not the pinned one
    kept = await stores.libraries.get(PAYMENTS.id)
    assert kept is not None
    assert kept.pinned_version == VersionRef("next")

    await stores.manifests.remove_version(PAYMENTS.id, VersionRef("next"))
    library = await stores.libraries.get(PAYMENTS.id)
    assert library is not None
    assert library.pinned_version is None  # an import of the ref again does not re-pin it


async def test_removing_a_version_deletes_its_manifests_in_every_state_and_keeps_others(
    stores: Stores,
) -> None:
    shared, only_main = entry("shared.md", "b1"), entry("main.md", "b2")
    await store(stores, manifest("m1", "main", "aaa111", shared, only_main))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "bbb222", shared))  # pending
    await store(stores, manifest("m3", "next", "ccc333", shared, kind=RefKind.TAG))
    await stores.manifests.activate(ManifestId("m3"), at=T0)

    removed = await stores.manifests.remove_version(PAYMENTS.id, VersionRef("main"))

    assert sorted(removed) == ["m1", "m2"]
    assert await stores.manifests.get(ManifestId("m1")) is None
    assert await stores.manifests.get(ManifestId("m2")) is None
    library = await stores.libraries.get(PAYMENTS.id)
    assert library is not None
    assert [str(v.ref) for v in library.versions] == ["next"]
    assert await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), "shared.md") is None
    kept = await stores.manifests.get_article(PAYMENTS.id, VersionRef("next"), "shared.md")
    assert kept is not None  # shared content survives the removal and the collection
    collected = await stores.manifests.collect_garbage(superseded_before=T0)
    assert (collected.manifests, collected.contents) == (0, 1)  # only main.md's text is freed
    assert await stores.count_contents() == 1


async def test_removing_an_unknown_version_changes_nothing(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    with pytest.raises(VersionNotFoundError):
        await stores.manifests.remove_version(PAYMENTS.id, VersionRef("v9"))
    with pytest.raises(LibraryNotFoundError):
        await stores.manifests.remove_library(LibraryId("/acme/ledger"))

    assert await stores.manifests.get(ManifestId("m1")) is not None


async def test_removing_a_library_deletes_versions_and_manifests(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "next", "bbb222", entry(INSTALL, "b1")))

    removed = await stores.manifests.remove_library(PAYMENTS.id)

    assert sorted(removed) == ["m1", "m2"]
    assert await stores.libraries.get(PAYMENTS.id) is None
    assert await stores.manifests.get(ManifestId("m2")) is None
    collected = await stores.manifests.collect_garbage(superseded_before=T0)
    assert collected.contents == 1
    assert await stores.count_contents() == 0


async def test_content_shared_across_libraries_survives_removing_one(stores: Stores) -> None:
    other = replace(PAYMENTS, id=LibraryId("/acme/ledger"), title="Ledger")
    await stores.libraries.save(other)
    shared, only_payments = entry("shared.md", "b1"), entry("pay.md", "b2")
    await store(stores, manifest("m1", "main", "aaa111", shared, only_payments))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    ledger = replace(manifest("m2", "main", "bbb222", shared), library=other.id)
    await store(stores, ledger)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    await stores.manifests.remove_library(PAYMENTS.id)
    collected = await stores.manifests.collect_garbage(superseded_before=T0)

    assert collected.contents == 1  # only pay.md's text
    assert await stores.count_contents() == 1
    kept = await stores.manifests.get_article(other.id, VersionRef("main"), "shared.md")
    assert kept is not None


async def test_a_manifest_that_needs_its_version_is_refused_once_the_version_is_gone(
    stores: Stores,
) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    refresh = manifest("m2", "main", "bbb222", entry(INSTALL, "b1"))
    await stores.manifests.add(refresh, contents(*refresh.entries), version_must_exist=True)
    await stores.manifests.remove_version(PAYMENTS.id, VersionRef("main"))

    assert await stores.manifests.get(ManifestId("m2")) is None  # removed with the version
    with pytest.raises(ManifestNotFoundError):
        await stores.manifests.activate(ManifestId("m2"), at=T0)
    again = manifest("m3", "main", "ccc333", entry(INSTALL, "b1"))
    with pytest.raises(VersionNotFoundError):
        await stores.manifests.add(again, contents(*again.entries), version_must_exist=True)
    await stores.manifests.add(again, contents(*again.entries))  # a first import still may


async def test_tags_are_counted_per_manifest_most_used_first_and_capped(stores: Stores) -> None:
    await store(
        stores,
        manifest(
            "m1",
            "main",
            "aaa111",
            entry("a.md", "b1", tags=("api", "auth")),
            entry("b.md", "b2", tags=("api",)),
            entry("c.md", "b3", tags=("zed",)),
            entry("d.md", "b4"),
        ),
    )

    assert list(await stores.manifests.count_tags(ManifestId("m1"), limit=10)) == [
        ("api", 2),
        ("auth", 1),
        ("zed", 1),
    ]
    assert list(await stores.manifests.count_tags(ManifestId("m1"), limit=2)) == [
        ("api", 2),
        ("auth", 1),
    ]
    assert not await stores.manifests.count_tags(ManifestId("none"), limit=10)


def rename(old: str, new: str, *, similarity: int = 84, from_ref: str = "v1.3.0") -> ManifestRename:
    return ManifestRename(
        from_ref=VersionRef(from_ref), old_path=old, new_path=new, similarity=similarity
    )


async def test_renames_are_stored_with_their_manifest_and_found_by_old_path(stores: Stores) -> None:
    moved = replace(
        manifest("m1", "v1.4.0", "aaa111", entry("guide/install.md", "b1"), kind=RefKind.TAG),
        renames=(rename("guide/setup.md", INSTALL), rename("old.md", "new.md", similarity=100)),
    )
    await store(stores, moved)

    found = await stores.manifests.find_rename(ManifestId("m1"), "guide/setup.md")

    assert found == rename("guide/setup.md", INSTALL)
    assert await stores.manifests.find_rename(ManifestId("m1"), INSTALL) is None  # not an old path
    assert (
        await stores.manifests.find_rename(ManifestId("m1"), INSTALL, RenameDirection.BACK) == found
    )
    assert (
        await stores.manifests.find_rename(ManifestId("m1"), "guide/setup.md", RenameDirection.BACK)
        is None
    )
    assert await stores.manifests.list_renames(ManifestId("m1"), limit=9) == (
        rename("guide/setup.md", INSTALL),
        rename("old.md", "new.md", similarity=100),
    )
    assert len(await stores.manifests.list_renames(ManifestId("m1"), limit=1)) == 1
    assert await stores.manifests.find_rename(ManifestId("nope"), "guide/setup.md") is None
    assert await fetch(stores.manifests, "m1") == replace(moved, entries=(), renames=())


async def test_renames_go_with_their_manifest(stores: Stores) -> None:
    pending = replace(
        manifest("m1", "v1.4.0", "aaa111", entry("a.md", "b1"), kind=RefKind.TAG),
        renames=(rename("b.md", "a.md"),),
    )
    await store(stores, pending)
    await discard(stores, manifest_id="m1")

    assert await stores.manifests.find_rename(ManifestId("m1"), "b.md") is None

    await store(stores, replace(pending, id=ManifestId("m2")))
    await stores.manifests.activate(ManifestId("m2"), at=T0)
    await stores.manifests.remove_version(PAYMENTS.id, VersionRef("v1.4.0"))

    assert await stores.manifests.find_rename(ManifestId("m2"), "b.md") is None


async def test_replacing_renames_keeps_only_renames_into_entries_once_per_old_path(
    stores: Stores,
) -> None:
    stored = replace(
        manifest("m1", "v1.4.0", "aaa111", entry(INSTALL, "b1"), kind=RefKind.TAG),
        renames=(rename("old.md", INSTALL, from_ref="v1.2.0"),),
    )
    await store(stores, stored)

    await stores.manifests.replace_renames(
        ManifestId("m1"),
        [
            rename("guide/setup.md", INSTALL, similarity=90),
            rename("guide/setup.md", INSTALL, similarity=50),  # a second one of the old path
            rename("gone.md", "not/an/article.md"),
        ],
    )

    assert await stores.manifests.list_renames(ManifestId("m1"), limit=9) == (
        rename("guide/setup.md", INSTALL, similarity=90),
    )
    await stores.manifests.replace_renames(ManifestId("m1"), [])
    assert await stores.manifests.list_renames(ManifestId("m1"), limit=9) == ()
    await stores.manifests.replace_renames(ManifestId("nope"), [rename("a.md", INSTALL)])
    assert (
        await stores.manifests.find_rename(ManifestId("nope"), INSTALL, RenameDirection.BACK)
        is None
    )


PNG = StoredImage(blob_sha=sha("1a"), content_type="image/png", data=b"\x89PNG\r\n\x1a\n-one")
GIF = StoredImage(blob_sha=sha("2b"), content_type="image/gif", data=b"GIF89a-two")


def with_images(
    stored: Manifest, paths: dict[str, StoredImage]
) -> tuple[Manifest, dict[str, StoredImage]]:
    """The manifest listing the images at ``paths`` and the blobs to store for it."""
    listed = tuple(
        ManifestImage(
            path=path,
            blob_sha=image.blob_sha,
            content_type=image.content_type,
            size=len(image.data),
        )
        for path, image in paths.items()
    )
    return replace(stored, images=listed), {i.blob_sha: i for i in paths.values()}


async def test_only_the_active_manifest_serves_its_images(stores: Stores) -> None:
    stored, blobs = with_images(
        manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {"img/a.png": PNG}
    )
    await stores.manifests.add(stored, contents(*stored.entries), images=blobs)
    main = VersionRef("main")

    assert await stores.manifests.get_image(PAYMENTS.id, main, "img/a.png") is None  # pending
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    assert await stores.manifests.get_image(PAYMENTS.id, main, "img/a.png") == PNG
    assert await stores.manifests.get_image(PAYMENTS.id, main, "img/b.png") is None
    assert await stores.manifests.get_image(PAYMENTS.id, VersionRef("v9"), "img/a.png") is None
    meta = await stores.manifests.get_image(PAYMENTS.id, main, "img/a.png", with_data=False)
    assert meta is not None
    assert (meta.blob_sha, meta.data) == (PNG.blob_sha, b"")  # the bytes are not read
    listing = await fetch(stores.manifests, "m1")
    assert listing.images == ()  # like entries, images are not part of a plain read


async def test_a_new_manifest_replaces_the_images_and_the_old_ones_are_collected(
    stores: Stores,
) -> None:
    first, blobs = with_images(
        manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {"img/a.png": PNG, "img/b.gif": GIF}
    )
    await stores.manifests.add(first, contents(*first.entries), images=blobs)
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    second, blobs = with_images(
        manifest("m2", "main", "bbb222", entry(INSTALL, "b1"), created_at=T0 + timedelta(hours=1)),
        {"img/a.png": PNG},  # unchanged: stays shared
    )
    await stores.manifests.add(second, contents(*second.entries), images=blobs)
    await stores.manifests.activate(ManifestId("m2"), at=T0 + timedelta(hours=1))
    main = VersionRef("main")

    assert await stores.manifests.get_image(PAYMENTS.id, main, "img/b.gif") is None
    early = await stores.manifests.collect_garbage(superseded_before=T0 - timedelta(hours=1))
    assert early.images == 0  # within the grace period
    done = await stores.manifests.collect_garbage(superseded_before=T0 + timedelta(hours=2))
    assert (done.manifests, done.images) == (1, 1)  # m1 and GIF; PNG is still used by m2
    assert await stores.manifests.get_image(PAYMENTS.id, main, "img/a.png") == PNG


async def test_removing_a_version_and_a_library_frees_their_images(stores: Stores) -> None:
    other = replace(PAYMENTS, id=LibraryId("/acme/ledger"), title="Ledger")
    await stores.libraries.save(other)
    a, blobs_a = with_images(manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {"x.png": PNG})
    await stores.manifests.add(a, contents(*a.entries), images=blobs_a)
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    b, blobs_b = with_images(
        replace(manifest("m2", "main", "bbb222", entry(INSTALL, "b1")), library=other.id),
        {"x.png": PNG, "y.gif": GIF},
    )
    await stores.manifests.add(b, contents(*b.entries), images=blobs_b)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    await stores.manifests.remove_library(PAYMENTS.id)
    freed = await stores.manifests.collect_garbage(superseded_before=T0)

    assert freed.images == 0  # the ledger still uses both
    assert await stores.manifests.get_image(other.id, VersionRef("main"), "x.png") == PNG
    await stores.manifests.remove_version(other.id, VersionRef("main"))
    freed = await stores.manifests.collect_garbage(superseded_before=T0)
    assert freed.images == 2


async def test_a_discarded_pending_manifest_leaves_no_listed_images(stores: Stores) -> None:
    stored, blobs = with_images(
        manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {"x.png": PNG}
    )
    await stores.manifests.add(stored, contents(*stored.entries), images=blobs)

    await stores.manifests.discard_pending(
        manifest_id=ManifestId("m1"), library_id=None, created_before=None
    )

    assert (await stores.manifests.collect_garbage(superseded_before=T0)).images == 1


async def test_manual_tags_are_kept_per_library_and_path_until_cleared(stores: Stores) -> None:
    libraries = stores.libraries
    await libraries.set_manual_tags(PAYMENTS.id, ManualTags.of("a.md", ["x", "y"]))
    await libraries.set_manual_tags(PAYMENTS.id, ManualTags.of("b.md", ["z"]))
    await libraries.set_manual_tags(PAYMENTS.id, ManualTags.of("a.md", ["w"]))
    await libraries.set_manual_tags(PAYMENTS.id, ManualTags.of("b.md", []))
    await libraries.set_manual_tags(LibraryId("/acme/unknown"), ManualTags.of("a.md", ["x"]))

    assert await libraries.get_manual_tags(PAYMENTS.id) == {"a.md": ("w",)}
    assert await libraries.get_manual_tags(LibraryId("/acme/unknown")) == {}


async def test_manual_tags_go_with_their_library(stores: Stores) -> None:
    await stores.libraries.set_manual_tags(PAYMENTS.id, ManualTags.of("a.md", ["x"]))

    await stores.manifests.remove_library(PAYMENTS.id)
    await stores.libraries.save(PAYMENTS)

    assert await stores.libraries.get_manual_tags(PAYMENTS.id) == {}


async def test_live_manifests_are_the_pending_and_active_ones(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "a1"))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "a2", created_at=T0 + timedelta(seconds=1)))
    await stores.manifests.activate(ManifestId("m2"), at=T0)  # m1 is superseded
    await store(stores, manifest("m3", "v1", "a3"))

    live = await stores.manifests.list_live(PAYMENTS.id)

    assert sorted((m.id, m.state, m.entries) for m in live) == [
        ("m2", ManifestState.ACTIVE, ()),
        ("m3", ManifestState.PENDING, ()),
    ]


async def test_imported_tags_are_replaced_and_manual_ones_kept(stores: Stores) -> None:
    await store(
        stores,
        manifest("m1", "main", "a1", entry("a.md", "a", tags=("old",)), entry("b.md", "b")),
    )
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.set_manual_tags(ManifestId("m1"), {"a.md": (ManualTag("x", "a.md"),)})
    many = {f"n{i}.md": ("n",) for i in range(1200)}  # more than one batch of paths

    touched = await stores.imported_tags.set_imported_tags(
        ManifestId("m1"), {"a.md": ("api", "new"), "b.md": (), **many}
    )
    other = await stores.imported_tags.set_imported_tags(ManifestId("nope"), {"a.md": ("z",)})
    listed = await stores.manifests.list_entries(
        ManifestId("m1"), prefix="", tags=TagSelection.of(["api"]), after=None, limit=10
    )
    counted = await stores.manifests.count_tags(ManifestId("m1"), limit=10)

    assert touched == {"a.md": ("api", "new", "x"), "b.md": ()}  # every given entry it has
    assert other == {}
    assert [(e.path, e.tags, e.all_tags) for e in listed] == [
        ("a.md", ("api", "new"), ("api", "new", "x"))
    ]
    assert dict(counted) == {"api": 1, "new": 1, "x": 1}


async def test_imported_tags_of_more_entries_than_one_query_takes_are_all_written(
    stores: Stores,
) -> None:
    paths = [f"d/{i:04}.md" for i in range(1201)]  # three batches of paths in SQLite
    entries = (entry(p, f"{i:04x}") for i, p in enumerate(paths))
    await store(stores, manifest("m1", "main", "a1", *entries))
    wanted = {p: ("t", str(i % 2)) for i, p in enumerate(paths)}

    touched = await stores.imported_tags.set_imported_tags(ManifestId("m1"), wanted)
    again = await stores.imported_tags.set_imported_tags(ManifestId("m1"), wanted)
    counted = await stores.manifests.count_tags(ManifestId("m1"), limit=10)

    assert touched == again == wanted  # unchanged entries are reported too
    assert dict(counted) == {"t": 1201, "0": 601, "1": 600}


async def test_manual_tags_of_entries_combine_with_imported_ones_and_can_be_undone(
    stores: Stores,
) -> None:
    api = entry("a.md", "a", tags=("api",))
    plain = entry("b.md", "b")
    await store(stores, manifest("m1", "main", "a1", api, plain))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    manifests = stores.manifests

    manual = (ManualTag("api", "a.md"), ManualTag("onboarding", "old.md"))
    touched = await manifests.set_manual_tags(
        ManifestId("m1"), {"a.md": manual, "gone.md": (ManualTag("x", "gone.md"),)}
    )
    listed = await manifests.list_entries(
        ManifestId("m1"),
        prefix="",
        tags=TagSelection.of(["onboarding"]),
        after=None,
        limit=10,
    )
    article = await manifests.get_article(PAYMENTS.id, VersionRef("main"), "a.md")
    counted = await manifests.count_tags(ManifestId("m1"), limit=10)

    assert touched == {"a.md": ("api", "onboarding")}
    assert [(e.path, e.tags, e.manual_tags, e.all_tags) for e in listed] == [
        ("a.md", ("api",), manual, ("api", "onboarding"))
    ]
    assert article is not None
    assert article.entry.manual_tags == manual
    assert list(counted) == [("api", 1), ("onboarding", 1)]

    undone = await manifests.set_manual_tags(ManifestId("m1"), {})

    assert undone == {"a.md": ("api",)}
    entries = await manifests.list_entries(
        ManifestId("m1"), prefix="", tags=TagSelection(), after=None, limit=10
    )
    assert entries == (api, plain)
    assert (
        await manifests.set_manual_tags(ManifestId("none"), {"a.md": (ManualTag("x", "a.md"),)})
        == {}
    )


async def test_a_copy_of_the_active_manifest_is_pending_with_everything_it_has(
    stores: Stores,
) -> None:
    first, blobs = with_images(
        replace(
            manifest(
                "m1",
                "v1.4.0",
                "aaa111",
                entry("a.md", "a", tags=("api",)),
                entry("b.md", "b", title="B"),
                kind=RefKind.TAG,
            ),
            renames=(rename("old.md", "a.md"),),
        ),
        {"img/a.png": PNG},
    )
    await stores.manifests.add(first, contents(*first.entries), images=blobs)
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.set_manual_tags(ManifestId("m1"), {"a.md": (ManualTag("x", "a.md"),)})
    later = T0 + timedelta(hours=1)

    copied = await stores.copier.copy_active(
        PAYMENTS.id, VersionRef("v1.4.0"), ManifestId("m2"), at=later, content_version=1
    )

    assert copied is not None
    header, articles = copied
    assert (header.id, header.state, header.created_at) == ("m2", ManifestState.PENDING, later)
    assert (header.commit_sha, header.kind) == (first.commit_sha, RefKind.TAG)
    assert [(a.entry.path, a.entry.tags, a.entry.all_tags, a.content) for a in articles] == [
        ("a.md", ("api",), ("api", "x"), body(first.entries[0])),
        ("b.md", (), (), body(first.entries[1])),
    ]
    assert articles[1].entry == first.entries[1]
    assert await stores.manifests.list_renames(ManifestId("m2"), limit=9) == (
        rename("old.md", "a.md"),
    )
    assert (await fetch(stores.manifests, "m1")).state is ManifestState.ACTIVE  # still served
    await stores.manifests.activate(ManifestId("m2"), at=later)
    image = await stores.manifests.get_image(PAYMENTS.id, VersionRef("v1.4.0"), "img/a.png")
    assert image == PNG
    assert (await fetch(stores.manifests, "m1")).state is ManifestState.SUPERSEDED


async def test_nothing_is_copied_from_text_another_parser_stored(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "a1", entry("a.md", "a", version=1)))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    with pytest.raises(StoredContentOutdatedError):
        await stores.copier.copy_active(
            PAYMENTS.id, VersionRef("main"), ManifestId("m2"), at=T0, content_version=2
        )

    assert await stores.manifests.get(ManifestId("m2")) is None
    assert (
        await stores.copier.copy_active(
            PAYMENTS.id, VersionRef("v9"), ManifestId("m3"), at=T0, content_version=1
        )
        is None
    )
