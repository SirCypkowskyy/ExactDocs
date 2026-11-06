"""Adapter contract: every ``AutoSyncStore`` behaves the same, whatever stores the data."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.memory import InMemoryAutoSyncStore
from exactdocs.ingestion.adapters.driven.sqlite import SqliteAutoSyncStore
from exactdocs.ingestion.models import AutoSync
from exactdocs.ingestion.ports import AutoSyncStore

T0 = datetime(2026, 11, 6, 9, 0, 0, 123456, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[AutoSyncStore]:
    if request.param == "memory":
        yield InMemoryAutoSyncStore()
        return
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteAutoSyncStore(engine)
    await engine.dispose()


async def test_starts_empty(store: AutoSyncStore) -> None:
    assert await store.get("/acme/docs") is None
    assert await store.list_all() == []


async def test_every_field_survives_a_round_trip(store: AutoSyncStore) -> None:
    saved = AutoSync(
        library="/acme/docs",
        tag_pattern="v*",
        keep_last=3,
        interval_minutes=90,
        sync_branches=True,
    ).checked(T0, "tags not checked: unreachable")

    await store.save(saved)

    assert await store.get("/acme/docs") == saved


async def test_saving_again_replaces_and_delete_forgets(store: AutoSyncStore) -> None:
    await store.save(AutoSync(library="/acme/b", tag_pattern="v*"))
    await store.save(AutoSync(library="/acme/a", sync_branches=True))
    replaced = AutoSync(library="/acme/b", tag_pattern=None, keep_last=1)

    await store.save(replaced)
    assert [s.library for s in await store.list_all()] == ["/acme/a", "/acme/b"]
    assert await store.get("/acme/b") == replaced

    await store.delete("/acme/b")
    await store.delete("/acme/unknown")
    assert [s.library for s in await store.list_all()] == ["/acme/a"]


async def test_a_check_is_recorded_only_on_the_schedule_it_read(store: AutoSyncStore) -> None:
    read = AutoSync(library="/acme/docs", tag_pattern="v*", revision="r1")
    await store.save(read)

    assert await store.record_check(read, read.checked(T0, None))
    recorded = await store.get("/acme/docs")
    assert recorded == read.checked(T0, None)

    # Saved again with the same values (a new revision) while a second check ran.
    resaved = AutoSync(library="/acme/docs", tag_pattern="v*", revision="r2")
    await store.save(resaved)
    assert recorded is not None
    assert not await store.record_check(recorded, recorded.checked(T0, "late"))
    assert await store.get("/acme/docs") == resaved

    await store.delete("/acme/docs")
    assert not await store.record_check(resaved, resaved.checked(T0, None))
    assert await store.get("/acme/docs") is None
