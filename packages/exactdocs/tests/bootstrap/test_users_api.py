"""The operator's users page over HTTP: operators only, sessions only, no self-signup."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
BOB = {"username": "bob", "password": "bob's long passphrase"}


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


async def session_of(client: httpx.AsyncClient, username: str, password: str) -> dict[str, str]:
    """Sign in without the jar's cookie, and return a header carrying exactly the new session."""
    request = client.build_request(
        "POST", "/api/v1/session", json={"username": username, "password": password}
    )
    request.headers.pop("cookie", None)
    response = await client.send(request)
    assert response.status_code == 201, response.text
    client.cookies.clear()
    return {"cookie": f"{SESSION_COOKIE}={response.cookies[SESSION_COOKIE]}"}


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> dict[str, str]:
    return await session_of(client, "ada", HORSE)


async def test_an_operator_creates_and_lists_users(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    created = await client.post("/api/v1/users", json=BOB, headers=ada)

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["username"], body["role"], body["disabled"]) == ("bob", "user", False)
    assert set(body) == {
        "id",
        "username",
        "role",
        "has_password",
        "created_at",
        "disabled",
        "provider",
        "groups",
        "last_active_at",
        "token_count",
        "rules",
    }
    assert (body["last_active_at"], body["token_count"]) == (None, 0)  # never active, no tokens
    assert BOB["password"] not in created.text
    listed = (await client.get("/api/v1/users", headers=ada)).json()["users"]
    assert [(u["username"], u["role"]) for u in listed] == [("ada", "admin"), ("bob", "user")]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"username": "ADA", "password": "a long enough one"}, 409, "username_taken"),
        ({"username": "a@address:x", "password": "a long enough one"}, 422, "invalid_username"),
        ({"username": "two words", "password": "a long enough one"}, 422, "invalid_username"),
        ({"username": "bob", "password": "short"}, 422, "validation_error"),
        ({"username": "bob", "password": "a long enough one", "role": "root"}, 422, None),
    ],
)
async def test_a_bad_new_user_is_refused(
    client: httpx.AsyncClient, ada: dict[str, str], body: dict, status: int, code: str | None
) -> None:
    response = await client.post("/api/v1/users", json=body, headers=ada)

    assert response.status_code == status, response.text
    if code:
        assert response.json()["error"] == code


async def test_disabling_and_enabling_a_user(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    bob_id = (await client.post("/api/v1/users", json=BOB, headers=ada)).json()["id"]
    bob = await session_of(client, "bob", BOB["password"])

    disabled = await client.post(f"/api/v1/users/{bob_id}/disable", headers=ada)

    assert (disabled.status_code, disabled.json()["disabled"]) == (200, True)
    assert (await client.get("/api/v1/libraries", headers=bob)).status_code == 401
    enabled = await client.post(f"/api/v1/users/{bob_id}/enable", headers=ada)
    assert (enabled.status_code, enabled.json()["disabled"]) == (200, False)
    assert (await client.get("/api/v1/libraries", headers=bob)).status_code == 401  # ended
    await session_of(client, "bob", BOB["password"])


async def test_the_last_operator_cannot_disable_themselves(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    ada_id = (await client.get("/api/v1/users", headers=ada)).json()["users"][0]["id"]

    response = await client.post(f"/api/v1/users/{ada_id}/disable", headers=ada)

    assert (response.status_code, response.json()["error"]) == (409, "last_operator")


async def test_an_unknown_user_is_404(client: httpx.AsyncClient, ada: dict[str, str]) -> None:
    for method, path, body in [
        ("POST", "/api/v1/users/nope/disable", None),
        ("POST", "/api/v1/users/nope/enable", None),
        ("PUT", "/api/v1/users/nope/password", {"password": "a long enough one"}),
    ]:
        response = await client.request(method, path, json=body, headers=ada)
        assert (response.status_code, response.json()["error"]) == (404, "unknown_account")


async def test_resetting_a_password_ends_the_users_sessions(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    bob_id = (await client.post("/api/v1/users", json=BOB, headers=ada)).json()["id"]
    bob = await session_of(client, "bob", BOB["password"])
    new = "bob's brand new passphrase"

    reset = await client.put(
        f"/api/v1/users/{bob_id}/password", json={"password": new}, headers=ada
    )

    assert reset.status_code == 200, reset.text
    assert (reset.json()["account"]["username"], reset.json()["throttle"]) == ("bob", "cleared")
    assert new not in reset.text
    assert (await client.get("/api/v1/libraries", headers=bob)).status_code == 401
    await session_of(client, "bob", new)
    assert (await client.get("/api/v1/libraries", headers=ada)).status_code == 200


async def test_a_user_who_is_not_an_operator_gets_403(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    await client.post("/api/v1/users", json=BOB, headers=ada)
    bob = await session_of(client, "bob", BOB["password"])

    for method, path in [
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("POST", "/api/v1/users/x/disable"),
        ("POST", "/api/v1/users/x/enable"),
        ("PUT", "/api/v1/users/x/password"),
    ]:
        response = await client.request(method, path, json=BOB, headers=bob)
        assert (response.status_code, response.json()["error"]) == (403, "forbidden"), path


async def test_an_api_token_or_no_session_gets_401(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    grant = (await client.post("/api/v1/tokens", json={"name": "ci"}, headers=ada)).json()

    with_token = await client.get(
        "/api/v1/users", headers={"authorization": f"Bearer {grant['token']}"}
    )
    signed_out = await client.post("/api/v1/users", json=BOB)

    assert (with_token.status_code, signed_out.status_code) == (401, 401)
    assert (await client.get("/api/v1/users", headers=ada)).json()["users"][-1]["username"] == "ada"


async def test_a_foreign_origin_cannot_create_a_user(
    client: httpx.AsyncClient, ada: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/users", json=BOB, headers={**ada, "origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert len((await client.get("/api/v1/users", headers=ada)).json()["users"]) == 1
