"""``PUT``/``DELETE /api/v1/libraries/{owner}/{repo}/default-version``: pin, unpin, errors."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

LIBRARY = "/api/v1/libraries/acme/payments"
PATH = f"{LIBRARY}/default-version"
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
        pinned = await anonymous.put(PATH, json={"ref": "v1.3.0"})
        unpinned = await anonymous.delete(PATH)

    assert [pinned.status_code, unpinned.status_code] == [401, 401]


async def test_pinning_and_unpinning_moves_the_default_everywhere(
    client: httpx.AsyncClient,
) -> None:
    pinned = await client.put(PATH, json={"ref": "v1.3.0"})

    assert pinned.status_code == 200
    assert (pinned.json()["default_version"], pinned.json()["default_pinned"]) == ("v1.3.0", True)
    listed = (await client.get("/api/v1/libraries")).json()["libraries"]
    (payments,) = [lib for lib in listed if lib["id"] == "/acme/payments"]
    assert (payments["default_version"], payments["default_pinned"]) == ("v1.3.0", True)
    flags = {v["ref"]: v["is_default"] for v in pinned.json()["versions"]}
    assert [ref for ref, default in flags.items() if default] == ["v1.3.0"]

    unpinned = await client.delete(PATH)

    assert unpinned.status_code == 200
    body = unpinned.json()
    assert (body["default_version"], body["default_pinned"]) == ("v1.4.0", False)


@pytest.mark.parametrize(
    ("path", "body", "status", "code"),
    [
        (PATH, {"ref": "v9.9.9"}, 404, "not_found"),
        (PATH, {"ref": "V1.3.0"}, 404, "not_found"),  # refs are case-sensitive
        ("/api/v1/libraries/nobody/nothing/default-version", {"ref": "v1"}, 404, "not_found"),
        (PATH, {}, 422, "validation_error"),
        (PATH, {"ref": ""}, 422, "validation_error"),
    ],
)
async def test_a_bad_pin_is_refused_and_changes_nothing(
    client: httpx.AsyncClient, path: str, body: dict[str, str], status: int, code: str
) -> None:
    response = await client.put(path, json=body)

    assert (response.status_code, response.json()["error"]) == (status, code)
    assert (await client.get(LIBRARY)).json()["default_pinned"] is False
