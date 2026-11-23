"""External sign-in use cases: the flow's checks, accounts, groups, roles and revalidation.

The provider is a scripted fake that trusts any code (the OIDC adapter's own checks are tested in
``test_oidc_provider.py``), so each check of the flow is proved on its own here.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import pytest
from pydantic import SecretStr

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
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
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccessLog,
    SqliteAccountRepository,
    SqliteExternalIdentityRepository,
    SqliteLibraryGrantRepository,
    SqlitePreferencesRepository,
    SqliteSessionRepository,
    SqliteSignInAttemptRepository,
    SqliteTokenRepository,
)
from exactdocs.identity.constants import SIGN_IN_ATTEMPT_LIFETIME
from exactdocs.identity.dtos import (
    AccountSummary,
    AuthenticateQuery,
    CreateTokenCommand,
    FinishExternalSignInCommand,
    ResetPasswordCommand,
    SetUserDisabledCommand,
    StartExternalSignInCommand,
    UserListQuery,
)
from exactdocs.identity.errors import (
    AccountDisabledError,
    ExternalAccountError,
    ExternalSignInFailedError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotAllowedError,
    NotSignedInError,
    ProviderAccessRevokedError,
    ProviderUnavailableError,
    SignInCancelledError,
    UnknownSignInProviderError,
    UsernameUnavailableError,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ExternalClaims,
    ExternalGrant,
    ExternalIdentity,
    Role,
    SignInPolicy,
    Username,
    safe_return_to,
    username_candidates,
)
from exactdocs.identity.module import IdentityModule
from exactdocs.identity.ports import AccountRepository, ExternalIdentityRepository
from exactdocs.identity.ports.driven import LinkOutcome
from exactdocs_kernel import SealedTextUnreadableError

ISSUER = "https://idp.example.com"
START = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
HORSE = "correct horse battery staple"


@dataclass(slots=True)
class Clock:
    at: datetime = START

    def now(self) -> datetime:
        return self.at


@dataclass(slots=True)
class FakeHasher:
    hashed: list[str] = field(default_factory=list)

    async def hash(self, password: str) -> str:
        self.hashed.append(password)
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


@dataclass(frozen=True, slots=True)
class FakeBox:
    def seal(self, plaintext: str) -> str:
        return f"sealed:{plaintext[::-1]}"

    def open(self, sealed: str) -> str:
        if not sealed.startswith("sealed:"):
            raise SealedTextUnreadableError
        return sealed.removeprefix("sealed:")[::-1]


@dataclass(slots=True)
class FakeProvider:
    """Trusts any code: it returns the claims of whoever the test scripted."""

    people: dict[str, ExternalClaims] = field(default_factory=dict)
    next_subject: str | None = None
    refresh_token: str | None = "refresh-1"
    refresh_error: Exception | None = None
    during_refresh: Callable[[], Awaitable[None]] | None = None
    """Runs once inside the next refresh, before it answers (what happens meanwhile)."""
    started: list[dict[str, str]] = field(default_factory=list)
    exchanged: list[dict[str, str]] = field(default_factory=list)
    id_tokens: dict[str, ExternalClaims] = field(default_factory=dict)
    """ID tokens the provider issued, by token (what MCP's OAuth hands over)."""

    def add(self, subject: str, username: str | None, *groups: str, email: str | None = None):
        self.people[subject] = ExternalClaims(
            issuer=ISSUER,
            subject=subject,
            username=username,
            email=email,
            groups=frozenset(groups),
        )
        self.next_subject = subject

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        self.started.append({"state": state, "nonce": nonce, "code_verifier": code_verifier})
        return f"{ISSUER}/authorize?state={state}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> ExternalGrant:
        self.exchanged.append({"code": code, "code_verifier": code_verifier, "nonce": nonce})
        assert self.next_subject is not None
        return ExternalGrant(
            claims=self.people[self.next_subject], refresh_token=self.refresh_token
        )

    async def verify_id_token(self, id_token: str) -> ExternalClaims:
        if (claims := self.id_tokens.get(id_token)) is None:
            raise ExternalSignInFailedError
        return claims

    async def refresh(self, refresh_token: str, *, subject: str) -> ExternalGrant:
        if (meanwhile := self.during_refresh) is not None:
            self.during_refresh = None
            await meanwhile()
        if self.refresh_error is not None:
            raise self.refresh_error
        return ExternalGrant(claims=self.people[subject], refresh_token=f"{refresh_token}+")


class SignsIn(Protocol):
    provider: FakeProvider
    identity: IdentityModule
    last_session: str


@dataclass(slots=True)
class World:
    clock: Clock
    accounts: InMemoryAccountRepository
    sessions: InMemorySessionRepository
    tokens: InMemoryTokenRepository
    externals: InMemoryExternalIdentityRepository
    attempts: InMemorySignInAttemptRepository
    provider: FakeProvider
    hasher: FakeHasher
    identity: IdentityModule
    last_session: str = ""


def policy(**overrides: Any) -> SignInPolicy:
    values: dict[str, Any] = {
        "name": "corp",
        "display_name": "Corp SSO",
        "allow_any_user": True,
        "admin_groups": frozenset({"exactdocs-admins"}),
        "revalidate_every": timedelta(minutes=60),
        "grace": timedelta(minutes=1440),
    }
    return SignInPolicy(**{**values, **overrides})


def build(
    *policies: SignInPolicy,
    externals: Callable[[InMemoryExternalIdentityRepository], Any] | None = None,
) -> World:
    clock = Clock()
    accounts = InMemoryAccountRepository()
    sessions = InMemorySessionRepository()
    tokens = InMemoryTokenRepository()
    links = InMemoryExternalIdentityRepository(accounts=accounts)
    attempts = InMemorySignInAttemptRepository()
    provider = FakeProvider()
    hasher = FakeHasher()
    configured = {p.name: p for p in policies or [policy()]}
    identity = IdentityModule.build(
        repository=accounts,
        sessions=sessions,
        tokens=tokens,
        hasher=hasher,
        failures=InMemoryFailedSignInLog(),
        externals=externals(links) if externals else links,
        library_grants=InMemoryLibraryGrantRepository(),
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=attempts,
        box=FakeBox(),
        clock=clock,
        providers=dict.fromkeys(configured, provider),
        policies=configured,
    )
    return World(clock, accounts, sessions, tokens, links, attempts, provider, hasher, identity)


@pytest.fixture
def world() -> World:
    return build()


async def start(world: SignsIn, return_to: str | None = "/libraries") -> tuple[str, str]:
    begun = await world.identity.start_external_sign_in(
        StartExternalSignInCommand(provider="corp", return_to=return_to)
    )
    return begun.binding.get_secret_value(), world.provider.started[-1]["state"]


async def sign_in(world: SignsIn, subject: str, **command: Any) -> AccountSummary:
    world.provider.next_subject = subject
    binding, state = await start(world)
    result = await world.identity.finish_external_sign_in(
        FinishExternalSignInCommand(
            provider="corp", binding=SecretStr(binding), state=state, code="code", **command
        )
    )
    world.last_session = result.session.token.get_secret_value()
    return result.session.account


async def callback(world: World, **fields: Any) -> Any:
    return await world.identity.finish_external_sign_in(
        FinishExternalSignInCommand(provider="corp", **fields)
    )


# ---------------------------------------------------------------- the flow's checks


async def test_the_start_sends_only_the_challenge_side_and_keeps_the_secrets(world: World) -> None:
    begun = await world.identity.start_external_sign_in(
        StartExternalSignInCommand(provider="corp", return_to="/libraries")
    )

    started = world.provider.started[0]
    assert begun.redirect_url == f"{ISSUER}/authorize?state={started['state']}"
    assert begun.max_age == int(SIGN_IN_ATTEMPT_LIFETIME.total_seconds())
    [attempt] = world.attempts.attempts.values()
    assert attempt.binding_hash != begun.binding.get_secret_value()  # only its hash is kept
    assert attempt.state == started["state"]
    assert attempt.nonce == started["nonce"]
    assert attempt.code_verifier == started["code_verifier"]
    assert len(attempt.code_verifier) >= 43
    assert len({begun.binding.get_secret_value(), attempt.state, attempt.nonce}) == 3


async def test_an_unknown_provider_is_refused(world: World) -> None:
    with pytest.raises(UnknownSignInProviderError):
        await world.identity.start_external_sign_in(StartExternalSignInCommand(provider="nope"))
    with pytest.raises(UnknownSignInProviderError):
        await world.identity.finish_external_sign_in(
            FinishExternalSignInCommand(provider="nope", state="s", code="c")
        )


async def test_a_callback_without_the_browser_binding_is_refused(world: World) -> None:
    world.provider.add("u-1", "alice")
    _, state = await start(world)

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, binding=None, state=state, code="code")
    assert world.provider.exchanged == []  # the code is never even exchanged


