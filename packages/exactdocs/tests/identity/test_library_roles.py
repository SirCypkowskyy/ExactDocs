"""Library roles (ACL-02): the highest role granted to an account or its groups, and sharing."""

from dataclasses import dataclass
from itertools import pairwise
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
    AccountSummary,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateUserCommand,
    DropLibraryGrantsCommand,
    ExternalTokenIdentity,
    GrantLibraryRoleCommand,
    LibraryRolesQuery,
    ListLibraryGrantsQuery,
    RevokeLibraryRoleCommand,
    SetUserDisabledCommand,
)
from exactdocs.identity.errors import (
    InvalidGrantError,
    LibraryRoleRequiredError,
    UnknownAccountError,
    UnknownGrantError,
)
from exactdocs.identity.models import (
    AccountId,
    LibraryGrant,
    LibraryRole,
    SubjectKind,
    effective_role,
)
from exactdocs.identity.module import IdentityModule
from exactdocs_kernel import SystemClock

LIBRARY = "/acme/payments"
PHRASE = "a long enough passphrase"


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
class World:
    identity: IdentityModule
    externals: InMemoryExternalIdentityRepository
    ids: dict[str, str]

    async def role(self, who: str, library: str = LIBRARY) -> str | None:
        found = await self.identity.resolve_library_roles(
            LibraryRolesQuery(account_id=self.ids[who], libraries=[library])
        )
        return found.roles.get(library.casefold())

    def in_groups(self, who: str, *groups: str) -> None:
        self.externals.groups[AccountId(self.ids[who])] = frozenset(groups)

    async def grant(
        self,
        caller: str,
        subject: str,
        role: Literal["viewer", "contributor", "admin"],
        kind: Literal["user", "group"] = "user",
    ) -> object:
        return await self.identity.grant_library_role(
            GrantLibraryRoleCommand(
                caller_id=self.ids[caller], library=LIBRARY, kind=kind, subject=subject, role=role
            )
        )


@pytest.fixture
async def world() -> World:
    accounts = InMemoryAccountRepository()
    externals = InMemoryExternalIdentityRepository(accounts=accounts)
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=externals,
        library_grants=InMemoryLibraryGrantRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=_NoBox(),
        clock=SystemClock(),
    )
    ids = {
        "ada": (
            await identity.create_first_admin(
                CreateFirstAdminCommand(username="ada", password=SecretStr(PHRASE))
            )
        ).id
    }
    for name in ("bob", "carol", "dave"):
        ids[name] = (
            await identity.create_user(CreateUserCommand(username=name, password=SecretStr(PHRASE)))
        ).id
    return World(identity, externals, ids)


def test_the_roles_are_ordered_viewer_contributor_admin_creator() -> None:
    order = [LibraryRole.VIEWER, LibraryRole.CONTRIBUTOR, LibraryRole.ADMIN, LibraryRole.CREATOR]

    assert sorted(LibraryRole, key=lambda r: r.rank) == order
    for low, high in pairwise(order):
        assert high.allows(low)
        assert not low.allows(high)
    assert all(role.allows(role) for role in order)


def test_the_effective_role_is_the_highest_granted() -> None:
    grants = [
        LibraryGrant(library=LIBRARY, kind=SubjectKind.USER, subject="b", role=role)
        for role in (LibraryRole.CONTRIBUTOR, LibraryRole.VIEWER, LibraryRole.ADMIN)
    ]

    assert effective_role(grants) is LibraryRole.ADMIN
    assert effective_role([]) is None


async def test_an_account_without_a_grant_has_no_role(world: World) -> None:
    assert await world.role("bob") is None


async def test_a_grant_to_a_user_gives_that_role_to_that_user_only(world: World) -> None:
    await world.grant("ada", "bob", "contributor")

    assert await world.role("bob") == "contributor"
    assert await world.role("carol") is None
    assert await world.role("bob", "/acme/ledger") is None


async def test_a_grant_to_a_group_reaches_its_members(world: World) -> None:
    world.in_groups("carol", "corp:payments")
    await world.grant("ada", "corp:payments", "viewer", kind="group")

    assert await world.role("carol") == "viewer"
    assert await world.role("bob") is None


async def test_the_effective_role_is_the_highest_of_the_user_and_its_groups(world: World) -> None:
    world.in_groups("bob", "readers", "writers")
    await world.grant("ada", "readers", "viewer", kind="group")
    await world.grant("ada", "writers", "contributor", kind="group")
    assert await world.role("bob") == "contributor"

    await world.grant("ada", "bob", "admin")

    assert await world.role("bob") == "admin"


