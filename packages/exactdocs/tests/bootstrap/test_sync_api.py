"""``POST /libraries/{owner}/{repo}/sync`` over a private copy of the fixture repository."""

import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import GetLibraryQuery, RemoveVersionCommand
from fixture_repo import DocsRepo, git

pytestmark = pytest.mark.usefixtures("demo_catalog")  # also puts a data dir in place
SYNC = "/api/v1/libraries/fixture/docs-repo/sync"


@pytest.fixture
def repo(docs_repo: DocsRepo, tmp_path: Path) -> Path:
    """A copy of the fixture repository whose branches may move."""
    copy = tmp_path / "fixture" / "docs-repo"
    shutil.copytree(docs_repo.path, copy)
    return copy


def move_next(repo: Path) -> None:
    git("checkout", "-q", "next", cwd=repo)
    with (repo / "docs/guide/install.md").open("a", encoding="utf-8") as article:
        article.write("\nMore.\n")
    git("-c", "user.name=T", "-c", "user.email=t@x.invalid", "commit", "-qam", "more", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running(jobs=False):  # jobs run when the test says so
        yield container


@pytest.fixture
def client(container: Container, demo_catalog: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    )


async def test_sync_answers_200_202_and_409_and_re_chunks_only_what_changed(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    added = await client.post(
        "/api/v1/libraries",
        json={"url": repo.as_uri(), "ref": "next", "include_paths": ["docs/"]},
    )
    assert added.status_code == 201, added.text
    assert await container.ingestion.run_next_job()

    unchanged = await client.post(SYNC)
    assert unchanged.status_code == 200, unchanged.text
    assert [v["status"] for v in unchanged.json()["versions"]] == ["up_to_date"]
    assert "location" not in unchanged.headers

    move_next(repo)
    moved = await client.post(SYNC)
    assert moved.status_code == 202, moved.text
    (version,) = moved.json()["versions"]
    assert version["status"] == "queued"
    assert (
        version["commit_sha"]
        == git("rev-parse", "next", cwd=repo)
        != version["previous_commit_sha"]
    )
    assert moved.headers["location"] == f"/api/v1/jobs/{version['job_id']}"

    busy = await client.post(SYNC)
    assert (busy.status_code, busy.json()["error"]) == (409, "version_importing")

    assert await container.ingestion.run_next_job()
    job = (await client.get(moved.headers["location"])).json()
    assert (job["state"], job["chunked"]) == ("succeeded", 1)
    assert job["reused"] > 0
    assert (await client.post(SYNC)).status_code == 200


async def test_sync_of_an_unknown_library_is_a_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/libraries/no/such/sync")
    assert (response.status_code, response.json()["error"]) == (404, "not_found")


async def test_sync_needs_a_caller(container: Container) -> None:
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    )
    async with anonymous:
        response = await anonymous.post(SYNC)
    assert (response.status_code, response.json()["error"]) == (401, "unauthenticated")


async def add_and_import(
    client: httpx.AsyncClient, container: Container, repo: Path, ref: str
) -> None:
    added = await client.post(
        "/api/v1/libraries",
        json={"url": repo.as_uri(), "ref": ref, "include_paths": ["docs/"]},
    )
    assert added.status_code == 201, added.text
    assert await container.ingestion.run_next_job()


async def test_two_moved_branches_answer_with_the_library_jobs_as_location(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    await add_and_import(client, container, repo, "next")
    git("branch", "second", "next", cwd=repo)
    second = await client.post(
        "/api/v1/libraries/fixture/docs-repo/versions", json={"ref": "second"}
    )
    assert second.status_code == 202, second.text
    assert await container.ingestion.run_next_job()
    move_next(repo)
    git("branch", "-f", "second", "next", cwd=repo)

    moved = await client.post(SYNC)

    assert moved.status_code == 202, moved.text
    assert sorted(v["status"] for v in moved.json()["versions"]) == ["queued", "queued"]
    assert moved.headers["location"] == "/api/v1/libraries/fixture/docs-repo/jobs"


async def test_simultaneous_syncs_queue_one_import_in_the_database(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    await add_and_import(client, container, repo, "next")
    move_next(repo)

    answers = await asyncio.gather(client.post(SYNC), client.post(SYNC))

    assert sorted(a.status_code for a in answers) == [202, 409]
    jobs = (await client.get("/api/v1/libraries/fixture/docs-repo/jobs")).json()["jobs"]
    assert [j["state"] for j in jobs].count("queued") == 1


async def test_a_queued_sync_blocks_removal_and_a_refresh_never_brings_a_removed_version_back(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    await add_and_import(client, container, repo, "next")
    move_next(repo)
    queued = await client.post(SYNC)
    job_id = queued.json()["versions"][0]["job_id"]

    refused = await client.delete("/api/v1/libraries/fixture/docs-repo/versions/next")
    assert (refused.status_code, refused.json()["error"]) == (409, "import_in_progress")

    # A removal that slipped in between (the guard is check-then-remove) must not be undone.
    await container.catalog.remove_version(
        RemoveVersionCommand(library="/fixture/docs-repo", ref="next")
    )
    assert await container.ingestion.run_next_job()
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert (job["kind"], job["state"]) == ("refresh", "failed")
    library = await container.catalog.get_library(GetLibraryQuery(id="/fixture/docs-repo"))
    assert library.versions == []


REIMPORT = "/api/v1/libraries/fixture/docs-repo/versions/reimport"


async def test_a_confirmed_moved_tag_answers_202_with_its_job_and_takes_the_new_commit(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    git("tag", "release/1.4", "v1.4.0", cwd=repo)  # a ref with a slash goes in the body
    await add_and_import(client, container, repo, "release/1.4")
    old = git("rev-parse", "release/1.4^{commit}", cwd=repo)
    git("tag", "-f", "release/1.4", "v1.3.0", cwd=repo)
    new = git("rev-parse", "release/1.4^{commit}", cwd=repo)

    response = await client.post(REIMPORT, json={"ref": "release/1.4"})

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["library_id"], body["ref"], body["ref_kind"]) == (
        "/fixture/docs-repo",
        "release/1.4",
        "tag",
    )
    assert (body["previous_commit_sha"], body["commit_sha"]) == (old, new)
    assert response.headers["location"] == f"/api/v1/jobs/{body['job_id']}"
    busy = await client.post(REIMPORT, json={"ref": "release/1.4"})
    assert (busy.status_code, busy.json()["error"]) == (409, "version_importing")
    assert await container.ingestion.run_next_job()
    job = (await client.get(response.headers["location"])).json()
    assert (job["state"], job["kind"]) == ("succeeded", "refresh")
    version = await client.get("/api/v1/libraries/fixture/docs-repo/versions/release/1.4")
    assert version.json()["commit_sha"] == new
    again = await client.post(REIMPORT, json={"ref": "release/1.4"})
    assert (again.status_code, again.json()["error"]) == (409, "tag_not_moved")


async def test_a_re_import_is_refused_for_what_is_not_a_moved_tag(
    client: httpx.AsyncClient, container: Container, repo: Path
) -> None:
    await add_and_import(client, container, repo, "next")

    branch = await client.post(REIMPORT, json={"ref": "next"})
    unknown = await client.post(REIMPORT, json={"ref": "v9.9.9"})
    empty = await client.post(REIMPORT, json={"ref": ""})

    assert (branch.status_code, branch.json()["error"]) == (422, "not_a_tag")
    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")
    assert empty.status_code == 422
    assert (await client.post(f"{REIMPORT}/v1.4.0", json={"ref": "v1.4.0"})).status_code in {
        404,
        405,
    }  # nothing follows `reimport`: the ref is in the body


async def test_a_re_import_of_an_unknown_library_is_a_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/libraries/no/such/versions/reimport", json={"ref": "v1"})
    assert (response.status_code, response.json()["error"]) == (404, "not_found")


async def test_a_re_import_needs_a_caller(container: Container) -> None:
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    )
    async with anonymous:
        response = await anonymous.post(REIMPORT, json={"ref": "v1.4.0"})
    assert (response.status_code, response.json()["error"]) == (401, "unauthenticated")
