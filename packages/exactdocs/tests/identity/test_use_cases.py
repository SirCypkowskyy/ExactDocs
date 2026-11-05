from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryFailedSignInLog,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.dtos import AuthenticateQuery, CreateFirstAdminCommand
from exactdocs.identity.errors import (
    AlreadySetUpError,
    InvalidCredentialsError,
    InvalidUsernameError,
)
from exactdocs.identity.models import Account, AccountId, Username
from exactdocs.identity.module import IdentityModule

HORSE = "correct horse battery staple"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class FakeHasher:
    """A reversible stand-in for the KDF: fast, and it records what it was asked to hash."""

    hashed: list[str] = field(default_factory=list)

    async def hash(self, password: str) -> str:
        self.hashed.append(password)
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


@dataclass(frozen=True, slots=True)
class FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass(slots=True)
class RacedRepository:
    """Says the table is empty, yet its insert finds an account: someone else was first."""

    inner: InMemoryAccountRepository

    async def add_first(self, account: Account) -> bool:
        return await self.inner.add_first(account)

    async def get(self, username: Username) -> Account | None:
        return await self.inner.get(username)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        return await self.inner.get_by_id(account_id)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        await self.inner.set_password_hash(account_id, password_hash)

    async def any_exists(self) -> bool:
        return False


@pytest.fixture
def hasher() -> FakeHasher:
    return FakeHasher()


@pytest.fixture
def repository() -> InMemoryAccountRepository:
    return InMemoryAccountRepository()


@pytest.fixture
def identity(repository: InMemoryAccountRepository, hasher: FakeHasher) -> IdentityModule:
    return IdentityModule.build(
        repository=repository,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=hasher,
        failures=InMemoryFailedSignInLog(),
        clock=FixedClock(),
    )


def command(username: str = "ada", password: str = HORSE) -> CreateFirstAdminCommand:
    return CreateFirstAdminCommand(username=username, password=SecretStr(password))


def credentials(username: str, password: str) -> AuthenticateQuery:
    return AuthenticateQuery(username=username, password=SecretStr(password))


async def test_a_fresh_instance_needs_setup(identity: IdentityModule) -> None:
    assert (await identity.get_setup_state()).setup_required is True


async def test_the_first_account_is_the_admin_and_ends_the_setup(identity: IdentityModule) -> None:
    created = await identity.create_first_admin(command())

    assert (created.username, created.role) == ("ada", "admin")
    assert (await identity.get_setup_state()).setup_required is False


async def test_the_password_is_stored_hashed_never_in_clear(
    identity: IdentityModule, repository: InMemoryAccountRepository
) -> None:
    created = await identity.create_first_admin(command())

    stored = await repository.get(Username("ada"))
    assert stored is not None
    assert HORSE not in stored.password_hash
    assert HORSE not in repr(stored)
    assert HORSE not in created.model_dump_json()
    assert stored.created_at == NOW


async def test_a_second_setup_is_refused_and_changes_nothing(identity: IdentityModule) -> None:
    await identity.create_first_admin(command())

    with pytest.raises(AlreadySetUpError):
        await identity.create_first_admin(command("mallory", "another strong password"))

    with pytest.raises(InvalidCredentialsError):
        await identity.authenticate(credentials("mallory", "another strong password"))
    assert (await identity.authenticate(credentials("ada", HORSE))).username == "ada"


async def test_a_lost_race_to_the_repository_is_refused_too(
    identity: IdentityModule, repository: InMemoryAccountRepository, hasher: FakeHasher
) -> None:
    # `any_exists` said no, but another process stored an account before ours: `add_first` decides.
    await identity.create_first_admin(command())
    racing = IdentityModule.build(
        repository=RacedRepository(repository),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=hasher,
        failures=InMemoryFailedSignInLog(),
        clock=FixedClock(),
    )

    with pytest.raises(AlreadySetUpError):
        await racing.create_first_admin(command("mallory", "another strong password"))


def test_the_command_does_not_leak_the_password() -> None:
    assert HORSE not in repr(command())
    assert HORSE not in str(command())


@pytest.mark.parametrize("password", ["", "short", "x" * 11, "x" * 1025])
def test_a_password_outside_the_length_bounds_is_rejected(password: str) -> None:
    with pytest.raises(ValidationError):
        command(password=password)


@pytest.mark.parametrize("username", ["", "   ", "a b", "tab\there", "x" * 65, "nul\x00"])
async def test_an_invalid_username_is_rejected(identity: IdentityModule, username: str) -> None:
    with pytest.raises(InvalidUsernameError):
        await identity.create_first_admin(command(username))

    assert (await identity.get_setup_state()).setup_required is True


async def test_usernames_are_case_insensitive_and_trimmed(identity: IdentityModule) -> None:
    await identity.create_first_admin(command("  Ada  "))

    signed_in = await identity.authenticate(credentials("ADA", HORSE))

    assert signed_in.username == "ada"


async def test_the_right_password_signs_in(identity: IdentityModule) -> None:
    await identity.create_first_admin(command())

    signed_in = await identity.authenticate(credentials("ada", HORSE))

    assert signed_in.role == "admin"


async def test_wrong_password_and_unknown_user_fail_with_the_same_error(
    identity: IdentityModule,
) -> None:
    await identity.create_first_admin(command())
    errors = []
    for attempt in (credentials("ada", "wrong password!"), credentials("nobody", HORSE)):
        with pytest.raises(InvalidCredentialsError) as raised:
            await identity.authenticate(attempt)
        errors.append((type(raised.value), str(raised.value), raised.value.code))

    assert errors[0] == errors[1]


async def test_an_unknown_user_costs_a_hash_so_timing_does_not_reveal_it(
    identity: IdentityModule, hasher: FakeHasher
) -> None:
    await identity.create_first_admin(command())
    hasher.hashed.clear()

    with pytest.raises(InvalidCredentialsError):
        await identity.authenticate(credentials("nobody", HORSE))
    with pytest.raises(InvalidCredentialsError):
        await identity.authenticate(credentials("not a valid\nname", HORSE))

    assert hasher.hashed == [HORSE, HORSE]


async def test_an_already_set_up_instance_answers_409_before_judging_the_username(
    identity: IdentityModule,
) -> None:
    await identity.create_first_admin(command())

    with pytest.raises(AlreadySetUpError):
        await identity.create_first_admin(command("not valid", HORSE))


def test_usernames_are_normalised_to_a_fixed_point() -> None:
    # U+0130 casefolds to "i" + U+0307, which NFKC would compose differently; the result is stable.
    once = Username("\u0130stanbul").value

    assert Username(once).value == once
