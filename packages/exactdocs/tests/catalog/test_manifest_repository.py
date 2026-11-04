"""Adapter contract: every ``ManifestRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryLibraryRepository,
    InMemoryManifestRepository,
)
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteLibraryRepository,
    SqliteManifestRepository,
    article_contents,
)
from exactdocs.catalog.errors import ManifestNotFoundError, ManifestNotPendingError
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    Manifest,
    ManifestEntry,
    ManifestId,
    ManifestState,
    RefKind,
    VersionRef,
)
from exactdocs.catalog.ports import LibraryRepository, ManifestRepository

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


def entry(path: str, blob: str, *, title: str = "T", tags: tuple[str, ...] = ()) -> ManifestEntry:
    return ManifestEntry(
        path=path,
        blob_sha=sha(blob),
        title=title,
        tags=tags,
        front_matter={"title": title, "nested": {"n": [1, None, "x"]}},
        size=7,
    )


def manifest(
    id_: str, ref: str, commit: str, *entries: ManifestEntry, kind: RefKind = RefKind.BRANCH
) -> Manifest:
    return Manifest(
        id=ManifestId(id_),
        library=PAYMENTS.id,
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha(commit),
        created_at=T0,
        entries=entries,
    )


def contents(*entries: ManifestEntry) -> dict[str, str]:
    return {e.blob_sha: f"content of {e.blob_sha[:6]}" for e in entries}


@dataclass(frozen=True, slots=True)
class Stores:
    libraries: LibraryRepository
    manifests: ManifestRepository
    count_contents: Callable[[], Awaitable[int]]


@pytest.fixture(params=["memory", "sqlite"])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    if request.param == "memory":
        libraries = InMemoryLibraryRepository()
        manifests = InMemoryManifestRepository(libraries)

        async def count() -> int:
            return len(manifests.contents)

        found = Stores(libraries, manifests, count)
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

    assert await stores.manifests.get(stored.id) == stored
    assert (await fetch(stores.manifests, stored.id)).state is ManifestState.PENDING
    assert await stores.manifests.get(ManifestId("nope")) is None


async def test_a_pending_manifest_is_invisible_until_it_is_activated(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)

    assert article is not None
    assert (article.commit_sha, article.manifest_id) == (sha("aaa111"), "m1")
    assert article.content == f"content of {sha('b1')[:6]}"
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


async def test_only_a_pending_manifest_can_be_activated(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111"))
    await store(stores, manifest("m2", "main", "bbb222"))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await stores.manifests.activate(ManifestId("m2"), at=T0)

    with pytest.raises(ManifestNotPendingError):  # active
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
    assert [e.path for e in (await fetch(stores.manifests, "m2")).entries] == [
        INSTALL,
        "new.md",
    ]


async def test_storing_content_again_keeps_what_is_there(stores: Stores) -> None:
    stored = manifest("m1", "main", "aaa111", entry(INSTALL, "b1"))
    await stores.manifests.add(stored, {sha("b1"): "first"})
    await stores.manifests.add(replace(stored, id=ManifestId("m2")), {sha("b1"): "second"})
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    article = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)

    assert article is not None
    assert (article.content, await stores.count_contents()) == ("first", 1)


async def test_an_article_that_is_not_in_the_active_manifest_is_none(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    pending = await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), INSTALL)
    await stores.manifests.activate(ManifestId("m1"), at=T0)

    assert pending is None
    assert await stores.manifests.get_article(PAYMENTS.id, VersionRef("main"), "other.md") is None
    assert await stores.manifests.get_article(PAYMENTS.id, VersionRef("next"), INSTALL) is None


async def test_discarding_removes_pending_manifests_and_nothing_else(stores: Stores) -> None:
    await store(stores, manifest("m1", "main", "aaa111", entry(INSTALL, "b1")))
    await stores.manifests.activate(ManifestId("m1"), at=T0)
    await store(stores, manifest("m2", "main", "bbb222", entry(INSTALL, "b2")))
    await store(stores, manifest("m3", "main", "ccc333"))
    await store(stores, manifest("m4", "next", "ddd444"))

    assert await stores.manifests.discard_pending(ManifestId("m2")) == 1
    assert await stores.manifests.discard_pending(ManifestId("m1")) == 0  # active: not pending
    assert await stores.manifests.discard_pending(ManifestId("nope")) == 0
    assert await stores.manifests.discard_pending(None) == 2

    assert await stores.manifests.get(ManifestId("m1")) is not None
    assert [await stores.manifests.get(ManifestId(i)) for i in ("m2", "m3", "m4")] == [None] * 3
    assert await active_commit(stores, "main") == sha("aaa111")


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
    await stores.manifests.discard_pending(None)

    collected = await stores.manifests.collect_garbage(superseded_before=T0)

    assert (collected.manifests, collected.contents) == (0, 1)
    assert await stores.count_contents() == 0


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
    await manifests.add(manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {sha("b1"): "old"})
    await manifests.add(manifest("m2", "main", "bbb222", entry(INSTALL, "b2")), {sha("b2"): "new"})
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


async def test_sqlite_saving_the_library_again_keeps_its_manifests(sqlite: Container) -> None:
    libraries = SqliteLibraryRepository(sqlite.engine)
    manifests = SqliteManifestRepository(sqlite.engine)
    await manifests.add(manifest("m1", "main", "aaa111", entry(INSTALL, "b1")), {sha("b1"): "x"})
    await manifests.activate(ManifestId("m1"), at=T0)
    moved = await libraries.get(PAYMENTS.id)
    assert moved is not None

    await libraries.save(replace(moved, title="Renamed"))

    assert (await manifests.get_active(PAYMENTS.id, VersionRef("main"))) is not None
