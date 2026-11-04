import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.models import RemoteRef, RemoteRefs, RepositoryUrl
from fixture_repo import DocsRepo, git

pytestmark = pytest.mark.usefixtures("demo_catalog")


@asynccontextmanager
async def _client(demo_catalog: dict[str, str], *, jobs: bool) -> AsyncGenerator[httpx.AsyncClient]:
    container = Container.build(Settings())  # the real system git
    async with (
        container.running(jobs=jobs),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        yield client


@pytest.fixture
async def client(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """The app without its job worker: queued imports stay queued.

    Yields:
        A client signed in as the admin.
    """
    async with _client(demo_catalog, jobs=False) as found:
        yield found


@pytest.fixture
async def client_with_jobs(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """The app with its job worker, so queued imports run.

    Yields:
        A client signed in as the admin.
    """
    async with _client(demo_catalog, jobs=True) as found:
        yield found


async def test_an_anonymous_caller_is_refused(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    assert (await client.post("/api/v1/libraries", json={"url": "x"})).status_code == 401
    assert (await client.get("/api/v1/repositories/refs", params={"url": "x"})).status_code == 401


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_adding_the_fixture_repository(
    client: httpx.AsyncClient, docs_repo: DocsRepo, transport: str
) -> None:
    response = await client.post(
        "/api/v1/libraries",
        json={
            "url": getattr(docs_repo, transport),
            "ref": "v1.4.0",
            "include_paths": ["docs/"],
            "exclude_paths": ["docs/archive/**"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.headers["location"] == "/api/v1/libraries/fixture/docs-repo"
    body = response.json()
    assert body["library_id"] == "/fixture/docs-repo"
    assert (body["ref"], body["ref_kind"]) == ("v1.4.0", "tag")
    assert body["commit_sha"] == git("rev-parse", "v1.4.0", cwd=docs_repo.path)
    library = (await client.get("/api/v1/libraries/fixture/docs-repo")).json()
    assert library["source_url"] == getattr(docs_repo, transport)
    assert library["versions"] == []  # a version exists once its import has run
    assert library["settings"]["include_paths"] == ["docs/"]
    assert library["settings"]["exclude_paths"] == ["docs/archive/**"]
    assert library["default_branch"] == "main"
    assert library["title"] == "docs-repo"
    job = (await client.get(f"/api/v1/jobs/{body['job_id']}")).json()
    assert (job["library"], job["version"], job["commit_sha"]) == (
        "/fixture/docs-repo",
        "v1.4.0",
        body["commit_sha"],
    )
    again = await client.post("/api/v1/libraries", json={"url": docs_repo.file_url})
    assert (again.status_code, again.json()["error"]) == (409, "library_id_taken")


async def test_an_unknown_ref_is_a_422(client: httpx.AsyncClient, docs_repo: DocsRepo) -> None:
    response = await client.post(
        "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": "v9.9.9"}
    )

    assert (response.status_code, response.json()["error"]) == (422, "unknown_ref")
    assert (await client.get("/api/v1/libraries/fixture/docs-repo")).status_code == 404


async def test_a_bad_id_creates_nothing(client: httpx.AsyncClient, docs_repo: DocsRepo) -> None:
    response = await client.post(
        "/api/v1/libraries", json={"url": docs_repo.file_url, "library_id": "not-an-id"}
    )

    assert response.status_code == 422


async def test_refs_for_the_picker(client: httpx.AsyncClient, docs_repo: DocsRepo) -> None:
    response = await client.get("/api/v1/repositories/refs", params={"url": docs_repo.http_url})

    assert response.status_code == 200
    body = response.json()
    assert body["default_branch"] == "main"
    assert [b["name"] for b in body["branches"]] == ["main", "next"]
    assert [t["name"] for t in body["tags"]] == ["v1.3.0", "v1.4.0"]
    assert body["tags"][0]["commit_sha"] == git("rev-parse", "v1.3.0", cwd=docs_repo.path)


async def test_refs_of_a_dangerous_url_are_refused_without_echoing_it(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/repositories/refs", params={"url": "https://user:hunter2@git.example.com/a/b"}
    )

    assert response.status_code == 422
    assert "hunter2" not in response.text


async def test_a_ref_that_is_not_a_plain_name_is_unknown(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    response = await client.post(
        "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": "refs/heads/next"}
    )

    assert (response.status_code, response.json()["error"]) == (422, "unknown_ref")


async def test_a_short_sha_in_capitals_is_pinned_to_the_full_commit(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    sha = git("rev-parse", "v1.3.0", cwd=docs_repo.path)

    response = await client.post(
        "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": sha[:10].upper()}
    )

    assert response.status_code == 201
    assert (response.json()["ref"], response.json()["ref_kind"]) == (sha, "commit")


class _TwoCommitsShareAPrefix:
    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        del repository, patterns
        return RemoteRefs(
            default_branch="main",
            refs=(
                RemoteRef(name="refs/heads/main", sha="abcdef0" + "1" * 33),
                RemoteRef(name="refs/heads/next", sha="abcdef0" + "2" * 33),
            ),
        )


async def test_an_ambiguous_short_sha_is_a_422(demo_catalog: dict[str, str]) -> None:
    container = Container.build(Settings(), remote=_TwoCommitsShareAPrefix())
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        url = "https://git.example.com/acme/docs"
        response = await client.post("/api/v1/libraries", json={"url": url, "ref": "abcdef0"})
        assert (response.status_code, response.json()["error"]) == (422, "ambiguous_ref")
        assert (await client.get("/api/v1/libraries/acme/docs")).status_code == 404

        ok = await client.post("/api/v1/libraries", json={"url": url, "ref": "abcdef01"})
        assert ok.status_code == 201


async def test_refs_of_an_unreachable_server(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/repositories/refs", params={"url": "http://127.0.0.1:1/acme/gone.git"}
    )

    assert (response.status_code, response.json()["error"]) == (422, "repository_unreachable")


async def test_the_queued_import_publishes_the_version(
    client_with_jobs: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    added = (
        await client_with_jobs.post(
            "/api/v1/libraries",
            json={"url": docs_repo.file_url, "ref": "v1.3.0", "include_paths": ["docs/guide/"]},
        )
    ).json()

    for _ in range(1000):
        job = (await client_with_jobs.get(f"/api/v1/jobs/{added['job_id']}")).json()
        if job["state"] in {"failed", "succeeded"}:
            break
        await asyncio.sleep(0.01)

    assert job["state"] == "succeeded", job
    assert (job["done"], job["total"]) == (4, 4)
    library = (await client_with_jobs.get("/api/v1/libraries/fixture/docs-repo")).json()
    assert [(v["ref"], v["commit_sha"]) for v in library["versions"]] == [
        ("v1.3.0", added["commit_sha"])
    ]


async def _imported_fixture(client: httpx.AsyncClient, docs_repo: DocsRepo, ref: str) -> None:
    added = await client.post(
        "/api/v1/libraries",
        json={"url": docs_repo.file_url, "ref": ref, "include_paths": ["docs/**"]},
    )
    assert added.status_code == 201, added.text
    await _job_done(client, added.json()["job_id"])


async def _job_done(client: httpx.AsyncClient, job_id: str) -> None:
    for _ in range(600):
        state = (await client.get(f"/api/v1/jobs/{job_id}")).json()["state"]
        if state in {"succeeded", "failed"}:
            assert state == "succeeded"
            return
        await asyncio.sleep(0.05)
    message = "the import did not finish"
    raise AssertionError(message)


async def test_adding_a_version_is_accepted_and_points_at_its_job(
    client_with_jobs: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    client = client_with_jobs
    await _imported_fixture(client, docs_repo, "v1.4.0")

    response = await client.post(
        "/api/v1/libraries/Fixture/Docs-Repo/versions", json={"ref": "v1.3.0"}
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["library_id"] == "/fixture/docs-repo"
    assert (body["ref"], body["ref_kind"]) == ("v1.3.0", "tag")
    assert response.headers["location"] == f"/api/v1/jobs/{body['job_id']}"
    await _job_done(client, body["job_id"])
    library = (await client.get("/api/v1/libraries/fixture/docs-repo")).json()
    assert [v["ref"] for v in library["versions"]] == ["v1.3.0", "v1.4.0"]


async def test_a_version_the_library_has_or_a_commit_it_has_is_a_409(
    client_with_jobs: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    client = client_with_jobs
    await _imported_fixture(client, docs_repo, "v1.4.0")
    url = "/api/v1/libraries/fixture/docs-repo/versions"
    sha = git("rev-parse", "v1.4.0", cwd=docs_repo.path)

    same = await client.post(url, json={"ref": "v1.4.0"})
    commit = await client.post(url, json={"ref": sha[:10]})

    assert (same.status_code, same.json()["error"]) == (409, "version_exists")
    assert (commit.status_code, commit.json()["error"]) == (409, "commit_already_imported")
    assert "v1.4.0" in commit.json()["detail"]


async def test_a_ref_still_importing_is_a_409(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    added = await client.post(
        "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": "v1.4.0"}
    )
    assert added.status_code == 201  # no worker here: the import stays queued
    url = "/api/v1/libraries/fixture/docs-repo/versions"

    first = await client.post(url, json={"ref": "v1.3.0"})
    second = await client.post(url, json={"ref": "v1.3.0"})
    running = await client.post(url, json={"ref": "v1.4.0"})

    assert first.status_code == 202
    assert (second.status_code, second.json()["error"]) == (409, "version_importing")
    assert (running.status_code, running.json()["error"]) == (409, "version_importing")


async def test_adding_a_version_needs_a_session(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    response = await client.post("/api/v1/libraries/fixture/docs-repo/versions", json={"ref": "x"})

    assert response.status_code == 401


async def test_adding_a_version_to_an_unknown_or_malformed_library(
    client: httpx.AsyncClient,
) -> None:
    unknown = await client.post("/api/v1/libraries/nobody/nothing/versions", json={"ref": "x"})
    malformed = await client.post("/api/v1/libraries/no~body/no thing/versions", json={"ref": "x"})
    empty_ref = await client.post("/api/v1/libraries/nobody/nothing/versions", json={"ref": ""})

    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")
    assert malformed.status_code == 422
    assert empty_ref.status_code == 422
