"""Instance creation permission uses stable identities and current trusted groups."""

from dataclasses import dataclass, replace

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
    CreateFirstAdminCommand,
    CreateUserCommand,
    ExternalTokenIdentity,
    LibraryCreationQuery,
    SetUserDisabledCommand,
)
from exactdocs.identity.models import (
    AccountId,
    LibraryCreationPolicy,
)
from exactdocs.identity.module import IdentityModule
from exactdocs.identity.use_cases import CanCreateLibraryUseCase
from exactdocs_kernel import SystemClock

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

    def in_groups(self, who: str, *groups: str) -> None:
        self.externals.groups[AccountId(self.ids[who])] = frozenset(groups)


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


@pytest.mark.parametrize(
    ("who", "users", "groups", "expected"),
    [
        ("bob", None, None, True),
        ("bob", (), (), False),
        ("ada", (), (), True),
        ("bob", ("bob",), (), True),
        ("carol", ("bob",), (), False),
        ("bob", (), ("corp:docs",), True),
        ("carol", (), ("corp:docs",), False),
    ],
)
async def test_creation_policy(world: World, who, users, groups, expected):
    world.in_groups("bob", "corp:docs")
    policy = (
        None
        if users is None
        else LibraryCreationPolicy(
            users=frozenset(world.ids[u] for u in users), groups=frozenset(groups)
        )
    )
    use_case = world.identity.can_create_library
    assert isinstance(use_case, CanCreateLibraryUseCase)
    use_case = replace(use_case, policy=policy)
    assert await use_case(LibraryCreationQuery(account_id=world.ids[who])) is expected


async def test_unknown_and_disabled_accounts_are_refused_even_without_policy(world: World):
    query = LibraryCreationQuery(account_id="unknown")
    assert not await world.identity.can_create_library(query)
    await world.identity.set_user_disabled(SetUserDisabledCommand(username="bob", disabled=True))
    assert not await world.identity.can_create_library(
        LibraryCreationQuery(account_id=world.ids["bob"])
    )


@pytest.mark.parametrize(
    ("stored", "verified", "expected"), [(True, False, False), (False, True, True)]
)
async def test_verified_groups_override_stored_groups(world: World, stored, verified, expected):
    world.in_groups("bob", *(["corp:docs"] if stored else []))
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["bob"], username="bob", role="user"),
        groups=frozenset({"corp:docs"} if verified else set()),
        linked=True,
    )
    base_case = world.identity.can_create_library
    assert isinstance(base_case, CanCreateLibraryUseCase)
    case = replace(
        base_case,
        policy=LibraryCreationPolicy(groups=frozenset({"corp:docs"})),
    )
    assert (
        await case(LibraryCreationQuery(account_id=world.ids["bob"], external_identity=principal))
        is expected
    )


@pytest.mark.parametrize(
    ("linked", "matching", "expected"),
    [(False, True, True), (True, True, False), (False, False, False)],
)
async def test_verified_unlinked_identity_uses_stable_subject(
    world: World, linked, matching, expected
):
    principal = ExternalTokenIdentity(
        account=AccountSummary(id="corp:subject-1", username="bob", role="user"),
        groups=frozenset(),
        linked=linked,
    )
    base_case = world.identity.can_create_library
    assert isinstance(base_case, CanCreateLibraryUseCase)
    case = replace(
        base_case,
        policy=LibraryCreationPolicy(users=frozenset({"corp:subject-1"})),
    )
    assert (
        await case(
            LibraryCreationQuery(
                account_id="corp:subject-1" if matching else "someone-else",
                external_identity=principal,
            )
        )
        is expected
    )


@pytest.mark.parametrize(("role", "expected"), [("admin", True), ("user", False)])
async def test_verified_role_is_used_instead_of_stored_role(world: World, role, expected):
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["ada"], username="ada", role=role),
        groups=frozenset(),
        linked=True,
    )
    base_case = world.identity.can_create_library
    assert isinstance(base_case, CanCreateLibraryUseCase)
    case = replace(base_case, policy=LibraryCreationPolicy())
    assert (
        await case(LibraryCreationQuery(account_id=world.ids["ada"], external_identity=principal))
        is expected
    )


async def test_disabled_linked_oauth_account_cannot_use_operator_or_group_permission(world: World):
    await world.identity.set_user_disabled(SetUserDisabledCommand(username="bob", disabled=True))
    principal = ExternalTokenIdentity(
        account=AccountSummary(id=world.ids["bob"], username="bob", role="admin"),
        groups=frozenset({"corp:docs"}),
        linked=True,
    )
    assert not await world.identity.can_create_library(
        LibraryCreationQuery(account_id=world.ids["bob"], external_identity=principal)
    )


async def test_same_display_name_does_not_match_an_allowed_stable_account(world: World):
    base_case = world.identity.can_create_library
    assert isinstance(base_case, CanCreateLibraryUseCase)
    case = replace(base_case, policy=LibraryCreationPolicy(users=frozenset({world.ids["bob"]})))
    principal = ExternalTokenIdentity(
        account=AccountSummary(id="corp:another-subject", username="bob", role="user"),
        groups=frozenset(),
        linked=False,
    )
    assert not await case(
        LibraryCreationQuery(account_id=principal.account.id, external_identity=principal)
    )