async def test_a_callback_with_another_attempts_state_is_refused(world: World) -> None:
    world.provider.add("u-1", "alice")
    _, attackers_state = await start(world)  # another browser's attempt
    binding, _ = await start(world)

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, binding=SecretStr(binding), state=attackers_state, code="code")
    assert world.provider.exchanged == []


async def test_a_callback_works_once(world: World) -> None:
    world.provider.add("u-1", "alice")
    binding, state = await start(world)
    fields = {"binding": SecretStr(binding), "state": state, "code": "code"}
    await callback(world, **fields)

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, **fields)
    assert len(world.provider.exchanged) == 1


async def test_a_wrong_state_still_uses_the_attempt_up(world: World) -> None:
    world.provider.add("u-1", "alice")
    binding, state = await start(world)

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, binding=SecretStr(binding), state="guess", code="code")
    with pytest.raises(ExternalSignInFailedError):  # no second guess on the same attempt
        await callback(world, binding=SecretStr(binding), state=state, code="code")


async def test_a_callback_after_the_attempt_expired_is_refused(world: World) -> None:
    world.provider.add("u-1", "alice")
    binding, state = await start(world)
    world.clock.at += SIGN_IN_ATTEMPT_LIFETIME

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, binding=SecretStr(binding), state=state, code="code")


