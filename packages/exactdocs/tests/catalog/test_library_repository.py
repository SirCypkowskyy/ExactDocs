"""Adapter contract: every ``LibraryRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import InMemoryLibraryRepository
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import (
    ChunkingConfig,
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    RefKind,
    TagRule,
    Version,
    VersionRef,
)
from exactdocs.catalog.ports import LibraryRepository


def version(ref: str, kind: RefKind, sha: str) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha.ljust(40, "0"),
        imported_at=datetime(2026, 11, 4, 12, 30, 5, 123456, tzinfo=UTC),
    )


PAYMENTS = Library(
    id=LibraryId("/acme/payments"),
    title="Payments",
    description="Payment processing SDK",
    source_url="https://github.com/acme/payments",
    host=HostKind.GITHUB,
    default_branch=VersionRef("main"),
    settings=LibrarySettings(
        include_paths=("docs",),
        exclude_paths=("docs/internal", "**/*.draft.md"),
        tag_rules=(TagRule(pattern="docs/api/**", tag="api"),),
        chunking=ChunkingConfig(split_level=2, min_chars=200, max_chars=4000),
    ),
    versions=frozenset(
        {
            version("v1.4.0", RefKind.TAG, "a1"),
            version("V1.4.0", RefKind.TAG, "a2"),  # refs are case-sensitive: a different version
            version("main", RefKind.BRANCH, "b1"),
            version("release/1.4", RefKind.BRANCH, "b2"),
            version("c0ffee1", RefKind.COMMIT, "c0ffee1"),
        }
    ),
)
LEDGER = Library(
    id=LibraryId("/acme/ledger"),
    title="Ledger",
    source_url="https://git.example.com/acme/ledger.git",
    host=HostKind.GIT,
)


@pytest.fixture(params=["memory", "sqlite"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[LibraryRepository]:
    if request.param == "memory":
        yield InMemoryLibraryRepository()
        return
    container = Container.build(Settings())
    async with container.running():
        yield SqliteLibraryRepository(container.engine)


async def test_starts_empty(repository: LibraryRepository) -> None:
    assert await repository.list_all() == ()
    assert await repository.get(PAYMENTS.id) is None


async def test_everything_about_a_saved_library_comes_back(repository: LibraryRepository) -> None:
    await repository.save(PAYMENTS)
    await repository.save(LEDGER)

    assert await repository.get(PAYMENTS.id) == PAYMENTS
    assert await repository.get(LEDGER.id) == LEDGER
    assert set(await repository.list_all()) == {PAYMENTS, LEDGER}


async def test_ids_are_matched_case_insensitively(repository: LibraryRepository) -> None:
    await repository.save(PAYMENTS)

    assert await repository.get(LibraryId("/ACME/Payments")) == PAYMENTS


async def test_get_needs_the_whole_id(repository: LibraryRepository) -> None:
    await repository.save(PAYMENTS)

    assert await repository.get(LibraryId("/acme/pay")) is None
    assert await repository.get(LibraryId("/other/payments")) is None


async def test_saving_again_updates_the_library_and_adds_versions_but_keeps_existing_ones(
    repository: LibraryRepository,
) -> None:
    # Activating a manifest moves versions too, so a save from an older read must not undo that.
    await repository.save(PAYMENTS)
    moved = version("main", RefKind.BRANCH, "ffff")  # same ref, other commit: stored one wins
    added = version("v2.0.0", RefKind.TAG, "d1")
    newer = replace(
        PAYMENTS,
        title="Payments 2",
        default_branch=None,
        versions=frozenset({moved, added}),
    )

    await repository.save(newer)

    saved = await repository.get(PAYMENTS.id)
    assert saved is not None
    assert (saved.title, saved.default_branch) == ("Payments 2", None)
    assert saved.versions == PAYMENTS.versions | {added}
    assert await repository.list_all() == (saved,)


async def test_a_library_without_versions_is_kept(repository: LibraryRepository) -> None:
    await repository.save(LEDGER)

    assert await repository.get(LEDGER.id) == LEDGER


async def test_sqlite_keeps_a_pinned_version_when_the_library_is_saved_again() -> None:
    # LIB-10 (MVP-2) will own `pinned_version`; until then saving must not clobber the column.
    container = Container.build(Settings())
    async with container.running():
        repository = SqliteLibraryRepository(container.engine)
        await repository.save(PAYMENTS)
        async with container.engine.begin() as connection:
            await connection.execute(text("UPDATE catalog_libraries SET pinned_version = 'v1.4.0'"))

        await repository.save(replace(PAYMENTS, title="Renamed"))

        async with container.engine.connect() as connection:
            pinned = await connection.execute(text("SELECT pinned_version FROM catalog_libraries"))
            assert pinned.scalar_one() == "v1.4.0"
