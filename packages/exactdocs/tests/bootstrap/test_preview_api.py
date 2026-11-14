import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.constants import MAX_FETCHES, MAX_PREVIEWS
from exactdocs.ingestion.errors import PreviewBusyError
from exactdocs.ingestion.models import FetchedFile
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


async def test_nothing_is_stored_and_only_context7_json_is_downloaded(
    client: httpx.AsyncClient, docs_repo: DocsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetches: list[list[str]] = []
    original = GitCli._run  # ruff: ignore[private-member-access]

    async def spy(self: GitCli, args: list[str], **kwargs: object) -> object:
        fetches.append(list(args))
        return await original(self, args, **kwargs)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(GitCli, "_run", spy)

    assert (await preview(client, docs_repo.file_url, ref="next")).status_code == 200

    git_args = [" ".join(a) for a in fetches]
    assert any("--filter=blob:none" in a for a in git_args)
    assert not any(" checkout " in a for a in git_args)
    # The one blob read is the root context7.json, found in the tree as a regular file.
    assert any(":(literal)context7.json" in a for a in git_args)
    assert sum(" cat-file blob " in a for a in git_args) == 1
    assert (await client.get("/api/v1/libraries/fixture/docs-repo")).status_code == 404
    assert (await client.get("/api/v1/jobs/latest")).json()["jobs"] == []


async def test_previewing_and_adding_do_not_wait_for_the_import_slots(
    demo_catalog: dict[str, str], docs_repo: DocsRepo
) -> None:
    git = GitCli.locate()
    for _ in range(MAX_FETCHES):
        await git.fetch_slots.acquire()  # two long imports are running
    container = Container.build(Settings(), remote=git, gateway=git, tree=git)
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
        asyncio.timeout(60),
    ):
        previewed = await preview(client, docs_repo.file_url, ref="next")
        added = await client.post(
            "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": "next"}
        )

    assert previewed.status_code == 200, previewed.text
    assert previewed.json()["context7"] is not None
    assert added.status_code == 201, added.text
    assert added.json()["include_paths"] == ["docs/"]


async def test_an_add_without_paths_answers_429_while_every_preview_slot_is_busy(
    demo_catalog: dict[str, str], docs_repo: DocsRepo
) -> None:
    git = GitCli(git=GitCli.locate().git, preview_wait=0.05)
    for _ in range(MAX_PREVIEWS):
        await git.preview_slots.acquire()  # every preview slot is taken
    container = Container.build(Settings(), remote=git, gateway=git, tree=git)
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        refused = await client.post(
            "/api/v1/libraries", json={"url": docs_repo.file_url, "ref": "next"}
        )
        missing = await client.get("/api/v1/libraries/fixture/docs-repo")
        added = await client.post(
            "/api/v1/libraries",
            json={"url": docs_repo.file_url, "ref": "next", "include_paths": ["docs/guide/"]},
        )
        # Let its import end before the app stops: a git process cut off by the shutdown
        # leaves its pipes to the garbage collector, which warns in a later test.
        job = f"/api/v1/jobs/{added.json()['job_id']}"
        for _ in range(1200):
            if (await client.get(job)).json()["state"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.05)

    assert refused.status_code == 429, refused.text
    assert refused.json()["error"] == "preview_busy"
    assert int(refused.headers["Retry-After"]) >= 1
    assert missing.status_code == 404  # nothing was stored
    assert added.status_code == 201, added.text
    assert added.json()["include_paths"] == ["docs/guide/"]
    assert "every preview slot is busy" in added.json()["context7_warning"]


async def test_without_paths_context7_json_pre_fills_the_preview(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    body = (await preview(client, docs_repo.file_url, ref="next")).json()

    assert body["context7_warning"] is None
    assert body["context7"]["rules"][0] == "Use v2 client"
    assert [v["tag"] for v in body["context7"]["previous_versions"]] == ["v1.4.0", "v1.3.0"]
    assert body["include_paths"] == ["docs/"]
    assert body["exclude_paths"] == body["context7"]["exclude_paths"]
    assert body["files"]
    assert all(f.startswith("docs/") and "/archive/" not in f for f in body["files"])


async def test_paths_a_user_sends_win_over_context7_json(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    body = (await preview(client, docs_repo.file_url, ref="next", include_paths=["**"])).json()

    assert (body["include_paths"], body["exclude_paths"]) == (["**"], [])
    assert "README.md" in body["files"]
    assert body["context7"]["include_paths"] == ["docs/"]  # still offered to the form


async def test_a_ref_without_context7_json_has_none(
    client: httpx.AsyncClient, docs_repo: DocsRepo
) -> None:
    body = (await preview(client, docs_repo.file_url, ref="v1.4.0")).json()

    assert (body["context7"], body["context7_warning"]) == (None, None)
    assert body["include_paths"] == []


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

        async def read_file(self, *_: object, **__: object) -> FetchedFile:
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
