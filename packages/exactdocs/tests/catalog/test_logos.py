"""A library's logo (#504): only the default version's is kept, read back and listed."""

from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryLogos,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.adapters.driven.sqlite import (
    SqliteLibraryLogos,
    SqliteLibraryRepository,
    SqliteManifestRepository,
)
from exactdocs.catalog.dtos import (
    ApplyLogoCommand,
    GetLibraryQuery,
    GetLogoQuery,
    ListLibrariesQuery,
    LogoIn,
)
from exactdocs.catalog.errors import InvalidLogoError, LibraryNotFoundError, LogoNotFoundError
from exactdocs.catalog.models import (
    Access,
    HostKind,
    Library,
    LibraryId,
    LibraryLogo,
    RefKind,
    Version,
    VersionRef,
)
from exactdocs.catalog.module import CatalogModule
from exactdocs.catalog.ports import LibraryLogos, LibraryRepository

LIBRARY = "/acme/payments"
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24


def version(ref: str, sha: str, age: int = 0) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=RefKind.TAG,
        commit_sha=sha.ljust(40, "0"),
        imported_at=NOW - timedelta(days=age),
    )


V13, V14 = version("v1.3.0", "a1", age=1), version("v1.4.0", "a2")
PAYMENTS = Library(
    id=LibraryId(LIBRARY),
    title="payments",
    source_url="https://github.com/acme/payments",
    host=HostKind.GITHUB,
    versions=frozenset({V13, V14}),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyListed:
    """An ``AccessPolicy`` double: the caller may read the listed libraries only."""

    readable_ids: frozenset[str]

    async def can_create(self, library: str | None = None) -> bool:
        del library
        return False

    async def allows(self, library: str, access: Access) -> bool:
        return access is Access.READ and library.lower() in self.readable_ids

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        return frozenset(lib.lower() for lib in libraries) & self.readable_ids

    async def claim(self, library: str) -> None:
        del library

    async def forget(self, library: str) -> None:
        del library


def build(*, readable: frozenset[str] | None = None) -> CatalogModule:
    repository = InMemoryLibraryRepository.of([PAYMENTS])
    written = InMemoryManifestRepository(libraries=repository)
    return CatalogModule.build(
        repository=repository,
        manifests=written,
        imported_tags=InMemoryImportedTags(repository=written),
        copier=InMemoryManifestCopier(repository=written),
        stored_articles=InMemoryStoredArticles(repository=written),
        logos=InMemoryLibraryLogos(libraries=repository),
        access=None if readable is None else OnlyListed(readable_ids=readable),
    )


def offer(
    ref: str, data: bytes | None = SVG, content_type: str = "image/svg+xml"
) -> ApplyLogoCommand:
    logo = None
    if data is not None:
        logo = LogoIn.model_validate(
            {"path": ".github/logo.svg", "content_type": content_type, "data": data}
        )
    return ApplyLogoCommand(library="/Acme/Payments", ref=ref, logo=logo)


def digest(data: bytes) -> str:
    return LibraryLogo(content_type="image/png", data=data, path="x", ref=VersionRef("v1")).digest


async def test_the_default_versions_logo_is_kept_and_listed_with_the_library() -> None:
    catalog = build()

    await catalog.apply_logo(offer("v1.4.0"))

    logo = await catalog.get_logo(GetLogoQuery(library=LIBRARY))
    assert (logo.content_type, logo.data, logo.unchanged) == ("image/svg+xml", SVG, False)
    assert len(logo.digest) == 16
    detail = await catalog.get_library(GetLibraryQuery(id=LIBRARY))
    (summary,) = (await catalog.list_libraries(ListLibrariesQuery())).libraries
    assert detail.logo == summary.logo == logo.digest


async def test_another_versions_logo_is_ignored() -> None:
    catalog = build()

    await catalog.apply_logo(offer("v1.3.0"))  # an older tag imported after the default

    with pytest.raises(LogoNotFoundError):
        await catalog.get_logo(GetLogoQuery(library=LIBRARY))
    assert (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).logo is None


async def test_a_default_version_without_a_logo_removes_the_librarys() -> None:
    catalog = build()
    await catalog.apply_logo(offer("v1.4.0"))

    await catalog.apply_logo(offer("v1.3.0", data=None))  # not the default: nothing changes
    assert (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).logo is not None

    await catalog.apply_logo(offer("v1.4.0", data=None))
    assert (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).logo is None


async def test_a_new_logo_replaces_the_old_one_and_changes_the_version() -> None:
    catalog = build()
    await catalog.apply_logo(offer("v1.4.0"))
    before = (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).logo

    await catalog.apply_logo(offer("v1.4.0", data=PNG, content_type="image/png"))

    logo = await catalog.get_logo(GetLogoQuery(library=LIBRARY))
    assert (logo.content_type, logo.data) == ("image/png", PNG)
    assert logo.digest == digest(PNG) != before


async def test_the_callers_current_copy_is_answered_without_the_bytes() -> None:
    catalog = build()
    await catalog.apply_logo(offer("v1.4.0"))
    current = (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).logo
    assert current is not None

    logo = await catalog.get_logo(GetLogoQuery(library=LIBRARY, known_digests=["old", current]))

    assert (logo.unchanged, logo.data, logo.digest) == (True, b"", current)


async def test_a_logo_of_a_hidden_or_unknown_library_is_not_found() -> None:
    hidden = build(readable=frozenset())
    await hidden.apply_logo(offer("v1.4.0"))  # the importer is not a caller
    everyone = build()

    with pytest.raises(LibraryNotFoundError):
        await hidden.get_logo(GetLogoQuery(library=LIBRARY))
    with pytest.raises(LibraryNotFoundError):
        await everyone.get_logo(GetLogoQuery(library="/acme/ledger"))
    with pytest.raises(LibraryNotFoundError):
        await everyone.apply_logo(ApplyLogoCommand(library="/acme/ledger", ref="v1"))


@pytest.mark.parametrize(
    ("content_type", "data"),
    [("image/gif", b"GIF89a"), ("image/png", b""), ("image/png", b"\0" * (512 * 1024 + 1))],
    ids=["gif", "empty", "too big"],
)
def test_the_catalog_re_checks_a_logos_type_and_size(content_type: str, data: bytes) -> None:
    with pytest.raises(InvalidLogoError):
        LibraryLogo(content_type=content_type, data=data, path="logo", ref=VersionRef("v1"))


# ---------------------------------------------------------------- adapter contract


@dataclass(frozen=True, slots=True, kw_only=True)
class Store:
    """A library repository and the logo store that shares its data."""

    libraries: LibraryRepository
    logos: LibraryLogos


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "memory":
        repository = InMemoryLibraryRepository()
        yield Store(libraries=repository, logos=InMemoryLibraryLogos(libraries=repository))
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield Store(
            libraries=SqliteLibraryRepository(engine=container.engine),
            logos=SqliteLibraryLogos(engine=container.engine),
        )


LOGO = LibraryLogo(
    content_type="image/svg+xml", data=SVG, path=".github/logo.svg", ref=VersionRef("v1.4.0")
)


async def test_a_kept_logo_comes_back_and_names_the_librarys_logo(store: Store) -> None:
    await store.libraries.save(PAYMENTS)

    await store.logos.put(LibraryId("/ACME/payments"), LOGO)

    assert await store.logos.get(PAYMENTS.id) == LOGO
    found = await store.libraries.get(PAYMENTS.id)
    assert found is not None
    assert found.logo == LOGO.digest
    assert [lib.logo for lib in await store.libraries.list_all()] == [LOGO.digest]


async def test_saving_a_library_keeps_its_logo(store: Store) -> None:
    await store.libraries.save(PAYMENTS)
    await store.logos.put(PAYMENTS.id, LOGO)

    await store.libraries.save(PAYMENTS)  # read before the logo was kept: `logo` is None

    found = await store.libraries.get(PAYMENTS.id)
    assert found is not None
    assert found.logo == LOGO.digest


async def test_a_logo_is_replaced_removed_and_never_kept_for_an_unknown_library(
    store: Store,
) -> None:
    await store.libraries.save(PAYMENTS)
    await store.logos.put(PAYMENTS.id, LOGO)
    other = LibraryLogo(content_type="image/png", data=PNG, path="logo.png", ref=VersionRef("v2"))

    await store.logos.put(PAYMENTS.id, other)
    assert await store.logos.get(PAYMENTS.id) == other

    await store.logos.remove(PAYMENTS.id)
    assert await store.logos.get(PAYMENTS.id) is None
    found = await store.libraries.get(PAYMENTS.id)
    assert found is not None
    assert found.logo is None

    await store.logos.put(LibraryId("/acme/ledger"), LOGO)
    assert await store.logos.get(LibraryId("/acme/ledger")) is None


async def test_a_logo_goes_with_its_library(store: Store) -> None:
    await store.libraries.save(PAYMENTS)
    await store.logos.put(PAYMENTS.id, LOGO)

    await store.libraries.delete(PAYMENTS.id)
    await store.libraries.save(PAYMENTS)  # the same ID again: a new library, no logo

    assert await store.logos.get(PAYMENTS.id) is None


@pytest.mark.parametrize("backend", ["memory", *SQL_BACKENDS])
async def test_a_removed_library_loses_its_logo(
    request: pytest.FixtureRequest, backend: str
) -> None:
    if backend == "memory":
        repository = InMemoryLibraryRepository()
        await repository.save(PAYMENTS)
        logos: LibraryLogos = InMemoryLibraryLogos(libraries=repository)
        await logos.put(PAYMENTS.id, LOGO)
        await InMemoryManifestRepository(libraries=repository).remove_library(PAYMENTS.id)
        await repository.save(PAYMENTS)
        assert await logos.get(PAYMENTS.id) is None
        return
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        libraries = SqliteLibraryRepository(engine=container.engine)
        logos = SqliteLibraryLogos(engine=container.engine)
        await libraries.save(PAYMENTS)
        await logos.put(PAYMENTS.id, LOGO)
        await SqliteManifestRepository(engine=container.engine).remove_library(PAYMENTS.id)
        await libraries.save(PAYMENTS)
        assert await logos.get(PAYMENTS.id) is None
