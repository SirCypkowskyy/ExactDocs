"""Who queued a job, the `origin` and `sync_state` filters and `GET /stats/jobs` (#512), over HTTP.

On both databases: the person is the account of the request (a session or an API token, its ID
and user name and nothing else), the library filter composes with `offset` and the cursor, and
the statistics are for operators only, every day of a bounded range listed.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind, Version, VersionRef
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqliteSessionRepository,
)
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.models import Account, AccountId, Role, Session, Username, hash_token
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.constants import JOB_KINDS, MAX_STATS_DAYS, JobKind
from exactdocs.ingestion.models import Job, JobId, JobState, VersionOrigin

DAY = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
ADMIN_COOKIE = "job-stats-admin"
USER_COOKIE = "job-stats-user"
NOT_A_HASH = "not-a-hash"
ADA = AccountId(f"{1:032d}")
BOB = AccountId(f"{2:032d}")
# The latest sync (newest import or refresh) of each library; `/acme/empty` never synced.
SYNCS = {
    "/acme/alpha": [JobState.SUCCEEDED, JobState.FAILED],
    "/acme/beta": [JobState.FAILED],
    "/acme/gamma": [JobState.FAILED, JobState.SUCCEEDED],
    "/acme/delta": [JobState.FAILED],
    "/acme/epsilon": [JobState.FAILED],
    "/acme/zeta": [JobState.QUEUED],
}
FAILED = ["/acme/alpha", "/acme/beta", "/acme/delta", "/acme/epsilon"]


def library(lib_id: str) -> Library:
    sha = hashlib.sha1(lib_id.encode(), usedforsecurity=False).hexdigest()
    return Library(
        id=LibraryId(lib_id),
        title=lib_id.rsplit("/", 1)[-1].title(),
        source_url=f"https://git.example.com{lib_id}.git",
        host=HostKind.GIT,
        default_branch=VersionRef("main"),
        versions=frozenset(
            {Version(ref=VersionRef("main"), kind=RefKind.BRANCH, commit_sha=sha, imported_at=DAY)}
        ),
    )


def ended(job: Job, state: JobState) -> Job:
    if state is JobState.QUEUED:
        return job
    started = job.started(job.created_at)
    if state is JobState.SUCCEEDED:
        return started.succeeded(job.created_at)
    return started.failed("the repository is gone", job.created_at)


async def seed(container: Container) -> None:
    libraries = SqliteLibraryRepository(engine=container.engine)
    for lib_id in [*SYNCS, "/acme/empty"]:
        await libraries.save(library(lib_id))
    jobs = SqliteJobRepository(engine=container.engine)
    n = 0
    for lib_id, states in SYNCS.items():
        for state in states:
            queued = Job.queued(
                job_id=JobId(f"job-{n:02d}"),
                kind=JobKind("refresh" if n % 2 else "import"),
                library=lib_id,
                version="main",
                now=DAY + timedelta(minutes=n),
                origin=VersionOrigin.AUTO if n % 3 == 0 else VersionOrigin.MANUAL,
            )
            await jobs.add(ended(queued, state))
            n += 1
    # A newer job that is no sync: it never decides a library's sync state.
    embed = Job.queued(
        job_id=JobId("job-99"),
        kind=JobKind("embed"),
        library="/acme/gamma",
        version="main",
        now=DAY + timedelta(days=1),
        origin=VersionOrigin.AUTO,
    )
    await jobs.add(ended(embed, JobState.FAILED))


async def sign_in(container: Container, client: httpx.AsyncClient) -> None:
    accounts = SqliteAccountRepository(engine=container.engine)
    assert await accounts.add_first(
        Account(
            id=ADA,
            username=Username("ada"),
            password_hash=NOT_A_HASH,
            role=Role.ADMIN,
            created_at=DAY,
        )
    )
    assert await accounts.add(
        Account(
            id=BOB,
            username=Username("bob"),
            password_hash=NOT_A_HASH,
            role=Role.USER,
            created_at=DAY,
        )
    )
    sessions = SqliteSessionRepository(engine=container.engine)
    now = datetime.now(UTC)
    for cookie, account in ((ADMIN_COOKIE, ADA), (USER_COOKIE, BOB)):
        await sessions.add(
            Session(
                token_hash=hash_token(cookie), account_id=account, created_at=now, last_used_at=now
            )
        )
    client.cookies.set(SESSION_COOKIE, ADMIN_COOKIE)


@pytest.fixture(params=SQL_BACKENDS)
async def client(request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    # No worker: the queued jobs stay queued.
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        await seed(container)
        await sign_in(container, client)
        yield client


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ who queued a job


async def test_a_job_names_the_account_of_the_session_or_token_that_queued_it(
    client: httpx.AsyncClient,
) -> None:
    by_session = await client.put(
        "/api/v1/libraries/acme/alpha/settings", json={"include_paths": ["docs/"]}
    )
    assert by_session.status_code == 202, by_session.text
    created = await client.post("/api/v1/tokens", json={"name": "ci"})
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    client.cookies.clear()  # the token alone
    by_token = await client.put(
        "/api/v1/libraries/acme/beta/settings",
        json={"include_paths": ["guide/"]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert by_token.status_code == 202, by_token.text
    client.cookies.set(SESSION_COOKIE, ADMIN_COOKIE)

    for response in (by_session, by_token):
        job = await get(client, response.headers["Location"].removeprefix("http://localhost"))
        assert job["created_by"] == {
            "id": ADA,
            "username": "ada",
            "via": None,
        }  # nothing of the token
        assert job["origin"] == "manual"
    listed = await get(client, "/api/v1/jobs", kind="reprocess")
    assert [j["created_by"]["username"] for j in listed["jobs"]] == ["ada", "ada"]
    assert token not in str(listed)


async def test_jobs_queued_before_or_by_the_instance_name_nobody(
    client: httpx.AsyncClient,
) -> None:
    body = await get(client, "/api/v1/jobs", limit=100)

    assert {job["created_by"] for job in body["jobs"]} == {None}


async def test_the_jobs_filter_by_origin(client: httpx.AsyncClient) -> None:
    every = await get(client, "/api/v1/jobs", limit=100)
    auto = await get(client, "/api/v1/jobs", origin="auto", limit=100)
    manual = await get(client, "/api/v1/jobs", origin="manual", limit=100)
    both = await client.get("/api/v1/jobs", params=[("origin", "auto"), ("origin", "manual")])
    library = await get(client, "/api/v1/libraries/acme/alpha/jobs", origin="auto")

    assert {job["origin"] for job in auto["jobs"]} == {"auto"}
    assert {job["origin"] for job in manual["jobs"]} == {"manual"}
    assert auto["total"] + manual["total"] == every["total"] == both.json()["total"]
    assert {job["id"] for job in auto["jobs"]} == {"job-00", "job-03", "job-06", "job-99"}
    assert [job["id"] for job in library["jobs"]] == ["job-00"]
    refused = await client.get("/api/v1/jobs", params={"origin": "robot"})
    assert (refused.status_code, refused.json()["error"]) == (422, "validation_error")


# ------------------------------------------------------------------ libraries by sync state


async def test_the_libraries_filter_by_the_state_of_their_latest_sync(
    client: httpx.AsyncClient,
) -> None:
    failed = await get(client, "/api/v1/libraries", sync_state="failed")
    either = await client.get(
        "/api/v1/libraries", params=[("sync_state", "succeeded"), ("sync_state", "queued")]
    )
    cancelled = await get(client, "/api/v1/libraries", sync_state="cancelled")

    assert [lib["id"] for lib in failed["libraries"]] == FAILED
    assert failed["total"] == len(FAILED)
    assert [lib["id"] for lib in either.json()["libraries"]] == ["/acme/gamma", "/acme/zeta"]
    assert (cancelled["libraries"], cancelled["total"]) == ([], 0)
    refused = await client.get("/api/v1/libraries", params={"sync_state": "stuck"})
    assert (refused.status_code, refused.json()["error"]) == (422, "validation_error")


async def test_the_sync_state_filter_pages_by_cursor_and_offset_alike(
    client: httpx.AsyncClient,
) -> None:
    walked, totals, cursor = [], set(), None
    while True:
        params = {"sync_state": "failed", "sort": "-id", "limit": 1}
        body = await get(
            client, "/api/v1/libraries", **params, **({"cursor": cursor} if cursor else {})
        )
        walked += [lib["id"] for lib in body["libraries"]]
        totals.add(body["total"])
        if (cursor := body["next_cursor"]) is None:
            break

    assert walked == FAILED[::-1]
    assert totals == {len(FAILED)}
    for offset in range(len(FAILED) + 1):
        body = await get(
            client, "/api/v1/libraries", sync_state="failed", sort="-id", limit=2, offset=offset
        )
        assert [lib["id"] for lib in body["libraries"]] == walked[offset : offset + 2]
        assert body["total"] == len(FAILED)
    # It composes with the catalog's own filters.
    narrowed = await get(client, "/api/v1/libraries", sync_state="failed", q="ta")
    assert [lib["id"] for lib in narrowed["libraries"]] == ["/acme/beta", "/acme/delta"]


# ------------------------------------------------------------------ the job statistics


async def test_the_stats_count_every_day_by_state_and_kind(client: httpx.AsyncClient) -> None:
    body = await get(
        client, "/api/v1/stats/jobs", bucket="day", **{"from": "2026-11-01", "to": "2026-11-04"}
    )

    assert (body["bucket"], body["from"], body["to"]) == ("day", "2026-11-01", "2026-11-04")
    days = {day["day"]: day for day in body["days"]}
    assert list(days) == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    seeded = days["2026-11-02"]
    assert seeded["total"] == 8
    assert seeded["by_state"] == {
        "queued": 1,
        "running": 0,
        "succeeded": 2,
        "failed": 5,
        "cancelled": 0,
    }
    assert list(seeded["by_kind"]) == list(JOB_KINDS)
    assert (seeded["by_kind"]["import"], seeded["by_kind"]["refresh"]) == (4, 4)
    assert days["2026-11-03"]["by_kind"]["embed"] == 1
    for empty in ("2026-11-01", "2026-11-04"):
        assert days[empty]["total"] == 0
        assert set(days[empty]["by_state"].values()) == {0}
        assert set(days[empty]["by_kind"].values()) == {0}


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-05", "to": "2026-11-01"},
        {"from": "2025-01-01", "to": "2026-11-01"},
    ],
    ids=["backwards", f"more than {MAX_STATS_DAYS} days"],
)
async def test_the_stats_refuse_a_range_backwards_or_too_long(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get("/api/v1/stats/jobs", params=params)

    assert (response.status_code, response.json()["error"]) == (422, "invalid_range")


async def test_the_stats_know_only_day_buckets_and_dates(client: httpx.AsyncClient) -> None:
    for params in ({"bucket": "week"}, {"from": "yesterday"}):
        response = await client.get("/api/v1/stats/jobs", params=params)
        assert (response.status_code, response.json()["error"]) == (422, "validation_error")


async def test_the_stats_are_for_operators_only(client: httpx.AsyncClient) -> None:
    client.cookies.set(SESSION_COOKIE, USER_COOKIE)
    as_user = await client.get("/api/v1/stats/jobs")
    client.cookies.clear()
    anonymous = await client.get("/api/v1/stats/jobs")

    assert (as_user.status_code, as_user.json()["error"]) == (403, "forbidden")
    assert anonymous.status_code == 401


async def test_the_openapi_describes_the_stats_and_the_new_filters(
    client: httpx.AsyncClient,
) -> None:
    spec = await get(client, "/api/v1/openapi.json")

    stats = spec["paths"]["/api/v1/stats/jobs"]["get"]
    assert {p["name"] for p in stats["parameters"]} == {"bucket", "from", "to"}
    names = {p["name"] for p in spec["paths"]["/api/v1/jobs"]["get"]["parameters"]}
    assert "origin" in names
    libraries = {p["name"] for p in spec["paths"]["/api/v1/libraries"]["get"]["parameters"]}
    assert "sync_state" in libraries
    schemas = spec["components"]["schemas"]
    assert set(schemas["JobStats"]["properties"]) == {"bucket", "from", "to", "days"}
    assert set(schemas["PersonSummary"]["properties"]) == {"id", "username", "via"}
