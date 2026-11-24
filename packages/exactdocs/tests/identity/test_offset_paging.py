"""Jumping to any page of the identity lists (#509): users, tokens, grants and both access logs."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

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
from exactdocs.identity.dtos import (
    AccountSummary,
    ClaimLibraryCommand,
    CreateFirstAdminCommand,
    CreateTokenCommand,
    CreateUserCommand,
    GrantLibraryRoleCommand,
    ListAccessLogQuery,
    ListLibraryAccessLogQuery,
    ListLibraryGrantsQuery,
    TokenListQuery,
    UserListQuery,
)
from exactdocs.identity.module import IdentityModule
from exactdocs_kernel import MAX_OFFSET, CursorWithOffsetError

LIBRARY = "/acme/payments"
PHRASE = "a long enough passphrase"
START = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


@dataclass(slots=True)
class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"fake${password[::-1]}"

    async def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"fake${password[::-1]}"


class _NoBox:
    def seal(self, plaintext: str) -> str:
        raise AssertionError(plaintext)

    def open(self, sealed: str) -> str:
        raise AssertionError(sealed)


@dataclass(slots=True)
class TickingClock:
    """Each reading is a minute after the one before."""

    at: datetime = START

    def now(self) -> datetime:
        self.at += timedelta(minutes=1)
        return self.at


@dataclass(slots=True)
class World:
    identity: IdentityModule
    ada: AccountSummary


type Page = tuple[list[Any], str | None, int]
type Fetch = Callable[[World, dict[str, Any]], Awaitable[Page]]


@pytest.fixture
async def world() -> World:
    accounts = InMemoryAccountRepository()
    identity = IdentityModule.build(
        repository=accounts,
        sessions=InMemorySessionRepository(),
        tokens=InMemoryTokenRepository(),
        hasher=FakeHasher(),
        failures=InMemoryFailedSignInLog(),
        externals=InMemoryExternalIdentityRepository(accounts=accounts),
        library_grants=InMemoryLibraryGrantRepository(),
        preferences=InMemoryPreferencesRepository(),
        access_log=InMemoryAccessLog(),
        attempts=InMemorySignInAttemptRepository(),
        box=_NoBox(),
        clock=TickingClock(),
    )
    ada = await identity.create_first_admin(
        CreateFirstAdminCommand(username="ada", password=SecretStr(PHRASE))
    )
    await identity.claim_library(ClaimLibraryCommand(account_id=ada.id, library=LIBRARY))
    for n, name in enumerate(("dave", "carol", "bob", "erin", "frank")):
        await identity.create_user(
            CreateUserCommand.model_validate(
                {"username": name, "password": PHRASE, "role": "admin" if n % 2 else "user"}
            )
        )
        await identity.grant_library_role(
            GrantLibraryRoleCommand(
                caller_id=ada.id,
                library=LIBRARY,
                kind="user",
                subject=name,
                role=("viewer", "contributor")[n % 2],
            )
        )
    await identity.grant_library_role(
        GrantLibraryRoleCommand(
            caller_id=ada.id, library=LIBRARY, kind="group", subject="writers", role="viewer"
        )
    )
    for name in ("laptop", "ci-main", "ci-nightly", "desk", "phone"):
        await identity.create_token(ada, CreateTokenCommand(name=name))
    return World(identity, ada)


async def users(world: World, query: dict[str, Any]) -> Page:
    page = await world.identity.list_users(UserListQuery.model_validate({"sort": "role", **query}))
    return page.users, page.next_cursor, page.total


async def tokens(world: World, query: dict[str, Any]) -> Page:
    page = await world.identity.list_tokens(
        world.ada, TokenListQuery.model_validate({"sort": "-name", **query})
    )
    return page.tokens, page.next_cursor, page.total


async def grants(world: World, query: dict[str, Any]) -> Page:
    page = await world.identity.list_library_grants(
        ListLibraryGrantsQuery.model_validate(
            {"caller_id": world.ada.id, "library": LIBRARY, "sort": "-role", **query}
        )
    )
    return page.grants, page.next_cursor, page.total


async def library_log(world: World, query: dict[str, Any]) -> Page:
    page = await world.identity.list_library_access_log(
        ListLibraryAccessLogQuery.model_validate(
            {"caller_id": world.ada.id, "library": LIBRARY, **query}
        )
    )
    return page.events, page.next_cursor, page.total


async def instance_log(world: World, query: dict[str, Any]) -> Page:
    page = await world.identity.list_access_log(
        ListAccessLogQuery.model_validate(
            {"caller_id": world.ada.id, "change": ["granted"], **query}
        )
    )
    return page.events, page.next_cursor, page.total


LISTS = [
    pytest.param(users, id="users"),
    pytest.param(tokens, id="tokens"),
    pytest.param(grants, id="grants"),
    pytest.param(library_log, id="library access log"),
    pytest.param(instance_log, id="access log"),
]


async def cursor_walk(world: World, fetch: Fetch) -> list[Any]:
    found, cursor = [], None
    while True:
        items, cursor, _ = await fetch(world, {"limit": 2, "cursor": cursor})
        found += items
        if cursor is None:
            return found


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_at_an_offset_is_the_slice_of_the_cursor_walk(
    world: World, fetch: Fetch
) -> None:
    walked = await cursor_walk(world, fetch)
    assert len(walked) > 3

    for offset in range(len(walked) + 2):
        items, next_cursor, total = await fetch(world, {"limit": 3, "offset": offset})

        assert items == walked[offset : offset + 3], offset
        assert total == len(walked)
        assert (next_cursor is None) == (offset + 3 >= len(walked))


@pytest.mark.parametrize("fetch", LISTS)
async def test_the_cursor_of_a_page_at_an_offset_goes_on_from_its_last_item(
    world: World, fetch: Fetch
) -> None:
    walked = await cursor_walk(world, fetch)
    _, next_cursor, _ = await fetch(world, {"limit": 2, "offset": 1})

    items, _, _ = await fetch(world, {"limit": 2, "cursor": next_cursor})

    assert items == walked[3:5]


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_after_a_cursor_and_at_an_offset_is_refused(
    world: World, fetch: Fetch
) -> None:
    _, cursor, _ = await fetch(world, {"limit": 1})

    with pytest.raises(CursorWithOffsetError):
        await fetch(world, {"limit": 1, "cursor": cursor, "offset": 0})


@pytest.mark.parametrize("fetch", LISTS)
@pytest.mark.parametrize("offset", [-1, MAX_OFFSET + 1])
async def test_an_offset_out_of_bounds_is_refused(world: World, fetch: Fetch, offset: int) -> None:
    with pytest.raises(ValidationError, match="offset"):
        await fetch(world, {"offset": offset})
