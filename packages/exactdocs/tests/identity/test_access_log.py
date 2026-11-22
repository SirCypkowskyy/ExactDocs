"""The access log (ACL-05): grants, revocations, creations and deletions, with actor and time."""

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
)
from exactdocs.identity.errors import (
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
from exactdocs_kernel import InvalidCursorError

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


async def test_a_transfer_recorded_by_the_sharing_use_cases_reads_back(world: World) -> None:
    """Ready for #109: an ``ownership_transferred`` event reads back like any other."""
    await world.log.record(
        AccessEvent(
            id="ffffffff-ffff-7fff-bfff-ffffffffffff",
            library=LIBRARY,
            at=START,
            actor=AccountId(world.ids["alice"]),
            change=AccessChange.OWNERSHIP_TRANSFERRED,
            kind=SubjectKind.USER,
            subject=world.ids["carol"],
            role=LibraryRole.CREATOR,
            previous_role=LibraryRole.ADMIN,
        )
    )

    assert rows(await world.read("alice"))[0] == (
        "alice",
        "ownership_transferred",
        "carol",
        "creator",
        "admin",
    )
