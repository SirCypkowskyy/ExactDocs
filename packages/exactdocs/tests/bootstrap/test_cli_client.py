"""The CLI as a client of the REST API: stored credentials, URL safety, error mapping."""

import http.server
import inspect
import os
import stat
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from exactdocs.bootstrap import cli, cli_library, client
from exactdocs.bootstrap.client import (
    ApiClient,
    ApiError,
    ClientConfig,
    ClientError,
    config_path,
    forget,
    normalize_url,
    read_stored,
    store,
)
from exactdocs.bootstrap.constants import LOCAL_COMMANDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.constants import FIRST_WAIT, FREE_FAILURES
from exactdocs.identity.dtos import CreateFirstAdminCommand
from forward_proxy import clear_outbound, forward_proxy
from tls_stand_in import CompanyCa, company_ca, https_server

HORSE = "correct horse battery staple"
URL = "https://docs.example.com"


@pytest.fixture
async def transport() -> AsyncIterator[httpx2.ASGITransport]:
    container = Container.build(Settings())
    async with container.running():
        await container.identity.create_first_admin(
            CreateFirstAdminCommand(username="ada", password=SecretStr(HORSE))
        )
        yield httpx2.ASGITransport(app=create_app(container))


async def test_login_issues_a_named_token_that_then_works(
    transport: httpx2.ASGITransport,
) -> None:
    async with ApiClient("http://localhost", transport=transport) as api:
        grant = await api.login("ada", HORSE, "laptop")
    async with ApiClient("http://localhost", grant["token"], transport=transport) as api:
        await api.check_token()
    assert grant["name"] == "laptop"


async def test_errors_are_mapped_to_readable_messages(transport: httpx2.ASGITransport) -> None:
    async with ApiClient("http://localhost", "exd_nope", transport=transport) as api:
        with pytest.raises(ApiError, match="did not accept the token") as unauthenticated:
            await api.check_token()
        with pytest.raises(ApiError, match="wrong username or password") as wrong:
            await api.login("ada", "wrong horse battery staple", "x")
        with pytest.raises(ApiError, match="invalid: name") as invalid:
            await api.request("POST", "/tokens/login", json={"username": "a", "password": "b"})
    assert unauthenticated.value.code == "unauthenticated"
    assert wrong.value.code == "invalid_credentials"
    assert "b" not in str(invalid.value).replace("invalid", "").replace("name", "")


async def test_a_throttled_login_says_to_wait_and_for_how_long(
    transport: httpx2.ASGITransport,
) -> None:
    async with ApiClient("http://localhost", transport=transport) as api:
        for _ in range(FREE_FAILURES):
            with pytest.raises(ApiError, match="wrong username or password"):
                await api.login("ada", "wrong horse battery staple", "x")
        with pytest.raises(ApiError, match="too many failed sign-ins") as throttled:
            await api.login("ada", HORSE, "x")

    assert throttled.value.code == "rate_limited"
    assert throttled.value.retry_after == FIRST_WAIT.total_seconds()
    assert str(throttled.value).endswith(f"(in {throttled.value.retry_after} seconds)")


async def test_a_server_that_is_not_there_or_not_exactdocs_is_said_so() -> None:
    async with ApiClient("http://127.0.0.1:1") as api:
        with pytest.raises(ClientError, match=r"cannot reach http://127\.0\.0\.1:1"):
            await api.check_token()
    stranger = httpx2.MockTransport(lambda _: httpx2.Response(200, text="<html>"))
    async with ApiClient("http://localhost", transport=stranger) as api:
        with pytest.raises(ClientError, match="is it an ExactDocs server"):
            await api.check_token()


async def test_redirects_are_not_followed_so_the_token_stays_put() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.host)
        return httpx2.Response(302, headers={"location": "https://evil.example/x"})

    async with ApiClient(URL, "exd_secret", transport=httpx2.MockTransport(handler)) as api:
        with pytest.raises(ClientError, match="redirected"):
            await api.check_token()
    assert seen == ["docs.example.com"]


