from datetime import UTC, datetime

import pytest

from exactdocs.bootstrap.bridges import (
    CatalogActiveManifests,
    CatalogDefaultVersions,
    CatalogLibraries,
    CatalogLibraryIds,
    CatalogLibrarySources,
    CatalogSearchableVersions,
)
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryLibraryRepository,
    InMemoryManifestRepository,
)
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    GetManifestStatesQuery,
    ManifestStates,
    StoreManifestCommand,
)
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    RefKind,
    Version,
    VersionOrigin,
    VersionRef,
)
from exactdocs.catalog.module import CatalogModule
from exactdocs.ingestion.models import ImportedRef, ProposedId
from exactdocs.ingestion.models import RefKind as IngestionRefKind
from exactdocs.ingestion.models import VersionOrigin as IngestionOrigin
from exactdocs.retrieval.models import DocTarget, ManifestStatus, SourceHost
from exactdocs_kernel import MAX_LIMIT

PAYMENTS = Library(
    id=LibraryId("/acme/payments"),
    title="Payments",
    source_url="https://github.com/acme/payments",
    host=HostKind.GITHUB,
    versions=frozenset(
        {
            Version(
                ref=VersionRef("v1.4.0"),
                kind=RefKind.TAG,
                commit_sha="a" * 40,
                imported_at=datetime(2026, 11, 4, tzinfo=UTC),
            ),
            Version(
                ref=VersionRef("abc1234"),
                kind=RefKind.COMMIT,
                commit_sha="abc1234" + "0" * 33,
                imported_at=datetime(2026, 11, 4, tzinfo=UTC),
            ),
        }
    ),
)
_LIBRARIES = InMemoryLibraryRepository.of([PAYMENTS])
CATALOG = CatalogModule.build(
    repository=_LIBRARIES, manifests=InMemoryManifestRepository(_LIBRARIES)
)
ACTIVE = CatalogActiveManifests(CATALOG.get_active_manifest, CATALOG.get_manifest_states)


_TAKEN = InMemoryLibraryRepository.of([PAYMENTS])
LIBRARY_IDS = CatalogLibraryIds(
    CatalogModule.build(repository=_TAKEN, manifests=InMemoryManifestRepository(_TAKEN)).get_library
)


@pytest.mark.parametrize(
    ("library", "taken"),
    [("/acme/payments", True), ("/Acme/Payments", True), ("/acme/ledger", False)],
)
async def test_a_library_id_is_taken_when_the_catalog_has_it(library: str, taken: bool) -> None:
    assert await LIBRARY_IDS.is_taken(ProposedId(library)) is taken


async def _store(commit: str) -> str:
    stored = await CATALOG.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref="v1.4.0",
            kind=RefKind.TAG,
            commit_sha=commit * 40,
            articles=[
                ArticleIn(path="a.md", blob_sha="1" * 40, content_version=1, title="A", content="a")
            ],
        )
    )
    return stored.manifest_id


async def test_manifest_statuses_follow_the_catalog_and_unknown_ids_are_left_out() -> None:
    first, second = await _store("a"), await _store("b")
    target = DocTarget(library="/acme/payments", version="v1.4.0")
    assert await ACTIVE.statuses([first, second, "nope"]) == {
        first: ManifestStatus.PENDING,
        second: ManifestStatus.PENDING,
    }
    assert await ACTIVE.active_id(target) is None

    await CATALOG.activate_manifest(ActivateManifestCommand(manifest_id=first))
    assert await ACTIVE.active_id(target) == first

    await CATALOG.activate_manifest(ActivateManifestCommand(manifest_id=second))
    assert await ACTIVE.active_id(target) == second
    assert await ACTIVE.statuses([first, second]) == {
        first: ManifestStatus.SUPERSEDED,
        second: ManifestStatus.ACTIVE,
    }


async def test_a_version_the_catalog_does_not_have_has_no_active_manifest() -> None:
    assert await ACTIVE.active_id(DocTarget(library="/acme/payments", version="nope")) is None


async def test_a_state_the_catalog_adds_later_maps_to_other_so_it_is_kept() -> None:
    async def newer_catalog(query: GetManifestStatesQuery) -> ManifestStates:
        assert query.manifest_ids
        states = {"m1": "failed", "m2": "active"}  # "failed" does not exist yet
        return ManifestStates.model_construct(states=states)

    bridge = CatalogActiveManifests(CATALOG.get_active_manifest, newer_catalog)

    assert await bridge.statuses(["m1", "m2"]) == {
        "m1": ManifestStatus.OTHER,
        "m2": ManifestStatus.ACTIVE,
    }


SEARCHABLE = CatalogSearchableVersions(CATALOG.get_library, CATALOG.get_active_manifest)


