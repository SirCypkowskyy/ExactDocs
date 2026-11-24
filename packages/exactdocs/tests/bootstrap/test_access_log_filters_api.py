"""Both access logs over HTTP sort and filter by actor, subject and date (#514), on both databases.

The filters compose with each other, with `change` and `library`, with `offset` and with the
cursor; a cursor only goes on with the `sort` it was made for.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid7

import httpx
import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, VersionRef
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccessLog,
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.models import (
    AccessChange,
    AccessEvent,
    Account,
    AccountId,
    LibraryRole,
    Role,
    Session,
    SubjectKind,
    Username,
    hash_token,
)

NOW = datetime.now(UTC).replace(microsecond=0)
PAYMENTS = "/acme/payments"
LEDGER = "/acme/ledger"
GLOBAL = "/api/v1/access-log"
LOCAL = f"/api/v1/libraries{PAYMENTS}/access-log"
COOKIE = "access-log-filters-session"
NOT_A_HASH = "not-a-hash"  # nobody signs in with a password: the session is planted
PEOPLE = {"ada": Role.ADMIN, "alice": Role.USER, "bob": Role.USER, "carol": Role.USER}
ID = {name: AccountId(f"{n + 1:032d}") for n, name in enumerate(PEOPLE)}
GONE = AccountId("f" * 32)  # an account that no longer exists: the log shows its ID

# (days ago, library, actor, kind, subject, change, role)
HISTORY = [
    (10, PAYMENTS, "alice", "user", "bob", "granted", "viewer"),
    (6, PAYMENTS, "alice", "user", "bob", "granted", "contributor"),
    (5, LEDGER, "alice", "user", "bob", "granted", "viewer"),
    (4, PAYMENTS, "carol", "user", "bob", "granted", "admin"),
    (4, PAYMENTS, "alice", "group", "bob", "granted", "viewer"),
    (3, PAYMENTS, "alice", "user", "carol", "granted", "admin"),
    (2, PAYMENTS, GONE, "user", GONE, "revoked", "viewer"),
    (1, PAYMENTS, "alice", "user", "bob", "revoked", "admin"),
]


def days_ago(n: int) -> str:
    return (NOW - timedelta(days=n)).isoformat()


async def seed(container: Container) -> None:
    accounts = SqliteAccountRepository(engine=container.engine)
    for n, (name, role) in enumerate(PEOPLE.items()):
        added = Account(
            id=ID[name],
            username=Username(name),
            password_hash=NOT_A_HASH,
            role=role,
            created_at=NOW - timedelta(days=30, minutes=-n),
        )
        assert await (accounts.add_first(added) if n == 0 else accounts.add(added))
    session = Session(
        token_hash=hash_token(COOKIE), account_id=ID["ada"], created_at=NOW, last_used_at=NOW
    )
    await SqliteSessionRepository(engine=container.engine).add(session)
    await SqliteLibraryRepository(engine=container.engine).save(
        Library(
            id=LibraryId(PAYMENTS),
            title="Payments",
            source_url="https://git.example.com/acme/payments.git",
            host=HostKind.GIT,
            default_branch=VersionRef("main"),
        )
    )
    log = SqliteAccessLog(engine=container.engine)
    for days, library, actor, kind, subject, change, role in HISTORY:
        await log.record(
            AccessEvent(
                id=str(uuid7()),
                library=library,
                at=NOW - timedelta(days=days),
                actor=ID.get(actor, AccountId(actor)),
                change=AccessChange(change),
                kind=SubjectKind(kind),
                subject=ID.get(subject, subject) if kind == "user" else subject,
                role=LibraryRole(role),
            )
        )


@pytest.fixture(params=SQL_BACKENDS)
async def client(request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", cookies={SESSION_COOKIE: COOKIE}
        ) as client,
    ):
        await seed(container)
        yield client


async def events(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def shown(body: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(e["library"], e["actor"], e["kind"], e["subject"], e["role"]) for e in body["events"]]


@pytest.mark.parametrize("path", [GLOBAL, LOCAL])
async def test_actor_subject_and_dates_filter_and_the_sort_orders(
    client: httpx.AsyncClient, path: str
) -> None:
    only_payments = {"library": PAYMENTS} if path == GLOBAL else {}
    body = await events(
        client,
        path,
        **only_payments,
        actor="ALICE",
        subject="bob",
        at_after=days_ago(7),
        at_before=days_ago(1),
        sort="at",
    )

    assert shown(body) == [
        (PAYMENTS, "alice", "user", "bob", "contributor"),
        (PAYMENTS, "alice", "group", "bob", "viewer"),
    ]
    assert (body["total"], body["next_cursor"]) == (2, None)
    newest = await events(client, path, **only_payments, subject="bob", at_after=days_ago(7))
    assert [e["actor"] for e in newest["events"]] == ["alice", "alice", "carol", "alice"]
    assert [e["at"] for e in newest["events"]] == sorted(
        (e["at"] for e in newest["events"]), reverse=True
    )


async def test_the_global_log_filters_across_libraries_and_the_library_log_stays_in_its_own(
    client: httpx.AsyncClient,
) -> None:
    every = await events(client, GLOBAL, actor="alice", subject="bob", sort="-library")
    mine = await events(client, LOCAL, actor="alice", subject="bob", sort="-library")

    assert [e["library"] for e in every["events"]] == [PAYMENTS] * 4 + [LEDGER]
    assert every["total"] == 5
    assert [e["library"] for e in mine["events"]] == [PAYMENTS] * 4


async def test_a_gone_account_is_found_by_the_id_the_log_shows(client: httpx.AsyncClient) -> None:
    by_actor = await events(client, GLOBAL, actor=GONE)
    about = await events(client, LOCAL, subject=GONE, change="revoked")

    assert shown(by_actor) == [(PAYMENTS, GONE, "user", GONE, "viewer")]
    assert about["events"] == by_actor["events"]
    assert (await events(client, GLOBAL, actor="nobody"))["total"] == 0


@pytest.mark.parametrize("path", [GLOBAL, LOCAL])
async def test_the_filtered_sorted_log_pages_by_cursor_and_offset_alike(
    client: httpx.AsyncClient, path: str
) -> None:
    params = {"subject": "bob", "at_before": days_ago(1), "sort": "change"}
    whole = await events(client, path, **params, limit=50)
    walked, cursor = [], None
    while True:
        body = await events(
            client, path, **params, limit=2, **({"cursor": cursor} if cursor else {})
        )
        walked += body["events"]
        assert body["total"] == whole["total"]
        if (cursor := body["next_cursor"]) is None:
            break

    assert walked == whole["events"]
    assert len(walked) >= 3
    jumped = await events(client, path, **params, limit=2, offset=1)
    assert jumped["events"] == walked[1:3]


@pytest.mark.parametrize("path", [GLOBAL, LOCAL])
async def test_a_wrong_sort_cursor_or_date_is_a_422(client: httpx.AsyncClient, path: str) -> None:
    first = await events(client, path, sort="at", limit=1)
    cases = [
        ({"sort": "actor"}, "invalid_sort"),
        ({"sort": "-at", "cursor": first["next_cursor"]}, "invalid_cursor"),
        ({"cursor": first["next_cursor"]}, "invalid_cursor"),  # the default sort is `-at`
        ({"at_after": "last week"}, "validation_error"),
        ({"actor": ""}, "validation_error"),
        ({"subject": "x" * 1000}, "validation_error"),
    ]
    for params, error in cases:
        refused = await client.get(path, params=params)

        assert (refused.status_code, refused.json()["error"]) == (422, error), params
