"""``exactdocs`` command line."""

import asyncio
import getpass
import os
import shutil
import sys
import tempfile
import time
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import uvicorn
from cyclopts import App, Parameter
from cyclopts.validators import Number
from pydantic import SecretStr, ValidationError

from exactdocs import __version__
from exactdocs.bootstrap import cli_library as lib
from exactdocs.bootstrap.backup import (
    BackupError,
    BackupSummary,
    create_backup,
    restore_backup,
    sweep_stale_staging,
)
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
from exactdocs.bootstrap.constants import (
    CLIENTS,
    DEFAULT_TOKEN_DAYS,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_USAGE,
    SHUTDOWN_GRACE_SECONDS,
    SKILL_PATH,
    STAGING_PREFIX,
)
from exactdocs.bootstrap.container import Container, ReadOnlyContainer
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.mcp import build_stdio_mcp
from exactdocs.bootstrap.mcp_config import Client, render
from exactdocs.bootstrap.models_pull import default_models
from exactdocs.bootstrap.models_pull import pull as pull_models
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.telemetry import start_telemetry
from exactdocs.identity.constants import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from exactdocs.identity.dtos import (
    CreateFirstAdminCommand,
    CreateUserCommand,
    PasswordReset,
    ResetPasswordCommand,
    SetUserDisabledCommand,
    UserSummary,
)
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.retrieval.dtos import (
    EmbeddingEstimateOut,
    ModelChecksOut,
    RebuiltIndexOut,
    SearchIndexStateOut,
)
from exactdocs_kernel import DomainError

app = App(name="exactdocs", version=__version__, help="Version-accurate docs for AI agents.")


admin = App(name="admin", help="Local administration; opens the database directly.")
app.command(admin)
user = App(
    name="user",
    help="Manage local user accounts; opens the database directly (no self-signup exists).",
)
app.command(user)


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
    """Run the server: web UI + REST API + MCP over HTTP, or MCP only over stdio.

    Args:
        stdio: Serve MCP over stdio instead of HTTP: read-only, needs an existing database.
        host: HTTP only: address to bind.
        port: HTTP only: port to listen on.
        reload: HTTP only: restart on code changes.

    Raises:
        SystemExit: An HTTP option is given with --stdio.
    """
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
        # SQLite: one process, it alone runs jobs and their recovery and its tag lock orders
        # re-tags; uvicorn would otherwise start WEB_CONCURRENCY workers. PostgreSQL: each worker
        # is a process of its own, with its own DBOS executor and the database's advisory locks,
        # so WEB_CONCURRENCY decides (docs/architecture.md).
        workers=None if settings.uses_postgres else 1,
        # PostgreSQL: a process that lost its executor slot stops itself with SIGTERM; open MCP
        # streams must not keep it alive (and its DBOS threads polling) for long.
        timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS if settings.uses_postgres else None,
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
    """Run a client command's work; a ``ClientError`` ends the process with its message.

    Args:
        work: The command's coroutine.

    Returns:
        What the work returned.

    Raises:
        SystemExit: The work failed (its ``exit_code``) or was interrupted.
    """
    try:
        return asyncio.run(work)
    except ClientError as exc:
        sys.stderr.write(f"exactdocs: {exc}\n")
        raise SystemExit(exit_code(exc)) from None
    except KeyboardInterrupt:  # `--wait` has already said the job keeps running
        raise SystemExit(EXIT_INTERRUPTED) from None


