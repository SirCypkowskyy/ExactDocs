"""Adapter contract: every ``LibraryGrantRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryLibraryGrantRepository
from exactdocs.identity.adapters.driven.sqlite import SqliteLibraryGrantRepository
from exactdocs.identity.models import AccountId, LibraryGrant, LibraryRole, SubjectKind
from exactdocs.identity.ports import LibraryGrantRepository

LIBRARY = "/acme/payments"
OTHER = "/acme/ledger"


def grant(
    role: LibraryRole,
    subject: str = "bob",
    kind: SubjectKind = SubjectKind.USER,
    library: str = LIBRARY,
) -> LibraryGrant:
    return LibraryGrant(library=library, kind=kind, subject=subject, role=role)


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def grants(request: pytest.FixtureRequest) -> AsyncIterator[LibraryGrantRepository]:
    if request.param == "memory":
        yield InMemoryLibraryGrantRepository()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteLibraryGrantRepository(engine=container.engine)


async def test_a_grant_is_stored_and_replaced(grants: LibraryGrantRepository) -> None:
    await grants.put(grant(LibraryRole.VIEWER))
    await grants.put(grant(LibraryRole.CONTRIBUTOR))

    assert await grants.get(LIBRARY, SubjectKind.USER, "bob") == grant(LibraryRole.CONTRIBUTOR)
    assert await grants.for_library(LIBRARY) == [grant(LibraryRole.CONTRIBUTOR)]


async def test_a_user_and_a_group_of_the_same_name_are_two_subjects(
    grants: LibraryGrantRepository,
) -> None:
    await grants.put(grant(LibraryRole.VIEWER, "payments", SubjectKind.GROUP))
    await grants.put(grant(LibraryRole.ADMIN, "payments", SubjectKind.USER))

    assert await grants.for_library(LIBRARY) == [
        grant(LibraryRole.ADMIN, "payments", SubjectKind.USER),
        grant(LibraryRole.VIEWER, "payments", SubjectKind.GROUP),
    ]


async def test_matching_finds_the_grants_to_the_account_and_to_its_groups_only(
    grants: LibraryGrantRepository,
) -> None:
    await grants.put(grant(LibraryRole.VIEWER, "bob"))
    await grants.put(grant(LibraryRole.CONTRIBUTOR, "payments", SubjectKind.GROUP))
    await grants.put(grant(LibraryRole.ADMIN, "other-group", SubjectKind.GROUP))
    await grants.put(grant(LibraryRole.ADMIN, "carol"))
    await grants.put(grant(LibraryRole.ADMIN, "bob", library=OTHER))

    found = await grants.matching(
        [LIBRARY], account_id=AccountId("bob"), groups=frozenset({"payments"})
    )

    assert sorted(g.role.value for g in found) == ["contributor", "viewer"]
    assert await grants.matching([], account_id=AccountId("bob"), groups=frozenset()) == []
    assert [
        g.role
        for g in await grants.matching(
            [LIBRARY, OTHER], account_id=AccountId("bob"), groups=frozenset()
        )
    ].count(LibraryRole.ADMIN) == 1


async def test_remove_says_whether_there_was_a_grant(grants: LibraryGrantRepository) -> None:
    await grants.put(grant(LibraryRole.VIEWER))

    assert await grants.remove(LIBRARY, SubjectKind.USER, "bob") is True
    assert await grants.remove(LIBRARY, SubjectKind.USER, "bob") is False
    assert await grants.for_library(LIBRARY) == []


async def test_claiming_replaces_every_grant_on_the_id(grants: LibraryGrantRepository) -> None:
    await grants.put(grant(LibraryRole.ADMIN, "stale"))
    await grants.put(grant(LibraryRole.VIEWER, "payments", SubjectKind.GROUP))
    await grants.put(grant(LibraryRole.VIEWER, "stale", library=OTHER))

    await grants.claim(LIBRARY, AccountId("ada"))

    assert await grants.for_library(LIBRARY) == [grant(LibraryRole.CREATOR, "ada")]
    assert await grants.for_library(OTHER) == [grant(LibraryRole.VIEWER, "stale", library=OTHER)]


async def test_clearing_drops_one_librarys_grants(grants: LibraryGrantRepository) -> None:
    await grants.put(grant(LibraryRole.ADMIN))
    await grants.put(grant(LibraryRole.VIEWER, library=OTHER))

    await grants.clear(LIBRARY)

    assert await grants.for_library(LIBRARY) == []
    assert len(await grants.for_library(OTHER)) == 1


async def test_transferring_makes_one_creator_and_the_creators_before_admins(
    grants: LibraryGrantRepository,
) -> None:
    await grants.put(grant(LibraryRole.CREATOR, "ada"))
    await grants.put(grant(LibraryRole.VIEWER, "bob"))
    await grants.put(grant(LibraryRole.VIEWER, "payments", SubjectKind.GROUP))
    await grants.put(grant(LibraryRole.CREATOR, "ada", library=OTHER))

    previous = await grants.transfer(LIBRARY, AccountId("bob"))

    assert previous == [AccountId("ada")]
    assert await grants.for_library(LIBRARY) == [
        grant(LibraryRole.ADMIN, "ada"),
        grant(LibraryRole.CREATOR, "bob"),
        grant(LibraryRole.VIEWER, "payments", SubjectKind.GROUP),
    ]
    assert await grants.for_library(OTHER) == [grant(LibraryRole.CREATOR, "ada", library=OTHER)]


async def test_transferring_a_library_without_a_creator_has_no_creator_before(
    grants: LibraryGrantRepository,
) -> None:
    assert await grants.transfer(LIBRARY, AccountId("bob")) == []
    assert await grants.for_library(LIBRARY) == [grant(LibraryRole.CREATOR, "bob")]
