"""``GET``/``PUT``/``DELETE /api/v1/libraries/{owner}/{repo}/auto-sync``: the scheduled check."""

from collections.abc import AsyncIterator

import httpx
import pytest

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.dtos import RemoveLibraryCommand

LIBRARY = "/api/v1/libraries/acme/payments"
PATH = f"{LIBRARY}/auto-sync"
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
        answers = [
            await anonymous.get(PATH),
            await anonymous.put(PATH, json={}),
            await anonymous.delete(PATH),
        ]

    assert [a.status_code for a in answers] == [401, 401, 401]


async def test_a_schedule_is_set_read_and_turned_off(client: httpx.AsyncClient) -> None:
    before = await client.get(PATH)
    assert before.status_code == 200
    assert (before.json()["enabled"], before.json()["tag_pattern"]) == (False, None)

    put = await client.put(PATH, json={"tag_pattern": "v*", "keep_last": 3})

    assert put.status_code == 200
    body = put.json()
    assert {k: body[k] for k in ("enabled", "tag_pattern", "keep_last", "interval_minutes")} == {
        "enabled": True,
        "tag_pattern": "v*",
        "keep_last": 3,
        "interval_minutes": 60,
    }
    assert (body["sync_branches"], body["checked_at"], body["next_check_at"]) == (False, None, None)
    assert (await client.get(PATH)).json() == body

    off = await client.delete(PATH)

    assert (off.status_code, off.json()["enabled"]) == (200, False)
    assert (await client.get(PATH)).json()["enabled"] is False


async def test_versions_say_who_added_them(client: httpx.AsyncClient) -> None:
    detail = (await client.get(LIBRARY)).json()

    assert {v["origin"] for v in detail["versions"]} == {"manual"}


@pytest.mark.parametrize(
    "body",
    [{"keep_last": 0}, {"interval_minutes": 0}, {"tag_pattern": ""}, {"tag_pattern": "v *"}],
)
async def test_an_unusable_schedule_is_refused(client: httpx.AsyncClient, body: dict) -> None:
    refused = await client.put(PATH, json=body)

    assert refused.status_code == 422, refused.text
    assert (await client.get(PATH)).json()["enabled"] is False


async def test_an_unknown_library_has_no_schedule(client: httpx.AsyncClient) -> None:
    unknown = "/api/v1/libraries/acme/unknown/auto-sync"

    assert [
        (await client.get(unknown)).status_code,
        (await client.put(unknown, json={})).status_code,
    ] == [404, 404]


async def test_removing_the_library_removes_its_schedule(
    client: httpx.AsyncClient, container: Container
) -> None:
    await client.put(PATH, json={"tag_pattern": "v*"})

    await container.ingestion.remove_library(RemoveLibraryCommand(library="/acme/payments"))

    assert (await client.get(PATH)).status_code == 404
