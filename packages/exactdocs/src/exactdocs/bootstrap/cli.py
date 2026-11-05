"""``exactdocs`` command line."""

import asyncio
import getpass
import os
import sys
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import uvicorn
from cyclopts import App, Parameter
from cyclopts.validators import Number
from pydantic import SecretStr, ValidationError

from exactdocs import __version__
from exactdocs.bootstrap import cli_library as lib
from exactdocs.bootstrap.cli_library import exit_code
from exactdocs.bootstrap.client import (
    ApiClient,
    ClientConfig,
    ClientError,
    config_path,
    forget,
    machine_name,
    normalize_url,
    resolve_url,
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

DEFAULT_TOKEN_DAYS = 90

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
        # One process: it alone runs jobs and their recovery, and its tag lock orders re-tags.
        # Without it uvicorn would start WEB_CONCURRENCY workers (docs/architecture.md).
        workers=1,
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
    str | None,
    Parameter(help="ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token."),
]
type CredentialTokenOption = Annotated[
    str | None,
    Parameter(
        help="ExactDocs API token (default: EXACTDOCS_TOKEN, config). Ignored when "
        "--git-token-file or --ssh-key is given: those need your password instead."
    ),
]
type WaitTimeout = Annotated[
    int,
    Parameter(
        name="--wait-timeout",
        help="With --wait: seconds to follow the import before leaving it to the server.",
        validator=Number(gte=1),
    ),
]


def _call[T](work: Coroutine[object, object, T]) -> T:
    """Run a client command's work; a ``ClientError`` ends the process with its message."""
    try:
        return asyncio.run(work)
    except ClientError as exc:
        sys.stderr.write(f"exactdocs: {exc}\n")
        raise SystemExit(exit_code(exc)) from None
    except KeyboardInterrupt:  # `--wait` has already said the job keeps running
        raise SystemExit(lib.EXIT_INTERRUPTED) from None


def _api(url: str | None = None, token: str | None = None) -> ApiClient:
    """Build the client for the resolved server and token (flags > environment > config file)."""
    try:
        config = ClientConfig.resolve(url=url, token=token)
        return ApiClient(config.url, config.token)
    except ClientError as exc:
        sys.stderr.write(f"exactdocs: {exc}\n")
        raise SystemExit(exit_code(exc)) from None


