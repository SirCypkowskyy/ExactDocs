"""Adapter contract: every ``AccessLog`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryAccessLog
from exactdocs.identity.adapters.driven.sqlite import SqliteAccessLog
from exactdocs.identity.models import (
    AccessChange,
    AccessEvent,
    AccessLogFilter,
    AccountId,
    LibraryRole,
    SubjectKind,
)
from exactdocs.identity.ports import AccessLog

LIBRARY = "/acme/payments"
OTHER = "/acme/ledger"
AT = datetime(2026, 11, 22, 9, 30, 15, 123456, tzinfo=UTC)


def granted(library: str = LIBRARY, subject: str = "bob", n: int = 0) -> AccessEvent:
    return AccessEvent(
        id=str(uuid7()),
        library=library,
        at=AT + timedelta(seconds=n),
        actor=AccountId("alice"),
        change=AccessChange.GRANTED,
        kind=SubjectKind.USER,
        subject=subject,
        role=LibraryRole.CONTRIBUTOR,
        previous_role=LibraryRole.VIEWER,
    )


def deleted(library: str = LIBRARY) -> AccessEvent:
    return AccessEvent(
        id=str(uuid7()), library=library, at=AT, actor=None, change=AccessChange.LIBRARY_DELETED
    )


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def log(request: pytest.FixtureRequest) -> AsyncIterator[AccessLog]:
    if request.param == "memory":
        yield InMemoryAccessLog()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        yield SqliteAccessLog(engine=container.engine)


async def test_an_event_reads_back_as_it_was_recorded(log: AccessLog) -> None:
    event, gone = granted(), deleted()
    await log.record(event)
    await log.record(gone)

    assert await log.newest(AccessLogFilter(), older_than=None, limit=10) == [gone, event]


async def test_events_are_filtered_by_library_change_and_age(log: AccessLog) -> None:
    first, other, gone, last = granted(), granted(OTHER), deleted(), granted(n=1)
    for event in (first, other, gone, last):
        await log.record(event)

    mine = AccessLogFilter(library=LIBRARY)
    assert await log.newest(mine, older_than=None, limit=10) == [last, gone, first]
    assert await log.count(mine) == 3
    deletions = AccessLogFilter(changes=frozenset({AccessChange.LIBRARY_DELETED}))
    assert await log.newest(deletions, older_than=None, limit=10) == [gone]
    since = AccessLogFilter(library=LIBRARY, newer_than=gone.id)
    assert await log.newest(since, older_than=None, limit=10) == [last]
    assert await log.count(since) == 1
    assert await log.count(AccessLogFilter(library="/nobody/here")) == 0


async def test_pages_follow_the_id_newest_first(log: AccessLog) -> None:
    events = [granted(subject=f"user-{n}", n=n) for n in range(5)]
    for event in events:
        await log.record(event)

    page = await log.newest(AccessLogFilter(), older_than=None, limit=2)
    rest = await log.newest(AccessLogFilter(), older_than=page[-1].id, limit=10)

    assert page + rest == events[::-1]
