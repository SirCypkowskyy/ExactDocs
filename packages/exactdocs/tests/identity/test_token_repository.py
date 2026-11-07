"""Adapter contract: every ``TokenRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryTokenRepository
from exactdocs.identity.adapters.driven.sqlite import SqliteAccountRepository, SqliteTokenRepository
from exactdocs.identity.models import Account, AccountId, ApiToken, Role, Username
from exactdocs.identity.ports import TokenRepository

NOW = datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC)
ADA = AccountId("id-ada")
NOT_A_HASH = "$argon2id$x"


def token(token_id: str, *, created: datetime = NOW, owner: AccountId = ADA) -> ApiToken:
    return ApiToken(
        id=token_id,
        account_id=owner,
        name=f"name {token_id}",
        token_hash=f"hash-{token_id}",
        prefix="exd_abcd",
        created_at=created,
        expires_at=created + timedelta(days=1),
    )


@pytest.fixture(params=["memory", "sqlite"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[TokenRepository]:
    if request.param == "memory":
        yield InMemoryTokenRepository()
        return
    container = Container.build(Settings())
    async with container.running():
        ada = Account(
            id=ADA,
            username=Username("ada"),
            password_hash=NOT_A_HASH,
            role=Role.ADMIN,
            created_at=NOW,
        )
        await SqliteAccountRepository(engine=container.engine).add_first(ada)
        yield SqliteTokenRepository(engine=container.engine)


async def test_a_stored_token_is_found_by_hash_and_an_unknown_one_is_not(
    repository: TokenRepository,
) -> None:
    await repository.add(token("t1"))

    assert await repository.get("hash-t1") == token("t1")
    assert await repository.get("hash-t2") is None


async def test_touching_sets_the_last_used_time(repository: TokenRepository) -> None:
    await repository.add(token("t1"))

    await repository.touch("hash-t1", NOW + timedelta(hours=2))

    stored = await repository.get("hash-t1")
    assert stored is not None
    assert stored.last_used_at == NOW + timedelta(hours=2)


async def test_tokens_are_listed_newest_first(repository: TokenRepository) -> None:
    await repository.add(token("old", created=NOW))
    await repository.add(token("new", created=NOW + timedelta(minutes=1)))

    assert [t.id for t in await repository.list_for_account(ADA)] == ["new", "old"]
    assert await repository.list_for_account(AccountId("nobody")) == []


async def test_delete_is_scoped_to_the_account(repository: TokenRepository) -> None:
    await repository.add(token("t1"))

    assert not await repository.delete(AccountId("nobody"), "t1")
    assert await repository.get("hash-t1") is not None
    assert await repository.delete(ADA, "t1")
    assert await repository.get("hash-t1") is None
    assert not await repository.delete(ADA, "t1")


async def test_expired_tokens_are_deleted_and_live_ones_stay(repository: TokenRepository) -> None:
    await repository.add(token("old", created=NOW - timedelta(days=5)))
    await repository.add(token("new"))

    await repository.delete_expired(NOW)

    assert [t.id for t in await repository.list_for_account(ADA)] == ["new"]


async def test_deleting_for_an_account_removes_all_its_tokens(repository: TokenRepository) -> None:
    await repository.add(token("t1"))
    await repository.add(token("t2"))

    await repository.delete_for_account(ADA)

    assert await repository.list_for_account(ADA) == []
