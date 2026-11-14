"""Adapter contract: the external identity and sign-in attempt stores, in memory and in SQL."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from databases import ADMIN_URL, SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import (
    InMemoryAccountRepository,
    InMemoryExternalIdentityRepository,
    InMemorySignInAttemptRepository,
)
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteExternalIdentityRepository,
    SqliteSignInAttemptRepository,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    ExternalIdentity,
    Role,
    SignInAttempt,
    Username,
)
from exactdocs.identity.ports import (
    AccountRepository,
    ExternalIdentityRepository,
    SignInAttemptRepository,
)

ISSUER = "https://idp.example.com"
NOW = datetime(2026, 11, 13, 9, 0, 0, 123456, tzinfo=UTC)


@dataclass(slots=True)
class Stores:
    accounts: AccountRepository
    externals: ExternalIdentityRepository
    attempts: SignInAttemptRepository


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    if request.param == "memory":
        accounts = InMemoryAccountRepository()
        yield Stores(
            accounts=accounts,
            externals=InMemoryExternalIdentityRepository(accounts=accounts),
            attempts=InMemorySignInAttemptRepository(),
        )
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        yield Stores(
            accounts=SqliteAccountRepository(engine=engine),
            externals=SqliteExternalIdentityRepository(engine=engine),
            attempts=SqliteSignInAttemptRepository(engine=engine),
        )


def account(name: str, *, password_hash: str | None = None) -> Account:
    return Account(
        id=AccountId(f"id-{name}"),
        username=Username(name),
        password_hash=password_hash,
        role=Role.USER,
        created_at=NOW,
    )


def link(subject: str, account_id: str, **changes: Any) -> ExternalIdentity:
    identity = ExternalIdentity(
        issuer=ISSUER,
        subject=subject,
        account_id=AccountId(account_id),
        provider="corp",
        sealed_tokens="sealed",
        signed_in_at=NOW,
        checked_at=NOW,
        next_check_at=NOW + timedelta(hours=1),
        access_until=NOW + timedelta(hours=25),
    )
    return replace(identity, **changes)


async def test_a_linked_account_is_stored_with_its_link_and_groups(stores: Stores) -> None:
    alice = account("alice")
    outcome = await stores.externals.create_linked_account(
        alice, link("u-1", alice.id), frozenset({"b", "a"})
    )

    assert outcome == "created"
    assert await stores.accounts.get(Username("alice")) == alice
    assert await stores.externals.get(ISSUER, "u-1") == link("u-1", alice.id)
    assert await stores.externals.get_for_account(alice.id) == link("u-1", alice.id)
    assert await stores.externals.get(ISSUER, "u-2") is None
    assert await stores.externals.groups_by_account() == {alice.id: ("corp", ["a", "b"])}


async def test_a_taken_username_stores_nothing(stores: Stores) -> None:
    await stores.accounts.add(account("bob", password_hash="$argon2id$x"))
    bob = account("bob")
    outcome = await stores.externals.create_linked_account(
        replace(bob, id=AccountId("other")), link("u-1", "other"), frozenset({"a"})
    )

    assert outcome == "username_taken"
    assert await stores.externals.get(ISSUER, "u-1") is None
    assert await stores.externals.groups_by_account() == {}


async def test_a_second_link_of_one_identity_stores_nothing(stores: Stores) -> None:
    alice = account("alice")
    await stores.externals.create_linked_account(alice, link("u-1", alice.id), frozenset())
    again = account("alice2")

    outcome = await stores.externals.create_linked_account(
        again, link("u-1", again.id), frozenset()
    )

    assert outcome == "already_linked"
    assert await stores.accounts.get(Username("alice2")) is None


async def test_concurrent_first_sign_ins_of_one_identity_link_it_once(stores: Stores) -> None:
    candidates = [account(f"alice{i}") for i in range(6)]
    outcomes = await asyncio.gather(
        *(
            stores.externals.create_linked_account(a, link("u-1", a.id), frozenset())
            for a in candidates
        )
    )

    assert outcomes.count("created") == 1
    assert set(outcomes) <= {"created", "already_linked"}
    assert len(await stores.accounts.list_all()) == 1


async def test_a_check_replaces_the_link_the_role_and_the_groups(stores: Stores) -> None:
    alice = account("alice")
    await stores.externals.create_linked_account(alice, link("u-1", alice.id), frozenset({"a"}))
    later = NOW + timedelta(hours=2)
    checked = link(
        "u-1",
        alice.id,
        sealed_tokens="rotated",
        checked_at=later,
        next_check_at=later + timedelta(hours=1),
        access_until=later + timedelta(hours=25),
    )

    await stores.externals.record_check(checked, role=Role.ADMIN, groups=frozenset({"c"}))

    assert await stores.externals.get(ISSUER, "u-1") == checked
    stored = await stores.accounts.get_by_id(alice.id)
    assert stored is not None
    assert stored.role is Role.ADMIN
    assert await stores.externals.groups_by_account() == {alice.id: ("corp", ["c"])}


def revalidated(claimed: ExternalIdentity) -> ExternalIdentity:
    later = NOW + timedelta(hours=2)
    return replace(
        claimed,
        sealed_tokens="refreshed",
        checked_at=later,
        next_check_at=later + timedelta(hours=1),
        access_until=later + timedelta(hours=25),
    )


async def claimed_link(stores: Stores, groups: frozenset[str] = frozenset({"a"})) -> Account:
    alice = account("alice")
    due = link("u-1", alice.id, next_check_at=NOW - timedelta(minutes=1))
    await stores.externals.create_linked_account(alice, due, groups)
    return alice


async def claim(stores: Stores) -> ExternalIdentity:
    (claimed,) = await stores.externals.claim_due(
        NOW, lease_until=NOW + timedelta(minutes=10), limit=1
    )
    return claimed


async def test_a_revalidation_of_an_unchanged_link_is_stored(stores: Stores) -> None:
    alice = await claimed_link(stores)
    claimed = await claim(stores)
    checked = revalidated(claimed)

    stored = await stores.externals.record_revalidation(
        claimed, checked, role=Role.ADMIN, groups=frozenset({"c"})
    )

    assert stored
    assert await stores.externals.get(ISSUER, "u-1") == checked
    found = await stores.accounts.get_by_id(alice.id)
    assert found is not None
    assert found.role is Role.ADMIN
    assert await stores.externals.groups_by_account() == {alice.id: ("corp", ["c"])}


async def change_disable(stores: Stores, alice: Account) -> None:
    await stores.accounts.set_disabled_at(alice.id, NOW)
    await stores.externals.forget_tokens(alice.id)


async def change_disable_flag_only(stores: Stores, alice: Account) -> None:
    """The disable's first write landed, its ``forget_tokens`` has not run yet."""
    await stores.accounts.set_disabled_at(alice.id, NOW)


