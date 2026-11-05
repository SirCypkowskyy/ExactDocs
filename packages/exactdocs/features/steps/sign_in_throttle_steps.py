"""Steps for the sign-in throttle, through a reverse proxy that names the client address."""

import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

import httpx
from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

HORSE = "correct horse battery staple"
PATHS = {"the web sign-in": "/api/v1/session", "the CLI login": "/api/v1/tokens/login"}


def _attempt(
    context: Context, via: str, address: str, username: str, password: str
) -> httpx.Response:
    body = {"username": username, "password": password}
    if via == "the CLI login":
        body["name"] = "laptop"
    # The proxy reports the client in X-Forwarded-For; the app sees it as the request's client.
    return context.client.post(PATHS[via], json=body, headers={"X-Forwarded-For": address})


@given("a fresh instance behind a reverse proxy")
def step_behind_proxy(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir)
    # What `exactdocs serve` runs: uvicorn's proxy headers, trusting `forwarded_allow_ips`
    # (loopback by default), here with the proxy on 127.0.0.1.
    app = create_app(Container.build(context.settings))
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=context.settings.forwarded_allow_ips)
    context.client = stack.enter_context(
        TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))
    )


@when('a client at "{address}" fails to sign in as "{username}" {count:d} times through {via}')
def step_fail_from_one(context: Context, address: str, username: str, count: int, via: str) -> None:
    context.address = address
    for _ in range(count):
        response = _attempt(context, via, address, username, "wrong horse battery staple")
        assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text


@when('clients at {count:d} different addresses fail to sign in as "{username}" through {via}')
def step_fail_from_many(context: Context, count: int, username: str, via: str) -> None:
    for n in range(count):
        response = _attempt(context, via, f"203.0.113.{n + 1}", username, "wrong horse")
        assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text


def _assert_rate_limited(response: httpx.Response) -> None:
    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS, response.text
    assert response.json()["error"] == "rate_limited", response.text
    assert int(response.headers["retry-after"]) > 0, response.headers


@then("its next sign-in through {via} is refused as rate limited, with a time to wait")
def step_next_refused(context: Context, via: str) -> None:
    # Even the right password: the address is waiting, so the password is not even checked.
    _assert_rate_limited(_attempt(context, via, context.address, "ada", HORSE))


@then(
    'a sign-in as "{username}" through {via} from "{address}" is refused as rate limited, '
    "with a time to wait"
)
def step_user_refused(context: Context, username: str, via: str, address: str) -> None:
    _assert_rate_limited(_attempt(context, via, address, username, HORSE))


@then('the admin can still sign in through {via} from "{address}"')
def step_still_signs_in(context: Context, via: str, address: str) -> None:
    response = _attempt(context, via, address, "ada", HORSE)
    assert response.status_code == HTTPStatus.CREATED, response.text
