"""Adapter contract: every ``SessionRepository`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemorySessionRepository
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.models import Account, AccountId, Role, Session, Username
from exactdocs.identity.ports import SessionRepository

NOW = datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC)
ADA = AccountId("id-ada")
NOT_A_HASH = "$argon2id$x"


def account(name: str) -> Account:
    return Account(
        id=AccountId(f"id-{name}"),
        username=Username(name),
        password_hash=NOT_A_HASH,
        role=Role.ADMIN,
        created_at=NOW,
    )


def session(token_hash: str, *, owner: AccountId = ADA, created: datetime = NOW) -> Session:
    return Session(
        token_hash=token_hash, account_id=owner, created_at=created, last_used_at=created
    )


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[SessionRepository]:
    if request.param == "memory":
        yield InMemorySessionRepository()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        accounts = SqliteAccountRepository(engine=container.engine)
        await accounts.add_first(account("ada"))
        yield SqliteSessionRepository(engine=container.engine)


async def test_a_stored_session_is_found_and_an_unknown_one_is_not(
    repository: SessionRepository,
) -> None:
    await repository.add(session("h1"))

    assert await repository.get("h1") == session("h1")
    assert await repository.get("h2") is None


async def test_touching_moves_only_the_last_used_time(repository: SessionRepository) -> None:
    await repository.add(session("h1"))
    later = NOW + timedelta(days=2)

    await repository.touch("h1", later)

    stored = await repository.get("h1")
    assert stored is not None
    assert (stored.created_at, stored.last_used_at) == (NOW, later)


async def test_delete_removes_one_session_and_tolerates_a_missing_one(
    repository: SessionRepository,
) -> None:
    await repository.add(session("h1"))
    await repository.add(session("h2"))

    await repository.delete("h1")
    await repository.delete("h1")

    assert await repository.get("h1") is None
    assert await repository.get("h2") is not None


async def test_delete_for_account_removes_all_of_its_sessions(
    repository: SessionRepository,
) -> None:
    await repository.add(session("h1"))
    await repository.add(session("h2"))

    await repository.delete_for_account(ADA)

    assert (await repository.get("h1"), await repository.get("h2")) == (None, None)


async def test_delete_expired_removes_idle_and_too_old_sessions_only(
    repository: SessionRepository,
) -> None:
    await repository.add(session("fresh", created=NOW))
    await repository.add(session("idle", created=NOW - timedelta(days=8)))
    await repository.add(session("old", created=NOW - timedelta(days=31)))
    await repository.touch("old", NOW)  # busy, but older than the absolute limit
    await repository.touch("idle", NOW - timedelta(days=8))

    await repository.delete_expired(
        idle_before=NOW - timedelta(days=7), created_before=NOW - timedelta(days=30)
    )

    assert await repository.get("fresh") is not None
    assert await repository.get("idle") is None
    assert await repository.get("old") is None
