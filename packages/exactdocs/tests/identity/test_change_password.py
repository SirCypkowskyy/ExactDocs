"""A person changes their own password (#505): checked, throttled, other sessions end."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, ValidationError

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryFailedSignInLog,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.constants import FREE_FAILURES, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    ChangePasswordCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
)
from exactdocs.identity.errors import (
    ExternalAccountError,
    InvalidCredentialsError,
    NotSignedInError,
    SignInThrottledError,
    WrongPasswordError,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    Role,
    Username,
    address_key,
    known_sign_in_key,
)
from exactdocs.identity.module import IdentityModule
from identity_stand_ins import no_external_sign_in

HORSE = "correct horse battery staple"
BOB = "bob's long passphrase"
NEW = "bob's brand new passphrase"
START = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
LAPTOP = "203.0.113.7"


@dataclass(slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


@dataclass(slots=True)
class MovableClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current


@dataclass(slots=True)
class World:
    identity: IdentityModule
    accounts: InMemoryAccountRepository
    sessions: InMemorySessionRepository
    failures: InMemoryFailedSignInLog
    clock: MovableClock = field(default_factory=MovableClock)


@pytest.fixture
async def world() -> World:
    clock = MovableClock()
    accounts, sessions = InMemoryAccountRepository(), InMemorySessionRepository()
    failures = InMemoryFailedSignInLog()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=sessions,
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=failures,
        clock=clock,
        **no_external_sign_in(),
    )
    await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    await identity.create_user(CreateUserCommand(username="bob", password=SecretStr(BOB)))
    return World(identity, accounts, sessions, failures, clock)


async def sign_in(world: World, password: str = BOB, client: str = LAPTOP) -> str:
    query = AuthenticateQuery(username="bob", password=SecretStr(password))
    grant = await world.identity.sign_in(query, client=client)
    return grant.token.get_secret_value()


def change(current: str, new: str = NEW) -> ChangePasswordCommand:
    return ChangePasswordCommand(current_password=SecretStr(current), new_password=SecretStr(new))


async def account_of(world: World, session: str) -> AccountSummary:
    return await world.identity.identify_caller(session)


async def test_the_new_password_works_and_the_old_one_no_longer_does(world: World) -> None:
    laptop = await sign_in(world)

    await world.identity.change_password(
        await account_of(world, laptop), change(BOB), session_token=laptop, client=LAPTOP
    )

    with pytest.raises(InvalidCredentialsError):
        await world.identity.authenticate(
            AuthenticateQuery(username="bob", password=SecretStr(BOB))
        )
    signed_in = await world.identity.authenticate(
        AuthenticateQuery(username="bob", password=SecretStr(NEW))
    )
    assert signed_in.username == "bob"


async def test_the_other_sessions_end_and_this_one_stays(world: World) -> None:
    laptop, phone = await sign_in(world), await sign_in(world, client="198.51.100.2")
    ada = (
        await world.identity.sign_in(AuthenticateQuery(username="ada", password=SecretStr(HORSE)))
    ).token.get_secret_value()

    await world.identity.change_password(
        await account_of(world, laptop), change(BOB), session_token=laptop, client=LAPTOP
    )

    assert (await account_of(world, laptop)).username == "bob"
    with pytest.raises(NotSignedInError):
        await account_of(world, phone)
    assert (await account_of(world, ada)).username == "ada"  # someone else's stays too


async def test_without_a_session_of_its_own_every_session_ends(world: World) -> None:
    laptop = await sign_in(world)
    bob = await account_of(world, laptop)

    await world.identity.change_password(bob, change(BOB))  # e.g. through Cloudflare Access

    with pytest.raises(NotSignedInError):
        await account_of(world, laptop)


async def test_api_tokens_keep_working(world: World) -> None:
    laptop = await sign_in(world)
    bob = await account_of(world, laptop)
    grant = await world.identity.create_token(bob, CreateTokenCommand(name="ci"))

    await world.identity.change_password(bob, change(BOB), session_token=laptop)

    assert (await world.identity.identify_token(grant.token)).username == "bob"


async def test_a_wrong_current_password_is_refused_and_nothing_changes(world: World) -> None:
    laptop, phone = await sign_in(world), await sign_in(world)
    bob = await account_of(world, laptop)

    with pytest.raises(WrongPasswordError):
        await world.identity.change_password(
            bob, change("not bob's passphrase"), session_token=laptop, client=LAPTOP
        )

    assert (await account_of(world, phone)).username == "bob"
    assert (await account_of(world, laptop)).username == "bob"  # still signed in, no 401
    await world.identity.authenticate(AuthenticateQuery(username="bob", password=SecretStr(BOB)))


async def test_wrong_current_passwords_are_throttled_like_sign_ins(world: World) -> None:
    laptop = await sign_in(world)
    bob = await account_of(world, laptop)
    for _ in range(FREE_FAILURES):
        with pytest.raises(WrongPasswordError):
            await world.identity.change_password(
                bob, change("not bob's passphrase"), session_token=laptop, client=LAPTOP
            )

    # The right password must wait now, unchecked; so must a sign-in from the same address.
    with pytest.raises(SignInThrottledError):
        await world.identity.change_password(bob, change(BOB), session_token=laptop, client=LAPTOP)
    with pytest.raises(SignInThrottledError):
        await world.identity.authenticate(
            AuthenticateQuery(username="bob", password=SecretStr(BOB)), client=LAPTOP
        )
    world.clock.current += timedelta(hours=1)  # failures are forgotten after an hour
    await world.identity.change_password(bob, change(BOB), session_token=laptop, client=LAPTOP)


async def test_the_addresses_of_the_old_password_are_forgotten(world: World) -> None:
    laptop = await sign_in(world)
    await sign_in(world, client="198.51.100.2")  # another machine that knew the old password
    await world.failures.charge(["username:bob"], world.clock.now())
    bob = await account_of(world, laptop)
    elsewhere = known_sign_in_key(Username("bob"), address_key("198.51.100.2"))
    here = known_sign_in_key(Username("bob"), address_key(LAPTOP))
    assert await world.failures.signed_in_before(elsewhere, world.clock.now())

    await world.identity.change_password(bob, change(BOB), session_token=laptop, client=LAPTOP)

    assert not await world.failures.signed_in_before(elsewhere, world.clock.now())
    assert await world.failures.signed_in_before(here, world.clock.now())  # it knows the new one
    assert await world.failures.get("username:bob") is None


async def test_an_account_without_a_password_is_refused(world: World) -> None:
    external = Account(
        id=AccountId("ext-1"),
        username=Username("erin"),
        password_hash=None,
        role=Role.USER,
        created_at=START,
    )
    await world.accounts.add(external)
    erin = AccountSummary.from_model(external)
    assert erin.has_password is False

    with pytest.raises(ExternalAccountError):
        await world.identity.change_password(erin, change("anything at all"))


async def test_a_vanished_account_is_signed_out(world: World) -> None:
    ghost = AccountSummary(id="gone", username="ghost", role="user", has_password=True)

    with pytest.raises(NotSignedInError):
        await world.identity.change_password(ghost, change(BOB))


async def test_the_session_says_whether_the_account_has_a_password(world: World) -> None:
    laptop = await sign_in(world)

    state = await world.identity.get_session_state(laptop)

    assert state.account is not None
    assert state.account.has_password is True


@pytest.mark.parametrize("new", ["x" * (MIN_PASSWORD_LENGTH - 1), "x" * (MAX_PASSWORD_LENGTH + 1)])
def test_the_new_password_follows_the_setup_length_rules(new: str) -> None:
    with pytest.raises(ValidationError):
        ChangePasswordCommand(current_password=SecretStr(BOB), new_password=SecretStr(new))


def test_the_passwords_never_show_in_a_repr() -> None:
    assert BOB not in repr(change(BOB))
    assert NEW not in repr(change(BOB))
