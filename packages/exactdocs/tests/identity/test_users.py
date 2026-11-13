"""Local user accounts (ACL-06): operators create, disable, enable and reset them; no signup."""

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
from exactdocs.identity.dtos import (
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    ResetPasswordCommand,
    SetUserDisabledCommand,
    UserSummary,
)
from exactdocs.identity.errors import (
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidUsernameError,
    LastOperatorError,
    NotSetUpError,
    NotSignedInError,
    ReservedUsernameError,
    UnknownAccountError,
    UsernameTakenError,
)
from exactdocs.identity.models import Account, AccountId, Session, Username, hash_token
from exactdocs.identity.module import IdentityModule

HORSE = "correct horse battery staple"
BOB = "bob's long passphrase"
START = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


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

    def advance(self, by: timedelta) -> None:
        self.current += by


@dataclass(slots=True)
class World:
    identity: IdentityModule
    accounts: InMemoryAccountRepository
    sessions: InMemorySessionRepository
    tokens: InMemoryTokenRepository
    failures: InMemoryFailedSignInLog
    clock: MovableClock = field(default_factory=MovableClock)


def build() -> World:
    clock = MovableClock()
    accounts, sessions = InMemoryAccountRepository(), InMemorySessionRepository()
    tokens, failures = InMemoryTokenRepository(), InMemoryFailedSignInLog()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=sessions,
        tokens=tokens,
        hasher=FakeHasher(),
        failures=failures,
        clock=clock,
    )
    return World(identity, accounts, sessions, tokens, failures, clock)


@pytest.fixture
async def world() -> World:
    world = build()
    await world.identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    return world


def credentials(username: str, password: str) -> AuthenticateQuery:
    return AuthenticateQuery(username=username, password=SecretStr(password))


async def create(world: World, username: str = "bob", role: str = "user") -> UserSummary:
    world.clock.advance(timedelta(minutes=1))
    command = CreateUserCommand.model_validate(
        {"username": username, "password": BOB, "role": role}
    )
    return await world.identity.create_user(command)


async def disable(world: World, username: str, *, disabled: bool = True) -> UserSummary:
    command = SetUserDisabledCommand(username=username, disabled=disabled)
    return await world.identity.set_user_disabled(command)


async def signed_in_with_token(world: World, username: str = "bob") -> tuple[str, str]:
    grant = await world.identity.sign_in(credentials(username, BOB))
    account = grant.account
    token = await world.identity.create_token(account, CreateTokenCommand(name="laptop"))
    return grant.token.get_secret_value(), token.token


async def test_a_user_cannot_be_created_before_the_setup() -> None:
    world = build()

    with pytest.raises(NotSetUpError):
        await create(world)

    assert (await world.identity.get_setup_state()).setup_required


async def test_a_created_user_signs_in_as_a_user(world: World) -> None:
    created = await create(world, "  Bob ")

    assert (created.username, created.role, created.disabled) == ("bob", "user", False)
    account = await world.identity.authenticate(credentials("BOB", BOB))
    assert (account.id, account.role) == (created.id, "user")


async def test_an_operator_may_create_another_admin(world: World) -> None:
    created = await create(world, "carol", role="admin")

    assert created.role == "admin"


async def test_users_are_listed_oldest_first_with_disabled_ones(world: World) -> None:
    await create(world, "carol")
    await create(world, "bob")
    await disable(world, "carol")

    users = (await world.identity.list_users()).users

    assert [(u.username, u.role, u.disabled) for u in users] == [
        ("ada", "admin", False),
        ("carol", "user", True),
        ("bob", "user", False),
    ]


@pytest.mark.parametrize("username", ["bob", "BOB", " bob "])
async def test_a_taken_username_is_refused(world: World, username: str) -> None:
    await create(world)

    with pytest.raises(UsernameTakenError):
        await create(world, username)


@dataclass(slots=True)
class LateAccounts:
    """Finds no account by username, yet its insert finds one: someone else was first."""

    inner: InMemoryAccountRepository

    async def add_first(self, account: Account) -> bool:
        return await self.inner.add_first(account)

    async def add(self, account: Account) -> bool:
        return await self.inner.add(account)

    async def list_all(self) -> list[Account]:
        return await self.inner.list_all()

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        return await self.inner.set_disabled_at(account_id, disabled_at)

    async def get(self, username: Username) -> Account | None:
        del username
        return None

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        return await self.inner.get_by_id(account_id)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        await self.inner.set_password_hash(account_id, password_hash)

    async def any_exists(self) -> bool:
        return await self.inner.any_exists()


async def test_a_lost_race_for_a_username_is_refused_too(world: World) -> None:
    await create(world)
    raced = IdentityModule.build(
        repository=LateAccounts(world.accounts),
        sessions=world.sessions,
        tokens=world.tokens,
        hasher=FakeHasher(),
        failures=world.failures,
        clock=world.clock,
    )

    with pytest.raises(UsernameTakenError):
        await raced.create_user(
            CreateUserCommand(username="bob", password=SecretStr("another passphrase"))
        )
    assert [u.username for u in (await world.identity.list_users()).users] == ["ada", "bob"]


@pytest.mark.parametrize("username", ["a@address:1.2.3.4", "x@ADDRESS:y"])
async def test_a_username_the_throttle_uses_in_its_keys_is_refused(
    world: World, username: str
) -> None:
    with pytest.raises(ReservedUsernameError):
        await create(world, username)