async def test_a_callback_to_another_provider_is_refused() -> None:
    world = build(policy(), policy(name="other"))
    world.provider.add("u-1", "alice")
    binding, state = await start(world)  # started with corp

    with pytest.raises(ExternalSignInFailedError):
        await world.identity.finish_external_sign_in(
            FinishExternalSignInCommand(
                provider="other", binding=SecretStr(binding), state=state, code="code"
            )
        )


async def test_the_providers_error_is_a_cancelled_sign_in(world: World) -> None:
    binding, state = await start(world)

    with pytest.raises(SignInCancelledError):
        await callback(world, binding=SecretStr(binding), state=state, error="access_denied")


async def test_a_callback_without_a_code_is_refused(world: World) -> None:
    binding, state = await start(world)

    with pytest.raises(ExternalSignInFailedError):
        await callback(world, binding=SecretStr(binding), state=state)


async def test_expired_attempts_are_pruned_when_another_starts(world: World) -> None:
    await start(world)
    world.clock.at += SIGN_IN_ATTEMPT_LIFETIME + timedelta(seconds=1)
    await start(world)

    assert len(world.attempts.attempts) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/libraries/vuejs/core?v=1", "/libraries/vuejs/core?v=1"),
        (None, "/"),
        ("", "/"),
        ("https://evil.example/", "/"),
        ("//evil.example/x", "/"),
        ("/\\evil.example", "/"),
        ("\\\\evil.example", "/"),
        ("/ok\nSet-Cookie: x", "/"),
        ("javascript:alert(1)", "/"),
        ("/sign-in", "/"),
        ("/setup", "/"),
        ("/" + "a" * 5000, "/"),
    ],
)
def test_return_to_is_a_path_on_this_server_only(raw: str | None, expected: str) -> None:
    assert safe_return_to(raw) == expected


# ---------------------------------------------------------------- accounts


async def test_the_first_sign_in_creates_a_user_without_a_password(world: World) -> None:
    world.provider.add("u-123", "alice", "payments")
    account = await sign_in(world, "u-123")

    assert account.username == "alice"
    assert account.role == "user"
    stored = await world.accounts.get(Username("alice"))
    assert stored is not None
    assert stored.is_external
    link = await world.externals.get(ISSUER, "u-123")
    assert link is not None
    assert link.account_id == stored.id
    assert link.provider == "corp"
    assert link.sealed_tokens == FakeBox().seal("refresh-1")
    assert link.access_until == START + timedelta(minutes=60 + 1440)
    assert world.externals.groups[stored.id] == frozenset({"payments"})


async def test_a_member_of_an_admin_group_is_an_admin_from_the_first_sign_in(world: World) -> None:
    world.provider.add("u-1", "alice", "exactdocs-admins")

    assert (await sign_in(world, "u-1")).role == "admin"


async def test_the_same_subject_reaches_the_same_account_whatever_it_is_called(
    world: World,
) -> None:
    world.provider.add("u-123", "alice", email="alice@example.com")
    first = await sign_in(world, "u-123")
    world.provider.add("u-123", "alice2", email="a2@example.com")

    again = await sign_in(world, "u-123")

    assert again.id == first.id
    assert again.username == "alice"  # set at creation only


