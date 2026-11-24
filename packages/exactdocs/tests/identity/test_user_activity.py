"""Operators see each account's last activity, sign-in provider and token count, and every token.

Last activity is kept to the hour and written at most once per hour per account; the token count
is one query for every account (#515).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import SecretStr, ValidationError

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemoryFailedSignInLog,
    InMemorySessionRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.dtos import (
    AccountSummary,
    AllTokensQuery,
    AuthenticateQuery,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    FinishExternalSignInCommand,
    StartExternalSignInCommand,
    UserListQuery,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ApiToken,
    ExternalClaims,
    ExternalGrant,
    SignInPolicy,
    Username,
    activity_hour,
)
from exactdocs.identity.module import IdentityModule
from exactdocs_kernel import InvalidSortError
from identity_stand_ins import no_external_sign_in

HORSE = "correct horse battery staple"
PHRASE = "a long enough passphrase"
START = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
ISSUER = "https://accounts.google.example"


@dataclass(slots=True)
class Clock:
    at: datetime = START

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


@dataclass(slots=True)
class CountingAccounts:
    """The in-memory accounts, counting the activity writes."""

    inner: InMemoryAccountRepository
    activity_writes: list[datetime] = field(default_factory=list)

    async def add_first(self, account: Account) -> bool:
        return await self.inner.add_first(account)

    async def add(self, account: Account) -> bool:
        return await self.inner.add(account)

    async def list_all(self) -> list[Account]:
        return await self.inner.list_all()

    async def set_disabled_at(self, account_id: AccountId, disabled_at: datetime | None) -> bool:
        return await self.inner.set_disabled_at(account_id, disabled_at)

    async def get(self, username: Username) -> Account | None:
        return await self.inner.get(username)

    async def get_by_id(self, account_id: AccountId) -> Account | None:
        return await self.inner.get_by_id(account_id)

    async def set_password_hash(self, account_id: AccountId, password_hash: str) -> None:
        await self.inner.set_password_hash(account_id, password_hash)

    async def any_exists(self) -> bool:
        return await self.inner.any_exists()

    async def record_activity(self, account_id: AccountId, hour: datetime) -> None:
        self.activity_writes.append(hour)
        await self.inner.record_activity(account_id, hour)


@dataclass(slots=True)
class OneQueryTokens:
    """The in-memory tokens, refusing a per-account read (the users list must not do N+1)."""

    inner: InMemoryTokenRepository = field(default_factory=InMemoryTokenRepository)

    async def add(self, token: ApiToken) -> None:
        await self.inner.add(token)

    async def get(self, token_hash: str) -> ApiToken | None:
        return await self.inner.get(token_hash)

    async def list_for_account(self, account_id: AccountId) -> list[ApiToken]:
        raise AssertionError(account_id[:0] + "the users list reads the tokens in one query")

    async def list_all(self) -> list[ApiToken]:
        return await self.inner.list_all()

    async def count_by_account(self, now: datetime) -> Mapping[AccountId, int]:
        return await self.inner.count_by_account(now)

    async def touch(self, token_hash: str, at: datetime) -> None:
        await self.inner.touch(token_hash, at)

    async def delete(self, account_id: AccountId, token_id: str) -> bool:
        return await self.inner.delete(account_id, token_id)

    async def delete_for_account(self, account_id: AccountId) -> None:
        await self.inner.delete_for_account(account_id)

    async def delete_expired(self, now: datetime) -> None:
        await self.inner.delete_expired(now)


@dataclass(slots=True)
class FakeProvider:
    """Trusts any code: it returns the claims of ``next_subject``."""

    next_subject: str = ""

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        return f"https://idp.example/authorize?state={state}{nonce[:0]}{code_verifier[:0]}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        claims = ExternalClaims(
            issuer=ISSUER,
            subject=self.next_subject,
            username=self.next_subject + code[:0] + code_verifier[:0] + nonce[:0],
            email=None,
            groups=frozenset(),
        )
        return ExternalGrant(claims=claims)

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        raise AssertionError(id_token[:0] + "no ID token in these tests")

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        raise AssertionError(refresh_token[:0] + subject[:0] + "no refresh in these tests")


@dataclass(slots=True)
class World:
    clock: Clock
    accounts: CountingAccounts
    tokens: InMemoryTokenRepository | OneQueryTokens
    provider: FakeProvider
    identity: IdentityModule


def build(tokens: InMemoryTokenRepository | OneQueryTokens | None = None) -> World:
    clock = Clock()
    stored = InMemoryAccountRepository()
    accounts = CountingAccounts(stored)
    tokens = tokens or InMemoryTokenRepository()
    provider = FakeProvider()
    policy = SignInPolicy(
        name="google",
        display_name="Google",
        allow_any_user=True,
        revalidate_every=timedelta(minutes=60),
        grace=timedelta(days=1),
    )
    stand_ins = no_external_sign_in()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=tokens,
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        clock=clock,
        externals=InMemoryExternalIdentityRepository(accounts=stored),
        library_grants=stand_ins["library_grants"],
        access_log=stand_ins["access_log"],
        attempts=stand_ins["attempts"],
        box=stand_ins["box"],
        providers={"google": provider},
        policies={"google": policy},
    )
    return World(clock, accounts, tokens, provider, identity)


@pytest.fixture
async def world() -> World:
    world = build()
    await world.identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    return world


async def sign_in(world: World, username: str, password: str = PHRASE) -> str:
    query = AuthenticateQuery(username=username, password=SecretStr(password))
    return (await world.identity.sign_in(query)).token.get_secret_value()


async def sign_in_through_google(world: World, subject: str) -> AccountSummary:
    world.provider.next_subject = subject
    begun = await world.identity.start_external_sign_in(
        StartExternalSignInCommand(provider="google", return_to="/")
    )
    state = begun.redirect_url.rsplit("state=", 1)[1]
    result = await world.identity.finish_external_sign_in(
        FinishExternalSignInCommand(
            provider="google", binding=begun.binding, state=state, code="code"
        )
    )
    return result.session.account


async def create(world: World, username: str) -> None:
    command = CreateUserCommand(username=username, password=SecretStr(PHRASE))
    await world.identity.create_user(command)


async def users(world: World, **query: object) -> dict[str, dict[str, object]]:
    listed = await world.identity.list_users(UserListQuery.model_validate(query))
    return {u.username: u.model_dump() for u in listed.users}


# ---------------------------------------------------------------- last activity


def test_activity_is_kept_to_the_hour_in_utc() -> None:
    moment = datetime(2026, 11, 13, 10, 40, 12, 345, tzinfo=UTC)

    in_warsaw = moment.astimezone(timezone(timedelta(hours=1)))

    assert activity_hour(moment) == datetime(2026, 11, 13, 10, tzinfo=UTC)
    assert activity_hour(in_warsaw) == activity_hour(moment)
    assert activity_hour(in_warsaw).tzinfo is UTC


async def test_a_new_account_was_never_active(world: World) -> None:
    await create(world, "bob")

    assert (await users(world))["bob"]["last_active_at"] is None


async def test_a_sign_in_is_activity_shown_to_the_hour(world: World) -> None:
    await create(world, "bob")
    world.clock.at = START + timedelta(minutes=37, seconds=5)

    await sign_in(world, "bob")

    assert (await users(world))["bob"]["last_active_at"] == START


async def test_requests_write_the_activity_once_per_hour(world: World) -> None:
    await create(world, "bob")
    session = await sign_in(world, "bob")
    token = (
        await world.identity.create_token(
            await world.identity.identify_caller(session), CreateTokenCommand(name="ci")
        )
    ).token
    written = len(world.accounts.activity_writes)

    for minutes in range(0, 60, 5):
        world.clock.at = START + timedelta(minutes=minutes)
        await world.identity.identify_caller(session)
        await world.identity.identify_token(token)

    assert len(world.accounts.activity_writes) == written  # nothing more within the hour
    world.clock.at = START + timedelta(hours=1, minutes=1)
    await world.identity.identify_caller(session)
    await world.identity.identify_token(token)
    assert world.accounts.activity_writes[written:] == [START + timedelta(hours=1)]


async def test_an_api_token_alone_is_activity(world: World) -> None:
    await create(world, "bob")
    bob = await world.identity.authenticate(
        AuthenticateQuery(username="bob", password=SecretStr(PHRASE))
    )
    token = (await world.identity.create_token(bob, CreateTokenCommand(name="ci"))).token
    world.clock.at = START + timedelta(days=3, hours=4, minutes=50)

    await world.identity.identify_token(token)

    assert (await users(world))["bob"]["last_active_at"] == START + timedelta(days=3, hours=4)


async def test_activity_never_moves_back(world: World) -> None:
    await create(world, "bob")
    world.clock.at = START + timedelta(hours=5)
    await sign_in(world, "bob")
    bob = await world.accounts.get(Username("bob"))
    assert bob is not None

    await world.accounts.record_activity(bob.id, START)

    assert (await users(world))["bob"]["last_active_at"] == START + timedelta(hours=5)


async def test_an_external_sign_in_is_activity(world: World) -> None:
    world.clock.at = START + timedelta(hours=2, minutes=59)

    await sign_in_through_google(world, "alice")

    assert (await users(world))["alice"]["last_active_at"] == START + timedelta(hours=2)


async def test_users_sort_by_last_activity_never_active_first(world: World) -> None:
    await create(world, "bob")
    await create(world, "carol")
    world.clock.at = START + timedelta(hours=3)
    await sign_in(world, "bob")
    world.clock.at = START + timedelta(hours=1)
    await sign_in(world, "ada", HORSE)

    found = await users(world, sort="-last_active_at")

    assert list(found) == ["bob", "ada", "carol"]


# ---------------------------------------------------------------- provider


async def test_the_provider_filter_names_password_for_local_accounts(world: World) -> None:
    await create(world, "bob")
    await sign_in_through_google(world, "alice")

    assert list(await users(world, provider=["google"])) == ["alice"]
    assert list(await users(world, provider=["password"])) == ["ada", "bob"]
    assert list(await users(world, provider=["password", "google"])) == ["ada", "bob", "alice"]
    assert list(await users(world, provider=["github"])) == []
    assert (await users(world, provider=["google"]))["alice"]["provider"] == "google"


async def test_the_provider_filter_counts_in_the_total(world: World) -> None:
    await create(world, "bob")
    await sign_in_through_google(world, "alice")

    page = await world.identity.list_users(UserListQuery(provider=["password"], limit=1))

    assert ([u.username for u in page.users], page.total) == (["ada"], 2)


# ---------------------------------------------------------------- token count


async def test_each_user_carries_the_count_of_their_live_tokens() -> None:
    world = build(OneQueryTokens())
    await world.identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
    )
    await create(world, "bob")
    bob = await world.identity.authenticate(
        AuthenticateQuery(username="bob", password=SecretStr(PHRASE))
    )
    for name in ("one", "two"):
        await world.tokens.add(token(name, AccountId(bob.id)))
    await world.tokens.add(token("old", AccountId(bob.id), expires_at=START - timedelta(days=1)))

    found = await users(world, sort="-token_count")

    assert [(name, u["token_count"]) for name, u in found.items()] == [("bob", 2), ("ada", 0)]


# ---------------------------------------------------------------- every token


def token(
    name: str,
    owner: AccountId,
    *,
    created_at: datetime = START,
    expires_at: datetime | None = None,
    last_used_at: datetime | None = None,
) -> ApiToken:
    return ApiToken(
        id=f"id-{name}",
        account_id=owner,
        name=name,
        token_hash=f"hash-{name}",
        prefix="exd_abcd",
        created_at=created_at,
        expires_at=expires_at,
        last_used_at=last_used_at,
    )


async def tokens_world(world: World) -> dict[str, Account]:
    await create(world, "bob")
    found = {name: await world.accounts.get(Username(name)) for name in ("ada", "bob")}
    owners = {name: a for name, a in found.items() if a is not None}
    used = START - timedelta(hours=1)
    for name, owner, minute, expires, last in [
        ("ada-laptop", "ada", 1, None, used),
        ("ada-ci", "ada", 2, START - timedelta(minutes=1), None),
        ("bob-laptop", "bob", 3, START + timedelta(days=1), None),
        ("bob-ci", "bob", 4, None, used),
    ]:
        await world.tokens.add(
            token(
                name,
                owners[owner].id,
                created_at=START - timedelta(days=1) + timedelta(minutes=minute),
                expires_at=expires,
                last_used_at=last,
            )
        )
    return owners


async def all_tokens(world: World, **query: object) -> list[str]:
    listed = await world.identity.list_all_tokens(AllTokensQuery.model_validate(query))
    return [t.name for t in listed.tokens]


async def test_every_token_is_listed_newest_first_with_its_owner(world: World) -> None:
    owners = await tokens_world(world)

    listed = await world.identity.list_all_tokens(AllTokensQuery())

    assert [(t.name, t.owner, t.owner_id) for t in listed.tokens] == [
        ("bob-ci", "bob", owners["bob"].id),
        ("bob-laptop", "bob", owners["bob"].id),
        ("ada-ci", "ada", owners["ada"].id),
        ("ada-laptop", "ada", owners["ada"].id),
    ]
    assert listed.total == 4
    dumped = listed.model_dump_json()
    assert "hash-" not in dumped
    assert "token_hash" not in dumped


async def test_every_token_filters_by_owner_expiry_and_use(world: World) -> None:
    owners = await tokens_world(world)

    assert await all_tokens(world, owner_id=owners["ada"].id) == ["ada-ci", "ada-laptop"]
    assert await all_tokens(world, expired=True) == ["ada-ci"]
    assert await all_tokens(world, expired=False) == ["bob-ci", "bob-laptop", "ada-laptop"]
    assert await all_tokens(world, unused=True) == ["bob-laptop", "ada-ci"]
    assert await all_tokens(world, unused=False) == ["bob-ci", "ada-laptop"]
    assert await all_tokens(world, q="LAPTOP", unused=False) == ["ada-laptop"]
    assert await all_tokens(world, owner_id="nobody") == []


async def test_every_token_sorts_by_owner_and_pages(world: World) -> None:
    await tokens_world(world)
    query = AllTokensQuery(sort="-owner", limit=3)

    first = await world.identity.list_all_tokens(query)
    second = await world.identity.list_all_tokens(
        AllTokensQuery(sort="-owner", limit=3, cursor=first.next_cursor)
    )
    jumped = await world.identity.list_all_tokens(AllTokensQuery(sort="-owner", offset=3))

    assert [t.owner for t in first.tokens] == ["bob", "bob", "ada"]
    assert [t.owner for t in second.tokens] == ["ada"]
    assert [t.name for t in jumped.tokens] == [t.name for t in second.tokens]
    assert (first.total, second.next_cursor) == (4, None)


async def test_an_unknown_sort_of_every_token_is_refused_by_name(world: World) -> None:
    with pytest.raises(InvalidSortError, match="token_hash"):
        await world.identity.list_all_tokens(AllTokensQuery(sort="token_hash"))


def test_every_token_has_no_other_filter() -> None:
    with pytest.raises(ValidationError, match="secret"):
        AllTokensQuery.model_validate({"secret": "x"})
