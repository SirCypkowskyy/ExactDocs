"""The jobs over HTTP, and the worker that starts with the app."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import migrate
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.dtos import GetJobQuery
from exactdocs.ingestion.models import Job, JobId, JobState, ProblemCode

pytestmark = pytest.mark.usefixtures("demo_catalog")  # also ends the setup state

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def a_job(job_id: str, library: str = "/acme/payments", kind: str = "import") -> Job:
    return Job.queued(
        job_id=JobId(job_id), kind=JobKind(kind), library=library, version="1.4", now=NOW
    )


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(container))
    # ASGITransport does not run the app's lifespan, which migrates the database.
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", cookies=demo_catalog
        ) as client,
    ):
        yield client


async def test_an_unknown_job_is_a_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/jobs/nope")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_a_library_without_jobs_has_an_empty_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/acme/payments/jobs")

    assert response.status_code == 200
    assert response.json() == {"jobs": [], "next_cursor": None}


async def test_a_library_lists_its_jobs_newest_first_in_pages(
    container: Container, client: httpx.AsyncClient
) -> None:
    repository = SqliteJobRepository(engine=container.engine)
    for job_id in ("job-1", "job-2", "job-3"):
        await repository.add(a_job(job_id).started(NOW).succeeded(NOW))
    url = "/api/v1/libraries/acme/payments/jobs"

    first = (await client.get(url, params={"limit": 2})).json()
    second = (await client.get(url, params={"limit": 2, "cursor": first["next_cursor"]})).json()

    assert [job["id"] for job in first["jobs"]] == ["job-3", "job-2"]
    assert [job["id"] for job in second["jobs"]] == ["job-1"]
    assert second["next_cursor"] is None


async def test_the_limit_of_the_job_list_is_validated(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/acme/payments/jobs", params={"limit": 0})

    assert response.status_code == 422


async def test_the_worker_starts_with_the_app_and_recovers_what_the_last_run_left() -> None:
    # No job kind is registered yet, so a recovered job is picked up and failed for that reason:
    # proof that the lifespan ran recovery and the worker.
    first = Container.build(Settings())
    await migrate(first.engine)
    await SqliteJobRepository(engine=first.engine).add(a_job("j1", kind="gone").started(NOW))
    await first.engine.dispose()

    second = Container.build(Settings())
    async with second.running():
        for _ in range(500):
            job = await second.ingestion.get_job(GetJobQuery(job_id="j1"))
            if job.state is JobState.FAILED:
                break
            await asyncio.sleep(0.01)

    assert job.state is JobState.FAILED
    assert job.error == "no handler is registered for job kind 'gone'"


async def test_a_process_started_without_jobs_neither_recovers_nor_runs_them() -> None:
    """`serve --stdio` leaves the jobs to the HTTP server."""
    first = Container.build(Settings())
    await migrate(first.engine)
    await SqliteJobRepository(engine=first.engine).add(a_job("j1", kind="gone").started(NOW))
    await first.engine.dispose()

    second = Container.build(Settings())
    async with second.running(jobs=False):
        await asyncio.sleep(0.1)
        job = await second.ingestion.get_job(GetJobQuery(job_id="j1"))

    assert job.state is JobState.RUNNING


async def test_the_latest_jobs_are_one_per_version_and_say_how_many_files_were_skipped(
    container: Container, client: httpx.AsyncClient
) -> None:
    repository = SqliteJobRepository(engine=container.engine)
    await repository.add(a_job("job-1").started(NOW).failed("old failure", NOW))
    await repository.add(
        a_job("job-2")
        .started(NOW)
        .with_problem("docs/a.md", ProblemCode.FRONT_MATTER, "invalid front matter")
        .with_problem("docs/b.md", ProblemCode.UNDECODABLE, "not text")
        .succeeded(NOW)
    )
    await repository.add(a_job("job-3", library="/acme/ledger").started(NOW).failed("boom", NOW))

    response = await client.get("/api/v1/jobs/latest")

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [(j["library"], j["state"], j["skipped"], j["error"]) for j in jobs] == [
        ("/acme/ledger", "failed", 0, "boom"),
        ("/acme/payments", "succeeded", 1, None),  # a note on an imported file is not a skip,
    ]
    assert all("problems" not in j for j in jobs)


async def test_the_latest_jobs_need_a_session(container: Container) -> None:
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as anonymous,
    ):
        response = await anonymous.get("/api/v1/jobs/latest")

    assert response.status_code == 401
