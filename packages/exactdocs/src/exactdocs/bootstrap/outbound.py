"""Outbound connections behind a corporate proxy (#538): one resolution, applied to every client.

``outbound_network`` resolves the instance's proxy, ``NO_PROXY`` and CA bundle once (the kernel's
``resolve_outbound``: the standard variables, each replaced by its ``EXACTDOCS_`` setting when
one is set). Every client ExactDocs builds takes them from there, explicitly:

- the clients built on ``httpx2`` (the CLI's client, the sign-in providers' client, the AI
  profiles' clients) go through ``RoutedTransport``, which sends each request directly or
  through the proxy the resolution names for its URL, never reads the environment itself, and
  turns a failure on the way through a proxy into an error naming the proxy and the host;
- ``git`` gets the resolution as its environment (``GitCli.network``), the CA as
  ``GIT_SSL_CAINFO`` (git's ``http.sslCAInfo``);
- the Hugging Face Hub's client (``hub_client.py``), the index backends' clients and the
  OpenTelemetry exporter take the proxy and the CA bundle as their own options;
- the libraries that read only the environment (google-auth's token refresh, FastMCP's OAuth
  proxy, Chroma's and Elasticsearch's HTTP clients) see the same settings: ``publish`` writes
  the resolution into this process's standard variables when a server or a command starts.

``tls_verify`` gives every client the same trust: the CA bundle when one is configured (it
replaces the system's certificates, as ``SSL_CERT_FILE`` does), else each library's default.
Verification is never turned off.
"""

import os
import ssl
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

import httpx2

from exactdocs.bootstrap.constants import (
    DEFAULT_PORTS,
    OUTBOUND_OVERRIDES,
    PROXY_FAILURE_MARKERS,
)
from exactdocs_kernel import OutboundNetwork, proxy_failure, resolve_outbound

type Route = Callable[[str], str | None]
"""Gives the proxy a URL goes through, or ``None`` to connect directly."""


def resolve(
    environ: Mapping[str, str] = os.environ,
    *,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    no_proxy: str | None = None,
    ca_bundle: str | None = None,
) -> OutboundNetwork:
    """Resolve the outbound settings: the standard variables, each replaced by its override.

    Args:
        environ: The process environment.
        http_proxy: ``EXACTDOCS_HTTP_PROXY``: replaces ``HTTP_PROXY``.
        https_proxy: ``EXACTDOCS_HTTPS_PROXY``: replaces ``HTTPS_PROXY``.
        no_proxy: ``EXACTDOCS_NO_PROXY``: replaces ``NO_PROXY``.
        ca_bundle: ``EXACTDOCS_CA_BUNDLE``: replaces ``SSL_CERT_FILE`` and the like.

    Returns:
        The settings every outbound client uses.

    Raises:
        ValueError: A proxy is not a usable URL (named without its credentials), or the CA
            bundle is not a readable file.
    """
    network = resolve_outbound(
        environ, http_proxy=http_proxy, https_proxy=https_proxy, no_proxy=no_proxy,
        ca_bundle=ca_bundle,
    )  # fmt: skip
    if network.ca_bundle is not None and not _readable(network.ca_bundle):
        message = (
            f"the CA bundle {network.ca_bundle} (EXACTDOCS_CA_BUNDLE, SSL_CERT_FILE, "
            "REQUESTS_CA_BUNDLE or CURL_CA_BUNDLE) is not a readable file"
        )
        raise ValueError(message)
    return network


def from_environment(environ: Mapping[str, str] = os.environ) -> OutboundNetwork:
    """Resolve the outbound settings from the environment alone, overrides included.

    For the command line's client, which reads no server settings: the ``EXACTDOCS_`` overrides
    come from the same environment.

    Args:
        environ: The process environment.

    Returns:
        The settings (``resolve`` raises ``ValueError`` for an unusable proxy or CA bundle).
    """
    overrides = {name: environ.get(variable) for name, variable in OUTBOUND_OVERRIDES.items()}
    return resolve(environ, **overrides)


def _readable(path: str) -> bool:
    """Whether a file exists and this process can read it.

    Args:
        path: The path.

    Returns:
        True when it can be opened for reading.
    """
    try:
        with Path(path).open("rb"):
            return True
    except OSError:
        return False


def tls_verify(network: OutboundNetwork) -> ssl.SSLContext | bool:
    """What a client verifies TLS with: the CA bundle, or the library's own default.

    Args:
        network: The outbound settings.

    Returns:
        A context trusting exactly the bundle's certificates, or ``True`` (verify, with the
        library's default trust) when no bundle is configured. Never ``False``.
    """
    return network.tls_context() or True