async def test_another_subject_with_the_same_email_gets_its_own_account(world: World) -> None:
    world.provider.add("u-1", None, email="alice@example.com")
    first = await sign_in(world, "u-1")
    world.provider.add("u-2", None, email="alice@example.com")

    second = await sign_in(world, "u-2")

    assert (first.username, second.username) == ("alice", "alice@corp")
    assert first.id != second.id


async def test_a_local_account_is_never_taken_over(world: World) -> None:
    local = Account(
        id=AccountId("local-bob"),
        username=Username("bob"),
        password_hash="fake$x",
        role=Role.ADMIN,
        created_at=START,
    )
    await world.accounts.add(local)
    world.provider.add("u-456", "bob")

    account = await sign_in(world, "u-456")

    assert account.username == "bob@corp"
    assert await world.accounts.get(Username("bob")) == local


async def test_when_the_fallback_is_taken_too_the_sign_in_is_refused(world: World) -> None:
    for name in ("bob", "bob@corp"):
        await world.accounts.add(
            Account(
                id=AccountId(name),
                username=Username(name),
                password_hash="fake$x",
                role=Role.USER,
                created_at=START,
            )
        )
    world.provider.add("u-456", "bob")

    with pytest.raises(UsernameUnavailableError, match="'bob' and 'bob@corp' are taken"):
        await sign_in(world, "u-456")
    assert await world.externals.get(ISSUER, "u-456") is None
    assert world.sessions.sessions == {}


async def test_a_provider_without_a_username_or_email_is_refused(world: World) -> None:
    world.provider.add("u-1", None)

    with pytest.raises(UsernameUnavailableError, match="no usable username"):
        await sign_in(world, "u-1")


def test_username_candidates_skip_reserved_and_invalid_names() -> None:
    claims = ExternalClaims(issuer=ISSUER, subject="s", username="Ada Lovelace")
    assert username_candidates(claims, "corp") == []
    claims = ExternalClaims(issuer=ISSUER, subject="s", username="x@address:1")
    assert username_candidates(claims, "corp") == []
    claims = ExternalClaims(issuer=ISSUER, subject="s", username="Ada")
    assert username_candidates(claims, "corp") == [Username("ada"), Username("ada@corp")]


async def test_two_concurrent_first_sign_ins_end_up_on_one_account() -> None:
    """The second sign-in's insert finds the identity linked meanwhile: it uses that account."""

    @dataclass(slots=True)
    class Racing:
        inner: InMemoryExternalIdentityRepository
        raced: bool = False

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        async def get(self, issuer: str, subject: str) -> ExternalIdentity | None:
            return await self.inner.get(issuer, subject) if self.raced else None

        async def create_linked_account(
            self, account: Account, identity: ExternalIdentity, groups: frozenset[str]
        ) -> LinkOutcome:
            if not self.raced:  # the other sign-in wins first
                self.raced = True
                winner = Account(
                    id=AccountId("winner"),
                    username=Username("alice"),
                    password_hash=None,
                    role=Role.USER,
                    created_at=START,
                )
                won = replace(identity, account_id=winner.id)
                assert await self.inner.create_linked_account(winner, won, groups) == "created"
            return await self.inner.create_linked_account(account, identity, groups)

    world = build(externals=Racing)
    world.provider.add("u-1", "alice")

    account = await sign_in(world, "u-1")

    assert account.id == "winner"
    assert [a.username.value for a in await world.accounts.list_all()] == ["alice"]


# ---------------------------------------------------------------- admission, roles, groups


async def test_someone_in_no_allowed_group_is_refused() -> None:
    world = build(policy(allow_any_user=False, allowed_groups=frozenset({"docs-readers"})))
    world.provider.add("u-1", "alice", "payments", "exactdocs-admins")  # an admin group alone

    with pytest.raises(NotAllowedError):
        await sign_in(world, "u-1")
    assert await world.accounts.list_all() == []


async def test_a_refused_sign_in_ends_the_access_the_account_had() -> None:
    world = build(policy(allow_any_user=False, allowed_groups=frozenset({"docs-readers"})))
    world.provider.add("u-1", "alice", "docs-readers")
    account = await sign_in(world, "u-1")
    session = world.last_session
    world.provider.add("u-1", "alice")

    with pytest.raises(NotAllowedError):
        await sign_in(world, "u-1")

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    assert link.access_until == START
    assert link.sealed_tokens is None
    assert AccountId(account.id) not in world.externals.groups


