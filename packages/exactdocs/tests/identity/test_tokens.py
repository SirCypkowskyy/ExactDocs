"""API token use cases: only hashes are kept, expiry and revocation, ownership."""

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
from exactdocs.identity.dtos import (
    AccountSummary,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    ResetPasswordCommand,
)
from exactdocs.identity.errors import (
    InvalidTokenError,
    InvalidTokenExpiryError,
    InvalidTokenNameError,
    TooManyTokensError,
    UnknownTokenError,
)
from exactdocs.identity.models import VALUE_PREFIX, hash_token
from exactdocs.identity.module import IdentityModule
from exactdocs.identity.use_cases import MAX_TOKENS_PER_ACCOUNT, TOUCH_INTERVAL

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password}"


@dataclass(slots=True)
class MovableClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current


@dataclass(slots=True)
class World:
    identity: IdentityModule
    tokens: InMemoryTokenRepository
    ada: AccountSummary
    clock: MovableClock = field(default_factory=MovableClock)


@pytest.fixture
async def world() -> World:
    clock, tokens = MovableClock(), InMemoryTokenRepository()
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=tokens,
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=clock,
    )
    ada = await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr("correct horse battery staple"))
    )
    return World(identity, tokens, ada, clock)


async def test_a_token_is_recognizable_shown_once_and_stored_only_hashed(world: World) -> None:
    grant = await world.identity.create_token(world.ada, CreateTokenCommand(name=" laptop "))

    assert grant.token.startswith(VALUE_PREFIX)
    assert len(grant.token) >= len(VALUE_PREFIX) + 43  # 256 bits, url-safe base64
    assert grant.name == "laptop"
    assert grant.prefix == grant.token[: len(grant.prefix)] != grant.token
    stored = next(iter(world.tokens.tokens.values()))
    assert stored.token_hash == hash_token(grant.token)
    assert grant.token not in repr(stored)
    assert grant.token not in str(stored)
    listed = (await world.identity.list_tokens(world.ada)).tokens
    assert [t.id for t in listed] == [grant.id]
    assert grant.token not in listed[0].model_dump_json()


async def test_a_token_acts_as_its_account_and_records_when_it_was_used(world: World) -> None:
    grant = await world.identity.create_token(world.ada, CreateTokenCommand(name="laptop"))

    assert await world.identity.identify_token(grant.token) == world.ada
    listed = (await world.identity.list_tokens(world.ada)).tokens[0]
    assert listed.last_used_at == START

    world.clock.current += TOUCH_INTERVAL / 2  # too soon for another write
    await world.identity.identify_token(grant.token)
    assert (await world.identity.list_tokens(world.ada)).tokens[0].last_used_at == START

    world.clock.current += TOUCH_INTERVAL
    await world.identity.identify_token(grant.token)
    last_used = (await world.identity.list_tokens(world.ada)).tokens[0].last_used_at
    assert last_used is not None
    assert last_used > START


@pytest.mark.parametrize("secret", ["", "exd_nope", "nope", "x" * 5000])
async def test_an_unknown_token_is_refused(world: World, secret: str) -> None:
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(secret)


async def test_an_expired_token_is_refused_but_a_live_one_is_not(world: World) -> None:
    expiry = START + timedelta(days=1)
    grant = await world.identity.create_token(
        world.ada, CreateTokenCommand(name="short", expires_at=expiry)
    )
    assert grant.expires_at == expiry

    world.clock.current = expiry - timedelta(seconds=1)
    await world.identity.identify_token(grant.token)
    world.clock.current = expiry
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(grant.token)


async def test_a_token_cannot_be_created_already_expired(world: World) -> None:
    with pytest.raises(InvalidTokenExpiryError):
        await world.identity.create_token(world.ada, CreateTokenCommand(name="x", expires_at=START))


@pytest.mark.parametrize("name", ["", "   ", "n" * 65])
async def test_a_token_needs_a_sensible_name(world: World, name: str) -> None:
    with pytest.raises(InvalidTokenNameError):
        await world.identity.create_token(world.ada, CreateTokenCommand(name=name))


async def test_a_revoked_token_stops_working_at_once(world: World) -> None:
    grant = await world.identity.create_token(world.ada, CreateTokenCommand(name="laptop"))

    await world.identity.revoke_token(world.ada, grant.id)

    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(grant.token)
    assert (await world.identity.list_tokens(world.ada)).tokens == []
    with pytest.raises(UnknownTokenError):
        await world.identity.revoke_token(world.ada, grant.id)


async def test_nobody_revokes_or_sees_the_tokens_of_another_account(world: World) -> None:
    grant = await world.identity.create_token(world.ada, CreateTokenCommand(name="laptop"))
    stranger = AccountSummary(id="someone-else", username="eve", role="admin")

    assert (await world.identity.list_tokens(stranger)).tokens == []
    with pytest.raises(UnknownTokenError):
        await world.identity.revoke_token(stranger, grant.id)
    await world.identity.identify_token(grant.token)  # still works


async def test_two_tokens_never_share_a_secret(world: World) -> None:
    first = await world.identity.create_token(world.ada, CreateTokenCommand(name="a"))
    second = await world.identity.create_token(world.ada, CreateTokenCommand(name="a"))

    assert first.token != second.token
    assert first.id != second.id


async def test_a_password_reset_revokes_the_accounts_tokens(world: World) -> None:
    grant = await world.identity.create_token(world.ada, CreateTokenCommand(name="laptop"))

    await world.identity.reset_password(
        ResetPasswordCommand(username="ada", password=SecretStr("a brand new passphrase"))
    )

    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(grant.token)
    assert (await world.identity.list_tokens(world.ada)).tokens == []


async def test_creating_a_token_purges_the_expired_ones(world: World) -> None:
    soon = START + timedelta(days=1)
    await world.identity.create_token(world.ada, CreateTokenCommand(name="old", expires_at=soon))
    world.clock.current = START + timedelta(days=2)

    await world.identity.create_token(world.ada, CreateTokenCommand(name="new"))

    assert [t.name for t in (await world.identity.list_tokens(world.ada)).tokens] == ["new"]


async def test_an_account_holds_a_limited_number_of_tokens(world: World) -> None:
    for i in range(MAX_TOKENS_PER_ACCOUNT):
        await world.identity.create_token(world.ada, CreateTokenCommand(name=f"t{i}"))

    with pytest.raises(TooManyTokensError):
        await world.identity.create_token(world.ada, CreateTokenCommand(name="one too many"))


class LockedTokens(InMemoryTokenRepository):
    async def touch(self, token_hash: str, at: datetime) -> None:
        raise RuntimeError(token_hash, at)


async def test_a_failing_last_used_write_does_not_fail_the_authentication(
    caplog: pytest.LogCaptureFixture,
) -> None:
    identity = IdentityModule.build(
        repository=InMemoryAccountRepository(),
        sessions=InMemorySessionRepository(),
        tokens=LockedTokens(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=MovableClock(),
    )
    ada = await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr("correct horse battery staple"))
    )
    grant = await identity.create_token(ada, CreateTokenCommand(name="laptop"))

    account = await identity.identify_token(grant.token)

    assert account.username == "ada"
    assert "could not record API token use" in caplog.text
    assert grant.token not in caplog.text
