"""``PUT``/``DELETE /api/v1/libraries/{owner}/{repo}/tags?path=``: callers, errors, the copies."""

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand

URL = "/api/v1/libraries/acme/payments/tags"
pytestmark = pytest.mark.usefixtures("demo_catalog")


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    built = Container.build(Settings())
    async with built.running():
        yield built


@pytest.fixture
def client(container: Container, demo_catalog: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    )


async def publish(container: Container, ref: str, path: str) -> None:
    """Store, index and activate one article, as an import does."""
    blob = hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest()
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref=ref,
            kind=RefKind.TAG,
            commit_sha=blob,
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=blob,
                    content_version=1,
                    title="Setup",
                    tags=["guide"],
                    content="# Setup\n\nRun the installer.",
                )
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library="/acme/payments",
            ref=ref,
            config_hash="c",
            articles=[
                ArticleChunksIn(
                    path=path,
                    blob_sha=blob,
                    tags=["guide"],
                    chunks=[
                        ChunkIn(
                            heading_path=["Setup"],
                            occurrence_index=0,
                            content="Run the installer.",
                            content_hash="h",
                            anchor="setup",
                            code_languages=[],
                        )
                    ],
                )
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def search_tags(client: httpx.AsyncClient, tag: str) -> list[list[str]]:
    response = await client.get(
        "/api/v1/libraries/acme/payments/search",
        params={"q": "installer", "ref": "v1.3.0", "tags": tag},
    )
    assert response.status_code == 200, response.text
    return [r["tags"] for r in response.json()["results"]]


async def test_it_needs_a_caller(container: Container) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as anonymous:
        put = await anonymous.put(URL, params={"path": "a.md"}, json={"tags": ["x"]})
        delete = await anonymous.delete(URL, params={"path": "a.md"})

    assert (put.status_code, delete.status_code) == (401, 401)


async def test_tags_reach_the_article_and_its_search_chunks_and_go_again(
    client: httpx.AsyncClient, container: Container
) -> None:
    await publish(container, "v1.3.0", "guide/setup.md")

    put = await client.put(
        URL, params={"path": "guide/setup.md"}, json={"tags": ["Onboarding", "onboarding"]}
    )

    assert put.status_code == 200, put.text
    assert put.json() == {
        "library": "/acme/payments",
        "path": "guide/setup.md",
        "tags": ["onboarding"],
    }
    article = await client.get(
        "/api/v1/libraries/acme/payments/article",
        params={"ref": "v1.3.0", "path": "guide/setup.md"},
    )
    assert (article.json()["tags"], article.json()["manual_tags"]) == (
        ["guide", "onboarding"],
        ["onboarding"],
    )
    assert await search_tags(client, "onboarding") == [["guide", "onboarding"]]

    delete = await client.delete(URL, params={"path": "guide/setup.md"})

    assert (delete.status_code, delete.content) == (204, b"")
    assert await search_tags(client, "onboarding") == []
    assert await search_tags(client, "guide") == [["guide"]]


async def test_an_unknown_library_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/api/v1/libraries/acme/nope/tags", params={"path": "a.md"}, json={"tags": ["x"]}
    )

    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    ("params", "body", "error"),
    [
        ({"path": "a.md"}, {"tags": ["#!?"]}, "invalid_tags"),
        ({"path": "../a.md"}, {"tags": ["x"]}, None),
        ({"path": "a.md"}, {"tags": [f"t{i}" for i in range(21)]}, None),
        ({}, {"tags": ["x"]}, None),
    ],
)
async def test_bad_input_is_refused(
    client: httpx.AsyncClient, params: dict[str, str], body: dict[str, object], error: str | None
) -> None:
    response = await client.put(URL, params=params, json=body)

    assert response.status_code == 422, response.text
    if error:
        assert response.json()["error"] == error
