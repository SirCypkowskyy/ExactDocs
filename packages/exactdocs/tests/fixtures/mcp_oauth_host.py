"""A web MCP host (Claude, ChatGPT) connecting with OAuth, against an app in the test process.

``connect`` plays the host's side of the flow: discover the authorization server, register
dynamically, send the person to the consent page and on to the identity provider (the fake
issuer approves whoever the test names), come back with the code and trade it for the access
token. ``call_tool`` then uses that token on ``/mcp`` as the host would. FastMCP's proxy
discovers the issuer with a blocking request and calls its token endpoint with its own client;
``fake_issuer`` points both at the fake issuer instead of the network.
"""

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx2
from fastapi.testclient import TestClient
from fastmcp.server.auth.oauth_proxy import proxy as oauth_proxy
from fastmcp.server.auth.oauth_proxy.upstream import AsyncOAuth2Client
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration

from fake_oidc import FakeIssuer

REDIRECT_URI = "http://localhost:8765/callback"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
_OK = 200


@contextmanager
def fake_issuer(issuer: FakeIssuer, *, oidc: bool = True) -> Generator[None]:
    """Make FastMCP's OAuth proxy reach ``issuer`` (discovery and token endpoint) in-process.

    Yields:
        Nothing: the patches hold for the block.
    """
    document = (
        TestClient(issuer.app).get("/.well-known/openid-configuration").json() if oidc else {}
    )

    class ViaIssuer(AsyncOAuth2Client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._client = httpx2.AsyncClient(transport=issuer.transport())

    def discovered(
        cls: type[OIDCConfiguration], _: object, *, strict: bool | None, **__: Any
    ) -> OIDCConfiguration:
        return cls.model_validate({**document, "strict": strict})

    with (
        patch.object(OIDCConfiguration, "get_oidc_configuration", classmethod(discovered)),
        patch.object(oauth_proxy, "AsyncOAuth2Client", ViaIssuer),
    ):
        yield


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def connect(
    client: TestClient, issuer: FakeIssuer, subject: str, *, scope: str = "openid"
) -> httpx2.Response:
    """Run the host's OAuth flow for ``subject``; return the answer of the token endpoint.

    Args:
        client: The app, as a browser and host reach it.
        issuer: The fake identity provider.
        subject: The person the provider signs in.

    Returns:
        The token endpoint's response (``access_token`` in its JSON when it was granted).
    """
    client.cookies.clear()
    registered = client.post(
        "/register",
        json={
            "client_name": "Web host",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registered.status_code in {_OK, 201}, registered.text
    client_id = registered.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(8)
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
            "scope": scope,
            "resource": f"{client.base_url}/mcp",
        },
        follow_redirects=False,
    )
    assert authorize.status_code in {302, 303, 307}, authorize.text
    consent_url = authorize.headers["location"]
    consent = client.get(consent_url, follow_redirects=False)
    assert consent.status_code == _OK, consent.text
    found = _CSRF.search(consent.text)
    assert found, "the consent page has no CSRF token"
    approved = client.post(
        urlsplit(consent_url).path,
        params={"txn_id": parse_qs(urlsplit(consent_url).query)["txn_id"][0]},
        data={
            "action": "approve",
            "txn_id": parse_qs(urlsplit(consent_url).query)["txn_id"][0],
            "csrf_token": found.group(1),
        },
        follow_redirects=False,
    )
    assert approved.status_code in {302, 303, 307}, approved.text
    callback = issuer.authorize(approved.headers["location"], subject)
    back = client.get(callback, follow_redirects=False)
    assert back.status_code in {302, 303, 307}, back.text
    code = parse_qs(urlsplit(back.headers["location"]).query)["code"][0]
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
        },
    )


def call_tool(client: TestClient, token: str | None, name: str) -> httpx2.Response:
    """Call a tool without arguments on ``/mcp`` with this bearer token.

    Args:
        client: The app.
        token: The bearer token, or ``None`` for none.
        name: The tool.

    Returns:
        The response (a 401 for a refused token; otherwise the JSON-RPC answer, as SSE).
    """
    headers = dict(MCP_HEADERS)
    if token:
        headers["authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
    )


def tool_result(response: httpx2.Response) -> dict[str, Any]:
    """Read the JSON-RPC result of a ``/mcp`` response (plain JSON or one SSE ``data:`` line).

    Args:
        response: The response of a successful call.

    Returns:
        The ``result`` object.
    """
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        text = next(
            line.removeprefix("data:") for line in text.splitlines() if line.startswith("data:")
        )
    return json.loads(text)["result"]
