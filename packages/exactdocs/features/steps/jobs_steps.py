"""Steps for background jobs: the job is seeded through the repository, read over HTTP."""

import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.models import Job, JobId, JobKind

START = datetime(2026, 1, 1, tzinfo=UTC)


def _queued(context: Context, job_id: str, library: str) -> Job:
    context.jobs_created = getattr(context, "jobs_created", 0) + 1
    created = START + timedelta(minutes=context.jobs_created)
    return Job.queued(
        job_id=JobId(job_id), kind=JobKind("import"), library=library, version=None, now=created
    )


def _store(context: Context, job: Job) -> None:
    repository = SqliteJobRepository(context.container.engine)
    context.client.portal.call(repository.add, job)  # runs on the app's own event loop


@given("ExactDocs is running")
def step_running(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)  # runs the app's shutdown after the scenario
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.container = Container.build(Settings(data_dir=data_dir))
    context.client = stack.enter_context(
        TestClient(create_app(context.container), base_url="http://localhost")
    )


@given('a job over {total:d} files of "{library}" that has finished {done:d}')
def step_job_in_progress(context: Context, total: int, library: str, done: int) -> None:
    queued = _queued(context, "import-1", library)
    context.job_id = queued.id
    _store(context, queued.started(queued.created_at).progressed(done=done, total=total))


@given('a finished job "{job_id}" of "{library}"')
def step_finished_job(context: Context, job_id: str, library: str) -> None:
    queued = _queued(context, job_id, library)
    _store(context, queued.started(queued.created_at).succeeded(queued.created_at))


@when("I request that job")
def step_get_job(context: Context) -> None:
    context.response = context.client.get(f"/api/v1/jobs/{context.job_id}")


@when('I request the job "{job_id}"')
def step_get_unknown_job(context: Context, job_id: str) -> None:
    context.response = context.client.get(f"/api/v1/jobs/{job_id}")


@when('I list the jobs of the library "{library}"')
def step_list_jobs(context: Context, library: str) -> None:
    context.response = context.client.get(f"/api/v1/libraries{library}/jobs")


@then("the job is running with {done:d} of {total:d} files done")
def step_progress(context: Context, done: int, total: int) -> None:
    body = context.response.json()
    assert (body["state"], body["done"], body["total"]) == ("running", done, total), body


@then("the jobs are, newest first: {ids}")
def step_job_ids(context: Context, ids: str) -> None:
    expected = [item.strip().strip('"') for item in ids.split(",")]
    assert [job["id"] for job in context.response.json()["jobs"]] == expected