def _api(url: str | None = None, token: str | None = None) -> ApiClient:
    """Build the client for the resolved server and token (flags > environment > config file).

    Args:
        url: The ``--url`` flag, if given.
        token: The ``--token`` flag, if given.

    Returns:
        The client, not opened yet.

    Raises:
        SystemExit: No server or token is known, or the URL is not usable.
    """
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
    library: Annotated[
        list[str] | None,
        Parameter(help="Limit to these library IDs; repeat --library to select more."),
    ] = None,
    no_expiry: Annotated[bool, Parameter(help="Create a token that never expires.")] = False,
) -> None:
    """Sign in to an instance and store the server URL and an API token for the other commands.

    With a token (--token, --token-stdin or EXACTDOCS_TOKEN) no new token is created and the
    expiry options do not apply. Otherwise the new token expires after 90 days unless told not to.

    Args:
        url: Server URL (default: EXACTDOCS_URL).
        token: Use this existing API token instead of creating one.
        token_stdin: Read an existing API token from one line of stdin.
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        name: Name of the new token (default: this machine's name).
        expires_in: Days until the new token expires.
        library: Selected library IDs; omitted means all current user access.
        no_expiry: Create a token that never expires.

    Raises:
        SystemExit: The URL is not usable, or stdin holds no token.
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
        """Check the given token, or create one with the password, then store it.

        Returns:
            What was stored, for the confirmation line.

        Raises:
            ClientError: There is no username or password to read.
        """
        async with ApiClient(server, token) as api:
            if token is None:
                try:
                    user, password = _read_login(username, password_stdin=password_stdin)
                except EOFError, KeyboardInterrupt:
                    message = "no username or password to read"
                    raise ClientError(message) from None
                grant = await api.login(
                    user, password, name or machine_name(), expires_at, library_ids=library
                )
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
    """Read the username (unless given) and the password, never echoing the password.

    Args:
        username: The ``--username`` flag; asked for when ``None``.
        password_stdin: Read the password from one line of stdin instead of prompting.

    Returns:
        The username and the password.

    Raises:
        EOFError: Stdin is empty, or is not a terminal to prompt on.
    """
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

    Args:
        url: The ``--url`` flag, if given.
        username: Who signs in; asked for when ``None``.
        password_stdin: Read the password from one line of stdin instead of prompting.

    Yields:
        The signed-in client; the session ends when the block does.

    Raises:
        ClientError: There is no username or password to read.
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
    """Read a repository credential from files (never from the command line).

    Args:
        git_token_file: File holding an access token for a private https repository.
        ssh_key: File holding an SSH deploy key.
        git_user: User name that goes with the token.

    Returns:
        The API's ``credential`` object, or ``None`` when no file is given.

    Raises:
        UsageError: Both a token file and a key are given (caught: the process ends).
        SystemExit: The credential cannot be used, or both files are given.
    """
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
    dry_run: Annotated[
        bool,
        Parameter(
            help="List the files the import would take (and how many) without adding anything; "
            "--id and --wait have no effect then, --tag-rule is only checked."
        ),
    ] = False,
    url: UrlOption = None,
    token: CredentialTokenOption = None,
) -> None:
    """Add a library from a git repository and queue its import.

    A private repository's credential is accepted from a signed-in session only, never from an
    API token: with --git-token-file or --ssh-key you are asked for your password.

    Args:
        git_url: The repository's clone URL.
        id: Library ID /owner/repo.
        ref: Tag, branch or commit (default: default branch).
        path: Folder, file or glob to import; repeatable.
        exclude: Path to leave out; repeatable.
        tag_rule: PATTERN=TAG; repeatable.
        git_token_file: File holding an access token for a private https repository.
        git_user: User name that goes with the token.
        ssh_key: File holding an SSH deploy key (ssh URL).
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        wait: Wait for the import and show its progress (on stderr).
        wait_timeout: With --wait: seconds to follow the import before leaving it to the server.
        json_output: Print JSON for scripts.
        dry_run: List the files the import would take without adding anything.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); ignored with a git
            credential, which needs your password instead.

    Raises:
        SystemExit: A tag rule is malformed.
    """
    credential = _credential(git_token_file, ssh_key, git_user)
    try:  # before any request or password prompt, so a dry run catches a bad rule too
        lib.parse_tag_rules(tag_rule or ())
    except ClientError as exc:
        sys.stderr.write(f"exactdocs: {exc}\n")
        raise SystemExit(exit_code(exc)) from None

    async def go(api: ApiClient) -> None:
        """Preview the import, or add the library.

        Args:
            api: The API client.
        """
        if dry_run:
            await lib.preview_import(
                api,
                git_url,
                ref=ref,
                include=path or (),
                exclude=exclude or (),
                credential=credential,
                as_json=json_output,
            )
            return
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
        """Run it with the token, or with a session when a credential is sent."""
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
    """List the libraries and their versions.

    Args:
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
    """

    async def work() -> None:
        """List the libraries."""
        async with _api(url, token) as api:
            await lib.list_libraries(api, as_json=json_output)

    _call(work())


@app.command(usage="Usage: exactdocs library [OPTIONS] NAME [QUERY...]")
def library(
    name: Annotated[str, Parameter(help="Library name to look for, e.g. react.")],
    /,
    *query: Annotated[
        str, Parameter(name="QUERY", help="What to look up; ranks the matches (default: the name).")
    ],
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Find the ID of a library by name (like `ctx7 library`); QUERY ranks the matches.

    Args:
        name: Library name to look for, e.g. react.
        *query: What to look up; ranks the matches (default: the name).
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
    """

    async def work() -> None:
        """Look the library up."""
        async with _api(url, token) as api:
            await lib.find_library(api, name, " ".join(query) or None, as_json=json_output)

    _call(work())