async def test_groups_and_role_follow_the_provider_at_every_sign_in(world: World) -> None:
    world.provider.add("u-1", "alice", "payments", "exactdocs-admins")
    first = await sign_in(world, "u-1")
    world.provider.add("u-1", "alice", "ops")

    again = await sign_in(world, "u-1")

    assert (first.role, again.role) == ("admin", "user")
    assert world.externals.groups[AccountId(first.id)] == frozenset({"ops"})


async def test_the_group_prefix_names_the_stored_groups() -> None:
    world = build(policy(group_prefix="corp:"))
    world.provider.add("u-1", "alice", "payments")
    account = await sign_in(world, "u-1")

    assert world.externals.groups[AccountId(account.id)] == frozenset({"corp:payments"})


def test_a_policy_must_admit_someone_on_purpose() -> None:
    with pytest.raises(ValueError, match="allowed_groups or allow_any_user"):
        policy(allow_any_user=False)
    with pytest.raises(ValueError, match="must match"):
        policy(name="Corp")


async def test_demoting_the_last_admin_is_not_blocked(world: World) -> None:
    world.provider.add("u-1", "alice", "exactdocs-admins")
    await sign_in(world, "u-1")  # the only admin of the instance
    world.provider.add("u-1", "alice")

    assert (await sign_in(world, "u-1")).role == "user"


async def test_a_disabled_account_stays_disabled(world: World) -> None:
    world.provider.add("u-1", "alice", "payments")
    account = await sign_in(world, "u-1")
    await world.identity.set_user_disabled(SetUserDisabledCommand(id=account.id, disabled=True))

    with pytest.raises(AccountDisabledError):
        await sign_in(world, "u-1")
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    assert link.sealed_tokens is None
    assert world.sessions.sessions == {}


# ---------------------------------------------------------------- no password


async def test_password_sign_in_treats_an_external_account_as_unknown(world: World) -> None:
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")
    world.hasher.hashed.clear()

    with pytest.raises(InvalidCredentialsError):
        await world.identity.authenticate(
            AuthenticateQuery(username="alice", password=SecretStr(HORSE))
        )
    assert world.hasher.hashed == [HORSE]  # one dummy hash, as for an unknown user


async def test_an_external_account_has_no_password_to_reset(world: World) -> None:
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")

    with pytest.raises(ExternalAccountError):
        await world.identity.reset_password(
            ResetPasswordCommand(username="alice", password=SecretStr(HORSE))
        )


async def test_users_show_their_provider_and_groups(world: World) -> None:
    world.provider.add("u-1", "alice", "b", "a")
    await sign_in(world, "u-1")

    [user] = (await world.identity.list_users(UserListQuery())).users

    assert (user.provider, user.groups) == ("corp", ["a", "b"])


async def test_the_session_state_offers_the_providers(world: World) -> None:
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")

    state = await world.identity.get_session_state(None)

    assert state.state == "signed_out"
    assert [(p.name, p.display_name) for p in state.providers] == [("corp", "Corp SSO")]


# ---------------------------------------------------------------- access_until


async def access_with_token(world: World, subject: str) -> tuple[str, str]:
    account = await sign_in(world, subject)
    grant = await world.identity.create_token(account, CreateTokenCommand(name="laptop"))
    return world.last_session, grant.token


async def test_sessions_and_tokens_end_with_access_even_without_a_revalidation(
    world: World,
) -> None:
    world.provider.refresh_token = None
    world.provider.add("u-1", "erin")
    session, token = await access_with_token(world, "u-1")
    world.clock.at += timedelta(minutes=1440) - timedelta(seconds=1)
    await world.identity.identify_caller(session)
    await world.identity.identify_token(token)

    world.clock.at += timedelta(seconds=1)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)
    assert world.sessions.sessions == {}  # the session row went too


async def test_a_new_sign_in_gives_the_api_tokens_back(world: World) -> None:
    world.provider.refresh_token = None
    world.provider.add("u-1", "erin")
    _, token = await access_with_token(world, "u-1")
    world.clock.at += timedelta(days=2)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)

    await sign_in(world, "u-1")

    assert (await world.identity.identify_token(token)).username == "erin"


# ---------------------------------------------------------------- revalidation


async def test_nothing_is_due_before_the_interval(world: World) -> None:
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")
    world.clock.at += timedelta(minutes=59)

    report = await world.identity.revalidate_external_accounts()

    assert (report.extended, report.revoked, report.unreachable) == (0, 0, 0)


