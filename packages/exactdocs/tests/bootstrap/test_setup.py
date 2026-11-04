"""The first-run guard: until an account exists, `/api/v1` offers nothing but the setup."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand

CREDENTIALS = {"username": "ada", "password": "correct horse battery staple"}


@pytest.fixture
def container() -> Container:
    return Container.build(Settings())


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        yield client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/libraries"),
        ("GET", "/api/v1/libraries/acme/payments"),
        ("GET", "/api/v1/search"),
        ("POST", "/api/v1/libraries"),
        ("DELETE", "/api/v1/libraries"),
        ("GET", "/api/v1/nope"),
        ("POST", "/api/v1/session"),  # only `GET /session` is exempt
        ("GET", "/api/v1/setup"),
        ("GET", "/api/v1/setup/"),
        ("POST", "/api/v1/setup/"),
        ("GET", "/api/v1"),
    ],
)
async def test_everything_but_setup_is_refused_before_the_first_account(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)

    assert response.status_code == 403
    assert response.json()["error"] == "setup_required"
    assert response.json()["detail"]


@pytest.mark.parametrize("path", ["/api/health", "/api/v1/openapi.json"])
async def test_health_and_the_api_description_stay_reachable(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 200


async def test_setup_creates_the_admin_and_opens_the_api(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/setup", json=CREDENTIALS)

    assert created.status_code == 201
    body = created.json()
    assert (body["username"], body["role"]) == ("ada", "admin")
    assert set(body) == {"id", "username", "role"}
    assert CREDENTIALS["password"] not in created.text
    assert (await client.get("/api/v1/libraries")).status_code == 200


async def test_setup_works_once(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/setup", json=CREDENTIALS)

    again = await client.post(
        "/api/v1/setup", json={"username": "mallory", "password": "another strong password"}
    )

    assert again.status_code == 409
    assert again.json()["error"] == "already_set_up"


async def test_a_refused_setup_creates_nothing(client: httpx.AsyncClient) -> None:
    short = await client.post("/api/v1/setup", json={**CREDENTIALS, "password": "tiny-9"})
    blank = await client.post("/api/v1/setup", json={**CREDENTIALS, "username": " "})
    extra = await client.post("/api/v1/setup", json={**CREDENTIALS, "role": "admin"})

    assert (short.status_code, blank.status_code, extra.status_code) == (422, 422, 422)
    assert blank.json()["error"] == "invalid_username"
    assert short.json()["error"] == "validation_error"
    assert "tiny-9" not in short.text  # the input is never echoed back
    assert (await client.get("/api/v1/libraries")).status_code == 403


async def test_concurrent_setups_create_exactly_one_admin(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/setup", json={"username": f"user{i}", "password": CREDENTIALS["password"]}
            )
            for i in range(4)
        )
    )

    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409]


async def test_an_admin_created_elsewhere_ends_the_setup_state(client: httpx.AsyncClient) -> None:
    # The CLI creates the admin in another process while the server is already running.
    assert (await client.get("/api/v1/libraries")).status_code == 403
    other = Container.build(Settings())
    async with other.running():
        await other.identity.create_first_admin(
            CreateFirstAdminCommand(
                username=CREDENTIALS["username"], password=SecretStr(CREDENTIALS["password"])
            )
        )

    assert (await client.get("/api/v1/libraries")).status_code == 200
    assert (await client.post("/api/v1/setup", json=CREDENTIALS)).status_code == 409