@pytest.mark.parametrize("username", ["", "two words", "x" * 65])
async def test_an_invalid_username_is_refused(world: World, username: str) -> None:
    with pytest.raises(InvalidUsernameError):
        await create(world, username)


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_a_password_outside_the_bounds_is_refused(password: str) -> None:
    with pytest.raises(ValidationError):
        CreateUserCommand(username="bob", password=SecretStr(password))


def test_there_is_no_role_beyond_admin_and_user() -> None:
    with pytest.raises(ValidationError):
        CreateUserCommand.model_validate({"username": "bob", "password": BOB, "role": "root"})


async def test_creating_a_user_forgets_failures_counted_against_the_name(world: World) -> None:
    await world.failures.charge(["username:bob"], world.clock.now())

    await create(world)

    assert await world.failures.get("username:bob") is None


async def test_disabling_locks_the_user_out_at_once(world: World) -> None:
    await create(world)
    session, token = await signed_in_with_token(world)

    disabled = await disable(world, "bob")

    assert disabled.disabled
    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)
    with pytest.raises(InvalidCredentialsError):  # the same answer as a wrong password
        await world.identity.sign_in(credentials("bob", BOB))
    assert world.sessions.sessions == {}
    assert world.tokens.tokens == {}


async def test_a_session_that_raced_the_disable_is_refused(world: World) -> None:
    created = await create(world)
    await disable(world, "bob")
    # A sign-in that checked the password just before the disable stores its session after it.
    await world.sessions.add(
        Session(
            token_hash=hash_token("raced"),
            account_id=AccountId(created.id),
            created_at=world.clock.now(),
            last_used_at=world.clock.now(),
        )
    )

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller("raced")
    assert world.sessions.sessions == {}


async def test_disabling_twice_or_enabling_an_enabled_user_changes_nothing(world: World) -> None:
    await create(world)
    first = await disable(world, "bob")
    world.clock.advance(timedelta(hours=1))

    assert await disable(world, "bob") == first
    assert (await disable(world, "ada", disabled=False)).disabled is False


async def test_enabling_lets_the_user_sign_in_again_but_tokens_stay_revoked(world: World) -> None:
    await create(world)
    _, token = await signed_in_with_token(world)
    await disable(world, "bob")

    enabled = await disable(world, "bob", disabled=False)

    assert not enabled.disabled
    grant = await world.identity.sign_in(credentials("bob", BOB))
    assert (await world.identity.identify_caller(grant.token.get_secret_value())).username == "bob"
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)


async def test_other_accounts_keep_their_sessions(world: World) -> None:
    await create(world)
    ada = (await world.identity.sign_in(credentials("ada", HORSE))).token.get_secret_value()
    await signed_in_with_token(world)

    await disable(world, "bob")

    assert (await world.identity.identify_caller(ada)).username == "ada"


async def test_the_last_enabled_admin_cannot_be_disabled(world: World) -> None:
    await create(world, "carol", role="admin")
    await disable(world, "carol")

    with pytest.raises(LastOperatorError):
        await disable(world, "ada")

    assert not (await world.identity.list_users()).users[0].disabled


async def test_an_admin_can_be_disabled_while_another_stays(world: World) -> None:
    await create(world, "carol", role="admin")

    assert (await disable(world, "ada")).disabled
    with pytest.raises(LastOperatorError):
        await disable(world, "carol")


@pytest.mark.parametrize(
    "command",
    [
        SetUserDisabledCommand(username="nobody", disabled=True),
        SetUserDisabledCommand(username="two words", disabled=True),
        SetUserDisabledCommand(id="no-such-id", disabled=True),
    ],
)
async def test_an_unknown_account_is_named_as_such(
    world: World, command: SetUserDisabledCommand
) -> None:
    with pytest.raises(UnknownAccountError):
        await world.identity.set_user_disabled(command)


@pytest.mark.parametrize("fields", [{}, {"id": "x", "username": "bob"}])
def test_an_account_is_named_by_exactly_one_of_id_and_username(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SetUserDisabledCommand.model_validate({**fields, "disabled": True})
    with pytest.raises(ValidationError):
        ResetPasswordCommand.model_validate({**fields, "password": BOB})


async def test_a_reset_by_id_ends_the_sessions_and_clears_the_throttle(world: World) -> None:
    created = await create(world)
    session, token = await signed_in_with_token(world)
    await world.failures.charge(["username:bob"], world.clock.now())
    new = "bob's brand new passphrase"

    reset = await world.identity.reset_password(
        ResetPasswordCommand(id=created.id, password=SecretStr(new))
    )

    assert (reset.account.username, reset.throttle) == ("bob", "cleared")
    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)
    assert await world.failures.get("username:bob") is None
    assert (await world.identity.authenticate(credentials("bob", new))).username == "bob"


async def test_a_reset_leaves_a_disabled_user_disabled(world: World) -> None:
    await create(world)
    await disable(world, "bob")
    new = "bob's brand new passphrase"

    await world.identity.reset_password(
        ResetPasswordCommand(username="bob", password=SecretStr(new))
    )

    with pytest.raises(InvalidCredentialsError):
        await world.identity.authenticate(credentials("bob", new))
