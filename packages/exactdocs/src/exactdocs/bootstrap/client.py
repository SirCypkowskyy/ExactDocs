"""What the command line needs to be a client of the REST API: stored credentials and the client.

The client-side commands (``login``, and later the library and token commands) never open the
database: they go through ``ApiClient``, so they work against any instance. Nothing here imports
the container, the settings of the server or a domain.

Where the server and the token come from, strongest first: command-line flag, then
``EXACTDOCS_URL`` / ``EXACTDOCS_TOKEN``, then the config file (``EXACTDOCS_CONFIG_FILE``, else
``config.json`` in the platform config directory, mode 0600). The only host ever contacted is the
resolved server URL.
"""

import ipaddress
import json
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import httpx2
from platformdirs import user_config_path

URL_VARIABLE = "EXACTDOCS_URL"
TOKEN_VARIABLE = "EXACTDOCS_TOKEN"  # ruff: ignore[hardcoded-password-string] (a variable name, not a secret)
CONFIG_FILE_VARIABLE = "EXACTDOCS_CONFIG_FILE"
MAX_TOKEN_NAME_LENGTH = 64  # the server's limit, so a long hostname is cut instead of refused
TIMEOUT_SECONDS = 15.0


class ClientError(Exception):
    """Something the user can fix; ``str(error)`` is the whole message, safe to print."""


def config_path(env: Mapping[str, str] = os.environ) -> Path:
    """Return the credentials file: ``EXACTDOCS_CONFIG_FILE`` or the user config dir's file."""
    if override := env.get(CONFIG_FILE_VARIABLE):
        return Path(override)
    return user_config_path("exactdocs", appauthor=False) / "config.json"


def machine_name() -> str:
    """Return the default token name: this machine's hostname."""
    return (socket.gethostname() or "exactdocs-cli")[:MAX_TOKEN_NAME_LENGTH]


def normalize_url(url: str) -> str:
    """Return ``url`` without a trailing slash, or raise ``ClientError`` if it is not a server URL.

    Plain ``http`` is accepted for loopback only: the token and the password would cross the
    network in the clear otherwise.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        message = (
            f"{url!r} is not a server URL; use http(s)://host[:port], e.g. https://docs.example.com"
        )
        raise ClientError(message)
    if parts.username or parts.password or parts.query or parts.fragment:
        message = "the server URL must not hold credentials, a query or a fragment"
        raise ClientError(message)
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        message = (
            f"refusing to send credentials over plain http to {parts.hostname}; "
            "use an https:// URL (plain http is only allowed for localhost)"
        )
        raise ClientError(message)
    return url.strip().rstrip("/")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """The server to talk to and the API token to do it with (never shown in a repr)."""

    url: str
    token: str = field(repr=False)

    @classmethod
    def resolve(
        cls,
        *,
        url: str | None = None,
        token: str | None = None,
        env: Mapping[str, str] = os.environ,
    ) -> Self:
        """Combine flags, environment and the config file; raise ``ClientError`` if incomplete.

        A token from the config file is only used for the server it was issued by: pairing it
        with a different URL (a flag or the environment) would hand it to the wrong host.
        """
        stored = read_stored(config_path(env))
        chosen_url = url or env.get(URL_VARIABLE) or stored.get("url")
        if not chosen_url:
            message = "no server configured; run `exactdocs login <url>` or set EXACTDOCS_URL"
            raise ClientError(message)
        chosen_url = normalize_url(chosen_url)
        chosen_token = token or env.get(TOKEN_VARIABLE)
        if not chosen_token and stored.get("url") and normalize_url(stored["url"]) == chosen_url:
            chosen_token = stored.get("token")
        if not chosen_token:
            message = (
                f"not logged in to {chosen_url}; run `exactdocs login {chosen_url}` "
                "or set EXACTDOCS_TOKEN"
            )
            raise ClientError(message)
        return cls(url=chosen_url, token=chosen_token)


def read_stored(path: Path) -> dict[str, str]:
    """Read the config file; a missing one is empty, an unreadable one is an error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        message = f"cannot read {path} ({exc.__class__.__name__}); fix it or run `exactdocs login`"
        raise ClientError(message) from None
    if not isinstance(data, dict):
        message = f"{path} is not a config file; remove it and run `exactdocs login`"
        raise ClientError(message)
    return {k: v for k, v in data.items() if isinstance(v, str)}


