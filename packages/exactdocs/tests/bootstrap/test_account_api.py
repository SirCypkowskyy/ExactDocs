"""``PUT /api/v1/account/password`` over HTTP: sessions only, throttled, other sessions end."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import FREE_FAILURES, SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
NEW = "a brand new horse battery"
PASSWORD = "/api/v1/account/password"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        command = CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        await container.identity.create_first_admin(command)
        yield client


async def session_of(client: httpx.AsyncClient, password: str = HORSE) -> dict[str, str]:
    request = client.build_request(
        "POST", "/api/v1/session", json={"username": "ada", "password": password}
    )
    request.headers.pop("cookie", None)
    response = await client.send(request)
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return {"cookie": f"{SESSION_COOKIE}={response.cookies[SESSION_COOKIE]}"}


def body(current: str, new: str = NEW) -> dict[str, str]:
    return {"current_password": current, "new_password": new}


async def test_a_change_keeps_this_session_and_ends_the_others(client: httpx.AsyncClient) -> None:
    this, other = await session_of(client), await session_of(client)

    response = await client.put(PASSWORD, json=body(HORSE), headers=this)

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert (await client.get("/api/v1/libraries", headers=this)).status_code == 200
    assert (await client.get("/api/v1/libraries", headers=other)).status_code == 401
    await session_of(client, NEW)
    old = await client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
    assert old.status_code == 401


async def test_the_session_state_says_the_account_has_a_password(
    client: httpx.AsyncClient,
) -> None:
    state = (await client.get("/api/v1/session", headers=await session_of(client))).json()

    assert state["account"]["has_password"] is True


async def test_a_wrong_current_password_is_403_and_keeps_the_caller_signed_in(
    client: httpx.AsyncClient,
) -> None:
    this = await session_of(client)

    response = await client.put(PASSWORD, json=body("not the password"), headers=this)

    assert (response.status_code, response.json()["error"]) == (403, "wrong_password")
    assert (await client.get("/api/v1/libraries", headers=this)).status_code == 200


async def test_repeated_wrong_passwords_are_rate_limited(client: httpx.AsyncClient) -> None:
    this = await session_of(client)
    for _ in range(FREE_FAILURES):
        await client.put(PASSWORD, json=body("not the password"), headers=this)

    response = await client.put(PASSWORD, json=body(HORSE), headers=this)

    assert (response.status_code, response.json()["error"]) == (429, "rate_limited")
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("new", ["too short", "x" * 1025])
async def test_a_new_password_outside_the_setup_limits_is_422(
    client: httpx.AsyncClient, new: str
) -> None:
    response = await client.put(PASSWORD, json=body(HORSE, new), headers=await session_of(client))

    assert (response.status_code, response.json()["error"]) == (422, "validation_error")


async def test_an_api_token_cannot_change_the_password(client: httpx.AsyncClient) -> None:
    this = await session_of(client)
    token = (await client.post("/api/v1/tokens", json={"name": "ci"}, headers=this)).json()

    response = await client.put(
        PASSWORD, json=body(HORSE), headers={"authorization": f"Bearer {token['token']}"}
    )

    assert response.status_code == 401, response.text
    await session_of(client)  # unchanged


async def test_signed_out_it_is_401(client: httpx.AsyncClient) -> None:
    response = await client.put(PASSWORD, json=body(HORSE))

    assert response.status_code == 401, response.text


async def test_the_operation_is_documented_with_its_throttle(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()

    operation = spec["paths"][PASSWORD]["put"]
    assert {"204", "429"} <= set(operation["responses"])
    assert "wrong_password" in operation["description"]
