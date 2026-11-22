"""The users and token lists over HTTP: sort, filters, cursors and totals, on both databases."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand

HORSE = "correct horse battery staple"
PHRASE = "a long enough passphrase"


@pytest.fixture(params=SQL_BACKENDS)
async def client(request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    transport = httpx.ASGITransport(app=create_app(container))
    async with (
        container.running(),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        command = CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        await container.identity.create_first_admin(command)
        signed_in = await client.post(
            "/api/v1/session", json={"username": "ada", "password": HORSE}
        )
        assert signed_in.status_code == 201, signed_in.text
        client.cookies.set(SESSION_COOKIE, signed_in.cookies[SESSION_COOKIE])
        yield client


async def pages(client: httpx.AsyncClient, path: str, key: str, **params: str | int) -> list[dict]:
    """Follow ``next_cursor`` to the end; every page must report the same total."""
    found, totals, cursor = [], set(), None
    while True:
        response = await client.get(
            path, params={**params, **({"cursor": cursor} if cursor else {})}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        found.append(body[key])
        totals.add(body["total"])
        if (cursor := body["next_cursor"]) is None:
            break
    assert totals == {sum(len(page) for page in found)}, totals
    return found


async def test_the_users_list_sorts_filters_and_pages(client: httpx.AsyncClient) -> None:
    for name, role in [("dave", "user"), ("carol", "admin"), ("bob", "user"), ("erin", "user")]:
        body = {"username": name, "password": PHRASE, "role": role}
        assert (await client.post("/api/v1/users", json=body)).status_code == 201
    erin = next(
        u["id"]
        for u in (await client.get("/api/v1/users")).json()["users"]
        if u["username"] == "erin"
    )
    assert (await client.post(f"/api/v1/users/{erin}/disable")).status_code == 200

    found = await pages(
        client, "/api/v1/users", "users", sort="-username", role="user", disabled="false", limit=1
    )

    assert [[u["username"] for u in page] for page in found] == [["dave"], ["bob"]]
    everyone = await pages(client, "/api/v1/users", "users", sort="role", limit=2)
    assert [u["role"] for page in everyone for u in page] == ["admin"] * 2 + ["user"] * 3


async def test_the_token_list_sorts_filters_and_pages(client: httpx.AsyncClient) -> None:
    for name in ("laptop", "ci-main", "ci-nightly"):
        assert (await client.post("/api/v1/tokens", json={"name": name})).status_code == 201

    found = await pages(client, "/api/v1/tokens", "tokens", q="CI", sort="-name", limit=1)

    assert [[t["name"] for t in page] for page in found] == [["ci-nightly"], ["ci-main"]]


@pytest.mark.parametrize(
    ("path", "params", "named"),
    [
        ("/api/v1/users", {"sort": "password"}, "password"),
        ("/api/v1/users", {"colour": "red"}, "colour"),
        ("/api/v1/users", {"role": "root"}, "role"),
        ("/api/v1/tokens", {"sort": "-secret"}, "secret"),
        ("/api/v1/tokens", {"owner": "bob"}, "owner"),
    ],
)
async def test_an_unknown_sort_or_filter_is_a_422_naming_it(
    client: httpx.AsyncClient, path: str, params: dict[str, str], named: str
) -> None:
    response = await client.get(path, params=params)

    assert response.status_code == 422, response.text
    assert named in response.text


async def test_a_users_cursor_only_works_with_its_own_sort(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/api/v1/users", json={"username": "bob", "password": PHRASE})
    ).is_success
    first = (await client.get("/api/v1/users", params={"sort": "username", "limit": 1})).json()

    response = await client.get(
        "/api/v1/users", params={"sort": "-username", "cursor": first["next_cursor"]}
    )

    assert (response.status_code, response.json()["error"]) == (422, "invalid_cursor")
