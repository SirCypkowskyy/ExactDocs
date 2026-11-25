"""Outbound network settings (#538): which proxy a connection goes through, and which CA it trusts.

One resolution for every outbound client. ``resolve_outbound`` reads the standard variables
(``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY`` and ``NO_PROXY``, lower case winning over upper
case as in curl, ``urllib`` and ``requests``; the CA bundle from ``SSL_CERT_FILE``, then
``REQUESTS_CA_BUNDLE``, then ``CURL_CA_BUNDLE``), each of which an override replaces (bootstrap
passes ``EXACTDOCS_HTTPS_PROXY`` and the like). ``OutboundNetwork.proxy_for`` then answers, for
one URL, which proxy carries it. Clients are configured from it explicitly; a child process (git)
and the libraries that read only the environment get ``OutboundNetwork.environment()``.

``NO_PROXY`` holds comma- or space-separated entries:

- ``*`` alone: no host goes through the proxy;
- a host name matches itself and every name under it (``example.com``, ``.example.com`` and
  ``*.example.com`` all match ``example.com`` and ``docs.example.com``, as in curl);
- an IP address matches itself, a CIDR range (``10.0.0.0/8``, ``fd00::/8``) every address in it.
  A host name is never resolved to be compared: a range matches only URLs that name an address;
- any entry may end in ``:port`` (``[v6]:port`` for an IPv6 address), and then matches that port
  only.

Loopback (``localhost``, names under ``.localhost``, ``127.0.0.0/8``, ``::1``), link-local and
unspecified addresses (``169.254.0.0/16``, ``fe80::/10``: the cloud metadata endpoints) and
``metadata.google.internal`` never go through a proxy, whatever ``NO_PROXY`` says: a proxy cannot
reach this machine, and would answer for its own identity instead of ours.

Proxy URLs may carry credentials (``http://user:password@proxy:3128``). They are never shown:
``repr``, ``redact`` and ``redact_url`` replace them with ``***``.
"""

import ipaddress
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from exactdocs_kernel.constants import (
    _ALWAYS_DIRECT_NAMES,
    _ALWAYS_DIRECT_SUFFIX,
    _DEFAULT_PORTS,
    _MIN_SECRET,
    _PROXY_AUTH_MARKERS,
    _PROXY_REFUSED_MARKERS,
    _PROXY_SCHEMES,
    _PUBLISHED_DIRECT,
    _SCHEME_PROXY,
    _TLS_MARKERS,
    _URL_USERINFO,
    CA_BUNDLE_VARIABLES,
    REDACTED,
)

type _Address = ipaddress.IPv4Address | ipaddress.IPv6Address
"""An IP address of either family."""
type _Network = ipaddress.IPv4Network | ipaddress.IPv6Network
"""An IP range of either family."""


def redact_url(text: str) -> str:
    """Replace the credentials of every URL in a text with ``***``.

    Args:
        text: A URL, or any text that may hold URLs (an error message).

    Returns:
        The text, each ``scheme://user:password@`` shown as ``scheme://***@``.
    """
    return _URL_USERINFO.sub(rf"\g<scheme>{REDACTED}@", text)