def store(path: Path, config: ClientConfig) -> None:
    """Write the credentials atomically; the file is created readable by its owner only."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"url": config.url, "token": config.token}, handle)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def forget(path: Path) -> bool:
    """Delete the stored credentials; whether there were any."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


# What the API's `error` codes mean to a person at a terminal. Anything else shows the server's
# own `detail`, which is already a sentence.
FRIENDLY: dict[str, str] = {
    "invalid_credentials": "wrong username or password",
    "unauthenticated": "the server did not accept the token (invalid, expired or revoked); "
    "run `exactdocs login` again",
    "setup_required": "that instance has no admin account yet; "
    "run `exactdocs admin create` on the server first",
    "too_many_tokens": "this account holds the most API tokens it may; "
    "revoke one in the web UI or log in with --token",
    "not_found": "the server has no such endpoint; is that URL an ExactDocs instance "
    "of a compatible version?",
}


class ApiError(ClientError):
    """The server answered with its error shape; ``code`` is the stable machine code."""

    def __init__(self, status: int, code: str, detail: str, fields: tuple[str, ...] = ()) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        text = FRIENDLY.get(code) or detail or f"the server answered HTTP {status}"
        if fields:
            text += f" (invalid: {', '.join(fields)})"
        super().__init__(text)


class ApiClient:
    """Async client for ``/api/v1``. Use as ``async with ApiClient(config) as api``.

    Raises ``ApiError`` for an error answer and ``ClientError`` for anything else that goes
    wrong on the way (unreachable, timeout, not an ExactDocs server). Redirects are never
    followed, so credentials cannot be passed on to another host. ``transport`` is for tests.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = normalize_url(url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx2.AsyncClient(
            base_url=self.url,
            headers=headers,
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:  # ruff: ignore[any-type]
        """Call ``/api/v1<path>``; return the decoded JSON body (``None`` for 204)."""
        try:
            response = await self._http.request(method, f"/api/v1{path}", **kwargs)
        except httpx2.TimeoutException:
            message = f"{self.url} did not answer within {TIMEOUT_SECONDS:g} seconds"
            raise ClientError(message) from None
        except httpx2.TransportError as exc:
            message = f"cannot reach {self.url} ({exc.__class__.__name__}); is the server running?"
            raise ClientError(message) from None
        if response.is_redirect:
            message = f"{self.url} redirected the request; use the URL it redirects to"
            raise ClientError(message)
        if response.status_code == httpx2.codes.NO_CONTENT:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_success and body is not None:
            return body
        if isinstance(body, dict) and isinstance(body.get("error"), str):
            fields = tuple(
                ".".join(str(part) for part in item["loc"][1:] or item["loc"])
                for item in body.get("fields", [])
                if isinstance(item, dict) and isinstance(item.get("loc"), list)
            )
            raise ApiError(response.status_code, body["error"], str(body.get("detail", "")), fields)
        message = f"{self.url} answered HTTP {response.status_code}; is it an ExactDocs server?"
        raise ClientError(message)

    async def login(self, username: str, password: str, name: str) -> dict[str, Any]:
        """Exchange credentials for a new named API token (``POST /tokens/login``)."""
        body = {"username": username, "password": password, "name": name}
        return await self.request("POST", "/tokens/login", json=body)

    async def check_token(self) -> None:
        """Raise ``ApiError`` unless the token this client holds is accepted."""
        await self.request("GET", "/libraries")
