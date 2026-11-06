from datetime import UTC, datetime

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
)
from exactdocs.catalog.dtos import (
    CreateLibraryCommand,
    DiscardLibraryCommand,
    GetLibraryQuery,
    ListLibrariesQuery,
    ResolveVersionQuery,
)
from exactdocs.catalog.errors import (
    AmbiguousCommitError,
    InvalidLibraryIdError,
    LibraryAlreadyExistsError,
    LibraryNotEmptyError,
    LibraryNotFoundError,
    VersionNotFoundError,
)
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    RefKind,
    Version,
    VersionRef,
)
from exactdocs.catalog.module import CatalogModule


def version(ref: str, kind: RefKind, sha: str, hour: int = 12) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha.ljust(40, "0"),
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


@pytest.fixture
def catalog() -> CatalogModule:
    repository = InMemoryLibraryRepository.of(
        [
            library(
                "payments",
                version("v1.3.0", RefKind.TAG, "a1"),
                version("v1.4.0", RefKind.TAG, "a2"),
                version("v1.5.0-rc.1", RefKind.TAG, "a3", hour=18),
                version("main", RefKind.BRANCH, "a4", hour=19),
                version("release/1.4", RefKind.BRANCH, "a5"),
                version("1234abc1", RefKind.COMMIT, "1234abc1"),
                version("1234abc2", RefKind.COMMIT, "1234abc2"),
                version("fedcba98", RefKind.COMMIT, "fedcba9876"),
            ),
            library("ledger", version("main", RefKind.BRANCH, "b1")),
            library("empty"),
        ]
    )
    return CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(repository)),
        imported_tags=InMemoryImportedTags(written),
        copier=InMemoryManifestCopier(written),
    )


async def test_lists_libraries_sorted_by_id_with_sorted_refs_and_the_default(
    catalog: CatalogModule,
) -> None:
    result = await catalog.list_libraries(ListLibrariesQuery())

    assert [(lib.id, lib.default_version) for lib in result.libraries] == [
        ("/acme/empty", None),
        ("/acme/ledger", "main"),
        ("/acme/payments", "v1.4.0"),
    ]
    refs = [v.ref for v in result.libraries[2].refs]
    assert refs == sorted(refs)
    assert result.libraries[2].version_count == len(refs)


async def test_get_library_matches_the_id_case_insensitively(catalog: CatalogModule) -> None:
    result = await catalog.get_library(GetLibraryQuery(id="/ACME/Payments"))

    assert result.id == "/acme/payments"
    assert result.default_version == "v1.4.0"
    assert [v.ref for v in result.versions if v.is_default] == ["v1.4.0"]
    assert result.settings.chunking.split_level == 6


async def test_get_library_raises_for_an_unknown_id(catalog: CatalogModule) -> None:
    with pytest.raises(LibraryNotFoundError):
        await catalog.get_library(GetLibraryQuery(id="/vuejs/docs"))


async def test_get_library_raises_validation_error_for_a_malformed_id(
    catalog: CatalogModule,
) -> None:
    with pytest.raises(InvalidLibraryIdError):
        await catalog.get_library(GetLibraryQuery(id="/acme/payments/v1.4.0"))


async def test_libraries_are_listed_page_by_page_with_an_opaque_cursor(
    catalog: CatalogModule,
) -> None:
    first = await catalog.list_libraries(ListLibrariesQuery(limit=2))
    second = await catalog.list_libraries(ListLibrariesQuery(limit=2, cursor=first.next_cursor))

    assert [lib.id for lib in first.libraries] == ["/acme/empty", "/acme/ledger"]
    assert [lib.id for lib in second.libraries] == ["/acme/payments"]
    assert second.next_cursor is None


async def test_an_id_without_a_ref_resolves_to_the_default_version_and_says_so(
    catalog: CatalogModule,
) -> None:
    result = await catalog.resolve_version(ResolveVersionQuery(id="/acme/payments"))

    assert (result.library, result.ref, result.kind, result.is_default) == (
        "/acme/payments",
        "v1.4.0",
        RefKind.TAG,
        True,
    )
    assert result.commit_sha == "a2".ljust(40, "0")