async def test_a_due_check_refreshes_groups_role_and_access(world: World) -> None:
    world.provider.add("u-1", "alice", "exactdocs-admins", "payments")
    account = await sign_in(world, "u-1")
    world.provider.add("u-1", "alice", "ops")
    world.clock.at += timedelta(minutes=61)

    report = await world.identity.revalidate_external_accounts()

    assert report.extended == 1
    stored = await world.accounts.get(Username("alice"))
    assert stored is not None
    assert stored.role is Role.USER
    assert world.externals.groups[AccountId(account.id)] == frozenset({"ops"})
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    assert link.access_until == world.clock.at + timedelta(minutes=60 + 1440)
    assert link.next_check_at == world.clock.at + timedelta(minutes=60)
    assert FakeBox().open(link.sealed_tokens or "") == "refresh-1+"  # the rotated token is kept


async def test_a_lost_membership_ends_access_at_once() -> None:
    world = build(policy(allow_any_user=False, allowed_groups=frozenset({"docs-readers"})))
    world.provider.add("u-1", "carol", "docs-readers")
    session, token = await access_with_token(world, "u-1")
    world.provider.add("u-1", "carol")
    world.clock.at += timedelta(minutes=61)

    report = await world.identity.revalidate_external_accounts()

    assert report.revoked == 1
    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)
    with pytest.raises(NotAllowedError):
        await sign_in(world, "u-1")


async def test_a_revoked_refresh_token_ends_access(world: World) -> None:
    world.provider.add("u-1", "alice")
    session, _ = await access_with_token(world, "u-1")
    world.provider.refresh_error = ProviderAccessRevokedError()
    world.clock.at += timedelta(minutes=61)

    assert (await world.identity.revalidate_external_accounts()).revoked == 1
    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    assert link.sealed_tokens is None


async def test_an_unreachable_provider_keeps_access_until_the_grace_ends(world: World) -> None:
    world.provider.add("u-1", "alice")
    session, token = await access_with_token(world, "u-1")
    world.provider.refresh_error = ProviderUnavailableError()

    for _ in range(25):  # every ten minutes (the lease), the provider never answers
        world.clock.at += timedelta(minutes=61)
        report = await world.identity.revalidate_external_accounts()
        assert report.revoked == 0
        if world.clock.at < START + timedelta(minutes=60 + 1440):
            await world.identity.identify_caller(session)

    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)
    with pytest.raises(InvalidTokenError):
        await world.identity.identify_token(token)


async def test_a_provider_back_within_the_grace_extends_access(world: World) -> None:
    world.provider.add("u-1", "alice")
    session, _ = await access_with_token(world, "u-1")
    world.provider.refresh_error = ProviderUnavailableError()
    world.clock.at += timedelta(minutes=61)
    assert (await world.identity.revalidate_external_accounts()).unreachable == 1

    world.provider.refresh_error = None
    world.clock.at += timedelta(minutes=11)  # the lease is over
    assert (await world.identity.revalidate_external_accounts()).extended == 1
    world.clock.at += timedelta(minutes=1440)

    await world.identity.identify_caller(session)


async def test_a_link_without_a_refresh_token_is_never_checked(world: World) -> None:
    world.provider.refresh_token = None
    world.provider.add("u-1", "erin")
    await sign_in(world, "u-1")
    world.clock.at += timedelta(minutes=61)

    report = await world.identity.revalidate_external_accounts()

    assert (report.extended, report.revoked, report.unreachable) == (0, 0, 0)


async def test_a_link_whose_provider_is_no_longer_configured_loses_access(world: World) -> None:
    world.provider.add("u-1", "alice")
    session = (await access_with_token(world, "u-1"))[0]
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    world.externals.links[ISSUER, "u-1"] = replace(link, provider="removed")
    world.clock.at += timedelta(minutes=61)

    assert (await world.identity.revalidate_external_accounts()).revoked == 1
    with pytest.raises(NotSignedInError):
        await world.identity.identify_caller(session)


async def test_a_token_that_does_not_open_loses_access(world: World) -> None:
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")
    link = await world.externals.get(ISSUER, "u-1")
    assert link is not None
    world.externals.links[ISSUER, "u-1"] = replace(link, sealed_tokens="sealed with another key")
    world.clock.at += timedelta(minutes=61)

    assert (await world.identity.revalidate_external_accounts()).revoked == 1


