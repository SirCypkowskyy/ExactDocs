"""Adapter contract: every ``AccountRepository`` behaves the same, whatever stores the data."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryAccountRepository
from exactdocs.identity.adapters.driven.sqlite import SqliteAccountRepository
from exactdocs.identity.models import Account, AccountId, Role, Username
from exactdocs.identity.ports import AccountRepository

NOT_A_HASH = "$argon2id$not-a-real-hash"


def account(name: str) -> Account:
    return Account(
        id=AccountId(f"id-{name}"),
        username=Username(name),
        password_hash=NOT_A_HASH,
        role=Role.ADMIN,
        created_at=datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC),
    )


@pytest.fixture(params=["memory", "sqlite"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[AccountRepository]:
    if request.param == "memory":
        yield InMemoryAccountRepository()
        return
    container = Container.build(Settings())
    async with container.running():
        yield SqliteAccountRepository(container.engine)


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
