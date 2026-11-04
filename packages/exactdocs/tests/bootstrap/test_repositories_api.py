from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from fixture_repo import DocsRepo

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


async def check(client: httpx.AsyncClient, url: str) -> httpx.Response:
    return await client.post("/api/v1/repositories/check", json={"url": url})


async def test_an_anonymous_caller_is_refused(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    response = await check(client, "https://github.com/acme/orders")

    assert response.status_code == 401


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_the_fixture_repository_is_accepted(
    client: httpx.AsyncClient, docs_repo: DocsRepo, transport: str
) -> None:
    response = await check(client, getattr(docs_repo, transport))

    assert response.status_code == 200
    assert response.json() == {
        "host": "git",
        "library_id": "/fixture/docs-repo",
        "default_branch": "main",
    }


async def test_a_taken_id_is_a_conflict(client: httpx.AsyncClient) -> None:
    response = await check(client, "https://bitbucket.org/acme/payments")

    assert response.status_code == 409
    assert response.json()["error"] == "library_id_taken"


async def test_a_directory_without_a_repository(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    response = await check(client, docs_repo.path.parent.as_uri() + "/docs")

    assert response.status_code == 422
    assert response.json()["error"] == "not_a_git_repository"


async def test_an_unreachable_server(client: httpx.AsyncClient) -> None:
    response = await check(client, "http://127.0.0.1:1/acme/gone.git")

    assert response.status_code == 422
    assert response.json()["error"] == "repository_unreachable"


@pytest.mark.parametrize("url", ["--upload-pack=true", "ext::sh -c id", "git://127.0.0.1/a/b"])
async def test_dangerous_urls_are_refused_as_invalid(client: httpx.AsyncClient, url: str) -> None:
    response = await check(client, url)

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_repository_url"


async def test_credentials_in_a_url_are_never_echoed(client: httpx.AsyncClient) -> None:
    response = await check(client, "https://user:hunter2-secret@git.example.com/acme/x")

    assert response.status_code == 422
    assert "hunter2" not in response.text
    assert "git.example.com" not in response.text


async def test_a_missing_url_is_a_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/repositories/check", json={})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_without_git_the_app_starts_and_the_check_says_what_is_missing(
    demo_catalog: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PATH", "")

    container = Container.build(Settings())

    assert "git is not installed" in caplog.text
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        response = await check(client, "https://github.com/acme/orders")
    assert response.json()["error"] == "git_not_installed"
