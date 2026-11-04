"""``GET /api/v1/libraries/{owner}/{repo}/renamed-path``: both directions, defaults, errors."""

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import (
    ActivateManifestCommand,
    ArticleIn,
    RenameIn,
    StoreManifestCommand,
)
from exactdocs.catalog.models import RefKind

pytestmark = pytest.mark.usefixtures("demo_catalog")
URL = "/api/v1/libraries/acme/payments/renamed-path"


async def publish(container: Container, ref: str, commit: str, *renames: RenameIn) -> None:
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library="/acme/payments",
            ref=ref,
            kind=RefKind.TAG,
            commit_sha=commit * 40,
            articles=[
                ArticleIn(
                    path="guide/install.md",
                    blob_sha=hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest(),
                    content_version=1,
                    title="Install",
                    content=f"# Install {ref}",
                )
            ],
            renames=list(renames),
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


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
        await publish(container, "v1.3.0", "d")
        await publish(
            container,
            "v1.4.0",
            "e",
            RenameIn(
                from_ref="v1.3.0",
                old_path="guide/setup.md",
                new_path="guide/install.md",
                similarity=84,
            ),
        )
        yield client


async def test_a_moved_path_is_followed_forward_and_back(client: httpx.AsyncClient) -> None:
    forward = await client.get(URL, params={"ref": "v1.4.0", "path": "guide/setup.md"})
    back = await client.get(
        URL, params={"ref": "v1.4.0", "path": "guide/install.md", "direction": "back"}
    )

    expected = {
        "library": "/acme/payments",
        "ref": "v1.4.0",
        "from_ref": "v1.3.0",
        "old_path": "guide/setup.md",
        "new_path": "guide/install.md",
        "similarity": 84,
    }
    assert (forward.status_code, forward.json()) == (200, {"renamed": expected})
    assert (back.status_code, back.json()) == (200, {"renamed": expected})


async def test_a_blank_ref_means_the_default_version(client: httpx.AsyncClient) -> None:
    response = await client.get(URL, params={"ref": " ", "path": "guide/setup.md"})

    assert response.status_code == 200
    assert response.json()["renamed"]["ref"] == "v1.4.0"  # the newest stable tag


@pytest.mark.parametrize("params", [{"ref": "v1.3.0", "path": "guide/setup.md"}, {"path": "x.md"}])
async def test_a_path_that_was_not_renamed_is_a_200_with_null(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get(URL, params=params)

    assert (response.status_code, response.json()) == (200, {"renamed": None})


async def test_an_unknown_version_or_library_is_a_404(client: httpx.AsyncClient) -> None:
    unknown_ref = await client.get(URL, params={"ref": "v9", "path": "a.md"})
    unknown_library = await client.get(
        "/api/v1/libraries/nobody/nothing/renamed-path", params={"path": "a.md"}
    )

    assert unknown_ref.status_code == unknown_library.status_code == 404
    assert unknown_ref.json()["error"] == "not_found"


@pytest.mark.parametrize(
    "params", [{}, {"path": ""}, {"path": "x" * 5000}, {"path": "a.md", "direction": "sideways"}]
)
async def test_a_missing_empty_or_oversized_path_is_a_validation_error(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get(URL, params=params)

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


async def test_it_needs_a_session(client: httpx.AsyncClient) -> None:
    client.cookies.clear()

    response = await client.get(URL, params={"path": "a.md"})

    assert response.status_code == 401
