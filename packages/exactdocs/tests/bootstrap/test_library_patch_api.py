"""``PATCH /api/v1/libraries/{owner}/{repo}``: who may call it, what it accepts, what it keeps."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import ApplyReadmeCommand

PATH = "/api/v1/libraries/acme/payments"
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


async def test_it_needs_a_caller(container: Container) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container)), base_url="http://localhost"
    ) as anonymous:
        response = await anonymous.patch(PATH, json={"title": "X"})

    assert (response.status_code, response.json()["error"]) == (401, "unauthenticated")


async def test_it_changes_only_the_given_field_and_returns_the_library(
    client: httpx.AsyncClient,
) -> None:
    response = await client.patch(PATH, json={"title": "Payments SDK"})

    body = response.json()
    assert response.status_code == 200
    assert (body["title"], body["description"]) == ("Payments SDK", "Payment processing SDK")


async def test_an_edit_survives_the_readme_of_the_default_version(
    client: httpx.AsyncClient, container: Container
) -> None:
    await client.patch(PATH, json={"title": "Payments SDK"})

    await container.catalog.apply_readme(
        ApplyReadmeCommand(
            library="/acme/payments", ref="v1.4.0", title="From README", description="Newer."
        )
    )

    body = (await client.get(PATH)).json()
    assert (body["title"], body["description"]) == ("Payments SDK", "Newer.")


async def test_an_unknown_library_is_404(client: httpx.AsyncClient) -> None:
    response = await client.patch("/api/v1/libraries/acme/nope", json={"title": "X"})

    assert (response.status_code, response.json()["error"]) == (404, "not_found")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": None},
        {"title": ""},
        {"title": "x" * 201},
        {"title": "two\nlines"},
        {"description": "x" * 1001},
        {"title": "T", "unknown": 1},
    ],
)
async def test_a_bad_body_is_422(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.patch(PATH, json=body)

    assert (response.status_code, response.json()["error"]) == (422, "validation_error")
