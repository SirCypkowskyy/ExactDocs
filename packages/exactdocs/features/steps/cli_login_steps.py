"""Steps for ``exactdocs login``: the real CLI against a real server on a loopback port."""

import asyncio
import io
import os
import socket
import stat
import tempfile
import threading
import time
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.client import ApiClient, ClientConfig, machine_name
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app

PRIVATE = 0o600
TOLERANCE_DAYS = 0.1
HORSE = "correct horse battery staple"


@given("the instance is served on a loopback port")
def step_served(context: Context) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    # The server is the instance from here on: one job worker per process, and it is the server's.
    context.client.__exit__(None, None, None)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(create_app(Container.build(context.settings)), log_level="warning")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    stack.callback(thread.join, 10)
    stack.callback(setattr, server, "should_exit", True)
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the server did not start"
    context.server_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    context.client = stack.enter_context(httpx.Client(base_url=context.server_url))
    config_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-cfg-")))
    context.config_file = config_dir / "config.json"


def _login(
    context: Context, *args: str, stdin: str = "", extra_env: dict[str, str] | None = None
) -> None:
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file), **(extra_env or {})}
    output, errors = io.StringIO(), io.StringIO()
    context.exit_message = None
    with (
        patch.dict(os.environ, env),
        patch("sys.stdin", io.StringIO(stdin)),
        redirect_stdout(output),
        redirect_stderr(errors),
    ):
        try:
            cli.app(["login", *args], exit_on_error=False, result_action="return_value")
        except SystemExit as exc:
            context.exit_message = errors.getvalue() or str(exc.code)
    context.output = output.getvalue()


@when('the user runs "exactdocs login" with the admin\'s username and password')
def step_login(context: Context) -> None:
    _login(context, context.server_url, "--username", "ada", "--password-stdin", stdin=HORSE + "\n")
    assert context.exit_message is None, context.exit_message


@when('the user runs "exactdocs login" with the admin\'s username and password and "{options}"')
def step_login_flag(context: Context, options: str) -> None:
    args = [context.server_url, "--username", "ada", "--password-stdin", *options.split()]
    _login(context, *args, stdin=HORSE + "\n")
    assert context.exit_message is None, context.exit_message


@when('the user runs "exactdocs login" with that token on stdin')
def step_login_token_stdin(context: Context) -> None:
    _login(context, context.server_url, "--token-stdin", stdin=context.token + "\n")
    assert context.exit_message is None, context.exit_message


@when('the user runs "exactdocs login" with that token in EXACTDOCS_TOKEN')
def step_login_token_env(context: Context) -> None:
    _login(context, context.server_url, extra_env={"EXACTDOCS_TOKEN": context.token})
    assert context.exit_message is None, context.exit_message


@when('the user runs "exactdocs logout"')
def step_logout(context: Context) -> None:
    env = {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}
    output = io.StringIO()
    with patch.dict(os.environ, env), redirect_stdout(output):
        cli.app(["logout"], exit_on_error=False, result_action="return_value")
    context.output = output.getvalue()


@then("the output says the token is still valid until revoked")
def step_still_valid(context: Context) -> None:
    assert "still valid" in context.output
    assert "revoke" in context.output


def _tokens(context: Context) -> list[dict[str, str | None]]:
    context.client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
    return context.client.get("/api/v1/tokens").json()["tokens"]


def _days_left(token: dict[str, str | None]) -> float:
    assert token["expires_at"], token
    return (datetime.fromisoformat(token["expires_at"]) - datetime.now(UTC)).total_seconds() / 86400


@then("the admin's token expires in {days:d} days")
def step_expires(context: Context, days: int) -> None:
    (token,) = _tokens(context)
    assert abs(_days_left(token) - days) < TOLERANCE_DAYS, token


@then("the admin's newest token expires in {days:d} days")
def step_newest_expires(context: Context, days: int) -> None:
    token = _tokens(context)[0]  # newest first
    assert abs(_days_left(token) - days) < TOLERANCE_DAYS, token


@then("the admin's newest token never expires")
def step_never(context: Context) -> None:
    assert _tokens(context)[0]["expires_at"] is None


@when('the user runs "exactdocs login" with the password "{password}"')
def step_login_password(context: Context, password: str) -> None:
    args = [context.server_url, "--username", "ada", "--password-stdin"]
    _login(context, *args, stdin=password + "\n")


@when('the user runs "exactdocs login" with that token')
def step_login_token(context: Context) -> None:
    _login(context, context.server_url, "--token", context.token)
    assert context.exit_message is None, context.exit_message


@when('the user runs "exactdocs login {url}"')
def step_login_url(context: Context, url: str) -> None:
    _login(context, url, "--username", "ada", "--password-stdin", stdin=HORSE + "\n")


def _stored(context: Context) -> ClientConfig:
    with patch.dict(os.environ, {"EXACTDOCS_CONFIG_FILE": str(context.config_file)}):
        return ClientConfig.resolve()


@then("the CLI config holds the server URL and a token")
def step_config(context: Context) -> None:
    config = _stored(context)
    assert config.url == context.server_url
    context.stored_token = config.token


@then("the config file is readable by its owner only")
def step_private(context: Context) -> None:
    assert stat.S_IMODE(context.config_file.stat().st_mode) == PRIVATE


@then("the stored token is accepted by the server")
def step_accepted(context: Context) -> None:
    async def check() -> None:
        async with ApiClient(context.server_url, context.stored_token) as api:
            await api.check_token()

    asyncio.run(check())


@then("the token list of the admin has a token named after the machine")
def step_named(context: Context) -> None:
    context.client.post("/api/v1/session", json={"username": "ada", "password": HORSE})
    names = [t["name"] for t in context.client.get("/api/v1/tokens").json()["tokens"]]
    assert names == [machine_name()], names


@then("the token is not in the output")
def step_not_printed(context: Context) -> None:
    assert context.stored_token not in context.output


@then("the admin still has exactly {count:d} token")
def step_count(context: Context, count: int) -> None:
    tokens = context.client.get("/api/v1/tokens").json()["tokens"]
    assert len(tokens) == count, tokens


@then('the login is refused with "{message}"')
def step_refused(context: Context, message: str) -> None:
    assert context.exit_message, "the login was not refused"
    assert message in context.exit_message, context.exit_message
    assert HORSE not in context.exit_message


@then("no config file exists")
def step_no_config(context: Context) -> None:
    assert not context.config_file.exists()
