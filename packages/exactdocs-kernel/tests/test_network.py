"""#538: one resolution of the outbound settings, NO_PROXY matching, and redaction."""

import ssl
from pathlib import Path

import pytest

from exactdocs_kernel import (
    OUTBOUND_VARIABLES,
    OutboundNetwork,
    proxy_failure,
    redact_url,
    resolve_outbound,
)

PROXY = "http://proxy.corp.example:3128"
SECRET_PROXY = "http://ada:s3cr%40t-pass@proxy.corp.example:3128"


# ----------------------------------------------------------------- resolution and precedence


def test_nothing_set_connects_directly_and_trusts_the_system() -> None:
    network = resolve_outbound({})

    assert network == OutboundNetwork()
    assert not network.proxied
    assert network.proxy_for("https://github.com/acme/docs.git") is None
    assert network.environment() == {}


@pytest.mark.parametrize(
    ("environ", "http", "https"),
    [
        ({"HTTPS_PROXY": PROXY}, None, PROXY),
        ({"https_proxy": PROXY}, None, PROXY),
        ({"HTTP_PROXY": PROXY}, PROXY, None),
        ({"http_proxy": PROXY}, PROXY, None),
        # Lower case wins where both spellings are set, as in curl, urllib and requests.
        ({"HTTPS_PROXY": "http://upper:1", "https_proxy": PROXY}, None, PROXY),
        ({"HTTP_PROXY": "http://upper:1", "http_proxy": PROXY}, PROXY, None),
        # ALL_PROXY fills a scheme that has no proxy of its own, and only that one.
        ({"ALL_PROXY": PROXY}, PROXY, PROXY),
        ({"all_proxy": PROXY, "HTTPS_PROXY": "http://tls:1"}, PROXY, "http://tls:1"),
        # Blank counts as unset; a proxy without a scheme is http://.
        ({"HTTPS_PROXY": "  "}, None, None),
        ({"HTTPS_PROXY": "proxy.corp.example:3128"}, None, PROXY),
    ],
)
def test_the_standard_variables_resolve_with_the_usual_precedence(
    environ: dict[str, str], http: str | None, https: str | None
) -> None:
    network = resolve_outbound(environ)

    assert (network.http_proxy, network.https_proxy) == (http, https)


def test_an_override_replaces_each_standard_variable_on_its_own() -> None:
    environ = {
        "HTTPS_PROXY": "http://env:1",
        "HTTP_PROXY": "http://env-plain:1",
        "NO_PROXY": "env.example",
        "SSL_CERT_FILE": "/env/ca.pem",
    }

    network = resolve_outbound(environ, https_proxy=PROXY, ca_bundle="/etc/corp/ca.pem")

    assert network.https_proxy == PROXY
    assert network.http_proxy == "http://env-plain:1"  # not overridden: the environment's
    assert network.no_proxy == ("env.example",)
    assert network.ca_bundle == "/etc/corp/ca.pem"
    # An empty override clears NO_PROXY; a blank one for a proxy leaves the environment's.
    assert resolve_outbound(environ, no_proxy="").no_proxy == ()
    assert resolve_outbound(environ, https_proxy=" ").https_proxy == "http://env:1"


@pytest.mark.parametrize(
    ("environ", "bundle"),
    [
        ({"SSL_CERT_FILE": "/a.pem", "REQUESTS_CA_BUNDLE": "/b.pem"}, "/a.pem"),
        ({"REQUESTS_CA_BUNDLE": "/b.pem", "CURL_CA_BUNDLE": "/c.pem"}, "/b.pem"),
        ({"CURL_CA_BUNDLE": "/c.pem"}, "/c.pem"),
        ({"GIT_SSL_CAINFO": "/git-only.pem"}, None),  # git's own: handed to git, not read here
    ],
)
def test_the_ca_bundle_comes_from_the_first_variable_set(
    environ: dict[str, str], bundle: str | None
) -> None:
    assert resolve_outbound(environ).ca_bundle == bundle


@pytest.mark.parametrize(
    "proxy", ["ftp://proxy:21", "http://", "http://proxy:99999", "http://proxy:port"]
)
def test_an_unusable_proxy_is_refused_without_repeating_its_password(proxy: str) -> None:
    with_password = proxy.replace("://", "://ada:hunter22@", 1)

    with pytest.raises(ValueError, match="not a proxy URL") as refused:
        resolve_outbound({"HTTPS_PROXY": with_password})

    assert "hunter22" not in str(refused.value)