async def test_claims_of_another_subject_end_access(world: World) -> None:
    world.provider.add("u-2", "mallory")
    world.provider.add("u-1", "alice")
    await sign_in(world, "u-1")
    world.provider.people["u-1"] = world.provider.people["u-2"]
    world.clock.at += timedelta(minutes=61)

    assert (await world.identity.revalidate_external_accounts()).revoked == 1


async def test_a_local_accounts_sessions_never_depend_on_a_provider(world: World) -> None:
    local = Account(
        id=AccountId("ada"),
        username=Username("ada"),
        password_hash="fake$" + HORSE[::-1],
        role=Role.ADMIN,
        created_at=START,
    )
    await world.accounts.add(local)
    grant = await world.identity.sign_in(
        AuthenticateQuery(username="ada", password=SecretStr(HORSE))
    )
    world.clock.at += timedelta(days=6)

    assert (await world.identity.identify_caller(grant.token.get_secret_value())).id == "ada"


# ---------------------------------------------------------------- revalidation races, every store


@dataclass(slots=True)
class StoredWorld:
    clock: Clock
    accounts: AccountRepository
    externals: ExternalIdentityRepository
    provider: FakeProvider
    identity: IdentityModule
    last_session: str = ""


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stored(request: pytest.FixtureRequest) -> AsyncIterator[StoredWorld]:
    """The use cases over memory, SQLite or PostgreSQL stores, with the scripted provider."""

    def assemble(**stores: Any) -> StoredWorld:
        clock, provider, configured = Clock(), FakeProvider(), policy()
        identity = IdentityModule.build(
            hasher=FakeHasher(),
            failures=InMemoryFailedSignInLog(),
            box=FakeBox(),
            clock=clock,
            providers={"corp": provider},
            policies={"corp": configured},
            **stores,
        )
        return StoredWorld(clock, stores["repository"], stores["externals"], provider, identity)

    if request.param == "memory":
        accounts = InMemoryAccountRepository()
        yield assemble(
            repository=accounts,
            sessions=InMemorySessionRepository(),
            tokens=InMemoryTokenRepository(),
            externals=InMemoryExternalIdentityRepository(accounts=accounts),
            library_grants=InMemoryLibraryGrantRepository(),
            preferences=InMemoryPreferencesRepository(),
            access_log=InMemoryAccessLog(),
            attempts=InMemorySignInAttemptRepository(),
        )
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        yield assemble(
            repository=SqliteAccountRepository(engine=engine),
            sessions=SqliteSessionRepository(engine=engine),
            tokens=SqliteTokenRepository(engine=engine),
            externals=SqliteExternalIdentityRepository(engine=engine),
            library_grants=SqliteLibraryGrantRepository(engine=engine),
            preferences=SqlitePreferencesRepository(engine=engine),
            access_log=SqliteAccessLog(engine=engine),
            attempts=SqliteSignInAttemptRepository(engine=engine),
        )


async def test_a_disable_during_a_refresh_is_not_undone(stored: StoredWorld) -> None:
    """The disable drops the tokens while the provider answers; the answer must not restore them."""
    stored.provider.add("u-1", "alice", "payments")
    account = await sign_in(stored, "u-1")
    stored.clock.at += timedelta(minutes=61)
    signed_in = await stored.externals.get(ISSUER, "u-1")

    async def disable() -> None:
        await stored.identity.set_user_disabled(
            SetUserDisabledCommand(id=account.id, disabled=True)
        )

    stored.provider.during_refresh = disable
    report = await stored.identity.revalidate_external_accounts()

    assert (report.extended, report.superseded) == (0, 1)
    link = await stored.externals.get(ISSUER, "u-1")
    assert link is not None
    assert signed_in is not None
    assert link.sealed_tokens is None  # "disabling deletes the sealed provider tokens" holds
    assert link.access_until == signed_in.access_until  # not moved forward
    disabled = await stored.accounts.get_by_id(AccountId(account.id))
    assert disabled is not None
    assert disabled.is_disabled
    with pytest.raises(NotSignedInError):
        await stored.identity.identify_caller(stored.last_session)


