"""Adapter contract: every ``AccountRepository`` behaves the same, whatever stores the data."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryAccountRepository
from exactdocs.identity.adapters.driven.sqlite import SqliteAccountRepository
from exactdocs.identity.models import Account, AccountId, Role, Username
from exactdocs.identity.ports import AccountRepository

NOT_A_HASH = "$argon2id$not-a-real-hash"
ANOTHER_HASH = "$argon2id$another"


def account(name: str, role: Role = Role.ADMIN, minute: int = 0) -> Account:
    return Account(
        id=AccountId(f"id-{name}"),
        username=Username(name),
        password_hash=NOT_A_HASH,
        role=role,
        created_at=datetime(2026, 11, 4, 12, minute, 0, 123456, tzinfo=UTC),
    )


DISABLED_AT = datetime(2026, 11, 13, 9, 30, 0, 654321, tzinfo=UTC)


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[AccountRepository]:
    if request.param == "memory":
        yield InMemoryAccountRepository()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteAccountRepository(engine=container.engine)


async def test_starts_empty(repository: AccountRepository) -> None:
    assert await repository.any_exists() is False
    assert await repository.get(Username("ada")) is None


async def test_the_first_account_is_stored_and_found(repository: AccountRepository) -> None:
    assert await repository.add_first(account("ada")) is True

    assert await repository.any_exists() is True
    assert await repository.get(Username("ada")) == account("ada")


async def test_a_second_account_is_not_stored(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))

    assert await repository.add_first(account("bob")) is False
    assert await repository.get(Username("bob")) is None
    assert await repository.get(Username("ada")) == account("ada")


async def test_concurrent_first_accounts_store_exactly_one(repository: AccountRepository) -> None:
    results = await asyncio.gather(*(repository.add_first(account(f"user{i}")) for i in range(8)))

    assert results.count(True) == 1


async def test_an_account_is_found_by_id(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))

    assert await repository.get_by_id(AccountId("id-ada")) == account("ada")
    assert await repository.get_by_id(AccountId("id-nobody")) is None


async def test_the_password_hash_can_be_replaced(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))

    await repository.set_password_hash(AccountId("id-ada"), ANOTHER_HASH)

    stored = await repository.get(Username("ada"))
    assert stored is not None
    assert stored.password_hash == ANOTHER_HASH
    assert (stored.id, stored.username) == (AccountId("id-ada"), Username("ada"))


async def test_further_accounts_are_stored_unless_the_username_is_taken(
    repository: AccountRepository,
) -> None:
    await repository.add_first(account("ada"))

    assert await repository.add(account("bob", Role.USER, minute=1)) is True
    taken = replace(account("bob", Role.USER, minute=2), id=AccountId("id-bob-2"))
    assert await repository.add(taken) is False

    assert await repository.get(Username("bob")) == account("bob", Role.USER, minute=1)
    assert await repository.get_by_id(AccountId("id-bob-2")) is None


async def test_concurrent_accounts_with_one_username_store_exactly_one(
    repository: AccountRepository,
) -> None:
    await repository.add_first(account("ada"))
    same = [replace(account("bob", Role.USER), id=AccountId(f"id-bob-{i}")) for i in range(8)]

    results = await asyncio.gather(*(repository.add(a) for a in same))

    assert results.count(True) == 1


async def test_accounts_are_listed_oldest_first(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))
    await repository.add(account("carol", Role.USER, minute=2))
    await repository.add(account("bob", Role.USER, minute=1))

    assert [a.username.value for a in await repository.list_all()] == ["ada", "bob", "carol"]


async def test_an_account_is_disabled_and_enabled(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))
    await repository.add(account("bob", Role.USER, minute=1))

    assert await repository.set_disabled_at(AccountId("id-bob"), DISABLED_AT) is True
    stored = await repository.get(Username("bob"))
    assert stored is not None
    assert stored.disabled_at == DISABLED_AT
    assert stored.is_disabled

    assert await repository.set_disabled_at(AccountId("id-bob"), None) is True
    assert await repository.get_by_id(AccountId("id-bob")) == account("bob", Role.USER, minute=1)


async def test_the_last_enabled_admin_is_never_disabled(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))
    await repository.add(account("carol", minute=1))
    await repository.add(account("bob", Role.USER, minute=2))
    await repository.set_disabled_at(AccountId("id-carol"), DISABLED_AT)

    assert await repository.set_disabled_at(AccountId("id-ada"), DISABLED_AT) is False

    stored = await repository.get(Username("ada"))
    assert stored is not None
    assert not stored.is_disabled


async def test_two_admins_disabled_at_once_leave_one_enabled(
    repository: AccountRepository,
) -> None:
    await repository.add_first(account("ada"))
    await repository.add(account("carol", minute=1))

    results = await asyncio.gather(
        repository.set_disabled_at(AccountId("id-ada"), DISABLED_AT),
        repository.set_disabled_at(AccountId("id-carol"), DISABLED_AT),
    )

    assert sorted(results) == [False, True]
    assert [a.is_disabled for a in await repository.list_all()].count(False) == 1


async def test_activity_is_stored_and_only_moves_forward(repository: AccountRepository) -> None:
    await repository.add_first(account("ada"))
    await repository.add(account("bob", Role.USER, minute=1))
    hour = datetime(2026, 11, 13, 10, tzinfo=UTC)

    await repository.record_activity(AccountId("id-ada"), hour)
    await repository.record_activity(AccountId("id-ada"), hour - timedelta(hours=3))
    await repository.record_activity(AccountId("id-nobody"), hour)

    assert await repository.get(Username("ada")) == replace(account("ada"), last_active_at=hour)
    assert (await repository.get_by_id(AccountId("id-bob"))) == account("bob", Role.USER, minute=1)
    later = hour + timedelta(hours=1)
    await repository.record_activity(AccountId("id-ada"), later)
    assert [a.last_active_at for a in await repository.list_all()] == [later, None]
