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
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import httpx2
from platformdirs import user_config_path

URL_VARIABLE = "EXACTDOCS_URL"
TOKEN_VARIABLE = "EXACTDOCS_TOKEN"  # ruff: ignore[hardcoded-password-string] (a variable name, not a secret)
CONFIG_FILE_VARIABLE = "EXACTDOCS_CONFIG_FILE"
DEFAULT_PORTS = {"http": 80, "https": 443}
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
    """Return the canonical form of a server URL, or raise ``ClientError`` if it is not one.

    Scheme and host are lowercased, the host is IDNA-encoded, a default port and a trailing slash
    are dropped, so two spellings of one server compare equal (a stored token is matched by URL).
    Plain ``http`` is accepted for loopback only: the token and the password would cross the
    network in the clear otherwise.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        message = (
            f"{url!r} is not a server URL; use http(s)://host[:port], e.g. https://docs.example.com"
        )
        raise ClientError(message)
    if parts.username or parts.password or parts.query or parts.fragment:
        message = "the server URL must not hold credentials, a query or a fragment"
        raise ClientError(message)
    scheme = parts.scheme.lower()
    try:
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port
    except UnicodeError, ValueError:
        message = f"{url!r} is not a server URL (bad host or port)"
        raise ClientError(message) from None
    if scheme == "http" and not _is_loopback(host):
        message = (
            f"refusing to send credentials over plain http to {host}; "
            "use an https:// URL (plain http is only allowed for localhost)"
        )
        raise ClientError(message)
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{parts.path.rstrip('/')}"


def is_loopback_url(url: str) -> bool:
    """Whether a (normalized) URL points at this machine."""
    return _is_loopback(urlsplit(url).hostname or "")


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
        chosen_url = resolve_url(url=url, env=env)
        stored = read_stored(config_path(env))
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


def resolve_url(*, url: str | None = None, env: Mapping[str, str] = os.environ) -> str:
    """Return the server for a command that signs in with a password (no stored token needed)."""
    chosen = url or env.get(URL_VARIABLE) or read_stored(config_path(env)).get("url")
    if not chosen:
        message = "no server configured; run `exactdocs login <url>` or set EXACTDOCS_URL"
        raise ClientError(message)
    return normalize_url(chosen)


def read_stored(path: Path) -> dict[str, str]:
    """Read the config file; a missing one is empty, an unreadable one is an error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if os.name == "posix" and path.stat().st_mode & 0o077:
            sys.stderr.write(f"exactdocs: warning: {path} is readable by others; run chmod 600\n")
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
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    temporary = Path(name)  # mkstemp creates it 0600 and uniquely
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"url": config.url, "token": config.token}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        message = f"cannot write {path} ({exc.__class__.__name__})"
        raise ClientError(message) from None
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


def printable(text: str) -> str:
    """Drop control characters (a hostile server could send terminal escape sequences)."""
    return "".join(c for c in text if c.isprintable())


class ApiError(ClientError):
    """The server answered with its error shape; ``code`` is the stable machine code."""

    def __init__(self, status: int, code: str, detail: str, fields: tuple[str, ...] = ()) -> None:
        self.status = status
        self.code = code
        self.detail = printable(detail)
        text = FRIENDLY.get(code) or self.detail or f"the server answered HTTP {status}"
        if fields:
            text += f" (invalid: {printable(', '.join(fields))})"
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
            # Proxy variables are honoured for remote servers, but never for loopback: a proxy
            # must not see a plain-http password or token.
            trust_env=not is_loopback_url(self.url),
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

    async def login(
        self, username: str, password: str, name: str, expires_at: datetime | None = None
    ) -> dict[str, Any]:
        """Exchange credentials for a new named API token (``POST /tokens/login``)."""
        body = {"username": username, "password": password, "name": name}
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        return await self.request("POST", "/tokens/login", json=body)

    async def check_token(self) -> None:
        """Raise ``ApiError`` unless the token this client holds is accepted."""
        await self.request("GET", "/libraries")

    async def sign_in(self, username: str, password: str) -> None:
        """Start a browser-style session (``POST /session``); the client keeps its cookie.

        What a token cannot do (manage tokens, set a repository credential) needs a session.
        """
        await self.request("POST", "/session", json={"username": username, "password": password})

    async def sign_out(self) -> None:
        """End the session (``DELETE /session``); a failure is a warning, not an error."""
        try:
            await self.request("DELETE", "/session")
        except ClientError:
            sys.stderr.write(
                "exactdocs: warning: could not end the session; it expires on its own\n"
            )