@pytest.mark.parametrize("url", ["http://localhost:3000", "http://127.0.0.1", "http://[::1]:3000"])
def test_plain_http_is_fine_for_loopback(url: str) -> None:
    assert normalize_url(url + "/") == url


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.com",
        "http://10.0.0.5",
        "ftp://x",
        "docs",
        "https://u:p@x.io",
        "http://localhost.",
        "http://127.1",
        "http://0.0.0.0",
        "https://x.io:notaport",
    ],
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(ClientError):
        normalize_url(url)


def test_the_config_file_is_private_and_the_token_never_printed(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.json"
    config = ClientConfig(url=URL, token="exd_secret")

    store(path, config)
    store(path, config)  # overwriting works

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "exd_secret" not in repr(config)
    assert read_stored(path) == {"url": URL, "token": "exd_secret"}
    assert [p.name for p in path.parent.iterdir()] == ["config.json"]
    assert forget(path)
    assert not forget(path)


def test_flags_beat_environment_beat_the_file(tmp_path: Path) -> None:
    file = tmp_path / "c.json"
    store(file, ClientConfig(url=URL, token="from-file"))
    env = {"EXACTDOCS_CLIENT_CONFIG": str(file)}

    assert ClientConfig.resolve(env=env) == ClientConfig(url=URL, token="from-file")
    env |= {"EXACTDOCS_URL": "https://env.example.com", "EXACTDOCS_TOKEN": "from-env"}
    assert ClientConfig.resolve(env=env).token == "from-env"
    flagged = ClientConfig.resolve(url="https://flag.example.com", token="from-flag", env=env)
    assert (flagged.url, flagged.token) == ("https://flag.example.com", "from-flag")


def test_a_stored_token_is_never_sent_to_another_server(tmp_path: Path) -> None:
    file = tmp_path / "c.json"
    store(file, ClientConfig(url=URL, token="from-file"))
    env = {"EXACTDOCS_CLIENT_CONFIG": str(file), "EXACTDOCS_URL": "https://other.example.com"}

    with pytest.raises(ClientError, match=r"not logged in to https://other\.example\.com"):
        ClientConfig.resolve(env=env)


def test_nothing_configured_says_how_to_log_in(tmp_path: Path) -> None:
    with pytest.raises(ClientError, match="exactdocs login"):
        ClientConfig.resolve(env={"EXACTDOCS_CLIENT_CONFIG": str(tmp_path / "none.json")})


def test_the_default_config_path_is_in_the_user_config_dir() -> None:
    assert config_path({}).name == "config.json"
    assert "exactdocs" in str(config_path({}))


# Local commands open the database; every other command must go through the REST client.
def _commands(app: Any = cli.app, prefix: str = "") -> dict[str, Any]:
    """Flatten the cyclopts app into ``{"admin create": function}`` (uses a private attribute)."""
    found: dict[str, Any] = {}
    for name, sub in app._commands.items():  # ruff: ignore[private-member-access]
        if name.startswith("-"):
            continue
        if sub.default_command is not None:
            found[f"{prefix}{name}"] = sub.default_command
        found.update(_commands(sub, f"{prefix}{name} "))
    return found


def test_only_the_listed_commands_are_local() -> None:
    commands = _commands()
    assert commands.keys() >= LOCAL_COMMANDS
    assert {"login", "logout"} <= commands.keys()
    for name, command in commands.items():
        if name in LOCAL_COMMANDS:
            continue
        source = inspect.getsource(command)
        for forbidden in (
            "Container",
            "Settings",
            "_build(",
            "_run(",
            "sqlalchemy",
            "_create_first_admin",
            "_reset_password",
            "_create_user",
            "_set_user_disabled",
            "_serve_stdio",
            "_check_startup",
        ):
            assert forbidden not in source, f"{name} must use the REST client only"


def test_the_client_modules_stay_free_of_the_server() -> None:
    for module in (client, cli_library):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("bootstrap.container", "sqlalchemy", "bootstrap.settings"):
            assert forbidden not in source, module.__name__


def test_the_helpers_of_the_remote_commands_stay_free_of_the_server() -> None:
    for helper in (cli._session, cli._credential, cli._call, cli._api):  # ruff: ignore[private-member-access]
        source = inspect.getsource(helper)
        for forbidden in ("Container", "Settings", "_build(", "_run(", "sqlalchemy"):
            assert forbidden not in source, helper.__name__


@pytest.mark.parametrize(
    "spelling",
    [
        "HTTPS://Docs.Example.com",
        "https://docs.example.com:443/",
        "https://docs.example.com//",
        " https://docs.EXAMPLE.com ",
    ],
)
def test_spellings_of_one_server_normalize_alike(spelling: str) -> None:
    assert normalize_url(spelling) == "https://docs.example.com"


def test_urls_are_normalized_in_every_part() -> None:
    assert normalize_url("https://bücher.example") == "https://xn--bcher-kva.example"
    assert normalize_url("HTTP://LocalHost:80") == "http://localhost"
    assert normalize_url("http://localhost:3000/") == "http://localhost:3000"
    assert normalize_url("https://x.io:8443/docs/") == "https://x.io:8443/docs"
    assert normalize_url("http://[::ffff:127.0.0.1]:3000") == "http://[::ffff:127.0.0.1]:3000"
    assert normalize_url("http://[::1]") == "http://[::1]"


def test_a_stored_token_matches_another_spelling_of_its_url(tmp_path: Path) -> None:
    file = tmp_path / "c.json"
    store(file, ClientConfig(url=normalize_url("https://Docs.example.com"), token="t"))
    env = {"EXACTDOCS_CLIENT_CONFIG": str(file), "EXACTDOCS_URL": "https://docs.example.com:443"}

    assert ClientConfig.resolve(env=env).token == "t"


def test_store_survives_a_wide_umask_a_loose_old_file_and_a_stale_temp(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}")
    path.chmod(0o644)
    (tmp_path / f"config.json.{os.getpid()}.tmp").write_text("stale")
    old = os.umask(0)
    try:
        store(path, ClientConfig(url=URL, token="exd_secret"))
    finally:
        os.umask(old)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_stored(path)["token"] == "exd_secret"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".config.")]