def test_socks_proxies_from_all_proxy_are_accepted() -> None:
    network = resolve_outbound({"ALL_PROXY": "socks5h://bastion:1080"})

    assert network.proxy_for("https://huggingface.co") == "socks5h://bastion:1080"


# ----------------------------------------------------------------- NO_PROXY


NETWORK = resolve_outbound(
    {
        "HTTPS_PROXY": PROXY,
        "HTTP_PROXY": PROXY,
        "NO_PROXY": (
            "git.internal, .corp.example,*.svc.cluster.local  10.0.0.0/8,192.168.1.7,"
            "fd00::/8, models.example:8443, [2001:db8::1]:9200, Upper.Example."
        ),
    }
)


@pytest.mark.parametrize(
    "url",
    [
        # A host name matches itself and every name under it, whatever its prefix.
        "https://git.internal/acme/docs.git",
        "https://mirror.git.internal/acme/docs.git",
        "https://corp.example/",
        "https://llm.gateway.corp.example/v1",
        "https://svc.cluster.local/",
        "http://qdrant.retrieval.svc.cluster.local:6333",
        "https://GIT.INTERNAL./x",  # case and a trailing dot do not matter
        "https://upper.example/",
        # Addresses and ranges.
        "http://10.1.2.3:9200",
        "https://192.168.1.7/",
        "https://[fd12:3456::1]:8443/",
        "https://[::ffff:10.9.9.9]/",  # IPv4-mapped IPv6 is the IPv4 address
        # An entry with a port matches that port only (default ports count).
        "https://models.example:8443/model.onnx",
        "http://[2001:db8::1]:9200/",
    ],
)
def test_no_proxy_hosts_are_reached_directly(url: str) -> None:
    assert NETWORK.proxy_for(url) is None
    assert NETWORK.via(url) == "directly"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/docs.git",
        "https://notgit.internal/",  # a suffix only matches at a dot
        "https://git.internal.evil.example/",
        "http://11.1.2.3:9200",
        "https://192.168.1.8/",
        "https://models.example/model.onnx",  # :443, not :8443
        "https://[2001:db8::1]/",  # :443, not :9200
        "https://10.example.com/",  # a name is never compared with a range
    ],
)
def test_other_hosts_go_through_the_proxy(url: str) -> None:
    assert NETWORK.proxy_for(url) == PROXY
    assert NETWORK.via(url) == f"through the proxy {PROXY}"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:3000",
        "http://docs.localhost/",
        "http://127.0.0.1:8080",
        "http://127.9.9.9/",
        "http://[::1]:3000/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/metadata/identity/oauth2/token",  # IMDS: never a proxy's
        "http://[fe80::1]/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://0.0.0.0:3000/",
    ],
)
def test_loopback_and_link_local_are_never_proxied(url: str) -> None:
    everything = resolve_outbound({"ALL_PROXY": PROXY, "NO_PROXY": ""})

    assert everything.proxy_for(url) is None


def test_a_star_turns_the_proxy_off_for_every_host() -> None:
    network = resolve_outbound({"HTTPS_PROXY": PROXY, "NO_PROXY": "example.com,*"})

    assert network.proxy_for("https://github.com/") is None
    assert network.proxied  # still configured: a star is an exception list, not "no proxy"


@pytest.mark.parametrize(
    "url", ["ssh://git@github.com/acme/docs.git", "redis://cache:6379", "file:///repo", "nonsense"]
)
def test_only_http_urls_use_an_http_proxy(url: str) -> None:
    assert NETWORK.proxy_for(url) is None


def test_each_scheme_uses_its_own_proxy() -> None:
    network = resolve_outbound({"HTTP_PROXY": "http://plain:1", "HTTPS_PROXY": "http://tls:2"})

    assert network.proxy_for("http://example.com") == "http://plain:1"
    assert network.proxy_for("ws://example.com") == "http://plain:1"
    assert network.proxy_for("https://example.com") == "http://tls:2"
    assert network.proxy_for("wss://example.com") == "http://tls:2"


def test_a_url_that_cannot_be_read_goes_nowhere_near_the_proxy() -> None:
    assert NETWORK.proxy_for("https://example.com:notaport/") is None
    assert NETWORK.proxy_for("https:///no-host") is None