async def change_revoke(stores: Stores, alice: Account) -> None:
    await stores.externals.revoke(alice.id, NOW)


async def change_sign_in(stores: Stores, alice: Account) -> None:
    signed_in = NOW + timedelta(minutes=1)
    fresh = link(
        "u-1",
        alice.id,
        sealed_tokens="from the sign-in",
        signed_in_at=signed_in,
        checked_at=signed_in,
        next_check_at=signed_in + timedelta(hours=1),
        access_until=signed_in + timedelta(hours=25),
    )
    await stores.externals.record_check(fresh, role=Role.USER, groups=frozenset({"new"}))


async def change_other_pass(stores: Stores, alice: Account) -> None:
    """Another pass claimed the link after the lease and stored its own answer first."""
    del alice
    claimed = await stores.externals.get(ISSUER, "u-1")
    assert claimed is not None
    first = replace(revalidated(claimed), sealed_tokens="the other pass's")
    assert await stores.externals.record_revalidation(
        claimed, first, role=Role.USER, groups=frozenset({"other"})
    )


@pytest.mark.parametrize(
    "change",
    [change_disable, change_disable_flag_only, change_revoke, change_sign_in, change_other_pass],
)
async def test_a_revalidation_of_a_link_changed_meanwhile_stores_nothing(
    stores: Stores, change: Any
) -> None:
    alice = await claimed_link(stores)
    claimed = await claim(stores)
    await change(stores, alice)
    before = await stores.externals.get(ISSUER, "u-1")
    groups_before = await stores.externals.groups_by_account()

    stored = await stores.externals.record_revalidation(
        claimed, revalidated(claimed), role=Role.ADMIN, groups=frozenset({"stale"})
    )

    assert not stored
    assert await stores.externals.get(ISSUER, "u-1") == before
    assert await stores.externals.groups_by_account() == groups_before
    found = await stores.accounts.get_by_id(alice.id)
    assert found is not None
    assert found.role is Role.USER


async def test_revoking_ends_access_and_drops_tokens_and_groups(stores: Stores) -> None:
    alice = account("alice")
    await stores.externals.create_linked_account(alice, link("u-1", alice.id), frozenset({"a"}))

    await stores.externals.revoke(alice.id, NOW)

    revoked = await stores.externals.get(ISSUER, "u-1")
    assert revoked == link("u-1", alice.id, access_until=NOW, sealed_tokens=None)
    assert revoked is not None
    assert not revoked.has_access(NOW)
    assert await stores.externals.groups_by_account() == {alice.id: ("corp", [])}


