"""The sign-in throttle over HTTP: 429 and Retry-After on both credential endpoints."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand
from exactdocs.identity.models import FIRST_WAIT, FREE_FAILURES

HORSE = "correct horse battery staple"
SESSION, TOKEN_LOGIN = "/api/v1/session", "/api/v1/tokens/login"


def body(path: str, username: str, password: str) -> dict[str, str]:
    extra = {"name": "laptop"} if path == TOKEN_LOGIN else {}
    return {"username": username, "password": password, **extra}


@pytest.fixture
async def container() -> AsyncIterator[Container]:
    container = Container.build(Settings())
    async with container.running():
        command = CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        await container.identity.create_first_admin(command)
        yield container


def client_at(app: Any, address: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(address, 4000))
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def fail(client: httpx.AsyncClient, path: str, times: int, **headers: str) -> None:
    for _ in range(times):
        response = await client.post(path, json=body(path, "root", "wrong"), headers=headers)
        assert response.status_code == 401, response.text


@pytest.mark.parametrize(("first", "then"), [(SESSION, TOKEN_LOGIN), (TOKEN_LOGIN, SESSION)])
async def test_both_endpoints_answer_429_with_retry_after_and_share_the_count(
    container: Container, first: str, then: str
) -> None:
    app = create_app(container)
    async with client_at(app, "203.0.113.7") as attacker, client_at(app, "198.51.100.2") as admin:
        await fail(attacker, first, FREE_FAILURES)

        refused = await attacker.post(then, json=body(then, "ada", HORSE))
        allowed = await admin.post(then, json=body(then, "ada", HORSE))

    assert refused.status_code == 429
    assert refused.headers["retry-after"] == str(int(FIRST_WAIT.total_seconds()))
    assert refused.json()["error"] == "rate_limited"
    assert "set-cookie" not in refused.headers
    assert allowed.status_code == 201


async def test_the_address_is_the_one_a_trusted_proxy_forwards(container: Container) -> None:
    # What `exactdocs serve` runs: uvicorn's proxy headers, trusting `forwarded_allow_ips`.
    app = create_app(container)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=container.settings.forwarded_allow_ips)
    async with client_at(app, "127.0.0.1") as proxy:
        await fail(proxy, SESSION, FREE_FAILURES, **{"x-forwarded-for": "203.0.113.7"})

        refused = await proxy.post(
            SESSION, json=body(SESSION, "ada", HORSE), headers={"x-forwarded-for": "203.0.113.7"}
        )
        allowed = await proxy.post(
            SESSION, json=body(SESSION, "ada", HORSE), headers={"x-forwarded-for": "198.51.100.2"}
        )

    assert (refused.status_code, allowed.status_code) == (429, 201)


async def test_an_untrusted_client_cannot_choose_its_address(container: Container) -> None:
    app = create_app(container)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=container.settings.forwarded_allow_ips)
    async with client_at(app, "203.0.113.7") as attacker:
        for n in range(FREE_FAILURES):
            await fail(attacker, SESSION, 1, **{"x-forwarded-for": f"192.0.2.{n}"})

        refused = await attacker.post(
            SESSION, json=body(SESSION, "ada", HORSE), headers={"x-forwarded-for": "192.0.2.99"}
        )

    assert refused.status_code == 429


async def test_429_is_part_of_the_typed_error_shape(container: Container) -> None:
    async with client_at(create_app(container), "127.0.0.1") as client:
        document = (await client.get("/api/v1/openapi.json")).json()

    paths = document["paths"]
    for path in (SESSION, TOKEN_LOGIN):
        responses = paths[path]["post"]["responses"]
        assert responses["429"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        assert "rate_limited" in responses["429"]["description"]
        assert responses["429"]["headers"]["Retry-After"]["schema"] == {"type": "integer"}
    throttled = {
        (path, method)
        for path, operations in paths.items()
        for method, operation in operations.items()
        if "429" in operation.get("responses", {})
    }
    # Besides the credential routes, only the import preview (busy slots, #62) and adding a
    # library without paths (its context7.json is read under a preview slot, #63) answer 429.
    assert throttled == {
        (SESSION, "post"),
        (TOKEN_LOGIN, "post"),
        ("/api/v1/repositories/preview", "post"),
        ("/api/v1/libraries", "post"),
    }
