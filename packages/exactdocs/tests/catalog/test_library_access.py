"""Library roles (ACL-02) in the catalog: every use case asks the ``AccessPolicy`` first.

The matrix runs each action as a caller holding each role (or none) on every library, through a
policy that answers from that one role: below what the action needs it is refused before anything
is read or changed; at or above, the action is not refused for access (it may still fail for
other reasons, such as a missing article).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest

from exactdocs.catalog.adapters.driven.memory import (
    InMemoryImportedTags,
    InMemoryLibraryRepository,
    InMemoryManifestCopier,
    InMemoryManifestRepository,
    InMemoryStoredArticles,
)
from exactdocs.catalog.dtos import (
    CreateLibraryCommand,
    DiscardLibraryCommand,
    GetArticleQuery,
    GetAssetQuery,
    GetLibraryQuery,
    ListArticlesQuery,
    ListLibrariesQuery,
    ListRenamesQuery,
    ListTagsQuery,
    PinDefaultVersionCommand,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    ResolveRenamedPathQuery,
    ResolveVersionQuery,
    SetLibrarySettingsCommand,
    UpdateLibraryCommand,
)
from exactdocs.catalog.errors import LibraryAccessDeniedError
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.catalog.module import CatalogModule
from library_access import ROLES, FakeAccess

LIBRARY = "/acme/payments"
ROLES_AND_NONE = [None, *ROLES]

type Action = Callable[[CatalogModule], Awaitable[object]]
ACTIONS: dict[str, tuple[str, Action]] = {
    "get_library": ("viewer", lambda c: c.get_library(GetLibraryQuery(id=LIBRARY))),
    "resolve_version": (
        "viewer",
        lambda c: c.resolve_version(ResolveVersionQuery(id=f"{LIBRARY}/v1.3.0")),
    ),
    "list_articles": ("viewer", lambda c: c.list_articles(ListArticlesQuery(library=LIBRARY))),
    "list_tags": ("viewer", lambda c: c.list_tags(ListTagsQuery(library=LIBRARY))),
    "get_article": (
        "viewer",
        lambda c: c.get_article(GetArticleQuery(library=LIBRARY, path="a.md")),
    ),
    "get_asset": ("viewer", lambda c: c.get_asset(GetAssetQuery(library=LIBRARY, path="a.png"))),
    "resolve_renamed_path": (
        "viewer",
        lambda c: c.resolve_renamed_path(ResolveRenamedPathQuery(library=LIBRARY, path="a.md")),
    ),
    "list_renames": ("viewer", lambda c: c.list_renames(ListRenamesQuery(library=LIBRARY))),
    "update_library": (
        "admin",
        lambda c: c.update_library(UpdateLibraryCommand(id=LIBRARY, title="Payments SDK")),
    ),
    "set_library_settings": (
        "admin",
        lambda c: c.set_library_settings(SetLibrarySettingsCommand(id=LIBRARY)),
    ),
    "pin_default_version": (
        "admin",
        lambda c: c.pin_default_version(PinDefaultVersionCommand(library=LIBRARY, ref="v1.3.0")),
    ),
    "remove_version": (
        "admin",
        lambda c: c.remove_version(RemoveVersionCommand(library=LIBRARY, ref="v1.3.0")),
    ),
    "remove_library": (
        "creator",
        lambda c: c.remove_library(RemoveLibraryCommand(library=LIBRARY)),
    ),
}


def module(access: FakeAccess) -> CatalogModule:
    repository = InMemoryLibraryRepository.of(
        [
            Library(
                id=LibraryId(LIBRARY),
                title="Payments",
                source_url="https://github.com/acme/payments",
                host=HostKind.GITHUB,
                default_branch=VersionRef("main"),
                versions=frozenset(
                    {
                        Version(
                            ref=VersionRef("v1.3.0"),
                            kind=RefKind.TAG,
                            commit_sha="a" * 40,
                            imported_at=datetime(2026, 11, 4, tzinfo=UTC),
                        )
                    }
                ),
            )
        ]
    )
    return CatalogModule.build(
        repository=repository,
        manifests=(written := InMemoryManifestRepository(libraries=repository)),
        imported_tags=InMemoryImportedTags(repository=written),
        copier=InMemoryManifestCopier(repository=written),
        stored_articles=InMemoryStoredArticles(repository=written),
        access=access,
    )


@pytest.mark.parametrize("role", ROLES_AND_NONE, ids=lambda r: r or "no role")
@pytest.mark.parametrize("name", ACTIONS)
async def test_an_action_is_refused_below_the_role_it_needs(name: str, role: str | None) -> None:
    needed, action = ACTIONS[name]
    access = FakeAccess(role=role)

    outcome: BaseException | None = None
    try:
        await action(module(access))
    except Exception as error:  # ruff: ignore[blind-except] - only whether it was refused for access matters
        outcome = error

    allowed = role is not None and ROLES.index(role) >= ROLES.index(needed)
    assert isinstance(outcome, LibraryAccessDeniedError) is not allowed, (name, role, outcome)
    assert access.asked[0] == (LIBRARY, needed)


@pytest.mark.parametrize("role", ROLES_AND_NONE, ids=lambda r: r or "no role")
async def test_the_listing_holds_only_the_libraries_the_caller_may_read(role: str | None) -> None:
    listed = await module(FakeAccess(role=role)).list_libraries(ListLibrariesQuery())

    assert [lib.id for lib in listed.libraries] == ([] if role is None else [LIBRARY])


async def test_a_new_library_is_claimed_by_its_caller_and_a_discarded_one_forgotten() -> None:
    access = FakeAccess()
    catalog = module(access)
    command = CreateLibraryCommand(
        id="/acme/ledger",
        title="Ledger",
        source_url="https://github.com/acme/ledger",
        host="github",
    )

    await catalog.create_library(command)
    await catalog.discard_library(DiscardLibraryCommand(id="/acme/ledger"))

    assert access.claimed == ["/acme/ledger"]
    assert access.forgotten == ["/acme/ledger"]


async def test_removing_a_library_drops_the_grants_on_its_id() -> None:
    access = FakeAccess(role="creator")

    await module(access).remove_library(RemoveLibraryCommand(library=LIBRARY))

    assert access.forgotten == [LIBRARY]
