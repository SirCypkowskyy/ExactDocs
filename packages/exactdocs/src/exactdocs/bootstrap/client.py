"""What the command line needs to be a client of the REST API: stored credentials and the client.

The client-side commands (``login``, and later the library and token commands) never open the
database: they go through ``ApiClient``, so they work against any instance. Nothing here imports
the container, the settings of the server or a domain.

Where the server and the token come from, strongest first: command-line flag, then
``EXACTDOCS_URL`` / ``EXACTDOCS_TOKEN``, then the config file (``EXACTDOCS_CLIENT_CONFIG``, else
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

from exactdocs.bootstrap.constants import (
    CONFIG_FILE_VARIABLE,
    DEFAULT_PORTS,
    FRIENDLY,
    MAX_TOKEN_NAME_LENGTH,
    PROXY_FAILURE_MARKERS,
    TIMEOUT_SECONDS,
    TOKEN_VARIABLE,
    URL_VARIABLE,
)
from exactdocs.bootstrap.outbound import from_environment, routed_transport


class ClientError(Exception):
    """Something the user can fix; ``str(error)`` is the whole message, safe to print."""


class ClientTimeoutError(ClientError):
    """The server did not answer in time; it may still be doing what it was asked."""


def config_path(env: Mapping[str, str] = os.environ) -> Path:
    """Return the credentials file: ``EXACTDOCS_CLIENT_CONFIG`` or the user config dir's file.

    Args:
        env: The environment to read ``EXACTDOCS_CLIENT_CONFIG`` from.

    Returns:
        The file's path (it may not exist).
    """
    if override := env.get(CONFIG_FILE_VARIABLE):
        return Path(override)
    return user_config_path("exactdocs", appauthor=False) / "config.json"


def machine_name() -> str:
    """Return the default token name: this machine's hostname.

    Returns:
        The hostname, cut to ``MAX_TOKEN_NAME_LENGTH`` (``exactdocs-cli`` when there is none).
    """
    return (socket.gethostname() or "exactdocs-cli")[:MAX_TOKEN_NAME_LENGTH]


def normalize_url(url: str) -> str:
    """Return the canonical form of a server URL, or raise ``ClientError`` if it is not one.

    Scheme and host are lowercased, the host is IDNA-encoded, a default port and a trailing slash
    are dropped, so two spellings of one server compare equal (a stored token is matched by URL).
    Plain ``http`` is accepted for loopback only: the token and the password would cross the
    network in the clear otherwise.

    Args:
        url: The URL as the user typed it.

    Returns:
        The canonical URL.

    Raises:
        ClientError: It is not an http(s) URL with a host, it holds credentials, a query or a
            fragment, its host or port is malformed, or it is plain http to another machine.
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
    """Whether a (normalized) URL points at this machine.

    Args:
        url: The URL.

    Returns:
        ``True`` for ``localhost`` or a loopback address.
    """
    return _is_loopback(urlsplit(url).hostname or "")


def _is_loopback(host: str) -> bool:
    """Whether a host name is this machine.

    Args:
        host: The host name or IP address.

    Returns:
        ``True`` for ``localhost`` or a loopback address.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True, kw_only=True)
class ClientConfig:
    """The server to talk to and the API token to do it with (never shown in a repr)."""

    url: str
    """The server's normalized URL."""
    token: str = field(repr=False)
    """The API token; kept out of ``repr``."""

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

        Args:
            url: The ``--url`` flag, if given.
            token: The ``--token`` flag, if given.
            env: The environment, for ``EXACTDOCS_URL``, ``EXACTDOCS_TOKEN`` and the config file.

        Returns:
            The server and its token.

        Raises:
            ClientError: No token is known for the chosen server.
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
    """Return the server for a command that signs in with a password (no stored token needed).

    Args:
        url: The ``--url`` flag, if given.
        env: The environment, for ``EXACTDOCS_URL`` and the config file.

    Returns:
        The normalized URL: the flag's, else the environment's, else the stored one.

    Raises:
        ClientError: No server is configured.
    """
    chosen = url or env.get(URL_VARIABLE) or read_stored(config_path(env)).get("url")
    if not chosen:
        message = "no server configured; run `exactdocs login <url>` or set EXACTDOCS_URL"
        raise ClientError(message)
    return normalize_url(chosen)