@app.command
def login(
    url: str | None = None,
    *,
    token: Annotated[
        str | None,
        Parameter(
            help="Use this existing API token instead of creating one. It lands in your shell "
            "history and `ps`: prefer EXACTDOCS_TOKEN or --token-stdin."
        ),
    ] = None,
    token_stdin: Annotated[
        bool, Parameter(help="Read an existing API token from one line of stdin.")
    ] = False,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
    name: Annotated[
        str | None, Parameter(help="Name of the new token (default: this machine's name).")
    ] = None,
    expires_in: Annotated[
        int, Parameter(help="Days until the new token expires.", validator=Number(gte=1))
    ] = DEFAULT_TOKEN_DAYS,
    no_expiry: Annotated[bool, Parameter(help="Create a token that never expires.")] = False,
) -> None:
    """Sign in to an instance and store the server URL and an API token for the other commands.

    With a token (--token, --token-stdin or EXACTDOCS_TOKEN) no new token is created and the
    expiry options do not apply. Otherwise the new token expires after 90 days unless told not to.
    """
    try:
        server = normalize_url(url or os.environ.get("EXACTDOCS_URL") or "")
    except ClientError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from None
    path = config_path()
    if token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            message = "exactdocs: no token on stdin"
            raise SystemExit(message)
    token = token or os.environ.get("EXACTDOCS_TOKEN") or None
    expires_at = None if no_expiry else datetime.now(UTC) + timedelta(days=expires_in)

    async def work() -> str:
        async with ApiClient(server, token) as api:
            if token is None:
                try:
                    user, password = _read_login(username, password_stdin=password_stdin)
                except EOFError, KeyboardInterrupt:
                    message = "no username or password to read"
                    raise ClientError(message) from None
                grant = await api.login(user, password, name or machine_name(), expires_at)
                secret, label = (
                    grant["token"],
                    f"new token {grant['name']!r} ({grant['prefix']}...), "
                    + (f"expires {expires_at:%Y-%m-%d}" if expires_at else "no expiry"),
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
    sys.stdout.write(
        "Logged out. The token is still valid on the server until you revoke it in the web UI "
        "(Tokens).\n"
        if removed
        else "Not logged in.\n"
    )


type JsonOption = Annotated[bool, Parameter(name="--json", help="Print JSON for scripts.")]
type WaitOption = Annotated[
    bool, Parameter(help="Wait for the import and show its progress (on stderr).")
]
type PasswordStdin = Annotated[
    bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
]
type UsernameOption = Annotated[str | None, Parameter(help="Asked for when omitted.")]


@asynccontextmanager
async def _session(
    url: str | None, username: str | None, *, password_stdin: bool
) -> AsyncGenerator[ApiClient]:
    """Yield a client signed in with a password (a session), for what a token may not do.

    Setting a repository credential and managing tokens need a session: a leaked token must not
    be able to mint a successor or replace a stored credential (identity's token routes).

    Yields:
        The signed-in client; the session ends when the block does.

    """
    server = resolve_url(url=url)
    try:
        user, password = _read_login(username, password_stdin=password_stdin)
    except EOFError, KeyboardInterrupt:
        message = "no username or password to read"
        raise ClientError(message) from None
    async with ApiClient(server) as api:
        await api.sign_in(user, password)
        try:
            yield api
        finally:
            await api.sign_out()


def _credential(
    git_token_file: str | None, ssh_key: str | None, git_user: str | None
) -> dict | None:
    """Read a repository credential from files (never from the command line)."""
    path = git_token_file or ssh_key
    try:
        if git_token_file and ssh_key:
            message = "give --git-token-file or --ssh-key, not both"
            raise lib.UsageError(message)
        secret = lib.read_secret(path) if path else None
    except ClientError as exc:
        sys.stderr.write(f"exactdocs: {exc}\n")
        raise SystemExit(exit_code(exc)) from None
    if secret is None:
        return None
    if git_token_file:
        return {"kind": "token", "token": secret.strip()} | (
            {"username": git_user} if git_user else {}
        )
    return {"kind": "ssh_key", "private_key": secret}


@app.command
def add(
    git_url: str,
    *,
    id: Annotated[str | None, Parameter(name="--id", help="Library ID /owner/repo.")] = None,  # ruff: ignore[builtin-argument-shadowing]
    ref: Annotated[
        str | None, Parameter(help="Tag, branch or commit (default: default branch).")
    ] = None,
    path: Annotated[
        list[str] | None, Parameter(help="Folder, file or glob to import; repeatable.")
    ] = None,
    exclude: Annotated[list[str] | None, Parameter(help="Path to leave out; repeatable.")] = None,
    tag_rule: Annotated[list[str] | None, Parameter(help="PATTERN=TAG; repeatable.")] = None,
    git_token_file: Annotated[
        str | None, Parameter(help="File holding an access token for a private https repository.")
    ] = None,
    git_user: Annotated[str | None, Parameter(help="User name that goes with the token.")] = None,
    ssh_key: Annotated[
        str | None, Parameter(help="File holding an SSH deploy key (ssh URL).")
    ] = None,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    wait: WaitOption = False,
    wait_timeout: WaitTimeout = 600,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: CredentialTokenOption = None,
) -> None:
    """Add a library from a git repository and queue its import.

    A private repository's credential is accepted from a signed-in session only, never from an
    API token: with --git-token-file or --ssh-key you are asked for your password.
    """
    credential = _credential(git_token_file, ssh_key, git_user)

    async def go(api: ApiClient) -> None:
        await lib.add_library(
            api,
            git_url,
            library_id=id,
            ref=ref,
            include=path or (),
            exclude=exclude or (),
            tag_rules=tag_rule or (),
            credential=credential,
            wait=wait,
            as_json=json_output,
            give_up_after=wait_timeout,
        )

    async def work() -> None:
        if credential is None:
            async with _api(url, token) as api:
                await go(api)
        else:
            async with _session(url, username, password_stdin=password_stdin) as api:
                await go(api)

    _call(work())


@app.command
def libraries(
    *, json_output: JsonOption = False, url: UrlOption = None, token: TokenOption = None
) -> None:
    """List the libraries and their versions."""

    async def work() -> None:
        async with _api(url, token) as api:
            await lib.list_libraries(api, as_json=json_output)

    _call(work())


version = App(name="version", help="Versions of a library.")
app.command(version)


@version.command(name="add")
def version_add(
    library: str,
    ref: str,
    *,
    git_token_file: Annotated[
        str | None, Parameter(help="Replace the stored access token (file).")
    ] = None,
    git_user: Annotated[str | None, Parameter(help="User name that goes with the token.")] = None,
    ssh_key: Annotated[str | None, Parameter(help="Replace the stored deploy key (file).")] = None,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    wait: WaitOption = False,
    wait_timeout: WaitTimeout = 600,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: CredentialTokenOption = None,
) -> None:
    """Import another version (tag, branch or commit) of a library, with its settings."""
    credential = _credential(git_token_file, ssh_key, git_user)

    async def go(api: ApiClient) -> None:
        await lib.add_version(
            api,
            library,
            ref,
            credential=credential,
            wait=wait,
            as_json=json_output,
            give_up_after=wait_timeout,
        )

    async def work() -> None:
        if credential is None:
            async with _api(url, token) as api:
                await go(api)
        else:
            async with _session(url, username, password_stdin=password_stdin) as api:
                await go(api)

    _call(work())


@app.command
def sync(
    library: str,
    *,
    wait: WaitOption = False,
    wait_timeout: WaitTimeout = 600,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Re-sync the branch versions of a library (tags and commits never move)."""

    async def work() -> None:
        async with _api(url, token) as api:
            await lib.sync_library(
                api, library, wait=wait, as_json=json_output, give_up_after=wait_timeout
            )

    _call(work())


@app.command
def remove(
    target: str,
    *,
    yes: Annotated[bool, Parameter(name=["--yes", "-y"], help="Do not ask first.")] = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Remove a version (/owner/repo/ref) or a whole library (/owner/repo) and its content."""
    if not yes:
        if not sys.stdin.isatty():
            sys.stderr.write("exactdocs: no terminal to confirm the removal; pass --yes\n")
            raise SystemExit(lib.EXIT_USAGE)
        try:
            lib.split_target(target)  # a bad target is a usage error before any question
            sys.stderr.write(lib.removal_prompt(target))  # stderr: stdout may be --json
            sys.stderr.flush()
            answer = sys.stdin.readline()
        except ClientError as exc:
            sys.stderr.write(f"exactdocs: {exc}\n")
            raise SystemExit(exit_code(exc)) from None
        except KeyboardInterrupt:
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            sys.stderr.write("exactdocs: not removed\n")
            raise SystemExit(lib.EXIT_FAILED)

    async def work() -> None:
        async with _api(url, token) as api:
            await lib.remove(api, target, as_json=json_output)

    _call(work())


tokens = App(name="token", help="API tokens; they need your password, not a token.")
app.command(tokens)


@tokens.command(name="create")
def token_create(
    name: str,
    *,
    expires_in: Annotated[
        int, Parameter(help="Days until it expires.", validator=Number(gte=1))
    ] = DEFAULT_TOKEN_DAYS,
    no_expiry: Annotated[bool, Parameter(help="Never expires.")] = False,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
) -> None:
    """Create an API token and print it once."""

    async def work() -> None:
        async with _session(url, username, password_stdin=password_stdin) as api:
            await lib.token_create(
                api, name, None if no_expiry else expires_in, as_json=json_output
            )

    _call(work())


@tokens.command(name="list")
def token_list(
    *,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
) -> None:
    """List your API tokens."""

    async def work() -> None:
        async with _session(url, username, password_stdin=password_stdin) as api:
            await lib.token_list(api, as_json=json_output)

    _call(work())


@tokens.command(name="revoke")
def token_revoke(
    token_id: str,
    *,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    url: UrlOption = None,
) -> None:
    """Revoke an API token by its ID (see `token list`)."""

    async def work() -> None:
        async with _session(url, username, password_stdin=password_stdin) as api:
            await lib.token_revoke(api, token_id)

    _call(work())


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
