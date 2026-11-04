"""``exactdocs`` command line."""

import asyncio
import getpass
import os
import sys
from collections.abc import Coroutine
from typing import Annotated

import uvicorn
from cyclopts import App, Parameter
from pydantic import SecretStr, ValidationError

from exactdocs import __version__
from exactdocs.bootstrap.client import (
    ApiClient,
    ClientConfig,
    ClientError,
    config_path,
    forget,
    machine_name,
    normalize_url,
    store,
)
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_stdio_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    CreateFirstAdminCommand,
    ResetPasswordCommand,
)
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs_kernel import DomainError

app = App(name="exactdocs", version=__version__, help="Version-accurate docs for AI agents.")


admin = App(name="admin", help="Local administration; opens the database directly.")
app.command(admin)


@app.command
def serve(
    *,
    stdio: Annotated[
        bool,
        Parameter(
            help="Serve MCP over stdio instead of HTTP: read-only, needs an existing database."
        ),
    ] = False,
    host: Annotated[str | None, Parameter(help="HTTP only: address to bind.")] = None,
    port: Annotated[int | None, Parameter(help="HTTP only: port to listen on.")] = None,
    reload: Annotated[bool, Parameter(help="HTTP only: restart on code changes.")] = False,
) -> None:
    """Run the server: web UI + REST API + MCP over HTTP, or MCP only over stdio."""
    settings = Settings()
    if stdio:
        if host or port or reload:
            message = "exactdocs: --host, --port and --reload are HTTP options; --stdio has none"
            raise SystemExit(message)
        asyncio.run(_serve_stdio(settings))
        return
    _check_startup(settings)
    uvicorn.run(
        "exactdocs.bootstrap.cli:asgi_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


# Every command is either local (opens the database, lives in LOCAL_COMMANDS) or a client of the
# REST API: those take `url`/`token` like the two options below, build their client with
# `_api()` and run their work with `_call()`. A test pins the split.
type UrlOption = Annotated[
    str | None, Parameter(help="Server URL (default: EXACTDOCS_URL, config).")
]
type TokenOption = Annotated[
    str | None, Parameter(help="API token (default: EXACTDOCS_TOKEN, config).")
]


def _call[T](work: Coroutine[object, object, T]) -> T:
    """Run a client command's work; a ``ClientError`` ends the process with its message."""
    try:
        return asyncio.run(work)
    except ClientError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from None


def _api(url: str | None = None, token: str | None = None) -> ApiClient:
    """Build the client for the resolved server and token (flags > environment > config file)."""
    try:
        config = ClientConfig.resolve(url=url, token=token)
        return ApiClient(config.url, config.token)
    except ClientError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from None


@app.command
def login(
    url: str | None = None,
    *,
    token: Annotated[
        str | None, Parameter(help="Use this existing API token instead of creating one.")
    ] = None,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
    name: Annotated[
        str | None, Parameter(help="Name of the new token (default: this machine's name).")
    ] = None,
) -> None:
    """Sign in to an instance and store the server URL and an API token for the other commands."""
    try:
        server = normalize_url(url or os.environ.get("EXACTDOCS_URL") or "")
    except ClientError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from None
    path = config_path()

    async def work() -> str:
        async with ApiClient(server, token) as api:
            if token is None:
                try:
                    user, password = _read_login(username, password_stdin=password_stdin)
                except EOFError, KeyboardInterrupt:
                    message = "no username or password to read"
                    raise ClientError(message) from None
                grant = await api.login(user, password, name or machine_name())
                secret, label = (
                    grant["token"],
                    f"new token {grant['name']!r} ({grant['prefix']}...)",
                )
            else:
                await api.check_token()
                secret, label = token, "the token you gave"
        store(path, ClientConfig(url=server, token=secret))
        return label

    label = _call(work())
    sys.stdout.write(f"Logged in to {server} with {label}; credentials stored in {path}.\n")


def _read_login(username: str | None, *, password_stdin: bool) -> tuple[str, str]:
    name = username if username is not None else input("Username: ")
    if password_stdin:
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return name, line.rstrip("\r\n")
    if not sys.stdin.isatty():
        raise EOFError
    return name, getpass.getpass("Password: ")


@app.command
def logout() -> None:
    """Forget the stored credentials (the token stays valid until revoked in the web UI)."""
    removed = forget(config_path())
    sys.stdout.write("Logged out.\n" if removed else "Not logged in.\n")


@admin.command
def create(
    *,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
) -> None:
    """Create the first admin account (only while no account exists)."""
    name, password = _read_credentials(username, password_stdin=password_stdin)
    created = _run(_create_first_admin(Settings(), name, password))
    sys.stdout.write(f"Created admin {created!r}.\n")


@admin.command
def reset_password(
    *,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the new password from one line of stdin instead of prompting.")
    ] = False,
) -> None:
    """Set a new password for an account and sign it out everywhere (lost-password recovery)."""
    name, password = _read_credentials(username, password_stdin=password_stdin, new=True)
    _run(_reset_password(Settings(), name, password))
    sys.stdout.write(f"Password of {name!r} changed; all its sessions ended.\n")


