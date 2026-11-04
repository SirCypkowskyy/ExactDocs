from datetime import UTC, datetime

import pytest

from exactdocs.bootstrap.bridges import CatalogIndexedVersions
from exactdocs.catalog.adapters.driven.memory import (
    InMemoryLibraryRepository,
    InMemoryManifestRepository,
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
from exactdocs.retrieval.models import DocTarget

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
BRIDGE = CatalogIndexedVersions(
    CatalogModule.build(
        repository=_LIBRARIES, manifests=InMemoryManifestRepository(_LIBRARIES)
    ).resolve_version
)


@pytest.mark.parametrize("library", ["/acme/payments", "/Acme/Payments", "/ACME/PAYMENTS"])
async def test_an_indexed_version_comes_back_with_the_stored_library_id(library: str) -> None:
    found = await BRIDGE.find_indexed(DocTarget(library=library, version="v1.4.0"))

    assert found == DocTarget(library="/acme/payments", version="v1.4.0")


@pytest.mark.parametrize(
    ("library", "version"),
    [
        ("/acme/payments", "V1.4.0"),  # refs are case-sensitive
        ("/acme/payments", "v1.3.0"),
        ("/acme/payments", "abc12340"),  # a short SHA of a commit is not the exact ref
        ("/acme/payments/v1", "v1.4.0"),  # the split must not move the ref into the ID
        ("/vuejs/docs", "v1.4.0"),
    ],
)
async def test_anything_but_an_exact_indexed_ref_is_not_indexed(library: str, version: str) -> None:
    assert await BRIDGE.find_indexed(DocTarget(library=library, version=version)) is None
