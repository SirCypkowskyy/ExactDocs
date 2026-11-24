"""The access log (ACL-05): grants, revocations, transfers, creations and deletions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from pydantic import SecretStr

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccessLog,
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemoryFailedSignInLog,
    InMemoryLibraryGrantRepository,
    InMemorySessionRepository,
    InMemorySignInAttemptRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.dtos import (
    AccessLogPage,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateUserCommand,
    DropLibraryGrantsCommand,
    GrantLibraryRoleCommand,
    ListAccessLogQuery,
    ListLibraryAccessLogQuery,
    RevokeLibraryRoleCommand,
    TransferLibraryCommand,
)
from exactdocs.identity.errors import (
    InvalidGrantError,
    LibraryRoleRequiredError,
    NotAnOperatorError,
    UnknownGrantError,
)
from exactdocs.identity.models import (
    AccessChange,
    AccessEvent,
    AccountId,
    LibraryRole,
    SubjectKind,
)
from exactdocs.identity.module import IdentityModule
from exactdocs_kernel import InvalidCursorError, InvalidSortError

LIBRARY = "/acme/payments"
OTHER = "/acme/ledger"
PHRASE = "a long enough passphrase"
START = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)

type Row = tuple[str | None, str, str | None, str | None, str | None]


@dataclass(slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


class _NoBox:
    def seal(self, plaintext: str) -> str:
        raise AssertionError(plaintext)

    def open(self, sealed: str) -> str:
        raise AssertionError(sealed)


@dataclass(slots=True)
class TickingClock:
    """Each reading is a minute after the one before."""

    at: datetime = START

    def now(self) -> datetime:
        self.at += timedelta(minutes=1)
        return self.at


@dataclass(slots=True)
class World:
    identity: IdentityModule
    log: InMemoryAccessLog
    ids: dict[str, str] = field(default_factory=dict)

    async def grant(
        self,
        caller: str,
        subject: str,
        role: Literal["viewer", "contributor", "admin"],
        kind: Literal["user", "group"] = "user",
        library: str = LIBRARY,
    ) -> None:
        await self.identity.grant_library_role(
            GrantLibraryRoleCommand(
                caller_id=self.ids[caller], library=library, kind=kind, subject=subject, role=role
            )
        )

    async def revoke(
        self, caller: str, subject: str, kind: Literal["user", "group"] = "user"
    ) -> None:
        await self.identity.revoke_library_role(
            RevokeLibraryRoleCommand(
                caller_id=self.ids[caller], library=LIBRARY, kind=kind, subject=subject
            )
        )

    async def transfer(self, caller: str, to: str, library: str = LIBRARY) -> None:
        await self.identity.transfer_library(
            TransferLibraryCommand(caller_id=self.ids[caller], library=library, username=to)
        )

    async def read(self, caller: str, library: str = LIBRARY, **options: object) -> AccessLogPage:
        return await self.identity.list_library_access_log(
            ListLibraryAccessLogQuery.model_validate(
                {"caller_id": self.ids[caller], "library": library, **options}
            )
        )

    async def read_all(self, caller: str, **options: object) -> AccessLogPage:
        return await self.identity.list_access_log(
            ListAccessLogQuery.model_validate({"caller_id": self.ids[caller], **options})
        )


def rows(page: AccessLogPage) -> list[Row]:
    return [(e.actor, e.change, e.subject, e.role, e.previous_role) for e in page.events]


@pytest.fixture
async def world() -> World:
    accounts = InMemoryAccountRepository()
    log = InMemoryAccessLog()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=InMemoryExternalIdentityRepository(accounts=accounts),
        library_grants=InMemoryLibraryGrantRepository(),
        access_log=log,
        attempts=InMemorySignInAttemptRepository(),
        box=_NoBox(),
        clock=TickingClock(),
    )
    world = World(identity, log)
    world.ids["ada"] = (
        await identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(PHRASE))
        )
    ).id
    for name in ("alice", "bob", "carol"):
        world.ids[name] = (
            await identity.create_user(CreateUserCommand(username=name, password=SecretStr(PHRASE)))
        ).id
    await identity.claim_library(
        ClaimLibraryCommand(account_id=world.ids["alice"], library=LIBRARY)
    )
    return world


async def test_a_grant_is_recorded_with_its_actor_change_and_time(world: World) -> None:
    await world.grant("alice", "bob", "viewer")

    newest = (await world.read("alice")).events[0]

    assert (newest.actor, newest.change, newest.kind, newest.subject, newest.role) == (
        "alice",
        "granted",
        "user",
        "bob",
        "viewer",
    )
    assert newest.library == LIBRARY
    assert newest.at > START


async def test_the_log_shows_creation_changes_and_revocations_newest_first(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.grant("alice", "bob", "contributor")
    await world.grant("alice", "corp:payments", "viewer", kind="group")
    await world.revoke("alice", "bob")

    page = await world.read("alice")

    assert rows(page) == [
        ("alice", "revoked", "bob", "contributor", None),
        ("alice", "granted", "corp:payments", "viewer", None),
        ("alice", "granted", "bob", "contributor", "viewer"),
        ("alice", "granted", "bob", "viewer", None),
        ("alice", "library_created", "alice", "creator", None),
    ]
    assert [e.at for e in page.events] == sorted((e.at for e in page.events), reverse=True)
    assert page.total == 5
    assert page.next_cursor is None


async def test_giving_the_same_role_again_or_a_refused_change_logs_nothing(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.grant("alice", "bob", "viewer")
    await world.grant("alice", "carol", "viewer")
    with pytest.raises(LibraryRoleRequiredError):
        await world.grant("carol", "bob", "contributor")
    with pytest.raises(UnknownGrantError):
        await world.revoke("alice", "nobody-has-this", kind="group")

    assert (await world.read("alice")).total == 3


async def test_only_admins_of_the_library_and_operators_read_its_log(world: World) -> None:
    await world.grant("alice", "bob", "contributor")
    await world.grant("alice", "carol", "admin")

    with pytest.raises(LibraryRoleRequiredError):
        await world.read("bob")
    assert (await world.read("carol")).total == 3
    assert (await world.read("ada")).total == 3
    with pytest.raises(LibraryRoleRequiredError):
        await world.read("carol", OTHER)


async def test_a_deletion_is_recorded_with_who_removed_the_library(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.identity.drop_library_grants(
        DropLibraryGrantsCommand(library=LIBRARY.upper(), actor_id=world.ids["alice"])
    )
    await world.identity.drop_library_grants(DropLibraryGrantsCommand(library=OTHER))

    page = await world.read_all("ada", library=LIBRARY)

    assert rows(page)[0] == ("alice", "library_deleted", None, None, None)
    assert page.events[0].kind is None
    assert page.total == 3
    every = await world.read_all("ada", change=["library_deleted"])
    assert [(e.library, e.actor) for e in every.events] == [(OTHER, None), (LIBRARY, "alice")]


async def test_a_library_created_again_shows_its_admins_only_its_own_history(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.identity.drop_library_grants(
        DropLibraryGrantsCommand(library=LIBRARY, actor_id=world.ids["alice"])
    )
    await world.identity.claim_library(
        ClaimLibraryCommand(account_id=world.ids["carol"], library=LIBRARY)
    )
    await world.grant("carol", "alice", "viewer")

    assert rows(await world.read("carol")) == [
        ("carol", "granted", "alice", "viewer", None),
        ("carol", "library_created", "carol", "creator", None),
    ]
    assert (await world.read("ada")).total == 5  # created, granted, deleted, created, granted


async def test_only_an_operator_reads_the_log_of_every_library(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.grant("ada", "carol", "viewer", library=OTHER)

    with pytest.raises(NotAnOperatorError):
        await world.read_all("alice")
    every = await world.read_all("ada")
    assert [e.library for e in every.events] == [OTHER, LIBRARY, LIBRARY]


async def test_the_log_pages_with_a_cursor_and_filters_by_change(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.grant("alice", "bob", "contributor")
    await world.grant("alice", "bob", "viewer")
    await world.revoke("alice", "bob")

    first = await world.read("alice", limit=2)
    second = await world.read("alice", limit=2, cursor=first.next_cursor)
    third = await world.read("alice", limit=2, cursor=second.next_cursor)

    assert [len(p.events) for p in (first, second, third)] == [2, 2, 1]
    assert {p.total for p in (first, second, third)} == {5}
    assert third.next_cursor is None
    seen = [e.id for p in (first, second, third) for e in p.events]
    assert len(set(seen)) == 5
    granted = await world.read("alice", change=["granted"])
    assert [e.change for e in granted.events] == ["granted"] * 3
    with pytest.raises(InvalidCursorError):
        await world.read("alice", cursor="not base64!")


def event(
    change: AccessChange,
    kind: SubjectKind | None = None,
    subject: str | None = None,
    role: LibraryRole | None = None,
    previous_role: LibraryRole | None = None,
) -> AccessEvent:
    return AccessEvent(
        id="x",
        library=LIBRARY,
        at=START,
        actor=AccountId("a"),
        change=change,
        kind=kind,
        subject=subject,
        role=role,
        previous_role=previous_role,
    )


def test_an_event_names_a_subject_and_role_exactly_when_it_is_about_someone() -> None:
    with pytest.raises(ValueError, match="needs a subject"):
        event(AccessChange.GRANTED)
    with pytest.raises(ValueError, match="names no subject"):
        event(
            AccessChange.LIBRARY_DELETED,
            kind=SubjectKind.USER,
            subject="bob",
            role=LibraryRole.VIEWER,
        )
    transfer = event(
        AccessChange.OWNERSHIP_TRANSFERRED,
        kind=SubjectKind.USER,
        subject="carol",
        role=LibraryRole.CREATOR,
        previous_role=LibraryRole.ADMIN,
    )
    assert transfer.previous_role is LibraryRole.ADMIN


async def test_a_transfer_records_the_new_creator_and_the_creator_before_as_admin(
    world: World,
) -> None:
    await world.grant("alice", "carol", "admin")

    await world.transfer("alice", "carol")

    assert rows(await world.read("carol")) == [
        ("alice", "ownership_transferred", "carol", "creator", "admin"),
        ("alice", "granted", "alice", "admin", "creator"),
        ("alice", "granted", "carol", "admin", None),
        ("alice", "library_created", "alice", "creator", None),
    ]
    transfers = await world.read("carol", change=["ownership_transferred"])
    assert [(e.kind, e.subject) for e in transfers.events] == [("user", "carol")]


async def test_an_operator_handing_over_a_library_with_no_creator_records_only_the_transfer(
    world: World,
) -> None:
    await world.transfer("ada", "bob", library=OTHER)

    assert rows(await world.read("bob", OTHER)) == [
        ("ada", "ownership_transferred", "bob", "creator", None),
    ]


async def test_a_refused_transfer_records_nothing(world: World) -> None:
    await world.grant("alice", "bob", "admin")
    with pytest.raises(LibraryRoleRequiredError):
        await world.transfer("bob", "carol")
    with pytest.raises(InvalidGrantError):
        await world.transfer("alice", "alice")

    assert (await world.read("alice")).total == 2  # created, granted


# ------------------------------------------------- sort and filters (#514)


async def history(world: World) -> None:
    """Created (alice), then, a minute apart each: bob viewer, carol viewer by ada, group bob
    viewer, bob contributor, bob revoked."""
    await world.grant("alice", "bob", "viewer")
    await world.grant("ada", "carol", "viewer")
    await world.grant("alice", "bob", "viewer", kind="group")
    await world.grant("alice", "bob", "contributor")
    await world.revoke("alice", "bob")


def when(world: World, n: int) -> datetime:
    """The time of the n-th event of the world, from 0 (the creation)."""
    return world.log.events[n].at


async def test_the_log_filters_by_actor_subject_and_date_and_sorts_oldest_first(
    world: World,
) -> None:
    await history(world)

    page = await world.read_all(
        "ada",
        actor="Alice",
        subject="bob",
        at_after=when(world, 2).isoformat(),
        at_before=(when(world, 5) + timedelta(seconds=1)).isoformat(),
        sort="at",
    )

    assert [(e.kind, e.subject, e.change, e.role) for e in page.events] == [
        ("group", "bob", "granted", "viewer"),
        ("user", "bob", "granted", "contributor"),
        ("user", "bob", "revoked", "contributor"),
    ]
    assert page.total == 3
    assert page.next_cursor is None
    assert [e.at for e in page.events] == [when(world, 3), when(world, 4), when(world, 5)]


async def test_each_filter_narrows_the_log_on_its_own(world: World) -> None:
    await history(world)

    by_ada = await world.read("alice", actor="ada")
    about_carol = await world.read("alice", subject="CAROL")
    since = await world.read("alice", at_after=when(world, 4).isoformat())
    before = await world.read("alice", at_before=when(world, 1).isoformat())

    assert rows(by_ada) == [("ada", "granted", "carol", "viewer", None)]
    assert rows(about_carol) == [("ada", "granted", "carol", "viewer", None)]
    assert [e.at for e in since.events] == [when(world, 5), when(world, 4)]
    assert rows(before) == [("alice", "library_created", "alice", "creator", None)]
    assert (by_ada.total, about_carol.total, since.total, before.total) == (1, 1, 2, 1)


async def test_a_time_without_an_offset_is_utc_and_the_bounds_are_after_inclusive(
    world: World,
) -> None:
    await history(world)

    naive = when(world, 4).replace(tzinfo=None).isoformat()
    page = await world.read("alice", at_after=naive, at_before=naive)

    assert page.total == 0
    assert (await world.read("alice", at_after=naive)).total == 2


async def test_nobody_by_that_name_matches_nothing_and_deletions_are_about_nobody(
    world: World,
) -> None:
    await history(world)
    await world.identity.drop_library_grants(DropLibraryGrantsCommand(library=LIBRARY))

    assert (await world.read_all("ada", actor="nobody")).total == 0
    assert (await world.read_all("ada", subject="nobody")).total == 0
    deletions = await world.read_all("ada", change=["library_deleted"], subject="bob")
    assert deletions.total == 0


async def test_an_account_that_is_gone_is_found_by_the_id_the_log_shows(world: World) -> None:
    gone = AccessEvent(
        id="00000000-0000-7000-8000-000000000001",
        library=LIBRARY,
        at=START,
        actor=AccountId("acct-gone"),
        change=AccessChange.GRANTED,
        kind=SubjectKind.USER,
        subject="acct-also-gone",
        role=LibraryRole.VIEWER,
    )
    await world.log.record(gone)

    by_actor = await world.read_all("ada", actor="acct-gone")
    about = await world.read_all("ada", subject="acct-also-gone")

    assert rows(by_actor) == [("acct-gone", "granted", "acct-also-gone", "viewer", None)]
    assert [e.id for e in about.events] == [gone.id]


async def test_the_log_sorts_by_library_and_change_with_ties_by_record_order(
    world: World,
) -> None:
    await history(world)
    await world.grant("ada", "carol", "viewer", library=OTHER)

    by_library = await world.read_all("ada", sort="library")
    by_change = await world.read_all("ada", sort="change", library=LIBRARY)

    assert [e.library for e in by_library.events] == [OTHER] + [LIBRARY] * 6
    mine = [e.at for e in by_library.events[1:]]
    assert mine == sorted(mine)
    assert [e.change for e in by_change.events] == [
        "granted",
        "granted",
        "granted",
        "granted",
        "library_created",
        "revoked",
    ]
    granted = [e.at for e in by_change.events[:4]]
    assert granted == sorted(granted)


async def test_an_unknown_sort_field_is_refused(world: World) -> None:
    with pytest.raises(InvalidSortError):
        await world.read("alice", sort="actor")


async def test_a_cursor_walk_keeps_the_sort_and_filters_and_refuses_another_sort(
    world: World,
) -> None:
    await history(world)

    seen, cursor, totals = [], None, set()
    while True:
        page = await world.read("alice", sort="at", subject="bob", limit=2, cursor=cursor)
        seen += [e.at for e in page.events]
        totals.add(page.total)
        if (cursor := page.next_cursor) is None:
            break

    assert seen == [when(world, 1), when(world, 3), when(world, 4), when(world, 5)]
    assert totals == {4}
    first = await world.read("alice", sort="at", limit=1)
    assert first.next_cursor is not None
    with pytest.raises(InvalidCursorError):
        await world.read("alice", sort="-at", cursor=first.next_cursor)
    with pytest.raises(InvalidCursorError):
        await world.read("alice", sort="library", cursor=first.next_cursor)


async def test_an_offset_pages_the_filtered_and_sorted_log(world: World) -> None:
    await history(world)

    page = await world.read("alice", sort="at", actor="alice", offset=2, limit=2)
    rest = await world.read("alice", sort="at", actor="alice", cursor=page.next_cursor)

    assert [e.at for e in page.events] == [when(world, 3), when(world, 4)]
    assert [e.at for e in rest.events] == [when(world, 5)]
    assert page.total == rest.total == 5


async def test_a_library_created_again_filters_only_its_own_history(world: World) -> None:
    await world.grant("alice", "bob", "viewer")
    await world.identity.drop_library_grants(
        DropLibraryGrantsCommand(library=LIBRARY, actor_id=world.ids["alice"])
    )
    await world.identity.claim_library(
        ClaimLibraryCommand(account_id=world.ids["carol"], library=LIBRARY)
    )
    await world.grant("carol", "bob", "viewer")

    carol_sees = await world.read("carol", subject="bob", sort="at")
    ada_sees = await world.read("ada", subject="bob", sort="at")

    assert rows(carol_sees) == [("carol", "granted", "bob", "viewer", None)]
    assert [e.actor for e in ada_sees.events] == ["alice", "carol"]
