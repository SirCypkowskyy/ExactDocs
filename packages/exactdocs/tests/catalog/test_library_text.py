"""Title and description of a library: README defaults for the default version, user edits win."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    ApplyReadmeCommand,
    GetLibraryQuery,
    LibraryPatch,
    UpdateLibraryCommand,
)
from exactdocs.catalog.errors import LibraryNotFoundError
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.catalog.module import CatalogModule

LIBRARY = "/acme/payments"


def version(ref: str, kind: RefKind, sha: str) -> Version:
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha.ljust(40, "0"),
        imported_at=datetime(2026, 11, 4, 12, tzinfo=UTC),
    )


REPOSITORIES: dict[int, InMemoryLibraryRepository] = {}  # the module hides its repository


def build(*versions: Version, **fields: object) -> CatalogModule:
    fields = {"title": "payments"} | fields
    repository = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
                versions=frozenset(versions),
                **fields,  # ty: ignore[invalid-argument-type]
            )
        ]
    )
    catalog = CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(libraries=repository)),
        imported_tags=InMemoryImportedTags(repository=written),
        copier=InMemoryManifestCopier(repository=written),
        stored_articles=InMemoryStoredArticles(repository=written),
    )
    REPOSITORIES[id(catalog)] = repository
    return catalog


async def texts(catalog: CatalogModule) -> tuple[str, str]:
    found = await catalog.get_library(GetLibraryQuery(id=LIBRARY))
    return found.title, found.description


MAIN = version("main", RefKind.BRANCH, "a1")
V1 = version("v1.0.0", RefKind.TAG, "b1")
V2 = version("v2.0.0", RefKind.TAG, "b2")


async def test_the_readme_of_the_default_version_sets_both() -> None:
    catalog = build(MAIN)

    await catalog.apply_readme(
        ApplyReadmeCommand(
            library=LIBRARY, ref="main", title="Acme Payments", description="An SDK."
        )
    )

    assert await texts(catalog) == ("Acme Payments", "An SDK.")


async def test_the_readme_of_another_version_is_ignored() -> None:
    catalog = build(V1, V2)

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="v1.0.0", title="Old", description="Old text.")
    )

    assert await texts(catalog) == ("payments", "")


async def test_a_newer_default_version_replaces_the_derived_text() -> None:
    catalog = build(V1)
    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="v1.0.0", title="One", description="First.")
    )
    (stored,) = repository_of(catalog).libraries.values()
    await repository_of(catalog).save(replace(stored, versions=stored.versions | {V2}))

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="v2.0.0", title="Two", description="Second.")
    )

    assert await texts(catalog) == ("Two", "Second.")


async def test_no_heading_or_paragraph_falls_back_to_the_repository_name_and_no_description() -> (
    None
):
    catalog = build(MAIN, title="Stale", description="Stale text.")

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="main", title=None, description=None)
    )

    assert await texts(catalog) == ("payments", "")


async def test_an_edited_field_is_never_overwritten_the_other_one_still_follows_the_readme() -> (
    None
):
    catalog = build(MAIN)
    await catalog.update_library(UpdateLibraryCommand(id=LIBRARY, title="Payments SDK"))

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="main", title="From README", description="Text.")
    )
    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="main", title=None, description="Newer text.")
    )

    assert await texts(catalog) == ("Payments SDK", "Newer text.")


async def test_editing_the_description_keeps_it_even_when_empty() -> None:
    catalog = build(MAIN)
    await catalog.update_library(UpdateLibraryCommand(id=LIBRARY, description=""))

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="main", title="T", description="Text.")
    )

    assert await texts(catalog) == ("T", "")


async def test_update_returns_the_library_and_leaves_unset_fields_alone() -> None:
    catalog = build(MAIN, description="Kept.")

    updated = await catalog.update_library(UpdateLibraryCommand(id=LIBRARY, title="  New  "))

    assert (updated.title, updated.description) == ("New", "Kept.")


async def test_unknown_libraries_are_not_found() -> None:
    catalog = build(MAIN)

    with pytest.raises(LibraryNotFoundError):
        await catalog.update_library(UpdateLibraryCommand(id="/x/y", title="T"))
    with pytest.raises(LibraryNotFoundError):
        await catalog.apply_readme(
            ApplyReadmeCommand(library="/x/y", ref="main", title="T", description=None)
        )


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_a_title_must_have_text_and_stay_short(title: str) -> None:
    with pytest.raises(ValidationError):
        UpdateLibraryCommand(id=LIBRARY, title=title)


def repository_of(catalog: CatalogModule) -> InMemoryLibraryRepository:
    return REPOSITORIES[id(catalog)]


@dataclass(frozen=True, slots=True, kw_only=True)
class EditsBetweenReadAndWrite(InMemoryLibraryRepository):
    """A user edit lands after the import read the library and before it writes."""

    edits: list[str] = field(default_factory=lambda: ["once"])

    async def get(self, library_id: LibraryId) -> Library | None:
        found = await super().get(library_id)
        if self.edits:
            self.edits.pop()
            await self.set_text(library_id, title="Payments SDK", description=None)
        return found


async def test_an_edit_between_the_import_read_and_write_survives() -> None:
    repository = EditsBetweenReadAndWrite.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                versions=frozenset({MAIN}),
                default_branch=VersionRef("main"),
            )
        ]
    )
    catalog = CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(libraries=repository)),
        imported_tags=InMemoryImportedTags(repository=written),
        copier=InMemoryManifestCopier(repository=written),
        stored_articles=InMemoryStoredArticles(repository=written),
    )

    await catalog.apply_readme(
        ApplyReadmeCommand(library=LIBRARY, ref="main", title="README", description="Text.")
    )

    assert await texts(catalog) == ("Payments SDK", "Text.")
    assert (await repository.get(LibraryId(LIBRARY))).title_edited  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"title": None},
        {"title": None, "description": None},
        {"title": "   "},
        {"title": "two\nlines"},
        {"title": "sep\u2028arated"},
        {"title": "\u200b\u202e"},
        {"title": "x" * 201},
        {"description": "x" * 1001},
    ],
)
def test_a_bad_patch_is_refused(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LibraryPatch(**patch)  # ty: ignore[invalid-argument-type]


def test_invisible_characters_and_extra_spaces_are_removed() -> None:
    patch = LibraryPatch(title=" Pay\u200bments \x1b[31m  SDK\u202e ", description="a\u200bb\x07\n")

    assert (patch.title, patch.description) == ("Payments [31m SDK", "ab")


async def test_the_default_versions_rules_replace_the_librarys_and_others_are_ignored() -> None:
    catalog = build(V1, V2)

    for ref, rules in [("v2.0.0", ["Use v2 client"]), ("v1.0.0", ["Use v1 client"])]:
        await catalog.apply_readme(ApplyReadmeCommand(library=LIBRARY, ref=ref, rules=rules))
    kept = (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).rules
    await catalog.apply_readme(ApplyReadmeCommand(library=LIBRARY, ref="v2.0.0"))
    dropped = (await catalog.get_library(GetLibraryQuery(id=LIBRARY))).rules

    assert (kept, dropped) == (["Use v2 client"], [])


@pytest.mark.parametrize("rules", [[""], ["r" * 501], ["r"] * 21])
def test_rules_are_bounded(rules: list[str]) -> None:
    with pytest.raises(ValidationError):
        ApplyReadmeCommand(library=LIBRARY, ref="main", rules=rules)
