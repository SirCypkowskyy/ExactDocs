from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from fixture_repo import DocsRepo, git

pytestmark = pytest.mark.usefixtures("demo_catalog")


@pytest.fixture
async def client(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())  # the real system git
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        yield client


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
    body = response.json()
    assert body["library_id"] == "/fixture/docs-repo"
    assert (body["ref"], body["ref_kind"]) == ("v1.4.0", "tag")
    assert body["commit_sha"] == git("rev-parse", "v1.4.0", cwd=docs_repo.path)
    library = (await client.get("/api/v1/libraries/fixture/docs-repo")).json()
    assert library["source_url"] == getattr(docs_repo, transport)
    assert library["versions"] == []  # a version exists once its import has run
    assert library["settings"]["include_paths"] == ["docs/"]
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
