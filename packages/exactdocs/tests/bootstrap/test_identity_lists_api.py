"""The users and token lists over HTTP: sort, filters, cursors and totals, on both databases.

Also what an operator sees of every account: last activity, provider, token count and every
token (#515).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

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


async def signed_in_user(client: httpx.AsyncClient, name: str) -> tuple[str, str]:
    """Create a user, sign it in and give it a token; the client keeps the operator's session."""
    operator = next(c.value for c in client.cookies.jar if c.name == SESSION_COOKIE)
    created = await client.post("/api/v1/users", json={"username": name, "password": PHRASE})
    assert created.status_code == 201, created.text
    as_session(client, None)  # a sign-in ends the session it arrives with
    signed_in = await client.post("/api/v1/session", json={"username": name, "password": PHRASE})
    assert signed_in.status_code == 201, signed_in.text
    session = signed_in.cookies[SESSION_COOKIE]
    as_session(client, session)
    minted = await client.post("/api/v1/tokens", json={"name": f"{name}-laptop"})
    assert minted.status_code == 201, minted.text
    as_session(client, operator)
    return session, minted.json()["token"]


def as_session(client: httpx.AsyncClient, session: str | None) -> None:
    """Make the client send exactly ``session`` (no session cookie for ``None``)."""
    client.cookies.clear()
    if session is not None:
        client.cookies.set(SESSION_COOKIE, session)


async def test_users_carry_last_activity_provider_and_token_count(
    client: httpx.AsyncClient,
) -> None:
    # The fixture's operator was active before this test started: its hour can be the one before.
    before = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    _, token = await signed_in_user(client, "bob")
    await signed_in_user(client, "carol")
    used = await client.get("/api/v1/libraries", headers={"authorization": f"Bearer {token}"})
    assert used.status_code == 200, used.text
    assert (await client.post("/api/v1/tokens", json={"name": "ada-ci"})).status_code == 201

    body = (await client.get("/api/v1/users", params={"provider": "password"})).json()

    users = {u["username"]: u for u in body["users"]}
    assert body["total"] == 3
    assert {name: u["token_count"] for name, u in users.items()} == {"ada": 1, "bob": 1, "carol": 1}
    for user in users.values():
        assert user["provider"] is None
        active = datetime.fromisoformat(user["last_active_at"])
        assert (active.minute, active.second, active.microsecond) == (0, 0, 0), active
        # Read the clock around the requests, not after them only: an hour can begin in between.
        assert before <= active <= datetime.now(UTC), active
    google = await client.get("/api/v1/users", params={"provider": ["google", "github"]})
    assert (google.json()["users"], google.json()["total"]) == ([], 0)
    by_tokens = await client.get("/api/v1/users", params={"sort": "-last_active_at"})
    assert by_tokens.status_code == 200, by_tokens.text


async def test_an_operator_lists_every_token_with_its_owner_and_no_secret(
    client: httpx.AsyncClient,
) -> None:
    _, bob_token = await signed_in_user(client, "bob")
    await signed_in_user(client, "carol")
    assert (await client.post("/api/v1/tokens", json={"name": "ada-ci"})).status_code == 201
    used = await client.get("/api/v1/libraries", headers={"authorization": f"Bearer {bob_token}"})
    assert used.status_code == 200, used.text

    found = await pages(client, "/api/v1/users/tokens", "tokens", sort="owner", limit=2)

    tokens = [t for page in found for t in page]
    assert [(t["owner"], t["name"]) for t in tokens] == [
        ("ada", "ada-ci"),
        ("bob", "bob-laptop"),
        ("carol", "carol-laptop"),
    ]
    assert all(t["prefix"].startswith("exd_") and "token" not in t for t in tokens), tokens
    assert bob_token not in str(found)
    bob = tokens[1]
    assert bob["last_used_at"] is not None
    unused = (await client.get("/api/v1/users/tokens", params={"unused": "true"})).json()
    assert sorted(t["name"] for t in unused["tokens"]) == ["ada-ci", "carol-laptop"]
    own = await client.get("/api/v1/users/tokens", params={"owner_id": bob["owner_id"]})
    assert [t["name"] for t in own.json()["tokens"]] == ["bob-laptop"]
    jumped = await client.get("/api/v1/users/tokens", params={"sort": "owner", "offset": 2})
    assert [t["name"] for t in jumped.json()["tokens"]] == ["carol-laptop"]
    bad = await client.get("/api/v1/users/tokens", params={"sort": "token_hash"})
    assert (bad.status_code, bad.json()["error"]) == (422, "invalid_sort")


async def test_only_an_operators_session_lists_every_token(client: httpx.AsyncClient) -> None:
    session, token = await signed_in_user(client, "bob")

    as_session(client, session)
    as_user = await client.get("/api/v1/users/tokens")
    as_session(client, None)
    with_token = await client.get(
        "/api/v1/users/tokens", headers={"authorization": f"Bearer {token}"}
    )

    assert (as_user.status_code, as_user.json()["error"]) == (403, "forbidden")
    assert "lists the API tokens of every account" in as_user.text
    assert with_token.status_code == 401, with_token.text
