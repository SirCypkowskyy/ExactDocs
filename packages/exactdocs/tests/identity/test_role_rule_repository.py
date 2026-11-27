"""Adapter contract: the stored role rules and private libraries, in memory and in SQL (#577)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import (
    InMemoryPrivateLibraries,
    InMemoryRoleRuleRepository,
)
from exactdocs.identity.adapters.driven.sqlite import (
    SqlitePrivateLibraries,
    SqliteRoleRuleRepository,
)
from exactdocs.identity.models import AccountId, RoleRule, RuleGrant, RuleSource
from exactdocs.identity.ports import PrivateLibraries, RoleRuleRepository

AT = datetime(2026, 11, 26, 9, 0, 0, 123456, tzinfo=UTC)


@dataclass(slots=True)
class Stores:
    rules: RoleRuleRepository
    private: PrivateLibraries


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    if request.param == "memory":
        yield Stores(rules=InMemoryRoleRuleRepository(), private=InMemoryPrivateLibraries())
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        engine = container.engine
        yield Stores(
            rules=SqliteRoleRuleRepository(engine=engine),
            private=SqlitePrivateLibraries(engine=engine),
        )


def rule(rule_id: str, **changes: Any) -> RoleRule:
    base = RoleRule(
        id=rule_id,
        provider="corp",
        source=RuleSource.GROUP,
        value="writers",
        grant=RuleGrant.CONTRIBUTOR,
        created_by=AccountId("ada"),
        created_at=AT,
    )
    return replace(base, **changes)


async def test_rules_read_back_oldest_first_and_go_once_removed(stores: Stores) -> None:
    first, second = rule("01", libraries=frozenset({"/acme/b", "/acme/a"})), rule("02")
    assert await stores.rules.add(first)
    assert await stores.rules.add(second)

    assert await stores.rules.stored() == [first, second]
    assert await stores.rules.remove("01") == first
    assert await stores.rules.remove("01") is None
    assert await stores.rules.stored() == [second]


async def test_the_same_rule_is_stored_once(stores: Stores) -> None:
    assert await stores.rules.add(rule("01"))

    assert not await stores.rules.add(rule("02"))
    assert await stores.rules.add(rule("03", grant=RuleGrant.ADMIN))
    assert await stores.rules.add(rule("04", libraries=frozenset({"/acme/a"})))
    assert [r.id for r in await stores.rules.stored()] == ["01", "03", "04"]


async def test_libraries_are_private_until_said_otherwise(stores: Stores) -> None:
    await stores.private.set_private("/acme/a", private=True)
    await stores.private.set_private("/acme/a", private=True)
    await stores.private.set_private("/acme/b", private=True)
    await stores.private.set_private("/acme/b", private=False)

    assert await stores.private.private_among({"/acme/a", "/acme/b", "/acme/c"}) == {"/acme/a"}
