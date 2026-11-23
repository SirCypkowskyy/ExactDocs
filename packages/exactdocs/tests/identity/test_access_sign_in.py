"""Signing in by the Cloudflare Access identity: accounts, roles, service tokens and the session.

The verifier is a scripted fake that maps a token to claims (the real one is tested in
``test_cloudflare_access_verifier.py``), so each rule of the use case is proved on its own.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccessLog,
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemoryFailedSignInLog,
    InMemoryLibraryGrantRepository,
    InMemoryPreferencesRepository,
    InMemorySessionRepository,
    InMemorySignInAttemptRepository,
    InMemoryTokenRepository,
)
from exactdocs.identity.constants import (
    ACCESS_LINK_LIFETIME,
    ACCESS_LINK_REFRESH,
    ACCESS_PROVIDER,
)
from exactdocs.identity.dtos import AuthenticateQuery, CreateTokenCommand
from exactdocs.identity.errors import (
    AccessAssertionRefusedError,
    InvalidTokenError,
    NotSignedInError,
    ProviderUnavailableError,
)
from exactdocs.identity.models import (
    AccessClaims,
    AccessPolicy,
    Account,
    AccountId,
    Role,
    Username,
    access_username_candidates,
)
from exactdocs.identity.module import IdentityModule
from exactdocs_kernel import SealedTextUnreadableError

TEAM = "https://team.cloudflareaccess.com"
START = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


@dataclass(slots=True)
class Clock:
    at: datetime = START

    def now(self) -> datetime:
        return self.at


@dataclass(frozen=True, slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password}"


@dataclass(frozen=True, slots=True)
class FakeBox:
    def seal(self, plaintext: str) -> str:
        return plaintext

    def open(self, sealed: str) -> str:
        del sealed
        raise SealedTextUnreadableError


@dataclass(slots=True)
class FakeVerifier:
    """Satisfies ``AccessAssertionVerifier``: each known token names scripted claims."""

    tokens: dict[str, AccessClaims] = field(default_factory=dict)
    error: Exception | None = None

    async def verify(self, assertion: str) -> AccessClaims:
        if self.error is not None:
            raise self.error
        claims = self.tokens.get(assertion)
        if claims is None:
            raise AccessAssertionRefusedError
        return claims


@dataclass(slots=True)
class World:
    clock: Clock
    accounts: InMemoryAccountRepository
    links: InMemoryExternalIdentityRepository
    verifier: FakeVerifier
    identity: IdentityModule

    def person(self, token: str, email: str, subject: str | None = None) -> str:
        self.verifier.tokens[token] = AccessClaims(
            issuer=TEAM, subject=subject or f"sub-{email}", email=email
        )
        return token

    def service(self, token: str, client_id: str) -> str:
        self.verifier.tokens[token] = AccessClaims(issuer=TEAM, subject="", common_name=client_id)
        return token

    async def add_local(self, username: str, role: Role = Role.USER) -> Account:
        account = Account(
            id=AccountId(f"id-{username}"),
            username=Username(username),
            password_hash="fake$a long enough passphrase",
            role=role,
            created_at=START,
        )
        assert await self.accounts.add(account)
        return account


def build(*, configured: bool = True, auto_create_users: bool = True) -> World:
    clock = Clock()
    accounts = InMemoryAccountRepository()
    links = InMemoryExternalIdentityRepository(accounts=accounts)
    verifier = FakeVerifier()
    access_policy = (
        AccessPolicy(
            team_domain=f"{TEAM}/",
            admin_emails=frozenset({"Boss@Example.com"}),
            auto_create_users=auto_create_users,
            service_tokens=MappingProxyType({"abc.access": Username("ci-bot")}),
        )
        if configured
        else None
    )
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=links,
        library_grants=InMemoryLibraryGrantRepository(),
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=FakeBox(),
        clock=clock,
        access_verifier=verifier if configured else None,
        access_policy=access_policy,
    )
    return World(clock, accounts, links, verifier, identity)


@pytest.fixture
def world() -> World:
    return build()


async def test_a_first_visit_creates_an_account_linked_by_sub(world: World) -> None:
    token = world.person("t1", "alice@example.com", "s-1")

    account = await world.identity.identify_access_caller(token)

    assert (account.username, account.role) == ("alice@example.com", "user")
    link = await world.links.get(TEAM, "s-1")
    assert link is not None
    assert (link.account_id, link.provider) == (account.id, ACCESS_PROVIDER)
    stored = await world.accounts.get_by_id(AccountId(account.id))
    assert stored is not None
    assert stored.is_external  # no password: nobody signs in to it with one


async def test_the_same_sub_reaches_the_same_account_whatever_its_email(world: World) -> None:
    first = await world.identity.identify_access_caller(world.person("t1", "a@example.com", "s-1"))

    again = await world.identity.identify_access_caller(world.person("t2", "b@example.com", "s-1"))
    other = await world.identity.identify_access_caller(world.person("t3", "a@example.com", "s-2"))

    assert again.id == first.id
    assert other.id != first.id


async def test_an_existing_account_is_never_taken_over_by_name(world: World) -> None:
    local = await world.add_local("alice@example.com")

    account = await world.identity.identify_access_caller(
        world.person("t1", "alice@example.com", "s-1")
    )

    assert account.id != local.id
    assert account.username == "alice"


def test_usernames_fall_back_to_the_local_part_then_the_provider() -> None:
    names = [u.value for u in access_username_candidates("Alice@Example.com")]

    assert names == ["alice@example.com", "alice", "alice@cloudflare-access"]


async def test_admin_emails_decide_the_role_at_every_visit(world: World) -> None:
    boss = await world.identity.identify_access_caller(world.person("t1", "boss@example.COM"))
    assert boss.role == "admin"

    rebuilt = IdentityModule.build(
        repository=world.accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=world.links,
        library_grants=InMemoryLibraryGrantRepository(),
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=FakeBox(),
        clock=world.clock,
        access_verifier=world.verifier,
        access_policy=AccessPolicy(team_domain=TEAM),
    )

    again = await rebuilt.identify_access_caller("t1")

    assert (again.id, again.role) == (boss.id, "user")
    stored = await world.accounts.get_by_id(AccountId(boss.id))
    assert stored is not None
    assert stored.role is Role.USER


async def test_without_auto_create_users_nobody_new_gets_in() -> None:
    world = build(auto_create_users=False)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller(world.person("t1", "alice@example.com"))

    assert await world.accounts.list_all() == []


async def test_without_auto_create_users_people_linked_already_still_get_in() -> None:
    world = build()
    first = await world.identity.identify_access_caller(world.person("t1", "a@example.com", "s"))
    closed = IdentityModule.build(
        repository=world.accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=world.links,
        library_grants=InMemoryLibraryGrantRepository(),
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=FakeBox(),
        clock=world.clock,
        access_verifier=world.verifier,
        access_policy=AccessPolicy(team_domain=TEAM, auto_create_users=False),
    )

    assert (await closed.identify_access_caller("t1")).id == first.id


async def test_a_disabled_account_is_refused(world: World) -> None:
    account = await world.identity.identify_access_caller(world.person("t1", "a@example.com"))
    await world.accounts.set_disabled_at(AccountId(account.id), START)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller("t1")


async def test_a_mapped_service_token_acts_as_its_account(world: World) -> None:
    bot = await world.add_local("ci-bot")

    account = await world.identity.identify_access_caller(world.service("t1", "abc.access"))

    assert (account.id, account.username, account.role) == (bot.id, "ci-bot", "user")


@pytest.mark.parametrize("case", ["unmapped", "missing account", "disabled account"])
async def test_a_service_token_without_a_usable_account_signs_nobody_in(
    world: World, case: str
) -> None:
    client_id = "other.access" if case == "unmapped" else "abc.access"
    if case != "missing account":
        bot = await world.add_local("ci-bot")
        if case == "disabled account":
            await world.accounts.set_disabled_at(bot.id, START)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller(world.service("t1", client_id))

    assert await world.links.get(TEAM, "") is None  # a service token never creates anything


@pytest.mark.parametrize(
    "error",
    [AccessAssertionRefusedError(), ProviderUnavailableError()],
    ids=["refused", "unavailable"],
)
async def test_a_token_the_verifier_refuses_signs_nobody_in(world: World, error: Exception) -> None:
    world.verifier.error = error

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller("anything")


async def test_a_token_naming_neither_a_person_nor_a_service_signs_nobody_in(
    world: World,
) -> None:
    world.verifier.tokens["t1"] = AccessClaims(issuer=TEAM, subject="s-1")

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller("t1")


async def test_access_is_off_unless_configured() -> None:
    world = build(configured=False)
    world.person("t1", "a@example.com")

    with pytest.raises(NotSignedInError):
        await world.identity.identify_access_caller("t1")
    state = await world.identity.get_session_state(None, "t1")

    assert state.state == "setup_required"  # no account was created


async def test_a_visit_writes_the_link_only_once_in_a_while(world: World) -> None:
    await world.identity.identify_access_caller(world.person("t1", "a@example.com", "s"))
    created = await world.links.get(TEAM, "s")
    assert created is not None

    world.clock.at += ACCESS_LINK_REFRESH - timedelta(seconds=1)
    await world.identity.identify_access_caller("t1")
    assert await world.links.get(TEAM, "s") == created

    world.clock.at += timedelta(seconds=1)
    await world.identity.identify_access_caller("t1")
    refreshed = await world.links.get(TEAM, "s")
    assert refreshed is not None
    assert refreshed.access_until == world.clock.at + ACCESS_LINK_LIFETIME


async def test_the_api_tokens_of_an_access_account_last_while_it_keeps_visiting(
    world: World,
) -> None:
    account = await world.identity.identify_access_caller(world.person("t1", "a@example.com"))
    grant = await world.identity.create_token(account, CreateTokenCommand(name="cli"))
    secret = grant.token

    world.clock.at += ACCESS_LINK_LIFETIME - timedelta(seconds=1)
    assert (await world.identity.identify_token(secret)).id == account.id

    world.clock.at += timedelta(seconds=1)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(secret)

    await world.identity.identify_access_caller("t1")  # she comes back through Access
    assert (await world.identity.identify_token(secret)).id == account.id


async def test_the_session_state_says_access_signed_her_in(world: World) -> None:
    await world.add_local("ada", Role.ADMIN)

    state = await world.identity.get_session_state(None, world.person("t1", "a@example.com"))

    assert state.state == "signed_in"
    assert state.account is not None
    assert state.account.username == "a@example.com"
    assert state.source == "cloudflare_access"
    assert state.sign_out_url == f"{TEAM}/cdn-cgi/access/logout"


async def test_a_live_session_wins_over_the_access_token(world: World) -> None:
    await world.add_local("ada", Role.ADMIN)
    grant = await world.identity.sign_in(
        AuthenticateQuery.model_validate(
            {"username": "ada", "password": "a long enough passphrase"}
        )
    )

    state = await world.identity.get_session_state(
        grant.token.get_secret_value(), world.person("t1", "a@example.com")
    )

    assert state.account is not None
    assert (state.account.username, state.source, state.sign_out_url) == ("ada", "session", None)


async def test_a_refused_token_leaves_the_caller_signed_out(world: World) -> None:
    await world.add_local("ada", Role.ADMIN)

    state = await world.identity.get_session_state(None, "forged")

    assert (state.state, state.source) == ("signed_out", None)


def test_the_team_domain_must_be_an_https_origin() -> None:
    with pytest.raises(ValueError, match="team domain"):
        AccessPolicy(team_domain="http://team.cloudflareaccess.com")


def test_the_module_needs_both_the_verifier_and_the_policy() -> None:
    with pytest.raises(ValueError, match="both"):
        IdentityModule.build(
            repository=InMemoryAccountRepository(),
            sessions=InMemorySessionRepository(),
            tokens=InMemoryTokenRepository(),
            hasher=FakeHasher(),
            failures=InMemoryFailedSignInLog(),
            externals=InMemoryExternalIdentityRepository(accounts=InMemoryAccountRepository()),
            library_grants=InMemoryLibraryGrantRepository(),
            preferences=InMemoryPreferencesRepository(),
            access_log=InMemoryAccessLog(),
            attempts=InMemorySignInAttemptRepository(),
            box=FakeBox(),
            clock=Clock(),
            access_verifier=FakeVerifier(),
        )
