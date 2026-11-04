"""The tag filter of `GET /api/v1/libraries/{owner}/{repo}/articles`: the REST contract."""

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind

pytestmark = pytest.mark.usefixtures("demo_catalog")

ARTICLES = {
    "a.md": ["api"],
    "b.md": ["adr"],
    "c.md": ["api", "auth"],
    "d.md": [],
}
URL = "/api/v1/libraries/acme/payments/articles"


@pytest.fixture
async def client(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        stored = await container.catalog.store_manifest(
            StoreManifestCommand(
                library="/acme/payments",
                ref="main",
                kind=RefKind.BRANCH,
                commit_sha="a" * 40,
                articles=[
                    ArticleIn(
                        path=path,
                        blob_sha=hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest(),
                        content_version=1,
                        title=path,
                        tags=tags,
                        content=path,
                    )
                    for path, tags in ARTICLES.items()
                ],
            )
        )
        await container.catalog.activate_manifest(
            ActivateManifestCommand(manifest_id=stored.manifest_id)
        )
        yield client


async def listed(client: httpx.AsyncClient, params: list[tuple[str, str]]) -> list[str]:
    response = await client.get(URL, params=[("ref", "main"), *params])
    assert response.status_code == 200, response.text
    return [a["path"] for a in response.json()["articles"]]


@pytest.mark.parametrize(
    ("params", "paths"),
    [
        ([("tags", "api"), ("tags", "adr")], ["a.md", "b.md", "c.md"]),  # repeated
        ([("tags", "api,adr")], ["a.md", "b.md", "c.md"]),  # comma-separated
        ([("tags", "api,adr"), ("tags", "auth")], ["a.md", "b.md", "c.md"]),  # mixed
        ([("tags", "API , Auth"), ("tags_match", "all")], ["c.md"]),  # case and blanks
        ([("tags", "a,%20,b".replace("%20", " "))], []),  # a blank value is ignored
        ([("tags", "")], ["a.md", "b.md", "c.md", "d.md"]),  # empty keeps everything
        ([], ["a.md", "b.md", "c.md", "d.md"]),
        ([("tags", "api"), ("tags_match", "any")], ["a.md", "c.md"]),
    ],
)
async def test_the_filter_forms(
    client: httpx.AsyncClient, params: list[tuple[str, str]], paths: list[str]
) -> None:
    assert await listed(client, params) == paths


@pytest.mark.parametrize(
    "params",
    [
        [("tags", ",".join(f"t{i}" for i in range(21)))],  # 21 values
        [("tags", f"t{i}") for i in range(21)],  # 21 repeats
        [("tags", "api"), ("tags_match", "bogus")],
        [("tags", "not a tag!")],
        [("tags", "a" * 41)],
        [("tags", "x" * 2000)],
    ],
)
async def test_a_bad_filter_is_a_422(
    client: httpx.AsyncClient, params: list[tuple[str, str]]
) -> None:
    response = await client.get(URL, params=[("ref", "main"), *params])

    assert response.status_code == 422, response.text


async def test_twenty_tags_are_fine(client: httpx.AsyncClient) -> None:
    params = [("tags", f"t{i}") for i in range(20)]

    assert await listed(client, params) == []


TAGS_URL = "/api/v1/libraries/acme/payments/tags"


async def test_the_tags_of_a_version_are_counted_most_used_first(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(TAGS_URL, params={"ref": "main"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tags"] == [
        {"tag": "api", "count": 2},
        {"tag": "adr", "count": 1},
        {"tag": "auth", "count": 1},
    ]
    assert body["ref"] == "main"
    assert body["truncated"] is False


async def test_the_tags_of_an_unknown_version_are_a_404(client: httpx.AsyncClient) -> None:
    response = await client.get(TAGS_URL, params={"ref": "v9"})

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_a_missing_article_names_its_close_matches_as_a_field(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/article", params={"ref": "main", "path": "docs/a.md"}
    )

    assert response.status_code == 404
    assert response.json()["close_matches"] == ["a.md"]


async def test_other_errors_have_no_close_matches(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/libraries/acme/nope")

    assert response.json()["close_matches"] == []