def publish(network: OutboundNetwork, environ: MutableMapping[str, str] = os.environ) -> None:
    """Write the resolution into the standard variables, for libraries that read only them.

    Called once when the command line starts (``cli.main``), so an ``EXACTDOCS_`` override
    reaches them too, in the server's worker processes as well (they inherit the environment).
    Variables the resolution leaves unset are left as they are.

    Args:
        network: The outbound settings.
        environ: The environment to write (the process's own by default).
    """
    environ.update(network.environment())


def describe(network: OutboundNetwork) -> str:
    """Summarize the outbound settings for a log line, without credentials.

    Args:
        network: The outbound settings.

    Returns:
        The proxies, the exceptions and the CA bundle.
    """
    shown = repr(network).removeprefix("OutboundNetwork(").removesuffix(")")
    return shown.replace("=None", " unset")


@dataclass(frozen=True, slots=True, kw_only=True)
class RoutedTransport(httpx2.AsyncBaseTransport):
    """An ``httpx2`` transport that sends each request directly or through its URL's proxy.

    One inner transport per proxy (and one direct), made on first use, none reading the
    environment. A failure on the way through a proxy (the proxy refused the tunnel, wanted
    credentials, could not be reached, or TLS failed through it) is raised as the same
    ``httpx2`` error class with a message naming the proxy and the host.
    """

    route: Route
    """Which proxy a URL goes through; ``None``: directly."""
    verify: ssl.SSLContext | bool = True
    """The TLS trust of every connection (``tls_verify``)."""
    retries: int = 0
    """Connection retries of each inner transport."""
    redact: Callable[[str], str] = str
    """Removes secrets from a failure's text before it is put in a message."""
    _inner: dict[str | None, httpx2.AsyncHTTPTransport] = field(
        default_factory=dict, init=False, repr=False
    )
    """The transport of each proxy, ``None`` for the direct one."""

    def _transport(self, proxy: str | None) -> httpx2.AsyncHTTPTransport:
        """Return the inner transport of a proxy, made on first use.

        Args:
            proxy: The proxy, or ``None`` for direct connections.

        Returns:
            The transport.
        """
        found = self._inner.get(proxy)
        if found is None:
            found = self._inner[proxy] = httpx2.AsyncHTTPTransport(
                proxy=proxy, verify=self.verify, retries=self.retries, trust_env=False
            )
        return found

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Send the request directly or through its proxy.

        Args:
            request: The request.

        Returns:
            The response.

        Raises:
            httpx2.ProxyError: The proxy refused the tunnel or wants credentials (for a plain
                ``http://`` URL too, which a proxy answers with 407).
            httpx2.ConnectError: The proxy could not be reached, or TLS failed through it.
            httpx2.ConnectTimeout: The proxy did not answer in time.
        """
        proxy = self.route(str(request.url))
        port = request.url.port or DEFAULT_PORTS.get(request.url.scheme, DEFAULT_PORTS["http"])
        target = f"{request.url.host}:{port}"
        try:
            response = await self._transport(proxy).handle_async_request(request)
        except (httpx2.ProxyError, httpx2.ConnectError, httpx2.ConnectTimeout) as error:
            if proxy is None:
                raise
            message = proxy_failure(proxy, target, self.redact(str(error)))
            raise type(error)(message, request=request) from error
        if proxy is not None and response.status_code == HTTPStatus.PROXY_AUTHENTICATION_REQUIRED:
            await response.aclose()
            message = proxy_failure(proxy, target, "407 Proxy Authentication Required")
            raise httpx2.ProxyError(message, request=request)
        return response

    async def aclose(self) -> None:
        """Close every inner transport."""
        inner = list(self._inner.values())
        self._inner.clear()
        for transport in inner:
            await transport.aclose()


def proxy_cause(error: BaseException) -> str | None:
    """Find, along an error's causes, the one that names a proxy and a host.

    An SDK wraps a transport's error in its own ("Connection error."); the error a
    ``RoutedTransport`` raised is still its cause.

    Args:
        error: What a call raised.

    Returns:
        That error's message, or ``None`` when no proxy was on the way.
    """
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if any(marker in str(cause) for marker in PROXY_FAILURE_MARKERS):
            return str(cause)
        cause = cause.__cause__ or cause.__context__
    return None


def routed_transport(network: OutboundNetwork, *, retries: int = 0) -> RoutedTransport:
    """The transport of a client that follows the instance's proxy settings.

    Args:
        network: The outbound settings.
        retries: Connection retries.

    Returns:
        The transport.
    """
    return RoutedTransport(
        route=network.proxy_for,
        verify=tls_verify(network),
        retries=retries,
        redact=network.redact,
    )
