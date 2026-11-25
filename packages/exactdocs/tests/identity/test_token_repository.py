"""Adapter contract: every ``TokenRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryTokenRepository
from exactdocs.identity.adapters.driven.sqlite import SqliteAccountRepository, SqliteTokenRepository
from exactdocs.identity.models import Account, AccountId, ApiToken, Role, Username
from exactdocs.identity.ports import TokenRepository

NOW = datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC)
ADA = AccountId("id-ada")
BOB = AccountId("id-bob")
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


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[TokenRepository]:
    if request.param == "memory":
        yield InMemoryTokenRepository()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        ada = Account(
            id=ADA,
            username=Username("ada"),
            password_hash=NOT_A_HASH,
            role=Role.ADMIN,
            created_at=NOW,
        )
        accounts = SqliteAccountRepository(engine=container.engine)
        await accounts.add_first(ada)
        await accounts.add(replace(ada, id=BOB, username=Username("bob"), role=Role.USER))
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


@pytest.mark.parametrize("selection", [None, frozenset(), frozenset({"/acme/docs"})])
async def test_token_library_selection_survives_storage_and_touch(
    repository: TokenRepository, selection: frozenset[str] | None
) -> None:
    scoped = replace(token("selected"), library_ids=selection)
    await repository.add(scoped)
    await repository.touch(scoped.token_hash, NOW)
    stored = await repository.get(scoped.token_hash)
    assert stored is not None
    assert stored.library_ids == selection
    assert (await repository.list_for_account(ADA))[0].library_ids == selection


async def test_every_token_is_listed_newest_first(repository: TokenRepository) -> None:
    await repository.add(token("ada-old", created=NOW))
    await repository.add(token("bob-new", created=NOW + timedelta(minutes=2), owner=BOB))
    await repository.add(token("ada-new", created=NOW + timedelta(minutes=1)))
    await repository.add(token("expired", created=NOW - timedelta(days=5), owner=BOB))

    listed = await repository.list_all()

    assert [(t.id, t.account_id) for t in listed] == [
        ("bob-new", BOB),
        ("ada-new", ADA),
        ("ada-old", ADA),
        ("expired", BOB),
    ]
    assert listed[1] == token("ada-new", created=NOW + timedelta(minutes=1))


async def test_live_tokens_are_counted_per_account(repository: TokenRepository) -> None:
    await repository.add(token("a1"))
    await repository.add(replace(token("a2"), expires_at=None))
    await repository.add(token("b1", owner=BOB))
    await repository.add(token("gone", created=NOW - timedelta(days=5), owner=BOB))
    await repository.add(token("ends-now", created=NOW - timedelta(days=1), owner=BOB))

    assert dict(await repository.count_by_account(NOW)) == {ADA: 2, BOB: 1}
    assert dict(await repository.count_by_account(NOW + timedelta(days=2))) == {ADA: 1}
