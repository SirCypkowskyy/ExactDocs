"""#538: every outbound client follows one resolution of the proxy, NO_PROXY and CA bundle.

The proxy here is ``forward_proxy`` on loopback, and the hosts behind it are ``.test`` names that
resolve nowhere: a request that reached one went through the proxy. Each test starts without the
machine's own proxy variables and CA bundle (``clear_outbound``).
"""

import http.server
import json
import logging
import sys
import threading
import types
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app_lifespan import serving
from exactdocs.bootstrap import ai_sdk
from exactdocs.bootstrap.ai_models import PydanticAiModels
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.database import StartupError
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.index_backends import build_index_backends
from exactdocs.bootstrap.index_kinds import IndexBackendKind
from exactdocs.bootstrap.models_pull import hub_downloader, pull
from exactdocs.bootstrap.outbound import publish, resolve
from exactdocs.bootstrap.settings import Settings
from exactdocs.bootstrap.sign_in import sign_in_client
from exactdocs.ingestion.adapters.driven.git_cli import GitCli, _environment
from exactdocs.ingestion.errors import RepositoryUnreachableError
from exactdocs.ingestion.models import RepositoryUrl
from exactdocs.retrieval.models import ModelRole, ProviderKind, ProviderProfile
from exactdocs_kernel import OutboundNetwork, resolve_outbound
from fake_hub import FakeHub, answer, fake_hub
from fake_llm import FakeGateway, gateway
from fixture_repo import REPO_PATH, DocsRepo, _handler
from forward_proxy import ForwardProxy, clear_outbound, forward_proxy
from tls_stand_in import CompanyCa, company_ca, https_server

SECRET = "s3cr3t-proxy-pass"
"""A proxy password no output may ever show."""


@pytest.fixture
def no_ambient_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_outbound(monkeypatch)


pytestmark = pytest.mark.usefixtures("no_ambient_outbound")


@pytest.fixture
def company(tmp_path: Path) -> CompanyCa:
    return company_ca(tmp_path / "ca", ["llm.example.test", "git.example.test"])


def _address(url: str) -> tuple[str, int]:
    host, _, port = url.removeprefix("http://").partition(":")
    return host, int(port.split("/")[0])


# ----------------------------------------------------------------- settings and start


def test_the_exactdocs_settings_replace_the_standard_variables(company: CompanyCa) -> None:
    environ = {
        "HTTPS_PROXY": "http://env-proxy.example:3128",
        "HTTP_PROXY": "http://env-plain.example:3128",
        "NO_PROXY": "env.example",
    }
    settings = Settings(
        https_proxy=SecretStr("http://corp-proxy.example:8080"),
        no_proxy=".corp.example,10.0.0.0/8",
        ca_bundle=company.bundle,
    )

    network = settings.outbound(environ)

    assert network.https_proxy == "http://corp-proxy.example:8080"
    assert network.http_proxy == "http://env-plain.example:3128"  # not overridden
    assert network.no_proxy == (".corp.example", "10.0.0.0/8")
    assert network.ca_bundle == str(company.bundle)


@pytest.mark.parametrize(
    ("variable", "value", "says"),
    [
        ("EXACTDOCS_HTTPS_PROXY", f"ftp://ada:{SECRET}@proxy:21", "is not a proxy URL"),
        ("HTTPS_PROXY", f"http://ada:{SECRET}@proxy:notaport", "is not a proxy URL"),
        ("EXACTDOCS_CA_BUNDLE", "/nonexistent/company-ca.pem", "is not a readable file"),
        ("SSL_CERT_FILE", "/nonexistent/company-ca.pem", "is not a readable file"),
    ],
)
def test_unusable_outbound_settings_stop_the_start_naming_them(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, says: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(StartupError, match=says) as refused:
        Container.build(Settings())

    assert SECRET not in str(refused.value)


def test_publish_hands_the_resolution_to_the_libraries_that_read_the_environment(
    company: CompanyCa,
) -> None:
    environ = {"HTTPS_PROXY": "http://ignored:1", "UNRELATED": "kept"}
    network = resolve(environ, https_proxy="http://corp:8080", ca_bundle=str(company.bundle))

    publish(network, environ)

    assert environ["HTTPS_PROXY"] == environ["https_proxy"] == "http://corp:8080"
    assert "127.0.0.1" in environ["NO_PROXY"].split(",")
    assert environ["REQUESTS_CA_BUNDLE"] == environ["SSL_CERT_FILE"] == str(company.bundle)
    assert environ["UNRELATED"] == "kept"


async def test_the_start_says_how_it_connects_out_without_the_proxys_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("EXACTDOCS_HTTPS_PROXY", f"http://ada:{SECRET}@proxy.corp.example:3128")
    monkeypatch.setenv("EXACTDOCS_NO_PROXY", ".corp.example")
    container = Container.build(Settings())

    with caplog.at_level(logging.INFO, logger="exactdocs.bootstrap.container"):
        async with container.running(jobs=False):
            pass

    said = [r.getMessage() for r in caplog.records if "Outbound connections" in r.getMessage()]
    assert said, caplog.text
    assert "http://***@proxy.corp.example:3128" in said[0]
    assert ".corp.example" in said[0]
    assert SECRET not in caplog.text
    assert "ada" not in said[0]


@pytest.fixture
async def proxied_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    monkeypatch.setenv("HTTPS_PROXY", f"http://ada:{SECRET}@proxy.corp.example:3128")
    monkeypatch.setenv("HTTP_PROXY", f"http://ada:{SECRET}@proxy.corp.example:3128")
    async with serving(create_app(Container.build(Settings()))) as app:
        yield app


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/api/health"])
async def test_the_probes_never_show_the_proxys_credentials(
    proxied_app: FastAPI, path: str
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=proxied_app), base_url="http://localhost"
    ) as client:
        answer = await client.get(path)

    assert answer.status_code == 200
    assert SECRET not in answer.text
    assert "ada:" not in answer.text


