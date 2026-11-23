"""Interface preferences over HTTP: the OpenAPI contract and who the request acts as."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import SESSION_COOKIE
from exactdocs.identity.dtos import CreateFirstAdminCommand

PATH = "/api/v1/account/preferences"
LOGIN = {"username": "ada", "password": "correct horse battery staple"}
CHOSEN = {
    "theme": "dark",
    "contrast": "more",
    "text_scale": 110,
    "text_spacing": "wide",
    "motion": "full",
    "font": "system",
    "underline_links": False,
    "large_targets": True,
    "language": "en",
    "library_logos": False,
    "leaderboard_opt_in": True,
}
OPTIONAL = {"leaderboard_opt_in"}  # a client older than #510 leaves it out


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    container = Container.build(Settings())
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(
                username=LOGIN["username"], password=SecretStr(LOGIN["password"])
            )
        )
        transport = httpx.ASGITransport(app=create_app(container))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client


async def _session(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/session", json=LOGIN)
    assert response.status_code == 201, response.text
    token = response.cookies[SESSION_COOKIE]
    client.cookies.clear()
    return {"cookie": f"{SESSION_COOKIE}={token}"}


async def test_the_openapi_document_describes_both_operations(client: httpx.AsyncClient) -> None:
    spec: dict[str, Any] = (await client.get("/api/v1/openapi.json")).json()
    item = spec["paths"][PATH]
    body = spec["components"]["schemas"]["InterfacePreferences"]

    assert item["get"]["operationId"] == "identity-get_account_preferences"
    assert item["put"]["operationId"] == "identity-save_account_preferences"
    for operation in item.values():
        assert {"ApiToken": []} in operation["security"]
        assert {"SessionCookie": []} in operation["security"]
    assert item["put"]["requestBody"]["required"] is True
    assert sorted(body["required"]) == sorted(set(CHOSEN) - OPTIONAL)
    assert body["additionalProperties"] is False
    assert body["properties"]["text_scale"]["enum"] == [90, 100, 110, 125, 150]
    assert body["properties"]["language"]["enum"] == ["system", "en", "pl"]
    assert body["properties"]["library_logos"]["type"] == "boolean"
    assert body["properties"]["leaderboard_opt_in"] == {
        "type": "boolean",
        "default": False,
        "description": body["properties"]["leaderboard_opt_in"]["description"],
        "title": "Leaderboard Opt In",
    }
    saved = spec["components"]["schemas"]["AccountPreferences"]
    assert sorted(saved["required"]) == ["preferences", "saved"]


async def test_an_api_token_acts_as_its_account(client: httpx.AsyncClient) -> None:
    session = await _session(client)
    created = await client.post("/api/v1/tokens", json={"name": "laptop"}, headers=session)
    assert created.status_code == 201, created.text
    bearer = {"authorization": f"Bearer {created.json()['token']}"}

    saved = await client.put(PATH, json=CHOSEN, headers=bearer)

    assert saved.status_code == 200, saved.text
    assert (await client.get(PATH, headers=session)).json() == {
        "saved": True,
        "preferences": CHOSEN,
    }


def without(field: str) -> dict[str, Any]:
    return {k: v for k, v in CHOSEN.items() if k != field}


@pytest.mark.parametrize(
    ("field", "body"),
    [
        ("language", {**CHOSEN, "language": "de"}),
        ("language", {**CHOSEN, "language": "EN"}),
        ("language", without("language")),
        ("library_logos", {**CHOSEN, "library_logos": "false"}),
        ("library_logos", {**CHOSEN, "library_logos": 0}),
        ("library_logos", without("library_logos")),
        ("leaderboard_opt_in", {**CHOSEN, "leaderboard_opt_in": "true"}),
        ("leaderboard_opt_in", {**CHOSEN, "leaderboard_opt_in": None}),
    ],
)
async def test_a_choice_the_interface_does_not_offer_is_refused(
    client: httpx.AsyncClient, field: str, body: dict[str, Any]
) -> None:
    session = await _session(client)

    refused = await client.put(PATH, json=body, headers=session)

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "validation_error"
    assert [error["loc"] for error in refused.json()["fields"]] == [["body", field]]
    assert (await client.get(PATH, headers=session)).json()["saved"] is False


async def test_a_client_that_does_not_know_the_leaderboard_opt_in_keeps_it(
    client: httpx.AsyncClient,
) -> None:
    session = await _session(client)
    opted = await client.put(PATH, json=CHOSEN, headers=session)
    assert opted.status_code == 200, opted.text

    older = {**without("leaderboard_opt_in"), "theme": "light"}
    saved = await client.put(PATH, json=older, headers=session)

    assert saved.status_code == 200, saved.text
    expected = {"saved": True, "preferences": {**CHOSEN, "theme": "light"}}
    assert saved.json() == expected
    assert (await client.get(PATH, headers=session)).json() == expected
