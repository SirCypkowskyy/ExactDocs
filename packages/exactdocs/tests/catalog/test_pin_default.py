"""Pinning the default version (LIB-10): a pin wins until it is removed, then the rule applies."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
)
from exactdocs.catalog.dtos import (
    GetLibraryQuery,
    ListLibrariesQuery,
    PinDefaultVersionCommand,
    RemoveVersionCommand,
    ResolveVersionQuery,
)
from exactdocs.catalog.errors import LibraryNotFoundError, VersionNotFoundError
from exactdocs.catalog.models import (
    HostKind,
    Library,
    LibraryId,
    LibrarySettings,
    ManualTags,
    RefKind,
    Version,
    VersionRef,
)
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/payments"
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def version(ref: str, kind: RefKind = RefKind.TAG, sha: str = "a", age: int = 0) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha.ljust(40, "0"),
        imported_at=NOW - timedelta(days=age),
    )


V13, V15 = version("v1.3.0", sha="b1", age=2), version("v1.5.0", sha="b2")
COMMIT = version("c0ffee1", RefKind.COMMIT, sha="c0ffee1", age=1)


def build(*versions: Version) -> CatalogModule:
    repository = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                versions=frozenset(versions),
            )
        ]
    )
    return CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(repository)),
        imported_tags=InMemoryImportedTags(written),
        copier=InMemoryManifestCopier(written),
    )


async def test_a_pinned_version_is_the_default_and_says_so() -> None:
    catalog = build(V13, V15)

    pinned = await catalog.pin_default_version(
        PinDefaultVersionCommand(library="/Acme/Payments", ref="v1.3.0")
    )

    assert (pinned.default_version, pinned.default_pinned) == ("v1.3.0", True)
    assert [v.ref for v in pinned.versions if v.is_default] == ["v1.3.0"]
    resolved = await catalog.resolve_version(ResolveVersionQuery(id=LIBRARY))
    assert resolved.ref == "v1.3.0"
    (summary,) = (await catalog.list_libraries(ListLibrariesQuery())).libraries
    assert (summary.default_version, summary.default_pinned) == ("v1.3.0", True)


async def test_unpinned_the_default_follows_the_rule_again() -> None:
    catalog = build(V13, V15)
    await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="v1.3.0"))

    unpinned = await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY))

    assert (unpinned.default_version, unpinned.default_pinned) == ("v1.5.0", False)


async def test_unpinning_an_unpinned_library_changes_nothing() -> None:
    catalog = build(V13, V15)

    unpinned = await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY))

    assert (unpinned.default_version, unpinned.default_pinned) == ("v1.5.0", False)


async def test_a_short_sha_pins_the_commit_version_it_names() -> None:
    catalog = build(V15, COMMIT)

    pinned = await catalog.pin_default_version(
        PinDefaultVersionCommand(library=LIBRARY, ref="c0ffee1000")
    )

    assert (pinned.default_version, pinned.default_pinned) == ("c0ffee1", True)


async def test_only_an_imported_version_can_be_pinned() -> None:
    catalog = build(V13)

    with pytest.raises(VersionNotFoundError):
        await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="v1.4.0"))
    with pytest.raises(VersionNotFoundError):  # refs are case-sensitive, never approximated
        await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="V1.3.0"))
    with pytest.raises(LibraryNotFoundError):
        await catalog.pin_default_version(
            PinDefaultVersionCommand(library="/acme/ledger", ref="v1.3.0")
        )

    assert not (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).default_pinned


async def test_removing_the_pinned_version_unpins_the_library() -> None:
    catalog = build(V13, V15, version("v1.4.0", sha="b3", age=1))
    await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="v1.4.0"))

    removal = await catalog.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v1.4.0"))

    assert removal.default_ref == "v1.5.0"
    found = await catalog.get_library(GetLibraryQuery(id=LIBRARY))
    assert (found.default_version, found.default_pinned) == ("v1.5.0", False)


class LibraryRemovedWhilePinning:
    """A repository where the library is deleted just before the pin is written."""

    def __init__(self, inner: InMemoryLibraryRepository) -> None:
        self.inner = inner

    async def list_all(self) -> Sequence[Library]:
        return await self.inner.list_all()

    async def get(self, library_id: LibraryId) -> Library | None:
        return await self.inner.get(library_id)

    async def add(self, library: Library) -> None:
        await self.inner.add(library)

    async def delete(self, library_id: LibraryId) -> None:
        await self.inner.delete(library_id)

    async def save(self, library: Library) -> None:
        await self.inner.save(library)

    async def set_text(
        self, library_id: LibraryId, *, title: str | None, description: str | None
    ) -> None:
        await self.inner.set_text(library_id, title=title, description=description)

    async def set_settings(self, library_id: LibraryId, settings: LibrarySettings) -> None:
        await self.inner.set_settings(library_id, settings)

    async def pin_default(self, library_id: LibraryId, ref: VersionRef | None) -> bool:
        await self.inner.delete(library_id)
        return await self.inner.pin_default(library_id, ref)

    async def follow_readme(
        self, library_id: LibraryId, *, title: str, description: str, rules: Sequence[str]
    ) -> None:
        await self.inner.follow_readme(
            library_id, title=title, description=description, rules=rules
        )

    async def get_manual_tags(self, library_id: LibraryId) -> Mapping[str, tuple[str, ...]]:
        return await self.inner.get_manual_tags(library_id)

    async def set_manual_tags(self, library_id: LibraryId, tags: ManualTags) -> None:
        await self.inner.set_manual_tags(library_id, tags)


async def test_a_library_removed_while_pinning_is_reported_as_missing() -> None:
    inner = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                versions=frozenset({V13}),
            )
        ]
    )
    repository = LibraryRemovedWhilePinning(inner)
    catalog = CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(inner)),
        imported_tags=InMemoryImportedTags(written),
        copier=InMemoryManifestCopier(written),
    )

    with pytest.raises(LibraryNotFoundError):
        await catalog.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="v1.3.0"))
