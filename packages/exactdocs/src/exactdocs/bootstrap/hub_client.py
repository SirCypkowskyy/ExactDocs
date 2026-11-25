"""The Hugging Face Hub's HTTP client behind the instance's proxy (#538), for ``models pull`` only.

``huggingface_hub`` makes its requests through one shared ``httpx.Client`` (``set_client_factory``
replaces it). The one built here sends each request directly or through the proxy the outbound
settings name for its URL (the Hub, then the CDN its downloads redirect to), trusts the CA bundle
when one is configured, reads nothing from the environment, and names the proxy and the host when
a connection through the proxy fails. With a proxy or a CA bundle configured, the Hub's Xet
transfers (a native client with its own network stack) are turned off for the pull, so every
byte goes through this client.

Imported only by ``models_pull.hub_download``: ``httpx`` and the Hub come with the ``[local]``
extra.
"""

import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

import httpx
from huggingface_hub import constants, set_client_factory

from exactdocs.bootstrap.constants import DEFAULT_PORTS, HUB_TIMEOUT_SECONDS
from exactdocs_kernel import OutboundNetwork, proxy_failure


@dataclass(frozen=True, slots=True, kw_only=True)
class HubTransport(httpx.BaseTransport):
    """A sync ``httpx`` transport that sends each request directly or through its URL's proxy."""

    network: OutboundNetwork
    """The outbound settings."""
    verify: ssl.SSLContext | bool = True
    """The TLS trust of every connection."""
    _inner: dict[str | None, httpx.HTTPTransport] = field(
        default_factory=dict, init=False, repr=False
    )
    """The transport of each proxy, ``None`` for the direct one."""

    def _transport(self, proxy: str | None) -> httpx.HTTPTransport:
        """Return the inner transport of a proxy, made on first use.

        Args:
            proxy: The proxy, or ``None`` for direct connections.

        Returns:
            The transport.
        """
        found = self._inner.get(proxy)
        if found is None:
            found = self._inner[proxy] = httpx.HTTPTransport(
                proxy=proxy, verify=self.verify, trust_env=False
            )
        return found

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request directly or through its proxy.

        Args:
            request: The request.

        Returns:
            The response.

        Raises:
            httpx.ProxyError: The proxy refused the tunnel or wants credentials.
            httpx.ConnectError: The proxy could not be reached, or TLS failed through it.
            httpx.ConnectTimeout: The proxy did not answer in time.
        """
        proxy = self.network.proxy_for(str(request.url))
        port = request.url.port or DEFAULT_PORTS.get(request.url.scheme, DEFAULT_PORTS["http"])
        target = f"{request.url.host}:{port}"
        try:
            response = self._transport(proxy).handle_request(request)
        except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as error:
            if proxy is None:
                raise
            message = proxy_failure(proxy, target, self.network.redact(str(error)))
            raise type(error)(message, request=request) from error
        if proxy is not None and response.status_code == HTTPStatus.PROXY_AUTHENTICATION_REQUIRED:
            response.close()
            message = proxy_failure(proxy, target, "407 Proxy Authentication Required")
            raise httpx.ProxyError(message, request=request)
        return response

    def close(self) -> None:
        """Close every inner transport."""
        inner = list(self._inner.values())
        self._inner.clear()
        for transport in inner:
            transport.close()


def hub_client_factory(
    network: OutboundNetwork, *, verify: ssl.SSLContext | bool
) -> Callable[[], httpx.Client]:
    """Make the factory of the Hub's shared client.

    Args:
        network: The outbound settings.
        verify: The TLS trust (``outbound.tls_verify``).

    Returns:
        What builds the client: redirects followed (downloads go to the CDN), a timeout per
        read (the Hub sets its own on most calls), this module's transport.
    """

    def client() -> httpx.Client:
        """Build the Hub's shared client.

        Returns:
            The client.
        """
        transport = HubTransport(network=network, verify=verify)
        timeout = httpx.Timeout(HUB_TIMEOUT_SECONDS)
        return httpx.Client(transport=transport, follow_redirects=True, timeout=timeout)

    return client


def use_outbound(network: OutboundNetwork, *, verify: ssl.SSLContext | bool) -> None:
    """Make every request of ``huggingface_hub`` in this process follow the outbound settings.

    Args:
        network: The outbound settings.
        verify: The TLS trust (``outbound.tls_verify``).
    """
    set_client_factory(hub_client_factory(network, verify=verify))
    if network.proxied or network.ca_bundle is not None:
        hub_constants: Any = constants  # read by the Hub at each download, not only at import
        hub_constants.HF_HUB_DISABLE_XET = True


def as_os_error[T](call: Callable[[], T]) -> T:
    """Run a download; an ``httpx`` error comes out as an ``OSError`` (as the Hub's own do).

    Args:
        call: The download.

    Returns:
        What it returned.

    Raises:
        OSError: The download failed on the network; the cause keeps the original error.
    """
    try:
        return call()
    except httpx.HTTPError as error:
        raise OSError(str(error)) from error