# ----------------------------------------------------------------- git


def test_git_is_given_the_resolution_not_this_processs_environment(
    monkeypatch: pytest.MonkeyPatch, company: CompanyCa, tmp_path: Path
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.example:1")  # what the resolution replaced
    network = resolve_outbound(
        {"HTTPS_PROXY": "http://corp:8080", "NO_PROXY": "*.corp.example,10.0.0.0/8"},
        ca_bundle=str(company.bundle),
    )

    environment = _environment(str(tmp_path), None, network)

    assert environment["https_proxy"] == environment["HTTPS_PROXY"] == "http://corp:8080"
    no_proxy = environment["no_proxy"].split(",")
    assert no_proxy[:2] == ["corp.example", "10.0.0.0/8"]
    assert {"localhost", "127.0.0.1", "::1"} <= set(no_proxy)
    assert environment["GIT_SSL_CAINFO"] == str(company.bundle)  # git's http.sslCAInfo
    assert "http_proxy" not in environment  # none resolved for http://


def test_without_a_proxy_git_gets_no_proxy_variable(tmp_path: Path) -> None:
    environment = _environment(str(tmp_path), None, OutboundNetwork())

    assert not {"http_proxy", "https_proxy", "all_proxy", "no_proxy"} & {
        name.lower() for name in environment
    }


@pytest.fixture
def https_git(company: CompanyCa, docs_repo: DocsRepo) -> Iterator[tuple[str, int]]:
    """The fixture repository over HTTPS, with a certificate of the company CA.

    Yields:
        Its loopback address.
    """
    base = docs_repo.path.parents[len(REPO_PATH.parts) - 1]
    with https_server(company, _handler(base)) as address:
        yield address


GIT_URL = f"https://git.example.test/{REPO_PATH.as_posix()}.git"
"""The fixture repository, under a name only the proxy knows."""


async def test_git_lists_refs_through_the_proxy_trusting_the_ca_bundle(
    company: CompanyCa, https_git: tuple[str, int]
) -> None:
    with forward_proxy({"git.example.test:443": https_git}, credentials=f"ada:{SECRET}") as proxy:
        network = resolve_outbound(
            {"HTTPS_PROXY": proxy.url_with(f"ada:{SECRET}")}, ca_bundle=str(company.bundle)
        )
        refs = await GitCli.locate(network=network).list_refs(RepositoryUrl.parse(GIT_URL))

    assert refs.default_branch == "main"
    assert proxy.hosts() == {"git.example.test:443"}


async def test_git_says_the_proxy_wants_credentials(
    company: CompanyCa, https_git: tuple[str, int]
) -> None:
    with forward_proxy({"git.example.test:443": https_git}, credentials=f"ada:{SECRET}") as proxy:
        network = resolve_outbound(
            {"HTTPS_PROXY": proxy.url_with("ada:wrong-pass")}, ca_bundle=str(company.bundle)
        )
        with pytest.raises(RepositoryUnreachableError) as failed:
            await GitCli.locate(network=network).list_refs(RepositoryUrl.parse(GIT_URL))

    message = str(failed.value)
    shown = proxy.url.replace("://", "://***@")
    assert f"the proxy {shown} wants credentials to reach git.example.test:443" in message
    assert "wrong-pass" not in message


async def test_git_says_tls_failed_through_the_proxy_without_the_ca_bundle(
    https_git: tuple[str, int],
) -> None:
    with forward_proxy({"git.example.test:443": https_git}) as proxy:
        network = resolve_outbound({"HTTPS_PROXY": proxy.url})  # the company CA is not trusted
        with pytest.raises(RepositoryUnreachableError) as failed:
            await GitCli.locate(network=network).list_refs(RepositoryUrl.parse(GIT_URL))

    message = str(failed.value)
    assert f"TLS failed reaching git.example.test:443 through the proxy {proxy.url}" in message
    assert "CA bundle" in message


async def test_a_host_the_proxy_refuses_is_named_with_the_proxy() -> None:
    with forward_proxy() as proxy:  # no route: every tunnel is refused with 403
        network = resolve_outbound({"HTTPS_PROXY": proxy.url})
        with pytest.raises(RepositoryUnreachableError) as failed:
            await GitCli.locate(network=network).list_refs(RepositoryUrl.parse(GIT_URL))

    assert f"the proxy {proxy.url} refused the connection to git.example.test:443" in str(
        failed.value
    )


# ----------------------------------------------------------------- AI providers


def _profile(base_url: str, proxy: str | None = None) -> ProviderProfile:
    return ProviderProfile(
        name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=base_url, proxy=proxy
    )


@pytest.fixture
def llm() -> Iterator[FakeGateway]:
    with gateway() as running:
        yield running


@pytest.fixture
def llm_proxy(llm: FakeGateway) -> Iterator[ForwardProxy]:
    with forward_proxy({"llm.example.test:80": _address(llm.url)}) as proxy:
        yield proxy


async def test_a_profile_uses_the_instance_proxy_only_when_asked(
    llm: FakeGateway, llm_proxy: ForwardProxy
) -> None:
    network = resolve_outbound({"HTTP_PROXY": llm_proxy.url})
    profile = _profile("http://llm.example.test/v1")

    through = await PydanticAiModels(network=network, use_instance_proxy=True).check(
        profile, "m", ModelRole.LLM
    )
    assert through.ok, through.error
    assert llm_proxy.seen == ["POST http://llm.example.test/v1/chat/completions"]

    llm_proxy.seen.clear()
    direct = await PydanticAiModels(network=network).check(profile, "m", ModelRole.LLM)
    assert not direct.ok  # the default: straight to llm.example.test, which resolves nowhere
    assert llm_proxy.seen == []
    assert llm.seen  # only the call that went through the proxy reached the gateway


async def test_the_profiles_own_proxy_wins_over_the_instance_proxy(
    llm_proxy: ForwardProxy,
) -> None:
    with forward_proxy() as instance:
        network = resolve_outbound({"HTTP_PROXY": instance.url})
        models = PydanticAiModels(network=network, use_instance_proxy=True)
        check = await models.check(
            _profile("http://llm.example.test/v1", proxy=llm_proxy.url), "m", ModelRole.LLM
        )

    assert check.ok, check.error
    assert llm_proxy.seen
    assert instance.seen == []


def test_no_proxy_keeps_an_internal_gateway_direct_with_the_instance_proxy() -> None:
    network = resolve_outbound(
        {"HTTPS_PROXY": "http://proxy.corp.example:3128", "NO_PROXY": ".corp.example,10.0.0.0/8"}
    )
    models = PydanticAiModels(network=network, use_instance_proxy=True)

    assert models.instance_proxy("https://api.openai.com/v1") == "http://proxy.corp.example:3128"
    assert models.instance_proxy("https://llm.gateway.corp.example/v1") is None
    assert models.instance_proxy("https://10.20.30.40/v1") is None
    assert models.instance_proxy("http://127.0.0.1:11434/v1") is None


def test_entra_id_gets_the_instance_proxy_when_profiles_use_it() -> None:
    profile = ProviderProfile(name="p", kind=ProviderKind.OPENAI_COMPATIBLE, base_url="https://x")
    proxy = "http://proxy.corp.example:3128"

    chain = ai_sdk.entra_chain(profile, {}, instance_proxy=proxy)

    assert chain[0][1] == {"proxies": {"http": proxy, "https": proxy}}  # EnvironmentCredential
    assert chain[-1][1] == {}  # managed identity: never a proxy


class _Chat(BaseHTTPRequestHandler):
    """An OpenAI-compatible chat endpoint, over TLS in the test below."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("content-length") or 0))
        body = json.dumps(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            }
        ).encode()  # fmt: skip
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        del code, size


async def test_a_provider_behind_a_re_signing_proxy_is_trusted_through_the_ca_bundle(
    company: CompanyCa,
) -> None:
    profile = _profile("https://llm.example.test/v1")
    with (
        https_server(company, _Chat) as tls_llm,
        forward_proxy({"llm.example.test:443": tls_llm}) as proxy,
    ):
        trusted = resolve_outbound({"HTTPS_PROXY": proxy.url}, ca_bundle=str(company.bundle))
        ok = await PydanticAiModels(network=trusted, use_instance_proxy=True).check(
            profile, "m", ModelRole.LLM
        )
        untrusted = resolve_outbound({"HTTPS_PROXY": proxy.url})
        refused = await PydanticAiModels(network=untrusted, use_instance_proxy=True).check(
            profile, "m", ModelRole.LLM
        )

    assert ok.ok, ok.error
    assert not refused.ok
    assert "llm.example.test:443" in (refused.error or "")
    assert proxy.url in (refused.error or "")


# ----------------------------------------------------------------- model downloads


@pytest.fixture
def stand_in_hub() -> Iterator[FakeHub]:
    with fake_hub() as hub:
        yield hub


@pytest.fixture
def hub_behind_proxy(
    stand_in_hub: FakeHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[ForwardProxy]:
    """The stand-in Hub as ``hub.example.test``, behind a proxy that asks for credentials.

    The Hub's client factory, endpoint and settings are process-wide: put back at teardown. Its
    telemetry starts on, and its registry of AI agent harnesses unknown (#589): not loaded in this
    process, no copy in the test's own ``HF_HOME``, whatever the machine's holds.

    Yields:
        The proxy.
    """
    huggingface_hub = pytest.importorskip("huggingface_hub")
    http = pytest.importorskip("huggingface_hub.utils._http")
    agents = pytest.importorskip("huggingface_hub.utils._detect_agent")
    constants = huggingface_hub.constants
    monkeypatch.setattr(constants, "ENDPOINT", "http://hub.example.test")
    monkeypatch.setattr(
        constants,
        "HUGGINGFACE_CO_URL_TEMPLATE",
        "http://hub.example.test/{repo_id}/resolve/{revision}/{filename}",
    )
    monkeypatch.setattr(constants, "HF_HUB_DISABLE_XET", constants.HF_HUB_DISABLE_XET)
    monkeypatch.setattr(constants, "HF_HUB_DISABLE_TELEMETRY", False)
    harnesses = tmp_path / "hf-home" / Path(constants.AGENT_HARNESSES_PATH).name
    monkeypatch.setattr(constants, "AGENT_HARNESSES_PATH", str(harnesses))
    monkeypatch.setattr(agents, "_registry", None)
    with forward_proxy(
        {"hub.example.test:80": _address(stand_in_hub.url)}, credentials=f"ada:{SECRET}"
    ) as proxy:
        yield proxy
    huggingface_hub.set_client_factory(http.default_client_factory)  # also closes the session


EMBEDDING = "BAAI/bge-small-en-v1.5"


def test_a_model_pull_goes_through_the_proxy(
    hub_behind_proxy: ForwardProxy, tmp_path: Path
) -> None:
    pytest.importorskip("fastembed")
    network = resolve_outbound({"HTTP_PROXY": hub_behind_proxy.url_with(f"ada:{SECRET}")})

    [outcome] = pull([EMBEDDING], tmp_path, download=hub_downloader(network))

    assert outcome.ok, outcome.message
    assert hub_behind_proxy.hosts() == {"hub.example.test:80"}


@pytest.mark.parametrize("cached", [False, True], ids=["no-cached-registry", "cached-registry"])
def test_a_model_pull_asks_the_hub_for_the_model_and_nothing_else(
    cached: bool, stand_in_hub: FakeHub, hub_behind_proxy: ForwardProxy, tmp_path: Path
) -> None:
    """#589: whatever ``HF_HOME`` holds, the pull sends only the requests the download needs.

    With its telemetry on, huggingface_hub fetches its registry of AI agent harnesses from the Hub
    before the first request, unless ``HF_HOME`` has a copy of the day.
    """
    pytest.importorskip("fastembed")
    harnesses = Path(pytest.importorskip("huggingface_hub.constants").AGENT_HARNESSES_PATH)
    if cached:
        harnesses.parent.mkdir(parents=True)
        harnesses.write_text(json.dumps({"standardEnvVars": [], "harnesses": {}}), "utf-8")
    network = resolve_outbound({"HTTP_PROXY": hub_behind_proxy.url_with(f"ada:{SECRET}")})

    [outcome] = pull([EMBEDDING], tmp_path / "models", download=hub_downloader(network))

    assert outcome.ok, outcome.message
    asked = [path for _, path, _ in stand_in_hub.seen]
    assert asked
    assert [path for path in asked if answer(path)[0] != HTTPStatus.OK] == []  # the model's only
    assert len(hub_behind_proxy.seen) == len(asked)  # each one through the proxy
    assert harnesses.exists() == cached


def test_a_pull_the_proxy_refuses_names_the_proxy_and_the_hub(
    hub_behind_proxy: ForwardProxy, tmp_path: Path
) -> None:
    pytest.importorskip("fastembed")
    network = resolve_outbound({"HTTP_PROXY": hub_behind_proxy.url_with("ada:wrong")})

    [outcome] = pull(["Xenova/ms-marco-MiniLM-L-6-v2"], tmp_path, download=hub_downloader(network))

    assert not outcome.ok
    shown = hub_behind_proxy.url.replace("://", "://***@")
    assert f"the proxy {shown} wants credentials to reach hub.example.test:80" in outcome.message
    assert "wrong" not in outcome.message


# ----------------------------------------------------------------- sign-in providers


class _Discovery(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"issuer": "http://idp.example.test"}'
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        del code, size


async def test_identity_providers_are_called_through_the_proxy() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Discovery)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        routes = {"idp.example.test:80": ("127.0.0.1", server.server_address[1])}
        with forward_proxy(routes) as proxy:
            client = sign_in_client(network=resolve_outbound({"HTTP_PROXY": proxy.url}))
            answer = await client.get("http://idp.example.test/.well-known/openid-configuration")
            await client.aclose()
    finally:
        server.shutdown()
        server.server_close()

    assert answer.status_code == 200
    assert proxy.seen == ["GET http://idp.example.test/.well-known/openid-configuration"]


# ----------------------------------------------------------------- index backends


def test_the_backends_that_connect_out_are_given_the_outbound_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    given: dict[str, Any] = {}

    def remote(options: Mapping[str, object], *, network: OutboundNetwork) -> object:
        del options
        given["remote"] = network
        return _Named("remote")

    def local(options: Mapping[str, object]) -> object:
        given["local"] = options
        return _Named("local")

    module = types.ModuleType("exactdocs_test_backends")
    vars(module).update(remote=remote, local=local)
    monkeypatch.setitem(sys.modules, "exactdocs_test_backends", module)
    kinds = {
        "remote": IndexBackendKind(
            name="remote", module="exactdocs_test_backends", search="remote", vectors=None,
            outbound=True,
        ),
        "local": IndexBackendKind(
            name="local", module="exactdocs_test_backends", search=None, vectors="local"
        ),
    }  # fmt: skip
    settings = Settings.model_construct(  # names only these test backends know
        search_backend="remote",
        vector_backend="local",
        https_proxy=SecretStr("http://proxy.corp.example:3128"),
    )

    build_index_backends(settings, kinds)

    assert given["remote"].https_proxy == "http://proxy.corp.example:3128"
    assert given["local"] == {}


@dataclass(frozen=True, slots=True)
class _Named:
    name: str


def test_backends_apply_the_proxy_and_the_ca_bundle(company: CompanyCa) -> None:
    azure = pytest.importorskip("exactdocs.retrieval.adapters.driven.azure_search_index")
    milvus = pytest.importorskip("exactdocs.retrieval.adapters.driven.milvus_index")
    redis = pytest.importorskip("exactdocs.retrieval.adapters.driven.redis_index")
    network = resolve_outbound(
        {"HTTPS_PROXY": "http://proxy.corp.example:3128", "NO_PROXY": ".corp.example"},
        ca_bundle=str(company.bundle),
    )

    service = azure.search_backend(
        {"endpoint": "https://acme.search.windows.net", "api_key": "k"}, network=network
    ).service.connection
    assert service.proxy == "http://proxy.corp.example:3128"
    internal = azure.search_backend(
        {"endpoint": "https://search.corp.example", "api_key": "k"}, network=network
    ).service.connection
    assert internal.proxy is None

    cloud = milvus.vector_backend({"uri": "https://in01.api.zillizcloud.com"}, network=network)
    assert cloud.channel_options() == {
        "grpc_options": {"grpc.http_proxy": "http://proxy.corp.example:3128"},
        "server_pem_path": str(company.bundle),
    }
    direct = milvus.vector_backend({"uri": "http://milvus.corp.example:19530"}, network=network)
    assert direct.channel_options() == {"grpc_options": {"grpc.enable_http_proxy": 0}}

    client = redis.search_backend(
        {"url": "rediss://cache.corp.example:6380"}, network=network
    ).connect()
    assert client.connection_pool.connection_kwargs["ssl_ca_certs"] == str(company.bundle)
