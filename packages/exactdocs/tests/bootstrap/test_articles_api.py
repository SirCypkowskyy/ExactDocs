"""The article routes under `/api/v1/libraries/{owner}/{repo}`: refs with `/`, defaults, errors."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind

pytestmark = pytest.mark.usefixtures("demo_catalog")
BLOB = "ab" * 20


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())
    # ASGITransport does not run the app's lifespan, which is what migrates the database.
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
        ) as client,
    ):
        stored = await container.catalog.store_manifest(
            StoreManifestCommand(
                library="/acme/payments",
                ref="release/1.4",
                kind=RefKind.BRANCH,
                commit_sha="c" * 40,
                articles=[
                    ArticleIn(
                        path="guide/install.md", blob_sha=BLOB, title="Install", content="# Install"
                    )
                ],
            )
        )
        await container.catalog.activate_manifest(
            ActivateManifestCommand(manifest_id=stored.manifest_id)
        )
        yield client


async def test_a_ref_with_a_slash_goes_in_the_query_string(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/article",
        params={"ref": "release/1.4", "path": "guide/install.md"},
    )

    assert response.status_code == 200
    assert response.json() | {"manifest_id": ""} == {
        "library": "/acme/payments",
        "ref": "release/1.4",
        "commit_sha": "c" * 40,
        "manifest_id": "",
        "path": "guide/install.md",
        "title": "Install",
        "tags": [],
        "size": 9,
        "front_matter": {},
        "content": "# Install",
    }


async def test_the_listing_names_the_version_it_came_from(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/articles", params={"ref": "release/1.4"}
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["ref"], body["commit_sha"], body["next_cursor"]) == ("release/1.4", "c" * 40, None)
    assert [a["path"] for a in body["articles"]] == ["guide/install.md"]


async def test_the_default_version_is_used_without_a_ref(client: httpx.AsyncClient) -> None:
    # The default is v1.4.0 (a stable tag), which has no manifest: never another version's.
    response = await client.get("/api/v1/libraries/acme/payments/articles")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "v1.4.0" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "params", "status", "error"),
    [
        ("/acme/payments/article", {}, 422, "validation_error"),  # path is required
        ("/acme/payments/articles", {"limit": 0}, 422, "validation_error"),
        ("/acme/payments/articles", {"ref": "release/1.4", "cursor": "!"}, 422, "invalid_cursor"),
        ("/vuejs/docs/article", {"path": "a.md"}, 404, "not_found"),
        ("/acme/pay$ments/articles", {}, 422, "validation_error"),
    ],
)
async def test_bad_requests_get_the_error_envelope(
    client: httpx.AsyncClient, path: str, params: dict[str, str | int], status: int, error: str
) -> None:
    response = await client.get(f"/api/v1/libraries{path}", params=params)

    assert (response.status_code, response.json()["error"]) == (status, error)