def proxy_failure(proxy: str, target: str, detail: str) -> str:
    """Say that a connection through a proxy failed, naming the proxy and the host it was for.

    Args:
        proxy: The proxy URL (its credentials are never shown).
        target: The host (``host`` or ``host:port``) the connection was for.
        detail: What the client reported: a status line, an OS or TLS error. It must hold no
            secret (``OutboundNetwork.redact`` it first).

    Returns:
        The message: credentials the proxy asked for, a TLS failure, or the connection failing.
    """
    shown, detail = redact_url(proxy), redact_url(detail.strip()) or "no answer"
    lowered = detail.lower()
    if any(marker in lowered for marker in _PROXY_AUTH_MARKERS):
        return (
            f"the proxy {shown} wants credentials to reach {target} ({detail}): give them in the "
            "proxy URL, http://user:password@host:port"
        )
    if any(marker in lowered for marker in _TLS_MARKERS):
        return (
            f"TLS failed reaching {target} through the proxy {shown} ({detail}): a proxy that "
            "re-signs TLS needs its CA in the CA bundle (EXACTDOCS_CA_BUNDLE or SSL_CERT_FILE)"
        )
    if any(marker in lowered for marker in _PROXY_REFUSED_MARKERS):
        return f"the proxy {shown} refused the connection to {target} ({detail})"
    return f"could not reach {target} through the proxy {shown} ({detail})"


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboundNetwork:
    """The resolved outbound settings: the proxy of each scheme, the exceptions, the CA bundle.

    The default (no proxy, no exceptions, no CA bundle) connects directly and trusts the system's
    certificates: what every client did before a proxy was configured.
    """

    http_proxy: str | None = None
    """The proxy of ``http://`` URLs, credentials included; ``None``: direct."""
    https_proxy: str | None = None
    """The proxy of ``https://`` URLs (``CONNECT``), credentials included; ``None``: direct."""
    no_proxy: tuple[str, ...] = ()
    """The ``NO_PROXY`` entries, lower case: the hosts, domains, addresses and ranges reached
    directly."""
    ca_bundle: str | None = None
    """A PEM file of the certificates TLS connections trust instead of the system's (a company CA
    that a proxy re-signs with); ``None``: the system's."""

    def __post_init__(self) -> None:
        """Refuse a proxy that is not a URL a client can use.

        Raises:
            ValueError: A proxy is not ``http(s)://`` or ``socks5://`` with a host, or its port
                is invalid. The message never repeats its credentials.
        """
        for name, value in (("http_proxy", self.http_proxy), ("https_proxy", self.https_proxy)):
            if value is not None and not _usable_proxy(value):
                message = (
                    f"{name} {redact_url(value)!r} is not a proxy URL: use "
                    "http://host:port (or https://, socks5://), credentials as user:password@"
                )
                raise ValueError(message)

    def __repr__(self) -> str:
        """Show the settings with the proxies' credentials replaced.

        Returns:
            The representation.
        """
        shown = ", ".join(
            f"{name}={value!r}"
            for name, value in (
                ("http_proxy", None if self.http_proxy is None else redact_url(self.http_proxy)),
                ("https_proxy", None if self.https_proxy is None else redact_url(self.https_proxy)),
                ("no_proxy", self.no_proxy),
                ("ca_bundle", self.ca_bundle),
            )
        )
        return f"OutboundNetwork({shown})"

    @property
    def proxied(self) -> bool:
        """Whether any scheme goes through a proxy."""
        return self.http_proxy is not None or self.https_proxy is not None

    def proxy_for(self, url: str) -> str | None:
        """Return the proxy a request to this URL goes through.

        Args:
            url: The URL to reach.

        Returns:
            The proxy URL (with its credentials), or ``None`` to connect directly: no proxy for
            the scheme (only ``http``/``ws`` and ``https``/``wss`` use one), a host ``NO_PROXY``
            lists, loopback, link-local, or a URL that cannot be read.
        """
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError:
            return None
        scheme = parts.scheme.lower()
        match _SCHEME_PROXY.get(scheme):
            case "http":
                proxy = self.http_proxy
            case "https":
                proxy = self.https_proxy
            case _:
                proxy = None
        if proxy is None or self.bypasses(parts.hostname or "", port or _DEFAULT_PORTS[scheme]):
            return None
        return proxy

    def bypasses(self, host: str, port: int | None = None) -> bool:
        """Whether a host is reached directly, whatever the scheme.

        Args:
            host: A host name or IP address (brackets around an IPv6 address are fine).
            port: The port connected to, for ``NO_PROXY`` entries that name one.

        Returns:
            True for an empty host, loopback, link-local, the metadata server, and every host a
            ``NO_PROXY`` entry matches.
        """
        name = host.strip().removeprefix("[").removesuffix("]").rstrip(".").lower()
        if not name or _always_direct(name):
            return True
        return any(_matches(entry, name, port) for entry in self.no_proxy)

    def tls_context(self) -> ssl.SSLContext | None:
        """A TLS context that trusts exactly the CA bundle's certificates.

        Returns:
            The context (verification on, host names checked), or ``None`` when no bundle is
            configured: the client keeps its own default trust. Verification is never off.
        """
        if self.ca_bundle is None:
            return None
        return ssl.create_default_context(cafile=self.ca_bundle)

    def via(self, url: str) -> str:
        """Say how a URL is reached, for a log line or an error.

        Args:
            url: The URL.

        Returns:
            ``through the proxy <url without credentials>`` or ``directly``.
        """
        proxy = self.proxy_for(url)
        return "directly" if proxy is None else f"through the proxy {redact_url(proxy)}"

    def environment(self) -> dict[str, str]:
        """The standard variables that say the same, for a child process or an env-only library.

        Both spellings of each proxy variable are set (curl reads only ``http_proxy`` in lower
        case). ``NO_PROXY`` gets loopback and link-local added, domains without a leading
        ``*.``/``.`` (every client reads a bare domain as itself and the names under it).

        Returns:
            The variables: none at all for the default settings.
        """
        found: dict[str, str] = {}
        for variable, value in (("http_proxy", self.http_proxy), ("https_proxy", self.https_proxy)):
            if value is not None:
                found[variable] = found[variable.upper()] = value
        if found:
            entries = [_published(entry) for entry in self.no_proxy]
            direct = ",".join(dict.fromkeys([*entries, *_PUBLISHED_DIRECT]))
            found["no_proxy"] = found["NO_PROXY"] = direct
        if self.ca_bundle is not None:
            found.update(dict.fromkeys(CA_BUNDLE_VARIABLES, self.ca_bundle))
        return found

    def redact(self, text: str) -> str:
        """Remove the proxies' credentials from a text, wherever they appear in it.

        Args:
            text: A message (a library's error, a child process's output).

        Returns:
            The text with every URL's credentials, and the proxies' passwords on their own,
            replaced with ``***``.
        """
        for proxy in (self.http_proxy, self.https_proxy):
            for secret in _secrets(proxy):
                text = text.replace(secret, REDACTED)
        return redact_url(text)