async def test_a_sign_in_during_a_refresh_is_not_overwritten(stored: StoredWorld) -> None:
    """The sign-in's newer token, groups and access stand; the older refresh answer is dropped."""
    stored.provider.add("u-1", "alice", "payments")
    account = await sign_in(stored, "u-1")
    stored.clock.at += timedelta(minutes=61)

    async def sign_in_again() -> None:
        stored.provider.refresh_token = "from-the-sign-in"
        stored.provider.add("u-1", "alice", "ops")
        await sign_in(stored, "u-1")
        stored.provider.add("u-1", "alice", "stale-group")

    stored.provider.during_refresh = sign_in_again
    report = await stored.identity.revalidate_external_accounts()

    assert (report.extended, report.superseded) == (0, 1)
    link = await stored.externals.get(ISSUER, "u-1")
    assert link is not None
    assert FakeBox().open(link.sealed_tokens or "") == "from-the-sign-in"
    assert link.signed_in_at == stored.clock.at
    groups = await stored.externals.groups_by_account()
    assert groups[AccountId(account.id)] == ("corp", ["ops"])


# ---------------------------------------------------------------- MCP OAuth: identify an ID token


async def test_an_id_token_of_an_allowed_person_acts_as_their_linked_account() -> None:
    world = build(policy(allow_any_user=False, allowed_groups=frozenset({"docs"})))
    world.provider.add("u-1", "alice", "docs")
    account = await sign_in(world, "u-1")
    world.provider.id_tokens["tok"] = world.provider.people["u-1"]

    caller = await world.identity.identify_external_token("corp", "tok")

    assert caller.account == account
    assert caller.groups == frozenset({"docs"})
    assert caller.linked is True


async def test_an_unlinked_person_is_identified_without_creating_an_account() -> None:
    world = build()
    world.provider.add("u-9", "dora", "exactdocs-admins")
    world.provider.id_tokens["tok"] = world.provider.people["u-9"]

    caller = await world.identity.identify_external_token("corp", "tok")

    assert (caller.account.id, caller.account.username, caller.account.role) == (
        "corp:u-9",
        "dora",
        "admin",
    )
    assert caller.groups == frozenset({"exactdocs-admins"})
    assert caller.linked is False
    assert await world.accounts.any_exists() is False


async def test_a_person_outside_the_allowed_groups_is_refused() -> None:
    world = build(policy(allow_any_user=False, allowed_groups=frozenset({"docs"})))
    world.provider.add("u-2", "bob", "other")
    world.provider.id_tokens["tok"] = world.provider.people["u-2"]

    with pytest.raises(NotAllowedError):
        await world.identity.identify_external_token("corp", "tok")


async def test_a_disabled_account_is_refused() -> None:
    world = build()
    world.provider.add("u-1", "alice")
    account = await sign_in(world, "u-1")
    await world.identity.set_user_disabled(SetUserDisabledCommand(id=account.id, disabled=True))
    world.provider.id_tokens["tok"] = world.provider.people["u-1"]

    with pytest.raises(AccountDisabledError):
        await world.identity.identify_external_token("corp", "tok")


async def test_a_token_the_provider_does_not_vouch_for_is_refused() -> None:
    world = build()

    with pytest.raises(ExternalSignInFailedError):
        await world.identity.identify_external_token("corp", "forged")


async def test_an_unknown_provider_is_refused_for_a_token_too() -> None:
    with pytest.raises(UnknownSignInProviderError):
        await build().identity.identify_external_token("nope", "tok")


async def test_an_oauth_token_cannot_revive_a_dangling_account_link() -> None:
    world = build()
    world.provider.add("u-1", "alice", "exactdocs-admins")
    await sign_in(world, "u-1")
    world.accounts.accounts.clear()
    world.provider.id_tokens["tok"] = world.provider.people["u-1"]
    with pytest.raises(ExternalSignInFailedError):
        await world.identity.identify_external_token("corp", "tok")


async def test_oauth_groups_use_the_same_provider_prefix_as_web_groups() -> None:
    world = build(policy(group_prefix="corp:"))
    world.provider.add("u-1", "alice", "docs")
    world.provider.id_tokens["tok"] = world.provider.people["u-1"]
    caller = await world.identity.identify_external_token("corp", "tok")
    assert caller.groups == frozenset({"corp:docs"})


async def test_oauth_uses_signed_groups_without_overwriting_web_memberships() -> None:
    world = build()
    world.provider.add("u-1", "alice", "docs")
    account = await sign_in(world, "u-1")
    before = await world.externals.get(ISSUER, "u-1")
    world.provider.add("u-1", "alice", "readers")
    world.provider.id_tokens["tok"] = world.provider.people["u-1"]
    caller = await world.identity.identify_external_token("corp", "tok")
    assert caller.groups == frozenset({"readers"})
    assert await world.externals.groups_of(AccountId(account.id)) == frozenset({"docs"})
    assert await world.externals.get(ISSUER, "u-1") == before
