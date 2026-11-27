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
    RoleRule,
    RuleGrant,
    RuleSource,
    SubjectKind,
)
from exactdocs.identity.ports import AccessLog
from exactdocs_kernel import Sort

NEWEST = Sort(field="at", descending=True)
OLDEST = Sort(field="at")

LIBRARY = "/acme/payments"
OTHER = "/acme/ledger"
AT = datetime(2026, 11, 22, 9, 30, 15, 123456, tzinfo=UTC)


def granted(
    library: str = LIBRARY,
    subject: str = "bob",
    n: int = 0,
    actor: str = "alice",
    kind: SubjectKind = SubjectKind.USER,
) -> AccessEvent:
    return AccessEvent(
        id=str(uuid7()),
        library=library,
        at=AT + timedelta(seconds=n),
        actor=AccountId(actor),
        change=AccessChange.GRANTED,
        kind=kind,
        subject=subject,
        role=LibraryRole.CONTRIBUTOR,
        previous_role=LibraryRole.VIEWER,
    )


def deleted(library: str = LIBRARY, n: int = 0) -> AccessEvent:
    return AccessEvent(
        id=str(uuid7()),
        library=library,
        at=AT + timedelta(seconds=n),
        actor=None,
        change=AccessChange.LIBRARY_DELETED,
    )


async def newest(log: AccessLog, where: AccessLogFilter, limit: int = 10) -> list[AccessEvent]:
    return await log.search(where, sort=NEWEST, after=None, limit=limit)


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

    assert await newest(log, AccessLogFilter()) == [gone, event]


async def test_events_are_filtered_by_library_change_and_age(log: AccessLog) -> None:
    first, other, gone, last = granted(), granted(OTHER), deleted(), granted(n=1)
    for event in (first, other, gone, last):
        await log.record(event)

    mine = AccessLogFilter(library=LIBRARY)
    assert await newest(log, mine) == [last, gone, first]
    assert await log.count(mine) == 3
    deletions = AccessLogFilter(changes=frozenset({AccessChange.LIBRARY_DELETED}))
    assert await newest(log, deletions) == [gone]
    since = AccessLogFilter(library=LIBRARY, newer_than=gone.id)
    assert await newest(log, since) == [last]
    assert await log.count(since) == 1
    assert await log.count(AccessLogFilter(library="/nobody/here")) == 0


def after(event: AccessEvent, sort: Sort) -> tuple[str, str]:
    return event.sort_value(sort.field), event.id


async def test_pages_follow_the_time_newest_first(log: AccessLog) -> None:
    events = [granted(subject=f"user-{n}", n=n) for n in range(5)]
    for event in events:
        await log.record(event)

    page = await log.search(AccessLogFilter(), sort=NEWEST, after=None, limit=2)
    rest = await log.search(AccessLogFilter(), sort=NEWEST, after=after(page[-1], NEWEST), limit=9)

    assert page + rest == events[::-1]


async def test_events_are_filtered_by_actor_subject_and_time(log: AccessLog) -> None:
    old = granted(n=-10)
    by_carol = granted(actor="carol", n=1)
    about_dave = granted(subject="dave", n=2)
    group = granted(kind=SubjectKind.GROUP, n=3)
    group_dave = granted(kind=SubjectKind.GROUP, subject="dave", n=4)
    last = granted(n=5)
    gone = deleted(n=6)
    for event in (old, by_carol, about_dave, group, group_dave, last, gone):
        await log.record(event)

    alice = AccessLogFilter(actor=AccountId("alice"))
    bob = AccessLogFilter(
        subjects=frozenset({(SubjectKind.USER, "bob"), (SubjectKind.GROUP, "bob")})
    )
    bob_user = AccessLogFilter(subjects=frozenset({(SubjectKind.USER, "bob")}))
    recent = AccessLogFilter(
        at_after=AT + timedelta(seconds=1), at_before=AT + timedelta(seconds=5)
    )
    together = AccessLogFilter(
        actor=AccountId("alice"),
        subjects=frozenset({(SubjectKind.USER, "bob"), (SubjectKind.GROUP, "bob")}),
        at_after=AT,
        library=LIBRARY,
        changes=frozenset({AccessChange.GRANTED}),
    )

    assert await newest(log, alice) == [last, group_dave, group, about_dave, old]
    assert await newest(log, bob) == [last, group, by_carol, old]
    assert await newest(log, bob_user) == [last, by_carol, old]
    assert await newest(log, recent) == [group_dave, group, about_dave, by_carol]
    assert await newest(log, together) == [last, group]
    assert await newest(log, AccessLogFilter(subjects=frozenset())) == []
    counts = [await log.count(w) for w in (alice, bob, bob_user, recent, together)]
    assert counts == [5, 4, 3, 4, 2]


async def test_events_sort_by_time_library_or_change_both_ways(log: AccessLog) -> None:
    late = granted(n=3)
    early_other = granted(OTHER, n=1)
    gone = deleted(n=2)
    same_time = granted(OTHER, subject="carol", n=1)  # ties with early_other, recorded after it
    for event in (late, early_other, gone, same_time):
        await log.record(event)
    every = AccessLogFilter()

    async def order(sort: Sort) -> list[AccessEvent]:
        return await log.search(every, sort=sort, after=None, limit=10)

    assert await order(OLDEST) == [early_other, same_time, gone, late]
    assert await order(NEWEST) == [late, gone, same_time, early_other]
    assert await order(Sort(field="library")) == [early_other, same_time, late, gone]
    assert await order(Sort(field="library", descending=True)) == [
        gone,
        late,
        same_time,
        early_other,
    ]
    assert await order(Sort(field="change")) == [late, early_other, same_time, gone]
    assert await order(Sort(field="change", descending=True)) == [
        gone,
        same_time,
        early_other,
        late,
    ]


async def test_a_keyset_walk_and_an_offset_agree_under_every_sort(log: AccessLog) -> None:
    for n in range(7):
        await log.record(granted(OTHER if n % 2 else LIBRARY, subject=f"user-{n}", n=n % 3))
        await log.record(deleted(n=n % 3))
    where = AccessLogFilter(changes=frozenset({AccessChange.GRANTED, AccessChange.LIBRARY_DELETED}))

    for field in ("at", "library", "change"):
        for descending in (False, True):
            sort = Sort(field=field, descending=descending)
            whole = await log.search(where, sort=sort, after=None, limit=100)
            walked: list[AccessEvent] = []
            while len(
                page := await log.search(
                    where, sort=sort, after=after(walked[-1], sort) if walked else None, limit=3
                )
            ):
                walked += page
            jumped = await log.search(where, sort=sort, after=None, limit=3, offset=6)
            assert walked == whole, sort
            assert jumped == whole[6:9], sort
            assert len(whole) == await log.count(where) == 14


async def test_a_rule_event_keeps_the_rule_as_it_was(log: AccessLog) -> None:
    rule = RoleRule(
        id="r1",
        provider="gh",
        source=RuleSource.GITHUB_TEAM,
        value="acme/docs-writers",
        grant=RuleGrant.CONTRIBUTOR,
        libraries=frozenset({LIBRARY, OTHER}),
        created_by=AccountId("alice"),
        created_at=AT,
    )
    event = AccessEvent(
        id=str(uuid7()),
        library="",
        at=AT,
        actor=AccountId("alice"),
        change=AccessChange.RULE_ADDED,
        rule=rule,
    )
    await log.record(event)

    assert await newest(log, AccessLogFilter()) == [event]
    assert await newest(log, AccessLogFilter(library=LIBRARY)) == []
