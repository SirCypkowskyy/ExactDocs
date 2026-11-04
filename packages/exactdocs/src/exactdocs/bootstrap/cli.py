"""``exactdocs`` command line."""

import asyncio
import getpass
import sys
from typing import Annotated

import uvicorn
from cyclopts import App, Parameter
from pydantic import SecretStr, ValidationError

from exactdocs import __version__
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.dtos import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    CreateFirstAdminCommand,
)
from exactdocs_kernel import DomainError

app = App(name="exactdocs", version=__version__, help="Version-accurate docs for AI agents.")


admin = App(name="admin", help="Local administration; opens the database directly.")
app.command(admin)


@app.command
def serve(
    *,
    stdio: Annotated[bool, Parameter(help="Serve MCP over stdio instead of HTTP.")] = False,
    host: str | None = None,
    port: int | None = None,
    reload: bool = False,
) -> None:
    """Run the server: web UI + REST API + MCP over HTTP, or MCP only over stdio."""
    settings = Settings()
    if stdio:
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


@admin.command
def create(
    *,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
) -> None:
    """Create the first admin account (only while no account exists)."""
    try:
        name = username if username is not None else input("Username: ")
        password = _read_password(from_stdin=password_stdin)
    except EOFError, KeyboardInterrupt:
        message = (
            "exactdocs: no username or password to read; run it in a terminal, "
            "or pass --username and --password-stdin"
        )
        raise SystemExit(message) from None
    try:
        created = asyncio.run(_create_first_admin(Settings(), name, password))
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
    sys.stdout.write(f"Created admin {created!r}.\n")


def _read_password(*, from_stdin: bool) -> str:
    if from_stdin:
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")
    if not sys.stdin.isatty():
        raise EOFError  # getpass would echo the password it reads from a pipe
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        message = "exactdocs: the passwords differ"
        raise SystemExit(message)
    return password


async def _create_first_admin(settings: Settings, username: str, password: str) -> str:
    container = _build(settings)
    async with container.running():
        command = CreateFirstAdminCommand(username=username, password=SecretStr(password))
        return (await container.identity.create_first_admin(command)).username


async def _serve_stdio(settings: Settings) -> None:
    container = _build(settings)
    async with container.running():
        await build_mcp(container).run_stdio_async(show_banner=False)


def _build(settings: Settings) -> Container:
    """Build the container; an unusable data directory ends the process with a clear message."""
    try:
        return Container.build(settings)
    except StartupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _check_startup(settings: Settings) -> None:
    """Fail before uvicorn starts (and before any reload worker) instead of with a traceback."""
    _build(settings)  # opens no connection, so there is nothing to release


def asgi_app() -> object:
    """ASGI factory used by uvicorn (also with ``--reload``)."""
    return create_app(Container.build(Settings()))


def main() -> None:
    """Console-script entry point."""
    app()