@app.command(usage="Usage: exactdocs docs [OPTIONS] LIBRARY-ID QUERY...")
def docs(
    library_id: Annotated[
        str,
        Parameter(
            name="LIBRARY-ID",
            help="Library ID from 'exactdocs library', e.g. /owner/repo or /owner/repo@v1.",
        ),
    ],
    /,
    *query: Annotated[str, Parameter(name="QUERY", help="The question; several words are joined.")],
    language: Annotated[
        str | None,
        Parameter(help="Language you write in; chunks with code in it come first (no filter)."),
    ] = None,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Show what an agent gets for a question about a library (like `ctx7 docs`).

    Args:
        library_id: Library ID from 'exactdocs library', e.g. /owner/repo or /owner/repo@v1.
        *query: The question; several words are joined.
        language: Language you write in; chunks with code in it come first (no filter).
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.

    Raises:
        SystemExit: No question is given.
    """
    if not query:
        sys.stderr.write("exactdocs: docs needs a question after the library ID\n")
        raise SystemExit(EXIT_USAGE)

    async def work() -> None:
        """Ask the question."""
        async with _api(url, token) as api:
            await lib.query_docs(
                api, library_id, " ".join(query), language=language, as_json=json_output
            )

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
    """Import another version (tag, branch or commit) of a library, with its settings.

    Args:
        library: The library, /owner/repo.
        ref: Tag, branch or commit to import.
        git_token_file: Replace the stored access token (file).
        git_user: User name that goes with the token.
        ssh_key: Replace the stored deploy key (file).
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        wait: Wait for the import and show its progress (on stderr).
        wait_timeout: With --wait: seconds to follow the import before leaving it to the server.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); ignored with a git
            credential, which needs your password instead.
    """
    credential = _credential(git_token_file, ssh_key, git_user)

    async def go(api: ApiClient) -> None:
        """Add the version.

        Args:
            api: The API client.
        """
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
        """Run it with the token, or with a session when a credential is sent."""
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
    confirm: Annotated[
        bool,
        Parameter(
            help="Confirm every tag of the library that moved upstream: re-import each at the "
            "commit it names now (old and new commit are printed)."
        ),
    ] = False,
    confirm_tag: Annotated[
        list[str] | None,
        Parameter(help="Confirm only this moved tag; repeatable. Other moved tags stay reported."),
    ] = None,
    wait: WaitOption = False,
    wait_timeout: WaitTimeout = 600,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Re-sync the branch versions of a library; moved tags are re-imported only on --confirm.

    Args:
        library: The library, /owner/repo.
        confirm: Confirm every tag of the library that moved upstream.
        confirm_tag: Confirm only this moved tag; repeatable.
        wait: Wait for the import and show its progress (on stderr).
        wait_timeout: With --wait: seconds to follow the import before leaving it to the server.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.

    Raises:
        SystemExit: Both --confirm and --confirm-tag are given.
    """
    if confirm and confirm_tag:  # "every moved tag" and "only these" cannot both be meant
        sys.stderr.write("exactdocs: use --confirm or --confirm-tag, not both\n")
        raise SystemExit(EXIT_USAGE)

    async def work() -> None:
        """Sync the library."""
        async with _api(url, token) as api:
            await lib.sync_library(
                api,
                library,
                confirm=confirm or confirm_tag or False,
                wait=wait,
                as_json=json_output,
                give_up_after=wait_timeout,
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
    """Remove a version (/owner/repo/ref) or a whole library (/owner/repo) and its content.

    Args:
        target: /owner/repo/ref or /owner/repo.
        yes: Do not ask first.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.

    Raises:
        SystemExit: There is no terminal to confirm on, the target is malformed, or the removal
            was not confirmed.
    """
    if not yes:
        if not sys.stdin.isatty():
            sys.stderr.write("exactdocs: no terminal to confirm the removal; pass --yes\n")
            raise SystemExit(EXIT_USAGE)
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
            raise SystemExit(EXIT_FAILED)

    async def work() -> None:
        """Remove the target."""
        async with _api(url, token) as api:
            await lib.remove(api, target, as_json=json_output)

    _call(work())


jobs = App(name="jobs", help="Background jobs: imports, syncs, re-processing, embedding.")
app.command(jobs)


@jobs.command(name="cancel")
def jobs_cancel(
    job_id: str,
    *,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Cancel a queued or running job (needs the contributor role on its library).

    A queued job never starts; a running one stops after the step it is running (an embedding
    after the batch in flight), keeping what it finished.

    Args:
        job_id: The job's ID (the web UI and `--json` output show it).
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
    """

    async def work() -> None:
        """Cancel the job."""
        async with _api(url, token) as api:
            await lib.cancel_job(api, job_id, as_json=json_output)

    _call(work())


sources = App(
    name="sources",
    help="Declare libraries in exactdocs.sources.yaml, review the diff, apply it.",
)
app.command(sources)

type PruneOption = Annotated[
    bool,
    Parameter(help="Also remove the libraries and manual versions the file does not declare."),
]


@sources.command(name="plan")
def sources_plan(
    file: Annotated[str, Parameter(help="The sources file, e.g. exactdocs.sources.yaml.")],
    *,
    prune: PruneOption = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Show what applying the sources file would change; the server changes nothing.

    Args:
        file: The sources file, e.g. exactdocs.sources.yaml.
        prune: Show the undeclared libraries and manual versions as removed.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
    """

    async def work() -> None:
        """Plan the file."""
        async with _api(url, token) as api:
            await lib.plan_sources(api, file, prune=prune, as_json=json_output)

    _call(work())


@sources.command(name="apply")
def sources_apply(
    file: Annotated[str, Parameter(help="The sources file, e.g. exactdocs.sources.yaml.")],
    *,
    prune: PruneOption = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
    token: TokenOption = None,
) -> None:
    """Apply the sources file: create, update and, with --prune, remove libraries.

    Args:
        file: The sources file, e.g. exactdocs.sources.yaml.
        prune: Also remove the libraries and manual versions the file does not declare.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
    """

    async def work() -> None:
        """Apply the file."""
        async with _api(url, token) as api:
            await lib.apply_sources(api, file, prune=prune, as_json=json_output)

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
    library: Annotated[
        list[str] | None,
        Parameter(help="Limit to these library IDs; repeat --library to select more."),
    ] = None,
    no_expiry: Annotated[bool, Parameter(help="Never expires.")] = False,
    username: UsernameOption = None,
    password_stdin: PasswordStdin = False,
    json_output: JsonOption = False,
    url: UrlOption = None,
) -> None:
    """Create an API token and print it once.

    Args:
        name: The token's name.
        expires_in: Days until it expires.
        library: Selected library IDs; omitted means all current user access.
        no_expiry: Never expires.
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
    """

    async def work() -> None:
        """Sign in and create the token."""
        async with _session(url, username, password_stdin=password_stdin) as api:
            await lib.token_create(
                api,
                name,
                None if no_expiry else expires_in,
                as_json=json_output,
                library_ids=library,
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
    """List your API tokens.

    Args:
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        json_output: Print JSON for scripts.
        url: Server URL (default: EXACTDOCS_URL, config).
    """

    async def work() -> None:
        """Sign in and list the tokens."""
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
    """Revoke an API token by its ID (see `token list`).

    Args:
        token_id: The token's ID.
        username: Who signs in; asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        url: Server URL (default: EXACTDOCS_URL, config).
    """

    async def work() -> None:
        """Sign in and revoke the token."""
        async with _session(url, username, password_stdin=password_stdin) as api:
            await lib.token_revoke(api, token_id)

    _call(work())


def _config_conflict(
    *,
    stdio: bool,
    show_token: bool,
    new_token: bool,
    token: str | None,
    needs_new_token: dict[str, bool],
) -> str | None:
    """Return the first flag combination `config` refuses, as a message, or ``None``.

    Args:
        stdio: ``--stdio`` is given.
        show_token: ``--show-token`` is given.
        new_token: ``--new-token`` is given.
        token: The ``--token`` flag.
        needs_new_token: Each flag that needs ``--new-token``, and whether it is given.

    Returns:
        What is wrong, or ``None`` when the combination is fine.
    """
    if stdio and (show_token or new_token):
        return "--stdio needs no token"
    if show_token and new_token:
        return "--show-token and --new-token exclude each other"
    if new_token and token is not None:
        return "--token is not used with --new-token"
    if not new_token:
        for flag, given in needs_new_token.items():
            if given:
                return f"{flag} needs --new-token"
    return None


@app.command
def config(
    *,
    client: Annotated[Client, Parameter(help=f"MCP client: {', '.join(CLIENTS)}.")],
    stdio: Annotated[
        bool, Parameter(help="Local read-only `serve --stdio` instead of HTTP with a token.")
    ] = False,
    url: UrlOption = None,
    token: TokenOption = None,
    show_token: Annotated[
        bool,
        Parameter(
            help="Write your real API token (EXACTDOCS_TOKEN, --token or the login) into the "
            "snippet. Without it the snippet refers to EXACTDOCS_TOKEN or asks for the token."
        ),
    ] = False,
    new_token: Annotated[
        bool,
        Parameter(
            help="Create a token for this client (asks for your password) and write it into the "
            "snippet; revoking it later affects only this client."
        ),
    ] = False,
    name: Annotated[
        str | None, Parameter(help="With --new-token: its name (default: mcp-<client>).")
    ] = None,
    expires_in: Annotated[
        int | None,
        Parameter(
            help=f"With --new-token: days until it expires (default {DEFAULT_TOKEN_DAYS}; "
            "for a token that never expires use `token create --no-expiry`).",
            validator=Number(gte=1),
        ),
    ] = None,
    username: Annotated[
        str | None, Parameter(help="With --new-token: who signs in (asked for when omitted).")
    ] = None,
    password_stdin: Annotated[
        bool, Parameter(help="With --new-token: read the password from one line of stdin.")
    ] = False,
) -> None:
    """Print a ready-to-paste MCP config for a client, never containing the token unless asked.

    Args:
        client: The MCP client.
        stdio: Local read-only `serve --stdio` instead of HTTP with a token.
        url: Server URL (default: EXACTDOCS_URL, config).
        token: ExactDocs API token (default: EXACTDOCS_TOKEN, config); not a git token.
        show_token: Write your real API token into the snippet.
        new_token: Create a token for this client (asks for your password) and write it in.
        name: With --new-token: its name (default: mcp-<client>).
        expires_in: With --new-token: days until it expires.
        username: With --new-token: who signs in (asked for when omitted).
        password_stdin: With --new-token: read the password from one line of stdin.

    Raises:
        SystemExit: The flags conflict.
    """
    conflict = _config_conflict(
        stdio=stdio,
        show_token=show_token,
        new_token=new_token,
        token=token,
        needs_new_token={
            "--name": name is not None,
            "--expires-in": expires_in is not None,
            "--username": username is not None,
            "--password-stdin": password_stdin,
        },
    )
    if conflict:
        sys.stderr.write(f"exactdocs: {conflict}\n")
        raise SystemExit(EXIT_USAGE)

    async def work() -> tuple[str, str | None]:
        """Find the server URL and the token to write, creating one with --new-token.

        Returns:
            The server URL (empty with --stdio) and the token, or ``None`` for a placeholder.
        """
        if stdio:
            return "", None  # no URL involved
        if new_token:
            async with _session(url, username, password_stdin=password_stdin) as api:
                grant = await lib.create_token(
                    api, name or f"mcp-{client}", expires_in or DEFAULT_TOKEN_DAYS
                )
                sys.stderr.write(
                    lib.printable(
                        f"exactdocs: created token {grant['name']!r} ({grant['id']}); "
                        f'revoke it with "exactdocs token revoke {grant["id"]}"'
                    )
                    + "\n"
                )
                return api.url, grant["token"]
        if show_token:
            resolved = ClientConfig.resolve(url=url, token=token)
            return resolved.url, resolved.token
        return resolve_url(url=url), None

    server, secret = _call(work())
    if secret:
        sys.stderr.write(
            "exactdocs: this snippet contains your API token; do not commit the file it goes into\n"
        )
    sys.stdout.write(render(client, mcp_url=f"{server}/mcp", token=secret, stdio=stdio))


@app.command
def skill() -> None:
    """Print the agent usage skill (SKILL.md) to save as `exactdocs/SKILL.md` in a skills folder."""
    sys.stdout.write(SKILL_PATH.read_text(encoding="utf-8"))


@admin.command
def create(
    *,
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
) -> None:
    """Create the first admin account (only while no account exists).

    Args:
        username: Asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
    """
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
    """Set a new password for an account and sign it out everywhere (lost-password recovery).

    Args:
        username: Asked for when omitted.
        password_stdin: Read the new password from one line of stdin instead of prompting.
    """
    name, password = _read_credentials(username, password_stdin=password_stdin, new=True)
    _report_reset(_run(_reset_password(Settings(), name, password)))


def _report_reset(reset: PasswordReset) -> None:
    """Say that a password changed, and warn when the sign-in throttle was not cleared.

    Args:
        reset: The outcome of the reset.
    """
    sys.stdout.write(f"Password of {reset.account.username!r} changed; all its sessions ended.\n")
    if reset.throttle != "cleared":
        cause = "was busy" if reset.throttle == "busy" else "failed"
        sys.stderr.write(
            f"exactdocs: warning: the password was changed, but the sign-in throttle {cause}, "
            "so its count or the addresses it remembers for this username may not have been "
            "reset: sign-ins may stay throttled (429) until Retry-After passes, and an address "
            "that signed in with the old password may still skip the username's count. Run the "
            "command again to retry (that is safe), or wait.\n"
        )


@user.command(name="create")
def user_create(
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    /,
    *,
    password_stdin: Annotated[
        bool, Parameter(help="Read the password from one line of stdin instead of prompting.")
    ] = False,
    operator: Annotated[
        bool, Parameter(help="Make the account an admin, who also manages accounts.")
    ] = False,
) -> None:
    """Create a local user account (after the setup; the first account is the admin).

    Args:
        username: Asked for when omitted.
        password_stdin: Read the password from one line of stdin instead of prompting.
        operator: Make the account an admin, who also manages accounts.
    """
    name, password = _read_credentials(username, password_stdin=password_stdin)
    created = _run(_create_user(Settings(), name, password, operator=operator))
    sys.stdout.write(f"Created {'admin' if operator else 'user'} {created.username!r}.\n")


@user.command(name="disable")
def user_disable(username: str, /) -> None:
    """Disable an account: it cannot sign in, its sessions end and its API tokens are revoked.

    Args:
        username: The account's username.
    """
    command = SetUserDisabledCommand(username=username, disabled=True)
    changed = _run(_set_user_disabled(Settings(), command))
    sys.stdout.write(
        f"Disabled {changed.username!r}; its sessions ended and its API tokens were revoked.\n"
    )


@user.command(name="enable")
def user_enable(username: str, /) -> None:
    """Let a disabled account sign in again, with its password unchanged.

    Args:
        username: The account's username.
    """
    command = SetUserDisabledCommand(username=username, disabled=False)
    changed = _run(_set_user_disabled(Settings(), command))
    sys.stdout.write(f"Enabled {changed.username!r}.\n")


@user.command(name="reset-password")
def user_reset_password(
    username: Annotated[str | None, Parameter(help="Asked for when omitted.")] = None,
    /,
    *,
    password_stdin: Annotated[
        bool, Parameter(help="Read the new password from one line of stdin instead of prompting.")
    ] = False,
) -> None:
    """Set a new password for an account and sign it out everywhere.

    Args:
        username: Asked for when omitted.
        password_stdin: Read the new password from one line of stdin instead of prompting.
    """
    name, password = _read_credentials(username, password_stdin=password_stdin, new=True)
    _report_reset(_run(_reset_password(Settings(), name, password)))


def _read_credentials(
    username: str | None, *, password_stdin: bool, new: bool = False
) -> tuple[str, str]:
    """Read the username (unless given) and a password for a local admin command.

    Args:
        username: The ``--username`` flag; asked for when ``None``.
        password_stdin: Read the password from one line of stdin instead of prompting.
        new: The password is a new one (prompted for as such).

    Returns:
        The username and the password.

    Raises:
        SystemExit: There is no username or password to read.
    """
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
    """Run a command's work, turning bad input and domain errors into a one-line exit.

    Args:
        work: The command's coroutine.

    Returns:
        What the work returned.

    Raises:
        SystemExit: The input is invalid (the password is never echoed), or a domain error.
    """
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
    """Read a password from stdin or the terminal; a prompted one is asked for twice.

    Args:
        from_stdin: Read one line of stdin instead of prompting.
        new: Prompt for a new password.

    Returns:
        The password.

    Raises:
        EOFError: Stdin is empty, or is not a terminal to prompt on.
        SystemExit: The two prompted passwords differ.
    """
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
    """Create the first admin in the local database.

    Args:
        settings: The server's settings.
        username: The admin's username.
        password: The admin's password.

    Returns:
        The username as stored (normalized).
    """
    container = _build(settings)
    async with container.running(jobs=False):  # the server runs the jobs
        command = CreateFirstAdminCommand(username=username, password=SecretStr(password))
        return (await container.identity.create_first_admin(command)).username


async def _reset_password(settings: Settings, username: str, password: str) -> PasswordReset:
    """Reset an account's password in the local database.

    Args:
        settings: The server's settings.
        username: The account's username.
        password: The new password.

    Returns:
        The account, and whether its sign-in throttle was cleared.
    """
    container = _build(settings)
    async with container.running(jobs=False):  # the server runs the jobs
        command = ResetPasswordCommand(username=username, password=SecretStr(password))
        return await container.identity.reset_password(command)


async def _create_user(
    settings: Settings, username: str, password: str, *, operator: bool
) -> UserSummary:
    """Create a local user account in the local database.

    Args:
        settings: The server's settings.
        username: The account's username.
        password: The account's password.
        operator: Make the account an admin.

    Returns:
        The new account, its username as stored (normalized).
    """
    # Built in here, so `_run` turns a refused password into a message that does not echo it.
    command = CreateUserCommand(
        username=username, password=SecretStr(password), role="admin" if operator else "user"
    )
    container = _build(settings)
    async with container.running(jobs=False):  # the server runs the jobs
        return await container.identity.create_user(command)


async def _set_user_disabled(settings: Settings, command: SetUserDisabledCommand) -> UserSummary:
    """Disable or enable an account in the local database.

    Args:
        settings: The server's settings.
        command: The account and what to do.

    Returns:
        The account as it is now.
    """
    container = _build(settings)
    async with container.running(jobs=False):  # the server runs the jobs
        return await container.identity.set_user_disabled(command)


@app.command
def reindex() -> None:
    """Rebuild the search index from the stored chunks; a running server keeps answering.

    Local: opens the database in the data directory (EXACTDOCS_DATA_DIR), so run it where the
    server runs (in Docker: `docker exec <container> exactdocs reindex`). Nothing is imported
    again. Needed after a release whose notes say "requires reindex"; harmless otherwise. Run one
    at a time: a second run started meanwhile drops the first one's new table, which then fails
    (the index that answers is not affected).
    """
    settings = Settings()
    started = time.monotonic()
    state, rebuilt = _run(_reindex(settings))
    seconds = time.monotonic() - started
    if state.stored_format is None:
        was = "no format was recorded"
    elif state.needs_rebuild:
        was = f"was format {state.stored_format}"
    else:
        was = f"was format {state.stored_format}, not older; rebuilt anyway"
    sys.stdout.write(
        f"Search index rebuilt in format {rebuilt.format} ({was}): "
        f"{rebuilt.entries} chunks in {seconds:.1f} s.\n"
    )


ai = App(name="ai", help="AI providers and model roles (local: reads this server's settings).")
app.command(ai)


@ai.command(name="check")
def ai_check() -> None:
    """Make one minimal call per configured model role and report latency, model and dimensions.

    Local: reads this server's settings (EXACTDOCS_AI__..., EXACTDOCS_CONFIG_FILE) and the profiles
    stored in its database, so run it where the server runs (in Docker: `docker exec <container>
    exactdocs ai check`). Keys are never printed. Exits 1 when a role fails, 2 when none is set.

    Raises:
        SystemExit: No role is configured, or a role failed.
    """
    checks = _run(_ai_check(Settings()))
    if not checks.checks:
        sys.stdout.write(
            "No model role is configured: searches use BM25. Set EXACTDOCS_AI__<ROLE>__MODEL "
            "(see docs/decisions/ai-retrieval.md).\n"
        )
        raise SystemExit(EXIT_USAGE)
    for check in checks.checks:
        role = check.role.value if check.role else "model"
        if check.status == "ok":
            dimensions = f", {check.dimensions} dimensions" if check.dimensions else ""
            sys.stdout.write(
                f"{role}: ok  {check.profile}:{check.model} answered as {check.served_model} "
                f"in {check.latency_ms:.0f} ms{dimensions}\n"
            )
        else:
            sys.stdout.write(f"{role}: error  {check.profile}:{check.model}: {check.error}\n")
    if not checks.ok:
        raise SystemExit(EXIT_FAILED)


async def _ai_check(settings: Settings) -> ModelChecksOut:
    """Check every configured role against the local database's profiles.

    Args:
        settings: The server's settings.

    Returns:
        One check per role that is set.
    """
    container = _build(settings)
    async with container.running(jobs=False):  # migrates first, as `serve` would
        return await container.retrieval.check_roles()


@ai.command(name="estimate")
def ai_estimate() -> None:
    """Print what embedding every version not embedded yet would send and cost, before it starts.

    Local: reads this server's settings and database, so run it where the server runs (in
    Docker: `docker exec <container> exactdocs ai estimate`). Counts the distinct chunks of every
    active version (libraries with AI on) without a vector from the configured embedding model,
    at 4 characters per token, priced with the bundled price list: an estimate. It calls no model
    and no tokenizer. Exits 2 when no embedding model is configured.

    Raises:
        SystemExit: No embedding model is configured.
    """
    estimate = _run(_ai_estimate(Settings()))
    if estimate.model is None:
        sys.stdout.write(
            "No embedding model is configured: nothing would be embedded. Set "
            "EXACTDOCS_AI__EMBEDDING__MODEL (see docs/decisions/ai-retrieval.md).\n"
        )
        raise SystemExit(EXIT_USAGE)
    if estimate.estimated_usd is None:
        usd = "unknown USD (the price list does not know this model)"
    else:
        usd = (
            f"{estimate.estimated_usd:.4f} USD estimated "
            f"(at {estimate.usd_per_million_tokens} USD per million tokens)"
        )
    sys.stdout.write(
        f"Embedding with {estimate.model}: {estimate.chunks} chunks of {estimate.versions} "
        f"versions to embed, {estimate.characters} characters, about "
        f"{estimate.estimated_tokens} estimated tokens, {usd}.\n{estimate.note}\n"
    )


async def _ai_estimate(settings: Settings) -> EmbeddingEstimateOut:
    """Estimate the embedding of what the local database has not embedded.

    Args:
        settings: The server's settings.

    Returns:
        The estimate.
    """
    container = _build(settings)
    async with container.running(jobs=False):  # migrates first, as `serve` would
        return await container.retrieval.estimate_embedding()


models = App(
    name="models",
    help="Local models (exactdocs[local]): fetched once by `pull`, never at run time.",
)
app.command(models)


@models.command(name="pull", usage="Usage: exactdocs models pull [MODEL...]")
def models_pull(
    *model: Annotated[
        str,
        Parameter(
            name="MODEL",
            help="fastembed embedding models or cross-encoders, e.g. BAAI/bge-small-en-v1.5 "
            "(default: BAAI/bge-small-en-v1.5 and Xenova/ms-marco-MiniLM-L-6-v2).",
        ),
    ],
) -> None:
    """Download local models from the Hugging Face Hub into EXACTDOCS_MODELS_DIR.

    The only command that contacts the Hub: the server loads `local` profiles' models from that
    directory (default: `models` in the data directory) and never downloads one. Run it where
    the server runs, then set a profile of kind `local` and a role on it:
    `EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local`,
    `EXACTDOCS_AI__EMBEDDING__MODEL=local:BAAI/bge-small-en-v1.5`. A model already there is
    skipped without contacting the Hub. Needs the [local] extra. Exits 1 when a model could not
    be pulled.

    Args:
        model: fastembed embedding models or cross-encoders (default: the two defaults).

    Raises:
        SystemExit: A model could not be pulled.
    """
    settings = Settings()
    models_dir = settings.effective_models_dir
    failed = False
    for outcome in pull_models(model or default_models(), models_dir):
        status = "ok" if outcome.ok else "error"
        sys.stdout.write(f"{outcome.model}: {status}  {outcome.message}\n")
        failed = failed or not outcome.ok
    if failed:
        raise SystemExit(EXIT_FAILED)


@app.command
def backup(
    path: Annotated[
        str,
        Parameter(
            help="Archive to write (.tar.gz), which must not exist; `-` for stdout.",
            allow_leading_hyphen=True,
        ),
    ],
    *,
    include_secret_key: Annotated[
        bool,
        Parameter(
            help="Also store secret.key. The archive then opens the stored repository "
            "credentials: keep it as safe as the key."
        ),
    ] = False,
) -> None:
    """Write a consistent backup of the instance while the server keeps serving.

    Local: reads the data directory (EXACTDOCS_DATA_DIR), so run it where the server runs (in
    Docker: `docker exec <container> exactdocs backup - > exactdocs.tar.gz`). The archive holds
    the database (libraries, versions, settings, accounts, tokens), the durable job steps and
    known_hosts; secret.key only with --include-secret-key.

    Args:
        path: Archive to write (.tar.gz), which must not exist; `-` for stdout.
        include_secret_key: Also store secret.key. The archive then opens the stored repository
            credentials: keep it as safe as the key.

    Raises:
        SystemExit: The archive would go to a terminal, or the backup failed.
    """
    settings = Settings()
    to_stdout = path == "-"
    if to_stdout and sys.stdout.isatty():
        message = "exactdocs: the archive is binary; redirect it (`backup - > file.tar.gz`)"
        raise SystemExit(message)
    report = sys.stderr if to_stdout else sys.stdout
    try:
        summary = (
            _backup_to_stdout(settings, include_secret_key=include_secret_key)
            if to_stdout
            else create_backup(settings, Path(path), include_secret_key=include_secret_key)
        )
    except BackupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc
    where = "stdout" if to_stdout else str(summary.path)
    report.write(
        f"Backed up {', '.join(summary.members)} (schema {summary.schema_revision}, "
        f"{summary.size} bytes) to {where}.\n"
    )
    if not include_secret_key:
        report.write(
            "secret.key is not in it: keep the key (or EXACTDOCS_SECRET_KEY) apart, or stored "
            "repository credentials must be sent again after a restore.\n"
        )


def _backup_to_stdout(settings: Settings, *, include_secret_key: bool) -> BackupSummary:
    """Write the archive to a temporary file, then copy it to stdout.

    Args:
        settings: Where the instance keeps its data.
        include_secret_key: Also store ``secret.key``.

    Returns:
        What was written (its path no longer exists).
    """
    # In the data dir: writable wherever the server runs (a container may have no usable /tmp).
    sweep_stale_staging(settings.data_dir)
    with tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=STAGING_PREFIX) as tmp:
        summary = create_backup(
            settings, Path(tmp) / "backup.tar.gz", include_secret_key=include_secret_key
        )
        with summary.path.open("rb") as archive:
            shutil.copyfileobj(archive, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    return summary


@app.command
def restore(
    path: Annotated[str, Parameter(help="Archive written by `exactdocs backup`.")],
) -> None:
    """Restore a backup into an empty data directory, migrating it to this version.

    Local: writes to the data directory (EXACTDOCS_DATA_DIR), which must hold no instance yet;
    stop the server first. A backup from a newer release is refused. Start `exactdocs serve`
    afterwards.

    Args:
        path: Archive written by `exactdocs backup`.

    Raises:
        SystemExit: The restore failed.
    """
    settings = Settings()
    try:
        summary = asyncio.run(restore_backup(settings, Path(path)))
    except (BackupError, StartupError, OSError) as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc
    migrated = (
        f", migrated {summary.schema_from} -> {summary.schema_to}"
        if summary.schema_to != summary.schema_from
        else ""
    )
    sys.stdout.write(
        f"Restored {', '.join(summary.members)} from ExactDocs {summary.version} into "
        f"{settings.data_dir}{migrated}.\n"
    )
    if "secret.key" not in summary.members and not settings.secret_key:
        sys.stdout.write(
            "The backup holds no secret.key: stored repository credentials open only with the "
            f"key they were sealed with. Copy that secret.key into {settings.data_dir} (or set "
            "EXACTDOCS_SECRET_KEY) before `exactdocs serve`; otherwise their libraries keep "
            "serving and ask for the credential again.\n"
        )
    if summary.reindex_required:
        sys.stdout.write("The search index is in an older format: run `exactdocs reindex`.\n")


async def _reindex(settings: Settings) -> tuple[SearchIndexStateOut, RebuiltIndexOut]:
    """Rebuild the local database's search index.

    Args:
        settings: The server's settings.

    Returns:
        The index's state before the rebuild, and the rebuilt index.
    """
    container = _build(settings)
    async with container.running(jobs=False):  # migrates first, as `serve` would
        state = await container.retrieval.get_search_index_state()
        return state, await container.retrieval.rebuild_search_index()


async def _serve_stdio(settings: Settings) -> None:
    """Serve MCP over stdio from the existing database, read-only.

    Telemetry is off unless ``EXACTDOCS_TELEMETRY=otlp``, and never on stdout. No ``/metrics``:
    there is nowhere to serve it.

    Args:
        settings: The server's settings.

    Raises:
        SystemExit: The database cannot be opened or is not current.
    """
    start_telemetry(settings)
    try:
        container = ReadOnlyContainer.build(settings)
        async with container.running():  # no worker, no migration: the HTTP server owns both
            await build_stdio_mcp(container).run_stdio_async(show_banner=False)
    except StartupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _build(settings: Settings) -> Container:
    """Build the container; an unusable data directory ends the process with a clear message.

    Args:
        settings: The server's settings.

    Returns:
        The container, not running yet.

    Raises:
        SystemExit: The instance cannot start with these settings.
    """
    try:
        return Container.build(settings)
    except StartupError as exc:
        message = f"exactdocs: {exc}"
        raise SystemExit(message) from exc


def _check_startup(settings: Settings) -> None:
    """Fail before uvicorn starts (and before any reload worker) instead of with a traceback.

    Args:
        settings: The server's settings.

    Raises:
        SystemExit: ``git`` is not installed, or the instance cannot start with these settings.
    """
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
    """ASGI factory used by uvicorn (also with ``--reload``).

    Returns:
        The app.
    """
    return create_app(Container.build(Settings()))


def main() -> None:
    """Console-script entry point."""
    app()
