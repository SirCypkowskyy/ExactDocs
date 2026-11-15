"""A job queued from a request must not run as the caller of that request (library roles, #108)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from exactdocs.bootstrap.caller import bind_caller, current_account_id
from exactdocs.ingestion.adapters.driven import dbos as dbos_queue
from exactdocs.ingestion.adapters.driven.dbos import DbosJobQueue
from exactdocs.ingestion.models import Job, JobId, JobKind


async def test_a_job_queued_from_a_request_does_not_inherit_its_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def enqueue(*_: Any) -> None:
        seen.append(current_account_id())

    monkeypatch.setattr(dbos_queue.DBOS, "enqueue_workflow_with_options_async", enqueue)
    job = Job.queued(
        job_id=JobId("job-1"),
        kind=JobKind("sync"),
        library="/acme/payments",
        version=None,
        now=datetime(2026, 11, 4, tzinfo=UTC),
    )

    async def request() -> None:
        bind_caller("a-contributor")  # what a REST request does before its use case runs
        assert current_account_id() == "a-contributor"
        await DbosJobQueue().submit(job)

    await asyncio.create_task(request())  # its own context, as a request has

    assert seen == [None]
