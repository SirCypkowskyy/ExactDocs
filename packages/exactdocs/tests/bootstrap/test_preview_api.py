from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.errors import PreviewBusyError
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


async def preview(client: httpx.AsyncClient, url: str, **body: object) -> httpx.Response:
    return await client.post("/api/v1/repositories/preview", json={"url": url, **body})


async def test_an_anonymous_caller_is_refused(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    client.cookies.clear()

    assert (await preview(client, docs_repo.file_url)).status_code == 401


@pytest.mark.parametrize("transport", ["file_url", "http_url"])
async def test_lists_the_files_an_import_would_take(
    client: httpx.AsyncClient, docs_repo: DocsRepo, transport: str
) -> None:
    response = await preview(
        client,
        getattr(docs_repo, transport),
        ref="v1.4.0",
        include_paths=["docs/guide/"],
        exclude_paths=["**/callouts.md"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["files"] == [
        f"docs/guide/{n}.md" for n in ("auth", "configuration", "install", "resilience")
    ]
    assert (body["total"], body["truncated"], body["ref"], body["ref_kind"]) == (
        4,
        False,
        "v1.4.0",
        "tag",
    )
    assert len(body["commit_sha"]) == 40


async def test_nothing_is_stored_and_no_blob_is_downloaded(
    client: httpx.AsyncClient, docs_repo: DocsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetches: list[list[str]] = []
    original = GitCli._run  # ruff: ignore[private-member-access]

    async def spy(self: GitCli, args: list[str], **kwargs: object) -> object:
        fetches.append(list(args))
        return await original(self, args, **kwargs)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(GitCli, "_run", spy)

    assert (await preview(client, docs_repo.file_url)).status_code == 200

    git_args = [" ".join(a) for a in fetches]
    assert any("--filter=blob:none" in a for a in git_args)
    assert not any(" checkout " in a or "cat-file" in a for a in git_args)
    assert (await client.get("/api/v1/libraries/fixture/docs-repo")).status_code == 404
    assert (await client.get("/api/v1/jobs/latest")).json()["jobs"] == []


async def test_the_list_is_capped_but_counted(
    client: httpx.AsyncClient, docs_repo: DocsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("exactdocs.ingestion.use_cases.MAX_PREVIEW_FILES", 3)

    body = (await preview(client, docs_repo.file_url, ref="v1.3.0")).json()

    assert len(body["files"]) == 3
    assert body["files"] == sorted(body["files"])
    assert body["total"] > 3
    assert body["truncated"] is True


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"ref": "v9.9.9"}, "unknown_ref"),
        ({"include_paths": ["../secrets"]}, "invalid_path_pattern"),
        ({"url": "--upload-pack=true"}, "invalid_repository_url"),
    ],
)
async def test_what_cannot_work_is_explained(
    client: httpx.AsyncClient, docs_repo: DocsRepo, body: dict[str, object], error: str
) -> None:
    response = await preview(client, **{"url": docs_repo.file_url, **body})  # ty: ignore[invalid-argument-type]

    assert response.status_code == 422
    assert response.json()["error"] == error


async def test_an_unreachable_server(client: httpx.AsyncClient) -> None:
    response = await preview(client, "http://127.0.0.1:1/acme/gone.git")

    assert (response.status_code, response.json()["error"]) == (422, "repository_unreachable")


async def test_busy_previews_answer_429(demo_catalog: dict[str, str], docs_repo: DocsRepo) -> None:
    class Busy:
        async def list_files(self, *_: object, **__: object) -> list[str]:
            raise PreviewBusyError(retry_after=7)

    container = Container.build(Settings(), tree=Busy())
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as busy,
    ):
        response = await preview(busy, docs_repo.file_url)

    assert (response.status_code, response.json()["error"]) == (429, "preview_busy")
    assert response.headers["retry-after"] == "7"
