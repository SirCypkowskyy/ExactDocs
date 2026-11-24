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
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.models import Account, AccountId, Role, Session, Username, hash_token
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JobKind
from exactdocs.ingestion.models import Job, JobId, JobState
from steps.http_steps import DEMO_LIBRARIES

START = datetime(2026, 1, 1, tzinfo=UTC)
NOT_A_HASH = "not-a-hash"
# Ends the setup state (the API refuses everything before an account exists). A session planted
# directly signs it in: these steps are not about signing in.
ADMIN_COOKIE = "admin-session-cookie"
PLACEHOLDER_ADMIN = Account(
    id=AccountId("00000000000000000000000000000001"),
    username=Username("admin"),
    password_hash=NOT_A_HASH,
    role=Role.ADMIN,
    created_at=START,
)


def _queued(context: Context, job_id: str, library: str) -> Job:
    context.jobs_created = getattr(context, "jobs_created", 0) + 1
    created = START + timedelta(minutes=context.jobs_created)
    return Job.queued(
        job_id=JobId(job_id), kind=JobKind("import"), library=library, version=None, now=created
    )


def _store(context: Context, job: Job) -> None:
    repository = SqliteJobRepository(engine=context.container.engine)
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
    accounts = SqliteAccountRepository(engine=context.container.engine)
    context.client.portal.call(accounts.add_first, PLACEHOLDER_ADMIN)
    session = Session(
        token_hash=hash_token(ADMIN_COOKIE),
        account_id=PLACEHOLDER_ADMIN.id,
        created_at=datetime.now(UTC),
        last_used_at=datetime.now(UTC),
    )
    sessions = SqliteSessionRepository(engine=context.container.engine)
    context.client.portal.call(sessions.add, session)
    context.client.cookies.set(SESSION_COOKIE, ADMIN_COOKIE)


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


@given('{count:d} finished jobs of "{library}"')
def step_many_finished_jobs(context: Context, count: int, library: str) -> None:
    finished = []
    for n in range(count):
        queued = _queued(context, f"job-{n:04d}", library)
        finished.append(queued.started(queued.created_at).succeeded(queued.created_at))
    repository = SqliteJobRepository(engine=context.container.engine)

    async def store_all() -> None:
        for job in finished:
            await repository.add(job)

    context.client.portal.call(store_all)  # one hop to the app's event loop, not one per job


@when("I list the jobs {limit:d} at a time, skipping the first {offset:d}")
def step_list_jobs_at_offset(context: Context, limit: int, offset: int) -> None:
    context.page_size = limit
    context.response = context.client.get("/api/v1/jobs", params={"limit": limit, "offset": offset})


@when("I list the jobs with both a cursor and an offset")
def step_list_jobs_with_cursor_and_offset(context: Context) -> None:
    first = context.client.get("/api/v1/jobs", params={"limit": 1}).json()
    assert first["next_cursor"] is not None, first
    context.response = context.client.get(
        "/api/v1/jobs", params={"limit": 1, "cursor": first["next_cursor"], "offset": 1}
    )


@then("I get the last {count:d} jobs, in the order a page-by-page walk gives them")
def step_last_jobs_of_the_walk(context: Context, count: int) -> None:
    walked, cursor = [], None
    while True:
        params = {"limit": context.page_size} | ({"cursor": cursor} if cursor else {})
        body = context.client.get("/api/v1/jobs", params=params).json()
        walked += [job["id"] for job in body["jobs"]]
        if (cursor := body["next_cursor"]) is None:
            break
    page = context.response.json()
    assert [job["id"] for job in page["jobs"]] == walked[-count:], page
    assert page["next_cursor"] is None, page


@then("the total is {total:d} jobs")
def step_job_total(context: Context, total: int) -> None:
    assert context.response.json()["total"] == total


@given("these jobs were queued:")
def step_jobs_on_days(context: Context) -> None:
    stored = []
    for n, row in enumerate(context.table or []):
        day = datetime.fromisoformat(row["day"]).replace(hour=12, minute=n, tzinfo=UTC)
        queued = Job.queued(
            job_id=JobId(f"job-{n:04d}"),
            kind=JobKind(row["kind"]),
            library="/acme/payments",
            version=None,
            now=day,
        ).started(day)
        state = JobState(row["state"])
        stored.append(queued.succeeded(day) if state is JobState.SUCCEEDED else
                      queued.failed("the repository is gone", day))  # fmt: skip
    repository = SqliteJobRepository(engine=context.container.engine)

    async def store_all() -> None:
        for job in stored:
            await repository.add(job)

    context.client.portal.call(store_all)


@when("the operator asks for the jobs per day from {start} to {end}")
def step_job_stats(context: Context, start: str, end: str) -> None:
    context.response = context.client.get(
        "/api/v1/stats/jobs", params={"bucket": "day", "from": start, "to": end}
    )


@then("the jobs per day are:")
def step_jobs_per_day(context: Context) -> None:
    days = {day["day"]: day for day in context.response.json()["days"]}
    rows = list(context.table or [])
    assert list(days) == [row["day"] for row in rows], days
    for row in rows:
        day = days[row["day"]]
        assert day["total"] == int(row["total"]), day
        for state in ("succeeded", "failed"):
            assert day["by_state"][state] == int(row[state]), day
        for kind in ("import", "embed"):
            assert day["by_kind"][kind] == int(row[kind]), day


@given("the demo libraries")
def step_demo_libraries(context: Context) -> None:
    repository = SqliteLibraryRepository(engine=context.container.engine)

    async def store_all() -> None:
        for library in DEMO_LIBRARIES:
            await repository.save(library)

    context.client.portal.call(store_all)


def _sync(context: Context, library: str, *, failed: bool) -> None:
    queued = _queued(context, f"sync-{getattr(context, 'jobs_created', 0):04d}", library)
    started = queued.started(queued.created_at)
    if failed:
        _store(context, started.failed("the repository is gone", queued.created_at))
    else:
        _store(context, started.succeeded(queued.created_at))


@given('the latest sync of "{library}" failed after an earlier one succeeded')
def step_latest_sync_failed(context: Context, library: str) -> None:
    _sync(context, library, failed=False)
    _sync(context, library, failed=True)


@given('the latest sync of "{library}" succeeded')
def step_latest_sync_succeeded(context: Context, library: str) -> None:
    _sync(context, library, failed=False)


@when("I list the libraries whose latest sync failed")
def step_list_failed_libraries(context: Context) -> None:
    context.response = context.client.get("/api/v1/libraries", params={"sync_state": "failed"})


@then('the libraries listed are "{ids}"')
def step_listed_libraries(context: Context, ids: str) -> None:
    expected = [item.strip().strip('"') for item in ids.split(",")]
    body = context.response.json()
    assert [library["id"] for library in body["libraries"]] == expected, body


@then("the total is {total:d} library")
def step_library_total(context: Context, total: int) -> None:
    assert context.response.json()["total"] == total
