"""`GET /api/v1/libraries/{owner}/{repo}/logo` (#504): from ExactDocs' origin, cached, hardened."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ApplyLogoCommand, LogoIn

pytestmark = pytest.mark.usefixtures("demo_catalog")

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
LOGO = "/api/v1/libraries/acme/payments/logo"


@pytest.fixture
async def container(demo_catalog: dict[str, str]) -> AsyncIterator[Container]:
    del demo_catalog  # stored first, by a container of its own
    container = Container.build(Settings())
    async with container.running():
        yield container


@pytest.fixture
async def client(
    container: Container, demo_catalog: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)),
        base_url="http://localhost",
        cookies=demo_catalog,
    ) as client:
        yield client


async def keep(container: Container, data: bytes, content_type: str) -> None:
    """Have the catalog keep a logo of the default version, as an import would."""
    logo = LogoIn.model_validate({"path": "logo", "content_type": content_type, "data": data})
    await container.catalog.apply_logo(
        ApplyLogoCommand(library="/acme/payments", ref="v1.4.0", logo=logo)
    )


async def test_a_library_says_which_logo_it_has_and_the_logo_is_served(
    container: Container, client: httpx.AsyncClient
) -> None:
    await keep(container, PNG, "image/png")

    library = (await client.get("/api/v1/libraries/acme/payments")).json()
    listed = (await client.get("/api/v1/libraries")).json()["libraries"]
    response = await client.get(LOGO)

    version = library["logo"]
    assert version
    assert {lib["id"]: lib["logo"] for lib in listed} == {
        "/acme/ledger": None,
        "/acme/payments": version,
    }
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == f'"{version}"'
    assert response.headers["cache-control"] == "private, no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "content-disposition" not in response.headers


async def test_the_current_version_is_cached_for_good_and_an_old_one_is_not(
    container: Container, client: httpx.AsyncClient
) -> None:
    await keep(container, PNG, "image/png")
    version = (await client.get("/api/v1/libraries/acme/payments")).json()["logo"]

    current = await client.get(LOGO, params={"v": version})
    stale = await client.get(LOGO, params={"v": "0123456789abcdef"})

    assert current.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert stale.headers["cache-control"] == "private, no-cache"
    assert stale.content == PNG  # the logo it has now, never one it had


async def test_a_matching_etag_answers_304_without_the_body(
    container: Container, client: httpx.AsyncClient
) -> None:
    await keep(container, PNG, "image/png")
    etag = (await client.get(LOGO)).headers["etag"]

    response = await client.get(LOGO, headers={"If-None-Match": f'"old", {etag}'})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag


async def test_an_svg_logo_is_an_attachment_under_a_csp_that_forbids_scripts(
    container: Container, client: httpx.AsyncClient
) -> None:
    await keep(container, SVG, "image/svg+xml")

    response = await client.get(LOGO)

    assert response.content == SVG
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-disposition"] == 'attachment; filename="logo.svg"'
    policy = response.headers["content-security-policy"]
    assert "sandbox" in policy
    assert "script-src" not in policy


@pytest.mark.parametrize(
    "path",
    ["/api/v1/libraries/acme/ledger/logo", "/api/v1/libraries/acme/nothing/logo"],
    ids=["no logo", "no library"],
)
async def test_no_logo_is_not_found(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_a_logo_needs_a_signed_in_caller(container: Container) -> None:
    await keep(container, PNG, "image/png")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as anonymous:
        response = await anonymous.get(LOGO)

    assert response.status_code == 401