async def test_forgetting_tokens_keeps_the_rest(stores: Stores) -> None:
    alice = account("alice")
    await stores.externals.create_linked_account(alice, link("u-1", alice.id), frozenset())

    await stores.externals.forget_tokens(alice.id)
    await stores.externals.forget_tokens(AccountId("a local account"))

    assert await stores.externals.get(ISSUER, "u-1") == link("u-1", alice.id, sealed_tokens=None)


async def test_only_due_links_with_a_token_are_claimed_and_leased(stores: Stores) -> None:
    for i, (due_in, tokens) in enumerate([(-2, "t"), (-1, "t"), (1, "t"), (-3, None)]):
        a = account(f"user{i}")
        identity = link(
            f"u-{i}", a.id, next_check_at=NOW + timedelta(minutes=due_in), sealed_tokens=tokens
        )
        await stores.externals.create_linked_account(a, identity, frozenset())
    lease = NOW + timedelta(minutes=10)

    first = await stores.externals.claim_due(NOW, lease_until=lease, limit=1)
    rest = await stores.externals.claim_due(NOW, lease_until=lease, limit=10)
    none = await stores.externals.claim_due(NOW, lease_until=lease, limit=10)

    assert [ln.subject for ln in first] == ["u-0"]  # the longest due first
    assert first[0].next_check_at == NOW - timedelta(minutes=2)  # as it was before the lease
    assert [ln.subject for ln in rest] == ["u-1"]
    assert none == []
    leased = await stores.externals.get(ISSUER, "u-0")
    assert leased is not None
    assert leased.next_check_at == lease


async def test_concurrent_claims_never_return_one_link_twice(stores: Stores) -> None:
    for i in range(12):
        a = account(f"user{i}")
        identity = link(f"u-{i}", a.id, next_check_at=NOW - timedelta(minutes=1))
        await stores.externals.create_linked_account(a, identity, frozenset())

    batches = await asyncio.gather(
        *(
            stores.externals.claim_due(NOW, lease_until=NOW + timedelta(minutes=10), limit=3)
            for _ in range(6)
        )
    )

    claimed = [ln.subject for batch in batches for ln in batch]
    assert sorted(claimed) == sorted(f"u-{i}" for i in range(12))


def attempt(binding: str, *, started: datetime = NOW) -> SignInAttempt:
    return SignInAttempt(
        binding_hash=binding,
        provider="corp",
        state=f"state-{binding}",
        nonce=f"nonce-{binding}",
        code_verifier="v" * 64,
        return_to="/libraries",
        created_at=started,
    )


async def test_an_attempt_is_taken_once(stores: Stores) -> None:
    await stores.attempts.add(attempt("b1"), expired_before=NOW - timedelta(minutes=10))

    taken = await asyncio.gather(*(stores.attempts.take("b1") for _ in range(5)))

    assert [t for t in taken if t is not None] == [attempt("b1")]
    assert await stores.attempts.take("b1") is None
    assert await stores.attempts.take("never-started") is None


async def test_expired_attempts_are_pruned_by_the_next_one(stores: Stores) -> None:
    old = NOW - timedelta(minutes=11)
    await stores.attempts.add(attempt("old", started=old), expired_before=old)
    await stores.attempts.add(attempt("new"), expired_before=NOW - timedelta(minutes=10))

    assert await stores.attempts.take("old") is None
    assert await stores.attempts.take("new") == attempt("new")


@pytest.mark.skipif(ADMIN_URL is None, reason="needs EXACTDOCS_TEST_POSTGRES_URL")
async def test_two_processes_never_claim_one_link_twice(on_postgres: None) -> None:
    """Two engines (two processes' pools) share the work through ``FOR UPDATE SKIP LOCKED``."""
    del on_postgres
    container = Container.build(Settings())
    async with container.running(jobs=False):
        other = open_database(Settings())
        try:
            mine = SqliteExternalIdentityRepository(engine=container.engine)
            theirs = SqliteExternalIdentityRepository(engine=other)
            accounts = SqliteExternalIdentityRepository(engine=container.engine)
            for i in range(20):
                a = account(f"user{i}")
                identity = link(f"u-{i}", a.id, next_check_at=NOW - timedelta(minutes=1))
                await accounts.create_linked_account(a, identity, frozenset())
            lease = NOW + timedelta(minutes=10)
            batches = await asyncio.gather(
                *(
                    repository.claim_due(NOW, lease_until=lease, limit=4)
                    for repository in [mine, theirs] * 5
                )
            )
        finally:
            await other.dispose()

    claimed = [ln.subject for batch in batches for ln in batch]
    assert sorted(claimed) == sorted(f"u-{i}" for i in range(20))
