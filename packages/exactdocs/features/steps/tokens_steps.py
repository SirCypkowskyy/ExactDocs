"""Steps for API tokens: created over REST with a session, used on REST and on MCP."""

import asyncio
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.identity.adapters.driven.sqlite import SqliteTokenRepository
from exactdocs.identity.models import AccountId, ApiToken, hash_token

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
LIST_LIBRARIES = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "list_libraries", "arguments": {}},
}
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


def _bearer(token: str | None) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"} if token else {}


def _mcp_status(context: Context, token: str | None) -> int:
    headers = {**MCP_HEADERS, **_bearer(token)}
    return context.client.post("/mcp", json=LIST_LIBRARIES, headers=headers).status_code


def _libraries_status(context: Context, token: str) -> int:
    # A bare header only: the client's cookie jar must not stand in for the token.
    request = context.client.build_request("GET", "/api/v1/libraries", headers=_bearer(token))
    request.headers.pop("cookie", None)
    return context.client.send(request).status_code


@given('the admin created a token named "{name}"')
def step_created(context: Context, name: str) -> None:
    context.response = context.client.post("/api/v1/tokens", json={"name": name})
    assert context.response.status_code == HTTPStatus.CREATED, context.response.text
    context.created = context.response.json()
    context.token = context.created["token"]


@then("the token value is shown once")
def step_shown_once(context: Context) -> None:
    assert context.token.startswith("exd_")
    assert "no-store" in context.response.headers["cache-control"]
    listing = context.client.get("/api/v1/tokens")
    assert listing.status_code == HTTPStatus.OK, listing.text
    assert context.token not in listing.text


@then("an MCP client with that token can list the libraries")
def step_mcp_ok(context: Context) -> None:
    assert _mcp_status(context, context.token) == HTTPStatus.OK


@then("a REST client with that token can list the libraries")
def step_rest_ok(context: Context) -> None:
    assert _libraries_status(context, context.token) == HTTPStatus.OK


@when('the admin revokes "{name}"')
def step_revoke(context: Context, name: str) -> None:
    tokens = context.client.get("/api/v1/tokens").json()["tokens"]
    token_id = next(t["id"] for t in tokens if t["name"] == name)
    response = context.client.delete(f"/api/v1/tokens/{token_id}")
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text


@then("the same MCP client is refused")
def step_mcp_refused(context: Context) -> None:
    assert _mcp_status(context, context.token) == HTTPStatus.UNAUTHORIZED


@then("the same REST client is refused")
def step_rest_refused(context: Context) -> None:
    assert _libraries_status(context, context.token) == HTTPStatus.UNAUTHORIZED


@given("a token that expired yesterday")
def step_expired(context: Context) -> None:
    secret = "exd_" + "e" * 43
    context.token = secret
    asyncio.run(_plant(context, secret))


async def _plant(context: Context, secret: str) -> None:
    container = Container.build(context.settings)
    async with container.running(jobs=False):
        owner = await _first_account_id(container)
        now = datetime.now(UTC)
        await SqliteTokenRepository(engine=container.engine).add(
            ApiToken(
                id="expired-token",
                account_id=owner,
                name="old",
                token_hash=hash_token(secret),
                prefix=secret[:8],
                created_at=now - timedelta(days=30),
                expires_at=now - timedelta(days=1),
            )
        )


async def _first_account_id(container: Container) -> AccountId:
    async with container.engine.connect() as connection:
        return AccountId(
            (await connection.execute(text("SELECT id FROM identity_accounts"))).scalar_one()
        )


@when("a REST client uses it")
def step_rest_uses(context: Context) -> None:
    request = context.client.build_request(
        "GET", "/api/v1/libraries", headers=_bearer(context.token)
    )
    request.headers.pop("cookie", None)
    context.response = context.client.send(request)


@then("the request is refused as unauthenticated")
def step_unauthenticated(context: Context) -> None:
    assert context.response.status_code == HTTPStatus.UNAUTHORIZED, context.response.text
    assert context.response.json()["error"] == "unauthenticated"


@then("a client with that token cannot create tokens")
def step_cannot_mint(context: Context) -> None:
    request = context.client.build_request(
        "POST", "/api/v1/tokens", json={"name": "child"}, headers=_bearer(context.token)
    )
    request.headers.pop("cookie", None)
    assert context.client.send(request).status_code == HTTPStatus.UNAUTHORIZED


@then("an MCP client without a token is refused")
def step_mcp_anonymous(context: Context) -> None:
    assert _mcp_status(context, None) == HTTPStatus.UNAUTHORIZED


@then("an MCP client with a made-up token is refused")
def step_mcp_made_up(context: Context) -> None:
    assert _mcp_status(context, "exd_made-up") == HTTPStatus.UNAUTHORIZED


@given('the admin created tokens named "{first}", "{second}" and "{third}"')
def step_created_tokens(context: Context, first: str, second: str, third: str) -> None:
    for name in (first, second, third):
        step_created(context, name)


@when('the admin lists the tokens matching "{needle}", by name from Z to A')
def step_list_tokens(context: Context, needle: str) -> None:
    context.response = context.client.get("/api/v1/tokens", params={"q": needle, "sort": "-name"})
    assert context.response.status_code == HTTPStatus.OK, context.response.text


@then('the token list shows "{names}" and counts {total:d} tokens')
def step_token_list(context: Context, names: str, total: int) -> None:
    body = context.response.json()
    assert ", ".join(t["name"] for t in body["tokens"]) == names, body
    assert (body["total"], body["next_cursor"]) == (total, None), body