def test_a_loose_config_file_is_warned_about(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.json"
    store(path, ClientConfig(url=URL, token="exd_secret"))
    read_stored(path)
    assert not capsys.readouterr().err

    path.chmod(0o644)
    read_stored(path)
    err = capsys.readouterr().err
    assert "chmod 600" in err
    assert "exd_secret" not in err


async def test_control_characters_from_a_server_never_reach_the_terminal() -> None:
    hostile = httpx2.MockTransport(
        lambda _: httpx2.Response(
            400, json={"error": "weird", "detail": "\x1b[2Jboom\x07", "fields": []}
        )
    )
    async with ApiClient("http://localhost", transport=hostile) as api:
        with pytest.raises(ApiError) as raised:
            await api.check_token()

    assert str(raised.value) == "[2Jboom"


class _ListAnswer(http.server.BaseHTTPRequestHandler):
    """Answers every ``GET`` with an empty JSON list, as ``GET /api/v1/libraries`` would."""

    def do_GET(self) -> None:
        body = b"[]"
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        del code, size


@pytest.fixture
def company(tmp_path: Path) -> CompanyCa:
    return company_ca(tmp_path / "ca", ["docs.example.test"])


@pytest.fixture
def remote_api(company: CompanyCa) -> Iterator[tuple[str, int]]:
    """``https://docs.example.test``, on loopback, with a certificate of the company CA.

    Yields:
        Its loopback address, for the proxy's route.
    """
    with https_server(company, _ListAnswer) as address:
        yield address


@pytest.fixture
def plain_api() -> Iterator[tuple[str, int]]:
    """The same answers over plain HTTP on 127.0.0.1.

    Yields:
        Its address.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ListAnswer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield ("127.0.0.1", server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


REMOTE = "https://docs.example.test"
"""A ``.test`` name resolves nowhere: only a proxy can reach it."""


async def test_a_remote_server_is_reached_through_the_proxy_and_its_ca(
    monkeypatch: pytest.MonkeyPatch, company: CompanyCa, remote_api: tuple[str, int]
) -> None:
    clear_outbound(monkeypatch)
    with forward_proxy({"docs.example.test:443": remote_api}, credentials="ada:s3cr") as proxy:
        monkeypatch.setenv("HTTPS_PROXY", proxy.url_with("ada:s3cr"))
        monkeypatch.setenv("EXACTDOCS_CA_BUNDLE", str(company.bundle))
        async with ApiClient(REMOTE, "exd_token") as api:
            await api.check_token()

    assert proxy.seen == ["CONNECT docs.example.test:443"]


async def test_a_proxy_that_wants_credentials_is_named_in_the_error(
    monkeypatch: pytest.MonkeyPatch, company: CompanyCa, remote_api: tuple[str, int]
) -> None:
    clear_outbound(monkeypatch)
    with forward_proxy({"docs.example.test:443": remote_api}, credentials="ada:right") as proxy:
        monkeypatch.setenv("HTTPS_PROXY", proxy.url_with("ada:wrong-pass"))
        monkeypatch.setenv("SSL_CERT_FILE", str(company.bundle))
        async with ApiClient(REMOTE, "exd_token") as api:
            with pytest.raises(ClientError) as refused:
                await api.check_token()

    message = str(refused.value)
    shown = proxy.url.replace("://", "://***@")
    assert f"the proxy {shown} wants credentials to reach docs.example.test:443" in message
    assert "wrong-pass" not in message


async def test_a_certificate_the_ca_bundle_does_not_vouch_for_is_refused_naming_the_proxy(
    monkeypatch: pytest.MonkeyPatch, remote_api: tuple[str, int], tmp_path: Path
) -> None:
    clear_outbound(monkeypatch)
    other = company_ca(tmp_path / "other", ["docs.example.test"])  # not the server's CA
    with forward_proxy({"docs.example.test:443": remote_api}) as proxy:
        monkeypatch.setenv("HTTPS_PROXY", proxy.url)
        monkeypatch.setenv("EXACTDOCS_CA_BUNDLE", str(other.bundle))
        async with ApiClient(REMOTE, "exd_token") as api:
            with pytest.raises(ClientError) as refused:
                await api.check_token()

    message = str(refused.value)
    assert f"TLS failed reaching docs.example.test:443 through the proxy {proxy.url}" in message
    assert "CA bundle" in message


async def test_loopback_never_goes_through_the_proxy(
    monkeypatch: pytest.MonkeyPatch, plain_api: tuple[str, int]
) -> None:
    clear_outbound(monkeypatch)
    with forward_proxy() as proxy:  # no route: anything sent to it would be refused
        monkeypatch.setenv("ALL_PROXY", proxy.url)
        host, port = plain_api
        async with ApiClient(f"http://{host}:{port}", "exd_token") as api:
            await api.check_token()

    assert proxy.seen == []


async def test_an_exactdocs_override_replaces_the_standard_proxy(
    monkeypatch: pytest.MonkeyPatch, company: CompanyCa, remote_api: tuple[str, int]
) -> None:
    clear_outbound(monkeypatch)
    with forward_proxy({"docs.example.test:443": remote_api}) as proxy, forward_proxy() as other:
        monkeypatch.setenv("HTTPS_PROXY", other.url)
        monkeypatch.setenv("EXACTDOCS_HTTPS_PROXY", proxy.url)
        monkeypatch.setenv("EXACTDOCS_CA_BUNDLE", str(company.bundle))
        async with ApiClient(REMOTE) as api:
            await api.check_token()

    assert proxy.seen == ["CONNECT docs.example.test:443"]
    assert other.seen == []


def test_an_unusable_proxy_is_a_client_error_without_its_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_outbound(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "ftp://ada:hunter22@proxy.example.com:21")

    with pytest.raises(ClientError, match="not a proxy URL") as refused:
        ApiClient(URL)

    assert "hunter22" not in str(refused.value)


@pytest.mark.parametrize("library_ids", [None, [], ["/acme/docs", "/acme/api"]])
async def test_login_preserves_the_optional_token_library_selection(
    transport: httpx2.ASGITransport, library_ids: list[str] | None
) -> None:
    async with ApiClient("http://localhost", transport=transport) as api:
        grant = await api.login("ada", HORSE, "selected", library_ids=library_ids)
    assert grant["library_ids"] == (None if library_ids is None else sorted(library_ids))