# ----------------------------------------------------------------- the environment of a child


def test_the_environment_names_both_spellings_and_keeps_loopback_direct() -> None:
    network = resolve_outbound(
        {"HTTPS_PROXY": PROXY, "NO_PROXY": "*.corp.example,.svc.local,10.0.0.0/8"},
        ca_bundle="/etc/corp/ca.pem",
    )

    environment = network.environment()

    assert environment["https_proxy"] == environment["HTTPS_PROXY"] == PROXY
    assert "http_proxy" not in environment  # no proxy for http://: none published
    no_proxy = environment["no_proxy"].split(",")
    assert environment["NO_PROXY"] == environment["no_proxy"]
    assert no_proxy[:3] == ["corp.example", "svc.local", "10.0.0.0/8"]  # domains as bare names
    assert {"localhost", "127.0.0.1", "127.0.0.0/8", "::1", "169.254.0.0/16"} <= set(no_proxy)
    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO"):
        assert environment[variable] == "/etc/corp/ca.pem"
    assert set(environment) <= set(OUTBOUND_VARIABLES)


def test_a_ca_bundle_alone_publishes_no_proxy_variable() -> None:
    environment = resolve_outbound({"SSL_CERT_FILE": "/etc/corp/ca.pem"}).environment()

    assert set(environment) == {
        "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO",
    }  # fmt: skip


# ----------------------------------------------------------------- credentials are never shown


def test_proxy_credentials_work_but_never_show() -> None:
    network = resolve_outbound({"HTTPS_PROXY": SECRET_PROXY})

    assert network.proxy_for("https://github.com/") == SECRET_PROXY  # the client gets them
    assert "s3cr" not in repr(network)
    assert "ada" not in repr(network)
    assert "http://***@proxy.corp.example:3128" in repr(network)
    assert (
        network.via("https://github.com/") == "through the proxy http://***@proxy.corp.example:3128"
    )


def test_redact_hides_the_credentials_of_any_url_and_the_proxys_password() -> None:
    network = resolve_outbound({"HTTPS_PROXY": SECRET_PROXY})
    message = (
        f"proxy {SECRET_PROXY} refused: 407 for user ada with s3cr@t-pass, "
        "fetching https://token:x-oauth@github.com/acme/docs.git"
    )

    shown = network.redact(message)

    assert "s3cr" not in shown
    assert "x-oauth" not in shown
    assert "http://***@proxy.corp.example:3128" in shown
    assert "https://***@github.com/acme/docs.git" in shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("http://u:p@h:1", "http://***@h:1"),
        ("socks5h://u@h", "socks5h://***@h"),
        ("no url here", "no url here"),
        ("https://example.com/path@v1", "https://example.com/path@v1"),  # an @ in the path
        ("'http://a:b@x' and \"https://c:d@y/\"", "'http://***@x' and \"https://***@y/\""),
    ],
)
def test_redact_url(text: str, shown: str) -> None:
    assert redact_url(text) == shown


# ----------------------------------------------------------------- errors that name the proxy


@pytest.mark.parametrize(
    ("detail", "says"),
    [
        ("407 Proxy Authentication Required", "wants credentials to reach github.com:443"),
        ("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", "TLS failed reaching"),
        ("403 Forbidden", "refused the connection to github.com:443"),
        ("CONNECT tunnel failed, HTTP 502", "refused the connection to github.com:443"),
        ("[Errno 111] Connection refused", "could not reach github.com:443 through the proxy"),
        ("", "could not reach github.com:443 through the proxy"),
    ],
)
def test_a_failure_through_the_proxy_names_the_proxy_and_the_host(detail: str, says: str) -> None:
    message = proxy_failure(SECRET_PROXY, "github.com:443", detail)

    assert says in message
    assert "http://***@proxy.corp.example:3128" in message
    assert "s3cr" not in message


def test_the_tls_context_trusts_the_bundle_and_always_verifies(tmp_path: Path) -> None:
    assert OutboundNetwork().tls_context() is None  # the client's own default trust
    bundle = tmp_path / "ca.pem"
    system = ssl.get_default_verify_paths().cafile or ssl.get_default_verify_paths().openssl_cafile
    if not Path(system).is_file():
        pytest.skip("no system CA file to copy")
    bundle.write_bytes(Path(system).read_bytes())

    context = OutboundNetwork(ca_bundle=str(bundle)).tls_context()

    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