def resolve_outbound(
    environ: Mapping[str, str],
    *,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
    no_proxy: str | None = None,
    ca_bundle: str | None = None,
) -> OutboundNetwork:
    """Resolve the outbound settings from the environment and the overrides.

    Each setting is the override when one is given, else the standard variable: ``http_proxy``
    then ``HTTP_PROXY`` (``https_proxy``/``HTTPS_PROXY`` likewise), then ``all_proxy`` /
    ``ALL_PROXY`` for either scheme; ``no_proxy`` then ``NO_PROXY``; ``SSL_CERT_FILE``, then
    ``REQUESTS_CA_BUNDLE``, then ``CURL_CA_BUNDLE``. A blank variable counts as unset. A proxy
    without a scheme is ``http://``.

    Args:
        environ: The process environment.
        http_proxy: Replaces the proxy of ``http://`` URLs.
        https_proxy: Replaces the proxy of ``https://`` URLs.
        no_proxy: Replaces ``NO_PROXY`` (an empty text: no exceptions).
        ca_bundle: Replaces the CA bundle file.

    Returns:
        The settings; building them raises ``ValueError`` for a proxy that is not a usable URL
        (the message names it without credentials).
    """
    every = _first(environ, "all_proxy", "ALL_PROXY")
    exceptions = _first(environ, "no_proxy", "NO_PROXY") if no_proxy is None else no_proxy
    return OutboundNetwork(
        http_proxy=_with_scheme(
            _blank(http_proxy) or _first(environ, "http_proxy", "HTTP_PROXY") or every
        ),
        https_proxy=_with_scheme(
            _blank(https_proxy) or _first(environ, "https_proxy", "HTTPS_PROXY") or every
        ),
        no_proxy=_entries(exceptions or ""),
        ca_bundle=_blank(ca_bundle) or _first(environ, *CA_BUNDLE_VARIABLES[:3]),
    )


def _blank(value: str | None) -> str | None:
    """Read a blank text as unset.

    Args:
        value: The text.

    Returns:
        It, stripped, or ``None`` when empty.
    """
    return (value or "").strip() or None


def _first(environ: Mapping[str, str], *names: str) -> str | None:
    """Return the first of the variables that is set and not blank.

    Args:
        environ: The environment.
        *names: The variables, strongest first.

    Returns:
        Its value, stripped, or ``None``.
    """
    return next((value for name in names if (value := _blank(environ.get(name)))), None)


def _with_scheme(proxy: str | None) -> str | None:
    """Give a proxy without a scheme ``http://``, as curl does.

    Args:
        proxy: The proxy, as configured.

    Returns:
        It, with a scheme.
    """
    if proxy is None or "://" in proxy:
        return proxy
    return f"http://{proxy}"