def read_stored(path: Path) -> dict[str, str]:
    """Read the config file; a missing one is empty, an unreadable one is an error.

    Args:
        path: The config file.

    Returns:
        Its text entries (``url``, ``token``); empty when the file does not exist.

    Raises:
        ClientError: The file cannot be read or is not a JSON object.
    """
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
    """Write the credentials atomically; the file is created readable by its owner only.

    Args:
        path: The config file.
        config: The server and token to store.

    Raises:
        ClientError: The file cannot be written.
    """
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
    """Delete the stored credentials; whether there were any.

    Args:
        path: The config file.

    Returns:
        ``True`` when a file was deleted.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def printable(text: str) -> str:
    """Drop control characters (a hostile server could send terminal escape sequences).

    Args:
        text: Text from the server.

    Returns:
        The text with only printable characters.
    """
    return "".join(c for c in text if c.isprintable())


def printable_text(text: str) -> str:
    """Like ``printable`` for a multi-line text: newlines and tabs stay (docs are read as text).

    Args:
        text: Text from the server.

    Returns:
        The text with only printable characters, newlines and tabs.
    """
    return "".join(c for c in text if c in "\n\t" or c.isprintable())


class ApiError(ClientError):
    """The server answered with its error shape; ``code`` is the stable machine code."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        fields: tuple[str, ...] = (),
        retry_after: int | None = None,
    ) -> None:
        """Build the message to print from the server's error.

        Args:
            status: The HTTP status.
            code: The stable machine code (``ErrorResponse.error``).
            detail: The server's message.
            fields: The invalid request fields, as dotted paths.
            retry_after: Seconds to wait before trying again, when the server said.
        """
        self.status = status
        self.code = code
        self.detail = printable(detail)
        self.retry_after = retry_after
        text = FRIENDLY.get(code) or self.detail or f"the server answered HTTP {status}"
        if retry_after is not None:
            text += f" (in {retry_after} seconds)"
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
        """Prepare the HTTP client; nothing is sent yet.

        Args:
            url: The server URL (normalized here).
            token: The API token to send as a bearer token, if any.
            transport: An HTTP transport to use instead of the network (tests).

        Raises:
            ClientError: A proxy or the CA bundle of the outbound settings is unusable.
        """
        self.url = normalize_url(url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if transport is None:
            # The outbound settings (#538): HTTP(S)_PROXY, NO_PROXY and the CA bundle, or their
            # EXACTDOCS_ overrides. Loopback never goes through a proxy: a proxy must not see a
            # plain-http password or token.
            try:
                transport = routed_transport(from_environment())
            except ValueError as error:
                raise ClientError(str(error)) from None
        self._http = httpx2.AsyncClient(
            base_url=self.url,
            headers=headers,
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self) -> Self:
        """Enter the client's context.

        Returns:
            This client.
        """
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the HTTP connections.

        Args:
            *_: The exception, if any (unused).
        """
        await self._http.aclose()

    async def _send(
        self,
        method: str,
        path: str,
        *,
        read_timeout: float | None = None,
        **kwargs: Any,  # ruff: ignore[any-type]
    ) -> httpx2.Response:
        """Send one request to ``/api/v1<path>``.

        Args:
            method: The HTTP method.
            path: The path under ``/api/v1``.
            read_timeout: Seconds to wait for the answer once the request is sent, for a call
                whose work grows with its input; ``TIMEOUT_SECONDS`` when None. Connecting
                and sending keep ``TIMEOUT_SECONDS``.
            **kwargs: Passed on to ``httpx2.AsyncClient.request``.

        Returns:
            The response, whatever its status.

        Raises:
            ClientTimeoutError: The server did not answer in time.
            ClientError: The server cannot be reached, or redirected the request.
        """
        waits = TIMEOUT_SECONDS if read_timeout is None else read_timeout
        try:
            response = await self._http.request(
                method,
                f"/api/v1{path}",
                timeout=httpx2.Timeout(TIMEOUT_SECONDS, read=waits),
                **kwargs,
            )
        except httpx2.TimeoutException:
            message = f"{self.url} did not answer within {waits:g} seconds"
            raise ClientTimeoutError(message) from None
        except httpx2.TransportError as exc:
            if any(marker in str(exc) for marker in PROXY_FAILURE_MARKERS):
                message = f"cannot reach {self.url}: {exc}"  # names the proxy and the host
            else:
                message = (
                    f"cannot reach {self.url} ({exc.__class__.__name__}); is the server running?"
                )
            raise ClientError(message) from None
        if response.is_redirect:
            message = f"{self.url} redirected the request; use the URL it redirects to"
            raise ClientError(message)
        return response

    def _error(self, response: httpx2.Response, body: object) -> ClientError:
        """Turn an error answer into the exception to raise.

        Args:
            response: The response.
            body: Its decoded JSON body, or ``None``.

        Returns:
            An ``ApiError`` for the API's error shape, a ``ClientError`` for anything else.
        """
        if isinstance(body, dict) and isinstance(body.get("error"), str):
            fields = tuple(
                ".".join(str(part) for part in item["loc"][1:] or item["loc"])
                for item in body.get("fields", [])
                if isinstance(item, dict) and isinstance(item.get("loc"), list)
            )
            retry_after = response.headers.get("retry-after", "")
            return ApiError(
                response.status_code,
                body["error"],
                str(body.get("detail", "")),
                fields,
                int(retry_after) if retry_after.isdecimal() else None,
            )
        message = f"{self.url} answered HTTP {response.status_code}; is it an ExactDocs server?"
        return ClientError(message)

    async def request(
        self,
        method: str,
        path: str,
        *,
        read_timeout: float | None = None,
        **kwargs: Any,  # ruff: ignore[any-type]
    ) -> Any:  # ruff: ignore[any-type]
        """Call ``/api/v1<path>``; return the decoded JSON body (``None`` for 204).

        An error answer raises ``ApiError`` (``ClientError`` when it is not the API's error
        shape), as does anything that goes wrong on the way.

        Args:
            method: The HTTP method.
            path: The path under ``/api/v1``.
            read_timeout: Seconds to wait for the answer; ``TIMEOUT_SECONDS`` when None.
            **kwargs: Passed on to ``httpx2.AsyncClient.request`` (e.g. ``json``, ``params``).

        Returns:
            The decoded JSON body, or ``None`` for 204.
        """
        response = await self._send(method, path, read_timeout=read_timeout, **kwargs)
        if response.status_code == httpx2.codes.NO_CONTENT:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_success and body is not None:
            return body
        raise self._error(response, body)

    async def request_text(self, method: str, path: str, **kwargs: Any) -> str:  # ruff: ignore[any-type]
        """Call ``/api/v1<path>``; return a ``text/*`` success body (errors are JSON as usual).

        Args:
            method: The HTTP method.
            path: The path under ``/api/v1``.
            **kwargs: Passed on to ``httpx2.AsyncClient.request``.

        Returns:
            The body's text.

        Raises:
            ClientError: A success answer is not text. An error answer raises ``ApiError`` as
                ``request`` does.
        """
        response = await self._send(method, path, **kwargs)
        content_type = response.headers.get("content-type", "")
        if response.is_success and content_type.startswith("text/"):
            return response.text
        if response.is_success:
            message = f"{self.url} answered HTTP {response.status_code}; expected a text body"
            raise ClientError(message + " (is it an older ExactDocs server?)")
        try:
            body = response.json()
        except ValueError:
            body = None
        raise self._error(response, body)

    async def login(
        self,
        username: str,
        password: str,
        name: str,
        expires_at: datetime | None = None,
        *,
        library_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Exchange credentials for a new named API token (``POST /tokens/login``).

        Args:
            username: The account's username.
            password: Its password.
            name: The new token's name.
            expires_at: When the token expires; never when ``None``.
            library_ids: Selected libraries; ``None`` leaves user access unrestricted.

        Returns:
            The decoded ``TokenGrant``, with the secret.
        """
        body: dict[str, Any] = {"username": username, "password": password, "name": name}
        if library_ids is not None:
            body["library_ids"] = library_ids
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        return await self.request("POST", "/tokens/login", json=body)

    async def check_token(self) -> None:
        """Raise ``ApiError`` unless the token this client holds is accepted."""
        await self.request("GET", "/libraries")

    async def sign_in(self, username: str, password: str) -> None:
        """Start a browser-style session (``POST /session``); the client keeps its cookie.

        What a token cannot do (manage tokens, set a repository credential) needs a session.

        Args:
            username: The account's username.
            password: Its password.
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
