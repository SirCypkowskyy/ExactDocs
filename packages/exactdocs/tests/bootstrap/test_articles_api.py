"""The article routes under `/api/v1/libraries/{owner}/{repo}`: refs with `/`, defaults, errors."""

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind
from exactdocs_kernel import NOTICE

pytestmark = pytest.mark.usefixtures("demo_catalog")


def _blob(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


async def publish(container: Container, ref: str, kind: RefKind, commit: str, *paths: str) -> None:
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref=ref,
            kind=kind,
            commit_sha=commit * 40,
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=hashlib.sha1(
                        f"{path}{ref}".encode(), usedforsecurity=False
                    ).hexdigest(),
                    content_version=1,
                    title=path,
                    content=f"# {path} at {ref}",
                )
                for path in paths
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


@pytest.fixture
async def client(demo_catalog: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())
    # ASGITransport does not run the app's lifespan, which is what migrates the database.
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=demo_catalog,
        ) as client,
    ):
        await publish(container, "release/1.4", RefKind.BRANCH, "c", "guide/install.md")
        await publish(container, "v1.3.0", RefKind.TAG, "d", "guide/install.md", "old-only.md")
        await publish(container, "v1.4.0", RefKind.TAG, "e", "guide/install.md", "new-only.md")
        yield client


async def test_a_ref_with_a_slash_goes_in_the_query_string(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/article",
        params={"ref": "release/1.4", "path": "guide/install.md"},
    )

    assert response.status_code == 200
    assert response.json() | {"manifest_id": ""} == {
        "notice": NOTICE,
        "source_url": f"https://github.com/acme/payments/blob/{'c' * 40}/guide/install.md",
        "library": "/acme/payments",
        "ref": "release/1.4",
        "commit_sha": "c" * 40,
        "manifest_id": "",
        "path": "guide/install.md",
        "title": "guide/install.md",
        "tags": [],
        "tag_origins": [],
        "manual_tags": [],
        "size": 33,
        "front_matter": {},
        "content": "# guide/install.md at release/1.4",
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
    response = await client.get("/api/v1/libraries/acme/payments/articles")

    body = response.json()
    assert response.status_code == 200
    assert (body["ref"], body["commit_sha"]) == ("v1.4.0", "e" * 40)


async def test_a_default_version_without_articles_is_not_replaced_by_another(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/ledger/articles"
    )  # ledger: main, no manifest

    assert response.status_code == 404
    assert "main" in response.json()["detail"]


@pytest.mark.parametrize(
    ("ref", "path"),
    [("v1.4.0", "old-only.md"), ("v1.3.0", "new-only.md"), ("main", "guide/install.md")],
)
async def test_another_versions_article_is_not_found_by_path(
    client: httpx.AsyncClient, ref: str, path: str
) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/article", params={"ref": ref, "path": path}
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_a_directory_prefix_does_not_reach_a_sibling_with_the_same_start(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/payments/articles", params={"ref": "v1.3.0", "path_prefix": "gui"}
    )

    assert response.json()["articles"] == []


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