async def test_a_searchable_version_needs_an_active_manifest_and_names_its_source() -> None:
    assert await SEARCHABLE.find("/acme/payments", "abc1234") is None  # no active manifest

    manifest_id = await _store("c")
    await CATALOG.activate_manifest(ActivateManifestCommand(manifest_id=manifest_id))

    found = await SEARCHABLE.find("/Acme/Payments", "v1.4.0")
    assert found is not None
    assert (found.library, found.version, found.manifest_id) == (
        "/acme/payments",
        "v1.4.0",
        manifest_id,
    )
    assert (found.commit_sha, found.host) == ("c" * 40, SourceHost.GITHUB)
    assert found.repository_url == "https://github.com/acme/payments"
    assert await SEARCHABLE.find("/acme/payments", None) == found  # the default version
    assert await SEARCHABLE.find("/acme/payments", "abc12340") is None  # not an exact ref
    assert await SEARCHABLE.find("/vuejs/docs", None) is None
    assert await SEARCHABLE.find("/acme/payments", "v 1") is None  # not a ref at all


async def test_the_library_bridge_reads_every_page_and_skips_libraries_without_a_version() -> None:
    many = [
        Library(
            id=LibraryId(f"/acme/lib-{i:03d}"),
            title=f"Lib {i}",
            source_url="https://github.com/acme/x",
            host=HostKind.GITHUB,
            versions=PAYMENTS.versions if i else frozenset(),
        )
        for i in range(MAX_LIMIT + 5)
    ]
    repository = InMemoryLibraryRepository.of(many)
    catalog = CatalogModule.build(
        repository=repository, manifests=InMemoryManifestRepository(repository)
    )

    found = await CatalogLibraries(catalog.list_libraries).all()

    assert len(found) == MAX_LIMIT + 4  # lib-000 has no version
    assert found[0].id == "/acme/lib-001"
    assert (found[0].title, found[0].default_version) == ("Lib 1", "v1.4.0")
    assert found[0].version_count == len(PAYMENTS.versions)


async def test_default_versions_come_in_one_call_with_active_manifests_only() -> None:
    other = Library(
        id=LibraryId("/acme/other"),
        title="Other",
        source_url="https://gitlab.com/acme/other",
        host=HostKind.GITLAB,
        versions=PAYMENTS.versions,
    )
    repository = InMemoryLibraryRepository.of([PAYMENTS, other])
    catalog = CatalogModule.build(
        repository=repository, manifests=InMemoryManifestRepository(repository)
    )
    stored = await catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/other",
            ref="v1.4.0",
            kind=RefKind.TAG,
            commit_sha="d" * 40,
            articles=[
                ArticleIn(
                    path="a.md",
                    blob_sha="e" * 40,
                    content_version=1,
                    title="A",
                    tags=[],
                    front_matter={},
                    content="x",
                )
            ],
        )
    )
    await catalog.activate_manifest(ActivateManifestCommand(manifest_id=stored.manifest_id))

    found = await CatalogDefaultVersions(catalog.list_default_manifests).all()

    # /acme/payments has a default version (v1.4.0) but nothing active: it is left out.
    assert [(v.library, v.version, v.manifest_id) for v in found] == [
        ("/acme/other", "v1.4.0", stored.manifest_id)
    ]
    assert (found[0].commit_sha, found[0].host) == ("d" * 40, SourceHost.GITLAB)
    assert found[0].repository_url == "https://gitlab.com/acme/other"


async def test_library_sources_report_each_versions_origin_and_the_pinned_default() -> None:
    at = datetime(2026, 11, 4, tzinfo=UTC)
    library = Library(
        id=LibraryId("/acme/ledger"),
        title="Ledger",
        source_url="https://github.com/acme/ledger",
        host=HostKind.GITHUB,
        versions=frozenset(
            {
                Version(
                    ref=VersionRef(ref),
                    kind=RefKind.TAG,
                    commit_sha=sha * 40,
                    imported_at=at,
                    origin=VersionOrigin.AUTO,
                )
                for ref, sha in (("v1.3.0", "a"), ("v1.4.0", "b"))
            }
        ),
        pinned_version=VersionRef("v1.3.0"),
    )
    repository = InMemoryLibraryRepository.of([library])
    catalog = CatalogModule.build(
        repository=repository, manifests=InMemoryManifestRepository(repository)
    )
    sources = CatalogLibrarySources(catalog.get_library, catalog.list_renames)

    found = sorted(await sources.imported_versions("/acme/ledger"), key=lambda v: v.ref)

    assert found == [
        ImportedRef(
            ref="v1.3.0",
            kind=IngestionRefKind.TAG,
            commit_sha="a" * 40,
            origin=IngestionOrigin.AUTO,
            pinned=True,
        ),
        ImportedRef(
            ref="v1.4.0",
            kind=IngestionRefKind.TAG,
            commit_sha="b" * 40,
            origin=IngestionOrigin.AUTO,
            pinned=False,
        ),
    ]
