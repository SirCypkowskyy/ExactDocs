"""Session use cases: expiry (idle and absolute) against a movable clock, sign-out, reset."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryFailedSignInLog,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.constants import ABSOLUTE_TIMEOUT, IDLE_TIMEOUT
from exactdocs.identity.dtos import (
    AuthenticateQuery,
    CreateFirstAdminCommand,
    ResetPasswordCommand,
)
from exactdocs.identity.errors import (
    InvalidCredentialsError,
    NotSignedInError,
    UnknownAccountError,
)
from exactdocs.identity.models import AccountId, Session, hash_token
from exactdocs.identity.module import IdentityModule

HORSE = "correct horse battery staple"
START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


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
    sessions: InMemorySessionRepository
    clock: MovableClock = field(default_factory=MovableClock)


@pytest.fixture
async def world() -> World:
    clock, sessions, tokens = MovableClock(), InMemorySessionRepository(), InMemoryTokenRepository()
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=sessions,
        tokens=tokens,
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=clock,
    )
    await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    return World(identity, sessions, clock)


def credentials(password: str = HORSE, username: str = "ada") -> AuthenticateQuery:
    return AuthenticateQuery(username=username, password=SecretStr(password))


async def sign_in(world: World) -> str:
    return (await world.identity.sign_in(credentials())).token.get_secret_value()


async def test_signing_in_gives_a_token_that_identifies_the_admin(world: World) -> None:
    grant = await world.identity.sign_in(credentials())

    caller = await world.identity.identify_caller(grant.token.get_secret_value())

    assert (caller.username, caller.role) == ("ada", "admin")
    assert grant.account == caller
    assert grant.max_age == ABSOLUTE_TIMEOUT.total_seconds()


async def test_signing_in_again_drops_the_previous_session(world: World) -> None:
    old = await sign_in(world)

    grant = await world.identity.sign_in(credentials(), old)

    assert set(world.sessions.sessions) == {hash_token(grant.token.get_secret_value())}


async def test_the_token_is_random_long_and_never_stored_or_shown(world: World) -> None:
    first, second = await sign_in(world), await sign_in(world)

    assert first != second
    assert len(first) >= 43  # 256 bits, url-safe base64
    assert set(world.sessions.sessions) == {hash_token(first), hash_token(second)}
    assert first not in world.sessions.sessions
    assert first not in repr(world.sessions.sessions)
    grant = await world.identity.sign_in(credentials())
    assert grant.token.get_secret_value() not in repr(grant)


async def test_bad_credentials_start_no_session(world: World) -> None:
    for attempt in (credentials("wrong password!"), credentials(username="nobody")):
        with pytest.raises(InvalidCredentialsError):
            await world.identity.sign_in(attempt)

    assert world.sessions.sessions == {}


@pytest.mark.parametrize("token", [None, "", "not-a-token", "x" * 5000])
async def test_no_token_or_an_unknown_one_identifies_nobody(
    world: World, token: str | None
) -> None:
    await sign_in(world)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(token)


async def test_a_session_ends_after_the_idle_timeout(world: World) -> None:
    token = await sign_in(world)

    world.clock.advance(IDLE_TIMEOUT - timedelta(seconds=1))
    await world.identity.identify_caller(token)  # still fine, and counts as use
    world.clock.advance(IDLE_TIMEOUT - timedelta(seconds=1))
    await world.identity.identify_caller(token)
    world.clock.advance(IDLE_TIMEOUT)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(token)
    assert world.sessions.sessions == {}  # the expired row is removed, not just ignored


async def test_a_busy_session_still_ends_at_the_absolute_timeout(world: World) -> None:
    token = await sign_in(world)

    for _ in range(5):  # day 5, 10, ... 25: used often enough never to be idle
        world.clock.advance(timedelta(days=5))
        await world.identity.identify_caller(token)
    world.clock.advance(timedelta(days=5))  # day 30

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(token)


async def test_using_a_session_only_writes_when_the_last_use_is_an_hour_old(world: World) -> None:
    token = await sign_in(world)
    stored = world.sessions.sessions[hash_token(token)]

    world.clock.advance(timedelta(minutes=59))
    await world.identity.identify_caller(token)
    assert world.sessions.sessions[hash_token(token)] == stored

    world.clock.advance(timedelta(minutes=2))
    await world.identity.identify_caller(token)
    assert world.sessions.sessions[hash_token(token)].last_used_at == world.clock.current


async def test_signing_out_ends_the_session_on_the_server(world: World) -> None:
    token = await sign_in(world)
    other = await sign_in(world)

    await world.identity.sign_out(token)
    await world.identity.sign_out(token)  # twice is fine

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(token)
    assert (await world.identity.identify_caller(other)).username == "ada"


async def test_signing_in_clears_sessions_that_have_expired(world: World) -> None:
    stale = await sign_in(world)
    world.clock.advance(IDLE_TIMEOUT + timedelta(days=1))

    fresh = await sign_in(world)

    assert set(world.sessions.sessions) == {hash_token(fresh)}
    assert hash_token(stale) not in world.sessions.sessions


async def test_session_state_tells_setup_signed_out_and_signed_in(world: World) -> None:
    token = await sign_in(world)

    assert (await world.identity.get_session_state(token)).state == "signed_in"
    assert (await world.identity.get_session_state(token)).account is not None
    assert (await world.identity.get_session_state(None)).state == "signed_out"
    assert (await world.identity.get_session_state("bogus")).account is None

    empty = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=MovableClock(),
    )
    assert (await empty.get_session_state(None)).state == "setup_required"


async def test_resetting_the_password_ends_every_session_and_changes_the_password(
    world: World,
) -> None:
    tokens = [await sign_in(world), await sign_in(world)]

    await world.identity.reset_password(
        ResetPasswordCommand(username=" ADA ", password=SecretStr("a brand new passphrase"))
    )

    for token in tokens:
        with pytest.raises(NotSignedInError):
            await world.identity.identify_caller(token)
    with pytest.raises(InvalidCredentialsError):
        await world.identity.sign_in(credentials())
    grant = await world.identity.sign_in(credentials("a brand new passphrase"))
    assert grant.account.username == "ada"


@pytest.mark.parametrize("username", ["nobody", "not valid\n"])
async def test_resetting_an_unknown_account_is_refused(world: World, username: str) -> None:
    with pytest.raises(UnknownAccountError):
        await world.identity.reset_password(
            ResetPasswordCommand(username=username, password=SecretStr("a brand new passphrase"))
        )


def test_session_expiry_is_the_earlier_of_idle_and_absolute() -> None:
    created, digest = START, hash_token("any")
    fresh = Session(
        token_hash=digest, account_id=AccountId("a"), created_at=created, last_used_at=created
    )
    used_late = Session(
        token_hash=digest,
        account_id=AccountId("a"),
        created_at=created,
        last_used_at=created + timedelta(days=29),
    )

    assert fresh.expires_at() == created + IDLE_TIMEOUT
    assert used_late.expires_at() == created + ABSOLUTE_TIMEOUT
    assert fresh.is_expired(created + IDLE_TIMEOUT)
    assert not fresh.is_expired(created + IDLE_TIMEOUT - timedelta(microseconds=1))