def _usable_proxy(proxy: str) -> bool:
    """Whether a proxy URL names a scheme clients speak, a host, and a valid port if any.

    Args:
        proxy: The proxy URL.

    Returns:
        True when usable.
    """
    try:
        parts = urlsplit(proxy)
        _ = parts.port
    except ValueError:
        return False
    return parts.scheme.lower() in _PROXY_SCHEMES and bool(parts.hostname)


def _entries(text: str) -> tuple[str, ...]:
    """Split a ``NO_PROXY`` value into its entries.

    Args:
        text: Comma- or whitespace-separated entries.

    Returns:
        The entries, lower case, without blanks or repeats.
    """
    found = (entry.strip().lower() for entry in text.replace(",", " ").split())
    return tuple(dict.fromkeys(entry for entry in found if entry))


def _address(host: str) -> _Address | None:
    """Read a host as an IP address; an IPv4-mapped IPv6 address as its IPv4 address.

    Args:
        host: The host (no brackets).

    Returns:
        The address, or ``None`` for a name.
    """
    try:
        address = ipaddress.ip_address(host.partition("%")[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _always_direct(host: str) -> bool:
    """Whether a host is never proxied: this machine, link-local, or the metadata server.

    Args:
        host: The host, lower case, no brackets or trailing dot.

    Returns:
        True when it is.
    """
    if host in _ALWAYS_DIRECT_NAMES or host.endswith(_ALWAYS_DIRECT_SUFFIX):
        return True
    address = _address(host)
    return address is not None and (
        address.is_loopback or address.is_link_local or address.is_unspecified
    )


def _split_port(entry: str) -> tuple[str, int | None]:
    """Split ``host:port`` (``[v6]:port``) into the host and the port.

    Args:
        entry: A ``NO_PROXY`` entry.

    Returns:
        The host part and the port, ``None`` when the entry names none.
    """
    if entry.startswith("["):
        host, _, rest = entry[1:].partition("]")
        port = rest.removeprefix(":")
        return host, int(port) if port.isdigit() else None
    if entry.count(":") == 1:
        host, _, port = entry.partition(":")
        if port.isdigit():
            return host, int(port)
    return entry, None


def _network(pattern: str) -> _Network | None:
    """Read an entry as an IP address or CIDR range.

    Args:
        pattern: The entry without its port.

    Returns:
        The range (a single address is a range of one), or ``None`` for a name.
    """
    try:
        return ipaddress.ip_network(pattern, strict=False)
    except ValueError:
        return None


def _matches(entry: str, host: str, port: int | None) -> bool:
    """Whether one ``NO_PROXY`` entry matches a host.

    Args:
        entry: The entry, lower case.
        host: The host, lower case, no brackets or trailing dot.
        port: The port connected to.

    Returns:
        True when the host (and port, if the entry names one) is reached directly.
    """
    if entry == "*":
        return True
    pattern, wanted = _split_port(entry)
    if wanted is not None and wanted != port:
        return False
    network = _network(pattern)
    if network is not None:
        address = _address(host)
        return address is not None and address.version == network.version and address in network
    domain = pattern.removeprefix("*").removeprefix(".").rstrip(".")
    return bool(domain) and (host == domain or host.endswith(f".{domain}"))


def _published(entry: str) -> str:
    """Write a ``NO_PROXY`` entry the way every client reads it alike.

    Args:
        entry: The entry.

    Returns:
        A domain without its leading ``*.`` or ``.``; anything else unchanged.
    """
    if entry == "*" or _network(_split_port(entry)[0]) is not None:
        return entry
    return entry.removeprefix("*").removeprefix(".") or entry


def _secrets(proxy: str | None) -> list[str]:
    """The parts of a proxy URL that must never be shown: its user information and password.

    Args:
        proxy: The proxy URL.

    Returns:
        The texts to hide (as written, and percent-decoded), longest first.
    """
    if proxy is None:
        return []
    try:
        parts = urlsplit(proxy)
    except ValueError:
        return []
    userinfo, at, _ = parts.netloc.rpartition("@")
    if not at:
        return []
    password = userinfo.partition(":")[2]
    found = {userinfo, unquote(userinfo), password, unquote(password)}
    # A password of one or two characters would blank out ordinary words of the message.
    return sorted((s for s in found if len(s) >= _MIN_SECRET), key=len, reverse=True)