def _read_credentials(
    username: str | None, *, password_stdin: bool, new: bool = False
) -> tuple[str, str]:
    try:
        name = username if username is not None else input("Username: ")
        return name, _read_password(from_stdin=password_stdin, new=new)
    except EOFError, KeyboardInterrupt:
        message = (
            "exactdocs: no username or password to read; run it in a terminal, "
            "or pass --username and --password-stdin"
        )
        raise SystemExit(message) from None


def _run[T](work: Coroutine[object, object, T]) -> T:
    """Run a command's work, turning bad input and domain errors into a one-line exit."""
    try:
        return asyncio.run(work)
    except ValidationError as exc:
        # Pydantic's message would echo the rejected password; say only what is wrong.
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
        message = (
            f"exactdocs: invalid {fields} "
            f"(the password needs {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters)"
        )
        raise SystemExit(message) from None
    except DomainError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _read_password(*, from_stdin: bool, new: bool = False) -> str:
    if from_stdin:
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")
    if not sys.stdin.isatty():
        raise EOFError  # getpass would echo the password it reads from a pipe
    password = getpass.getpass("New password: " if new else "Password: ")
    if getpass.getpass("Repeat password: ") != password:
        message = "exactdocs: the passwords differ"
        raise SystemExit(message)
    return password


async def _create_first_admin(settings: Settings, username: str, password: str) -> str:
    container = _build(settings)
    async with container.running():
        command = CreateFirstAdminCommand(username=username, password=SecretStr(password))
        return (await container.identity.create_first_admin(command)).username


async def _reset_password(settings: Settings, username: str, password: str) -> None:
    container = _build(settings)
    async with container.running():
        command = ResetPasswordCommand(username=username, password=SecretStr(password))
        await container.identity.reset_password(command)


async def _serve_stdio(settings: Settings) -> None:
    try:
        container = ReadOnlyContainer.build(settings)
        async with container.running():  # no worker, no migration: the HTTP server owns both
            await build_stdio_mcp(container).run_stdio_async(show_banner=False)
    except StartupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _build(settings: Settings) -> Container:
    """Build the container; an unusable data directory ends the process with a clear message."""
    try:
        return Container.build(settings)
    except StartupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _check_startup(settings: Settings) -> None:
    """Fail before uvicorn starts (and before any reload worker) instead of with a traceback."""
    try:
        GitCli.locate()  # imports need git; --stdio only reads, so it skips this check
    except GitNotInstalledError as exc:
        message = (
            f"exactdocs: {exc}. Install it (apt install git, brew install git, "
            "or https://git-scm.com) and run again. For read-only MCP use: exactdocs serve --stdio"
        )
        raise SystemExit(message) from exc
    _build(settings)  # opens no connection, so there is nothing to release


def asgi_app() -> object:
    """ASGI factory used by uvicorn (also with ``--reload``)."""
    return create_app(Container.build(Settings()))


LOCAL_COMMANDS = frozenset({"serve", "admin create", "admin reset-password"})


def main() -> None:
    """Console-script entry point."""
    app()
