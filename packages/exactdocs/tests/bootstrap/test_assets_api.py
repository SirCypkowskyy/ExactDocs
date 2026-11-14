"""`GET /api/v1/libraries/{owner}/{repo}/asset`: images with safe, content-addressed headers."""

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
    ImageIn,
    StoreManifestCommand,
)
from exactdocs.catalog.models import RefKind

pytestmark = pytest.mark.usefixtures("demo_catalog")

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 8
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
ASSET = "/api/v1/libraries/acme/payments/asset"


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


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
                ref="v1.4.0",
                kind=RefKind.TAG,
                commit_sha="e" * 40,
                articles=[
                    ArticleIn(
                        path="docs/a.md",
                        blob_sha="a" * 40,
                        content_version=1,
                        title="A",
                        content="x",
                    )
                ],
                images=[
                    ImageIn(
                        path="docs/img/flow.png",
                        blob_sha=blob(PNG),
                        content_type="image/png",
                        data=PNG,
                    ),
                    ImageIn(
                        path="docs/img/evil.svg",
                        blob_sha=blob(SVG),
                        content_type="image/svg+xml",
                        data=SVG,
                    ),
                ],
            )
        )
        await container.catalog.activate_manifest(
            ActivateManifestCommand(manifest_id=stored.manifest_id)
        )
        yield client


async def test_an_image_is_served_with_its_type_and_hardening_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(ASSET, params={"ref": "v1.4.0", "path": "docs/img/flow.png"})

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    policy = response.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert all(
        d in policy for d in ("frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'")
    )
    assert response.headers["cache-control"] == "private, no-cache"
    assert response.headers["etag"] == f'"{blob(PNG)}"'
    assert "content-disposition" not in response.headers


async def test_no_ref_means_the_default_version(client: httpx.AsyncClient) -> None:
    response = await client.get(ASSET, params={"path": "docs/img/flow.png"})

    assert response.status_code == 200


async def test_an_svg_is_an_attachment_under_a_csp_that_forbids_scripts(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(ASSET, params={"path": "docs/img/evil.svg"})

    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "script-src" not in response.headers["content-security-policy"]


async def test_a_matching_etag_answers_304_without_the_body(client: httpx.AsyncClient) -> None:
    etag = f'"{blob(PNG)}"'

    response = await client.get(
        ASSET, params={"path": "docs/img/flow.png"}, headers={"If-None-Match": f'"x", {etag}'}
    )

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag


@pytest.mark.parametrize(
    "params",
    [
        {"path": "docs/img/other.png"},
        {"path": "docs/a.md"},  # an article is not an image
        {"path": "../../etc/passwd"},
        {"path": "docs/img/flow.png", "ref": "v9"},
    ],
)
async def test_what_is_not_a_stored_image_is_not_found(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get(ASSET, params=params)

    assert response.status_code == 404


async def test_another_librarys_image_is_not_reachable(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/libraries/acme/ledger/asset", params={"path": "docs/img/flow.png"}
    )

    assert response.status_code == 404


async def test_images_need_a_signed_in_caller() -> None:
    container = Container.build(Settings())
    async with (
        container.running(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
        ) as anonymous,
    ):
        response = await anonymous.get(ASSET, params={"path": "docs/img/flow.png"})

    assert response.status_code == 401
