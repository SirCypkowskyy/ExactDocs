"""DELETE routes: what they answer, what they refuse, and the collection job they queue."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.models import LibraryId, RefKind, Version, VersionRef
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.models import Job, JobId, JobKind, JobState

pytestmark = pytest.mark.usefixtures("demo_catalog")

PAYMENTS = "/api/v1/libraries/acme/payments"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(
            transport=transport, base_url="http://localhost", cookies=demo_catalog
        ) as client,
    ):
        yield client


async def test_removing_the_default_version_recomputes_the_default(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get(PAYMENTS)).json()["default_version"] == "v1.4.0"

    response = await client.delete(f"{PAYMENTS}/versions/v1.4.0")

    assert response.status_code == 200
    body = response.json()
    assert (body["library"], body["ref"], body["default_version"]) == (
        "/acme/payments",
        "v1.4.0",
        "v1.3.0",
    )
    detail = (await client.get(PAYMENTS)).json()
    assert detail["default_version"] == "v1.3.0"
    assert "v1.4.0" not in [v["ref"] for v in detail["versions"]]
    job = (await client.get(f"/api/v1/jobs/{body['collection_job_id']}")).json()
    assert (job["kind"], job["library"], job["state"]) == ("collect", "/acme/payments", "queued")


async def test_removing_an_existing_version_whose_ref_has_slashes_is_a_200(
    container: Container, client: httpx.AsyncClient
) -> None:
    payments = await SqliteLibraryRepository(engine=container.engine).get(
        LibraryId("/acme/payments")
    )
    assert payments is not None
    slashed = Version(
        ref=VersionRef("release/1.4"), kind=RefKind.BRANCH, commit_sha="c" * 40, imported_at=NOW
    )
    await SqliteLibraryRepository(engine=container.engine).save(
        replace(payments, versions=payments.versions | {slashed})
    )

    response = await client.delete(f"{PAYMENTS}/versions/release/1.4")

    assert response.status_code == 200
    assert response.json()["ref"] == "release/1.4"
    detail = (await client.get(PAYMENTS)).json()
    assert "release/1.4" not in [v["ref"] for v in detail["versions"]]


async def test_a_ref_with_slashes_and_a_missing_version_are_handled(
    client: httpx.AsyncClient,
) -> None:
    missing = await client.delete(f"{PAYMENTS}/versions/release/1.4")
    trailing = await client.delete(f"{PAYMENTS}/versions/v1.4.0/")

    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"
    assert trailing.status_code == 404
    assert (await client.get(PAYMENTS)).json()["default_version"] == "v1.4.0"


async def test_removing_a_library_removes_it_and_a_second_removal_is_a_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.delete(PAYMENTS)

    assert response.status_code == 200
    assert response.json()["ref"] is None
    assert (await client.get(PAYMENTS)).status_code == 404
    assert (await client.delete(PAYMENTS)).status_code == 404
    ledger = await client.get("/api/v1/libraries/acme/ledger")
    assert ledger.status_code == 200  # other libraries are untouched


@pytest.mark.parametrize("state", [JobState.QUEUED, JobState.RUNNING])
async def test_removal_is_refused_with_409_while_an_import_is_unfinished(
    container: Container, client: httpx.AsyncClient, state: JobState
) -> None:
    job = Job.queued(
        job_id=JobId("import-1"),
        kind=JobKind("import"),
        library="/acme/payments",
        version="v1.4.0",
        now=NOW,
    )
    jobs = SqliteJobRepository(engine=container.engine)
    await jobs.add(job if state is JobState.QUEUED else job.started(NOW))

    version = await client.delete(f"{PAYMENTS}/versions/v1.4.0")
    library = await client.delete(PAYMENTS)
    other_version = await client.delete(f"{PAYMENTS}/versions/v1.3.0")

    assert (version.status_code, version.json()["error"]) == (409, "import_in_progress")
    assert (library.status_code, library.json()["error"]) == (409, "import_in_progress")
    assert other_version.status_code == 200  # only the version being imported is protected
    detail = (await client.get(PAYMENTS)).json()
    assert "v1.4.0" in [v["ref"] for v in detail["versions"]]


async def test_removal_needs_a_signed_in_caller(container: Container) -> None:
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as anonymous,
    ):
        library = await anonymous.delete(PAYMENTS)
        version = await anonymous.delete(f"{PAYMENTS}/versions/v1.4.0")

    assert (library.status_code, version.status_code) == (401, 401)