async def test_an_operator_is_the_creator_of_every_library(world: World) -> None:
    assert await world.role("ada") == "creator"
    assert await world.role("ada", "/never/seen") == "creator"


async def test_a_disabled_or_unknown_account_has_no_role(world: World) -> None:
    await world.grant("ada", "bob", "admin")
    await world.identity.set_user_disabled(
        SetUserDisabledCommand(id=world.ids["bob"], disabled=True)
    )

    assert await world.role("bob") is None
    nobody = await world.identity.resolve_library_roles(
        LibraryRolesQuery(account_id="nobody", libraries=[LIBRARY])
    )
    assert nobody.roles == {}


async def test_library_ids_are_compared_case_insensitively(world: World) -> None:
    await world.grant("ada", "bob", "viewer")

    assert await world.role("bob", "/ACME/Payments") == "viewer"


async def test_claiming_makes_the_creator_and_drops_what_was_left_on_the_id(world: World) -> None:
    await world.grant("ada", "carol", "admin")

    await world.identity.claim_library(
        ClaimLibraryCommand(account_id=world.ids["bob"], library=LIBRARY)
    )

    assert await world.role("bob") == "creator"
    assert await world.role("carol") is None


async def test_dropping_the_grants_of_a_removed_library(world: World) -> None:
    await world.grant("ada", "bob", "viewer")

    await world.identity.drop_library_grants(DropLibraryGrantsCommand(library=LIBRARY))

    assert await world.role("bob") is None


async def test_only_an_admin_of_the_library_lists_or_changes_its_grants(world: World) -> None:
    await world.grant("ada", "bob", "contributor")
    await world.grant("ada", "dave", "viewer")

    for caller in ("bob", "dave", "carol"):
        with pytest.raises(LibraryRoleRequiredError):
            await world.grant(caller, "carol", "viewer")
        with pytest.raises(LibraryRoleRequiredError):
            await world.identity.list_library_grants(
                ListLibraryGrantsQuery(caller_id=world.ids[caller], library=LIBRARY)
            )
        with pytest.raises(LibraryRoleRequiredError):
            await world.identity.revoke_library_role(
                RevokeLibraryRoleCommand(
                    caller_id=world.ids[caller], library=LIBRARY, kind="user", subject="dave"
                )
            )


async def test_an_admin_shares_below_admin_and_only_the_creator_gives_admin(world: World) -> None:
    await world.grant("ada", "bob", "admin")

    await world.grant("bob", "carol", "contributor")
    assert await world.role("carol") == "contributor"
    with pytest.raises(LibraryRoleRequiredError, match="creator"):
        await world.grant("bob", "dave", "admin")
    await world.grant("ada", "dave", "admin")  # the creator may
    assert await world.role("dave") == "admin"


async def test_an_admin_cannot_demote_or_remove_another_admin(world: World) -> None:
    await world.grant("ada", "bob", "admin")
    await world.grant("ada", "dave", "admin")

    with pytest.raises(LibraryRoleRequiredError, match="creator"):
        await world.grant("bob", "dave", "viewer")
    with pytest.raises(LibraryRoleRequiredError, match="creator"):
        await world.identity.revoke_library_role(
            RevokeLibraryRoleCommand(
                caller_id=world.ids["bob"], library=LIBRARY, kind="user", subject="dave"
            )
        )
    assert await world.role("dave") == "admin"


async def test_the_creators_role_is_not_changed_or_taken_away_by_sharing(world: World) -> None:
    await world.identity.claim_library(
        ClaimLibraryCommand(account_id=world.ids["bob"], library=LIBRARY)
    )

    with pytest.raises(InvalidGrantError):
        await world.grant("ada", "bob", "viewer")
    with pytest.raises(InvalidGrantError):
        await world.identity.revoke_library_role(
            RevokeLibraryRoleCommand(
                caller_id=world.ids["ada"], library=LIBRARY, kind="user", subject="bob"
            )
        )
    assert await world.role("bob") == "creator"


async def test_revoking_takes_the_role_away_and_an_unknown_grant_is_refused(world: World) -> None:
    await world.grant("ada", "bob", "viewer")

    shown = await world.identity.revoke_library_role(
        RevokeLibraryRoleCommand(
            caller_id=world.ids["ada"], library=LIBRARY, kind="user", subject="bob"
        )
    )

    assert shown.grants == []
    assert await world.role("bob") is None
    with pytest.raises(UnknownGrantError):
        await world.identity.revoke_library_role(
            RevokeLibraryRoleCommand(
                caller_id=world.ids["ada"], library=LIBRARY, kind="user", subject="bob"
            )
        )


