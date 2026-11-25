"""Jumping to any page of the job lists (#509), global and per library, on the in-memory store."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.dtos import ListJobsQuery, ListLibraryJobsQuery
from exactdocs.ingestion.models import Job, JobId
from exactdocs.ingestion.use_cases import ListJobsUseCase, ListLibraryJobsUseCase
from exactdocs_kernel import MAX_OFFSET, CursorWithOffsetError
from library_access import FakeAccess

START = datetime(2026, 1, 1, tzinfo=UTC)

type Page = tuple[list[str], str | None, int]
type Fetch = Callable[[InMemoryJobRepository, dict[str, Any]], Awaitable[Page]]


@pytest.fixture
async def jobs() -> InMemoryJobRepository:
    jobs = InMemoryJobRepository()
    for n in range(11):
        job = Job.queued(
            job_id=JobId(f"job-{n:02d}"),
            kind=JobKind(("import", "embed", "rechunk")[n % 3]),
            library=("/acme/payments", "/acme/ledger")[n % 2],
            version=None,
            now=START + timedelta(minutes=n),
        )
        await jobs.add(job.started(job.created_at).succeeded(job.created_at) if n % 4 else job)
    return jobs


async def every_library(jobs: InMemoryJobRepository, query: dict[str, Any]) -> Page:
    listing = ListJobsUseCase(jobs=jobs, access=FakeAccess(role="viewer"))
    page = await listing(ListJobsQuery.model_validate({"sort": "kind", **query}))
    return [job.id for job in page.jobs], page.next_cursor, page.total


async def one_library(jobs: InMemoryJobRepository, query: dict[str, Any]) -> Page:
    listing = ListLibraryJobsUseCase(jobs=jobs, access=FakeAccess(role="viewer"))
    page = await listing(
        ListLibraryJobsQuery.model_validate({"library": "/acme/payments", **query})
    )
    return [job.id for job in page.jobs], page.next_cursor, page.total


async def filtered(jobs: InMemoryJobRepository, query: dict[str, Any]) -> Page:
    listing = ListJobsUseCase(jobs=jobs, access=FakeAccess(role="viewer"))
    page = await listing(
        ListJobsQuery.model_validate({"state": ["succeeded"], "sort": "-created_at", **query})
    )
    return [job.id for job in page.jobs], page.next_cursor, page.total


LISTS = [
    pytest.param(every_library, id="jobs"),
    pytest.param(one_library, id="library jobs"),
    pytest.param(filtered, id="filtered jobs"),
]


async def cursor_walk(jobs: InMemoryJobRepository, fetch: Fetch) -> list[str]:
    found, cursor = [], None
    while True:
        items, cursor, _ = await fetch(jobs, {"limit": 2, "cursor": cursor})
        found += items
        if cursor is None:
            return found


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_at_an_offset_is_the_slice_of_the_cursor_walk(
    jobs: InMemoryJobRepository, fetch: Fetch
) -> None:
    walked = await cursor_walk(jobs, fetch)
    assert len(walked) > 3

    for offset in range(len(walked) + 2):
        items, next_cursor, total = await fetch(jobs, {"limit": 3, "offset": offset})

        assert items == walked[offset : offset + 3], offset
        assert total == len(walked)
        assert (next_cursor is None) == (offset + 3 >= len(walked))


@pytest.mark.parametrize("fetch", LISTS)
async def test_the_cursor_of_a_page_at_an_offset_goes_on_from_its_last_item(
    jobs: InMemoryJobRepository, fetch: Fetch
) -> None:
    walked = await cursor_walk(jobs, fetch)
    _, next_cursor, _ = await fetch(jobs, {"limit": 2, "offset": 1})

    items, _, _ = await fetch(jobs, {"limit": 2, "cursor": next_cursor})

    assert items == walked[3:5]


@pytest.mark.parametrize("fetch", LISTS)
async def test_a_page_after_a_cursor_and_at_an_offset_is_refused(
    jobs: InMemoryJobRepository, fetch: Fetch
) -> None:
    _, cursor, _ = await fetch(jobs, {"limit": 1})

    with pytest.raises(CursorWithOffsetError):
        await fetch(jobs, {"limit": 1, "cursor": cursor, "offset": 0})


@pytest.mark.parametrize("fetch", LISTS)
@pytest.mark.parametrize("offset", [-1, MAX_OFFSET + 1])
async def test_an_offset_out_of_bounds_is_refused(
    jobs: InMemoryJobRepository, fetch: Fetch, offset: int
) -> None:
    with pytest.raises(ValidationError, match="offset"):
        await fetch(jobs, {"offset": offset})