@pytest.mark.parametrize(
    ("id_", "ref", "is_default"),
    [
        ("/acme/payments/v1.3.0", "v1.3.0", False),
        ("/Acme/PAYMENTS/v1.4.0", "v1.4.0", True),
        ("/acme/payments/v1.5.0-rc.1", "v1.5.0-rc.1", False),
        ("/acme/payments/release/1.4", "release/1.4", False),
        ("/acme/payments/main", "main", False),
        ("/acme/payments/fedcba98", "fedcba98", False),
        ("/acme/payments/fedcba987", "fedcba98", False),  # unique short SHA of a commit version
        ("/acme/ledger/main", "main", True),
    ],
)
async def test_an_id_with_a_ref_resolves_to_exactly_that_version(
    catalog: CatalogModule, id_: str, ref: str, is_default: bool
) -> None:
    result = await catalog.resolve_version(ResolveVersionQuery(id=id_))

    assert (result.ref, result.is_default) == (ref, is_default)


@pytest.mark.parametrize(
    "id_",
    [
        "/acme/payments/V1.4.0",  # refs are case-sensitive
        "/acme/payments/v1.4",  # never a prefix or "closest" match
        "/acme/payments/release",
        "/acme/payments/1234abd",  # unknown short SHA
    ],
)
async def test_an_unknown_ref_is_not_found_never_another_version(
    catalog: CatalogModule, id_: str
) -> None:
    with pytest.raises(VersionNotFoundError):
        await catalog.resolve_version(ResolveVersionQuery(id=id_))


async def test_an_unknown_library_is_not_found(catalog: CatalogModule) -> None:
    with pytest.raises(LibraryNotFoundError):
        await catalog.resolve_version(ResolveVersionQuery(id="/vuejs/docs/v1"))


async def test_a_library_without_versions_has_no_default_version(catalog: CatalogModule) -> None:
    with pytest.raises(VersionNotFoundError, match="no imported version"):
        await catalog.resolve_version(ResolveVersionQuery(id="/acme/empty"))


async def test_an_ambiguous_short_sha_is_a_validation_error(catalog: CatalogModule) -> None:
    with pytest.raises(AmbiguousCommitError):
        await catalog.resolve_version(ResolveVersionQuery(id="/acme/payments/1234abc"))


async def test_a_library_is_created_without_versions_and_not_twice() -> None:
    repository = InMemoryLibraryRepository()
    create = CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(repository)),
        imported_tags=InMemoryImportedTags(written),
        copier=InMemoryManifestCopier(written),
    ).create_library
    command = CreateLibraryCommand(
        id="/Acme/Docs",
        title="docs",
        source_url="https://git.example.com/acme/docs",
        host=HostKind.GIT,
        default_branch="main",
        include_paths=["docs/"],
        exclude_paths=["docs/old/"],
    )

    created = await create(command)

    assert (created.id, created.versions, created.default_version) == ("/acme/docs", [], None)
    assert created.settings.include_paths == ["docs/"]
    with pytest.raises(LibraryAlreadyExistsError):
        await create(command)


async def test_a_new_library_can_be_discarded_but_an_imported_one_cannot(
    catalog: CatalogModule,
) -> None:
    await catalog.create_library(
        CreateLibraryCommand(id="/acme/new", title="new", source_url="x", host=HostKind.GIT)
    )

    await catalog.discard_library(DiscardLibraryCommand(id="/acme/new"))
    await catalog.discard_library(DiscardLibraryCommand(id="/acme/new"))  # absent: no-op
    with pytest.raises(LibraryNotEmptyError):
        await catalog.discard_library(DiscardLibraryCommand(id="/acme/payments"))

    with pytest.raises(LibraryNotFoundError):
        await catalog.get_library(GetLibraryQuery(id="/acme/new"))
    await catalog.get_library(GetLibraryQuery(id="/acme/payments"))
