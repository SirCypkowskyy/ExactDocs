"""Steps for ExactDocs behind a corporate proxy (#538), over the REST API.

The proxy is ``forward_proxy`` on loopback; the repository behind it is the fixture repository
under ``git.example.test``, a name that resolves nowhere, so a preview of it can only succeed
through the proxy. The proxy is given in the settings (``EXACTDOCS_HTTP(S)_PROXY``), with an empty
``NO_PROXY``: the machine's own proxy variables play no part.
"""

import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from pydantic import SecretStr

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import CreateFirstAdminCommand
from forward_proxy import forward_proxy

BEHIND = "git.example.test"
"""The repository's host behind the proxy (``.test``: no DNS answers for it)."""
PROXY_WORD = "hunter2-of-the-proxy"
"""The proxy's password, in the credentials scenario: never shown."""
HORSE = "correct horse battery staple"


def _behind(context: Context) -> str:
    """The fixture repository's URL under the name only the proxy knows.

    Args:
        context: The scenario.

    Returns:
        ``http://git.example.test/fixture/docs-repo.git``.
    """
    url = context.fixture_repo.http_url
    return url.replace(urlsplit(url).netloc, BEHIND)


def _run_behind(context: Context, *, asks: str | None, gives: str | None, routed: bool) -> None:
    """Start a proxy, and ExactDocs configured to go through it, signed in as an admin.

    Args:
        context: The scenario.
        asks: The ``user:password`` the proxy asks for, if any.
        gives: The ``user:password`` ExactDocs puts in the proxy URL, if any.
        routed: Whether the proxy can reach the fixture repository (as ``git.example.test``).
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    served = urlsplit(context.fixture_repo.http_url)
    routes = {f"{BEHIND}:80": (served.hostname or "", served.port or 80)} if routed else {}
    context.proxy = stack.enter_context(forward_proxy(routes, credentials=asks))
    url = context.proxy.url if gives is None else context.proxy.url_with(gives)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    settings = Settings(
        data_dir=data_dir,
        http_proxy=SecretStr(url),
        https_proxy=SecretStr(url),
        no_proxy="",
    )
    context.container = Container.build(settings)
    context.client = stack.enter_context(
        TestClient(create_app(context.container), base_url="http://localhost")
    )
    context.client.portal.call(
        context.container.identity.create_first_admin,
        CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE)),
    )
    signed_in = context.client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
    assert signed_in.status_code == HTTPStatus.CREATED, signed_in.text


@given("ExactDocs runs behind a forward proxy that alone can reach the fixture repository")
def step_behind_a_proxy(context: Context) -> None:
    _run_behind(context, asks="ada:" + PROXY_WORD, gives="ada:" + PROXY_WORD, routed=True)


@given("ExactDocs runs behind a forward proxy that wants credentials it was not given")
def step_proxy_wants_credentials(context: Context) -> None:
    _run_behind(context, asks="ada:" + PROXY_WORD, gives="ada:not-" + PROXY_WORD, routed=True)


@given("ExactDocs runs behind a forward proxy that refuses every host")
def step_proxy_refuses_everything(context: Context) -> None:
    _run_behind(context, asks=None, gives=None, routed=False)


def _preview(context: Context, url: str, ref: str, paths: str) -> None:
    context.response = context.client.post(
        "/api/v1/repositories/preview",
        json={"url": url, "ref": ref, "include_paths": [paths]},
    )


@when('a user previews the repository behind the proxy at "{ref}" with paths "{paths}"')
def step_preview_behind(context: Context, ref: str, paths: str) -> None:
    _preview(context, _behind(context), ref, paths)


@when(
    'a user previews the fixture repository served on this machine at "{ref}" with paths "{paths}"'
)
def step_preview_local(context: Context, ref: str, paths: str) -> None:
    _preview(context, context.fixture_repo.http_url, ref, paths)


@then("the proxy carried the request to the repository's host")
def step_proxy_carried(context: Context) -> None:
    assert context.proxy.hosts() == {f"{BEHIND}:80"}, context.proxy.seen


@then("the request fails naming the proxy and the repository's host")
def step_fails_naming_the_proxy(context: Context) -> None:
    refused = {HTTPStatus.CONFLICT, HTTPStatus.UNPROCESSABLE_ENTITY}
    assert context.response.status_code in refused, context.response.text
    body = context.response.json()
    assert body["error"] == "repository_unreachable", body
    shown = context.proxy.url.replace("://", "://***@")
    assert f"the proxy {shown} wants credentials to reach {BEHIND}:80" in body["detail"], body


@then("the error shows no proxy credentials")
def step_no_credentials_shown(context: Context) -> None:
    assert PROXY_WORD not in context.response.text
    assert "ada:" not in context.response.text


@then("the proxy received nothing")
def step_proxy_idle(context: Context) -> None:
    assert context.proxy.seen == []