async def test_a_grant_to_a_username_nobody_has_is_refused(world: World) -> None:
    with pytest.raises(UnknownAccountError):
        await world.grant("ada", "zed", "viewer")


async def test_the_grants_are_listed_with_usernames_users_first(world: World) -> None:
    await world.grant("ada", "corp:payments", "viewer", kind="group")
    await world.grant("ada", "carol", "contributor")
    await world.grant("ada", "bob", "viewer")

    shown = await world.identity.list_library_grants(
        ListLibraryGrantsQuery(caller_id=world.ids["ada"], library=LIBRARY)
    )

    assert [(g.kind, g.subject, g.role) for g in shown.grants] == [
        ("user", "bob", "viewer"),
        ("user", "carol", "contributor"),
        ("group", "corp:payments", "viewer"),
    ]


async def test_the_grants_are_filtered_sorted_by_role_and_paged_with_a_total(world: World) -> None:
    await world.grant("ada", "corp:payments", "viewer", kind="group")
    await world.grant("ada", "carol", "contributor")
    await world.grant("ada", "bob", "viewer")
    await world.grant("ada", "dave", "admin")
    query: dict[str, object] = {"caller_id": world.ids["ada"], "library": LIBRARY}
    query |= {"kind": ["user"], "sort": "-role", "limit": 2}

    first = await world.identity.list_library_grants(ListLibraryGrantsQuery.model_validate(query))
    second = await world.identity.list_library_grants(
        ListLibraryGrantsQuery.model_validate({**query, "cursor": first.next_cursor})
    )

    assert [g.subject for g in first.grants] == ["dave", "carol"]
    assert ([g.subject for g in second.grants], second.next_cursor) == (["bob"], None)
    assert (first.total, second.total) == (3, 3)


async def test_the_grants_text_filter_matches_users_and_groups(world: World) -> None:
    await world.grant("ada", "corp:payments", "viewer", kind="group")
    await world.grant("ada", "bob", "viewer")

    shown = await world.identity.list_library_grants(
        ListLibraryGrantsQuery(caller_id=world.ids["ada"], library=LIBRARY, q="PAY")
    )

    assert ([g.subject for g in shown.grants], shown.total) == (["corp:payments"], 1)


async def test_a_caller_who_may_not_see_the_grants_gets_no_page_and_no_count(
    world: World,
) -> None:
    await world.grant("ada", "bob", "viewer")

    with pytest.raises(LibraryRoleRequiredError):
        await world.identity.list_library_grants(
            ListLibraryGrantsQuery(caller_id=world.ids["bob"], library=LIBRARY, q="bob", limit=1)
        )


@pytest.mark.parametrize("linked", [True, False])
async def test_a_verified_identity_for_another_caller_has_no_library_role(
    world: World, linked: bool
) -> None:
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["ada"], username="ada", role="admin"),
        groups=frozenset(),
        linked=linked,
    )
    roles = await world.identity.resolve_library_roles(
        LibraryRolesQuery(
            account_id=world.ids["bob"], libraries=[LIBRARY], external_identity=principal
        )
    )
    assert roles.roles == {}


async def test_a_deleted_linked_oauth_operator_has_no_library_role(world: World) -> None:
    principal = ExternalTokenIdentity(
        account=AccountSummary(id="deleted-account", username="alice", role="admin"),
        groups=frozenset(),
        linked=True,
    )
    roles = await world.identity.resolve_library_roles(
        LibraryRolesQuery(
            account_id=principal.account.id, libraries=[LIBRARY], external_identity=principal
        )
    )
    assert roles.roles == {}


async def test_a_disabled_linked_account_cannot_use_signed_operator_claims(world: World) -> None:
    await world.identity.set_user_disabled(
        SetUserDisabledCommand(id=world.ids["bob"], disabled=True)
    )
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["bob"], username="bob", role="admin"),
        groups=frozenset(),
        linked=True,
    )
    roles = await world.identity.resolve_library_roles(
        LibraryRolesQuery(
            account_id=principal.account.id, libraries=[LIBRARY], external_identity=principal
        )
    )
    assert roles.roles == {}


async def test_a_linked_oauth_caller_does_not_inherit_an_old_stored_operator_role(
    world: World,
) -> None:
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["ada"], username="ada", role="user"),
        groups=frozenset(),
        linked=True,
    )
    roles = await world.identity.resolve_library_roles(
        LibraryRolesQuery(
            account_id=principal.account.id, libraries=[LIBRARY], external_identity=principal
        )
    )
    assert roles.roles == {}
