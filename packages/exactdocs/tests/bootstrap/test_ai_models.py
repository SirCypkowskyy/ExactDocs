"""#241: the ModelFactory builds every SDK client from explicit values, never the environment.

Each test runs with the SDKs' environment variables set to values that must not be used: keys,
base URLs, projects, regions. Real pydantic-ai calls go to a fake gateway on loopback, which
records what each request carried.
"""

import asyncio
import json
import re
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from anthropic import AsyncAnthropicVertex
from azure.identity import (
    EnvironmentCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.oauth2.credentials import Credentials
from pydantic import ValidationError
from pydantic_ai import Embedder
from pydantic_ai.models.instrumented import InstrumentationSettings, InstrumentedModel

from exactdocs.bootstrap import ai_models, ai_sdk
from exactdocs.bootstrap.ai_endpoint import Endpoint
from exactdocs.bootstrap.ai_models import PydanticAiModels, configured_ai
from exactdocs.bootstrap.ai_sdk import (
    ForeignHostError,
    _anthropic_client,
    _official_url,
    _openai_provider,
)
from exactdocs.bootstrap.constants import (
    AI_SDK_MODULE,
    AZURE_OPENAI_HOST,
    BEDROCK_HOST,
    CHECK_MAX_TOKENS,
    FOUNDRY_HOST,
    VERTEX_HOST,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.errors import InvalidProviderError, ProviderUnsupportedError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    KeySource,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    ThinkingLevel,
)
from exactdocs_kernel import SealedTextUnreadableError
from fake_llm import DIMENSIONS, FakeGateway, gateway

POISON = {
    "OPENAI_API_KEY": "env-openai-key",
    "OPENAI_BASE_URL": "https://env-openai.invalid/v1",
    "OPENAI_API_VERSION": "env-version",
    "OPENAI_ORG_ID": "env-org",
    "OPENAI_PROJECT_ID": "env-project",
    "ANTHROPIC_API_KEY": "env-anthropic-key",
    "ANTHROPIC_BASE_URL": "https://env-anthropic.invalid",
    "ANTHROPIC_VERTEX_BASE_URL": "https://env-vertex.invalid/v1",
    "ANTHROPIC_VERTEX_PROJECT_ID": "env-vertex-project",
    "CLOUD_ML_REGION": "env-region",
    "ANTHROPIC_FOUNDRY_BASE_URL": "https://env-foundry.invalid/anthropic/",
    "ANTHROPIC_FOUNDRY_RESOURCE": "env-foundry",
    "ANTHROPIC_FOUNDRY_API_KEY": "env-foundry-key",
    "AZURE_OPENAI_API_KEY": "env-azure-key",
    "AZURE_OPENAI_AD_TOKEN": "env-azure-token",
    "AZURE_OPENAI_ENDPOINT": "https://env-azure.invalid",
    "OPENROUTER_API_KEY": "env-openrouter-key",
    "OLLAMA_BASE_URL": "https://env-ollama.invalid/v1",
    "GOOGLE_API_KEY": "env-google-key",
    "GEMINI_API_KEY": "env-gemini-key",
    "GOOGLE_CLOUD_PROJECT": "env-gcp-project",
    "GOOGLE_CLOUD_LOCATION": "env-gcp-location",
    "DEEPSEEK_API_KEY": "env-deepseek-key",
    "HTTPS_PROXY": "http://env-proxy.invalid:3128",
    "OPENAI_CUSTOM_HEADERS": "Authorization: Bearer env-custom-openai\napi-key: env-custom-azure",
    "ANTHROPIC_CUSTOM_HEADERS": "x-api-key: env-custom-anthropic\nAuthorization: Bearer env-custom",
    "HTTP_PROXY": "http://env-proxy.invalid:3128",
}


@pytest.fixture
def poisoned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name, value in POISON.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "env-adc.json"))
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)


pytestmark = pytest.mark.usefixtures("poisoned")  # every test runs in the hostile environment


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    with gateway() as running:
        yield running


@dataclass(slots=True)
class FakeEntra:
    """Entra ID without Azure: counts the providers built and the tokens handed out."""

    providers: int = 0
    tokens: int = 0

    proxies: list[str | None] = field(default_factory=list)

    def provider(
        self, profile: ProviderProfile, *, instance_proxy: str | None = None
    ) -> Callable[[], str]:
        del profile
        self.providers += 1
        self.proxies.append(instance_proxy)

        def token() -> str:
            self.tokens += 1
            return f"entra-token-{self.tokens}"

        return token


@pytest.fixture
def entra(monkeypatch: pytest.MonkeyPatch) -> FakeEntra:
    fake_entra = FakeEntra()
    monkeypatch.setattr(ai_sdk, "entra_token_provider", fake_entra.provider)
    return fake_entra


@pytest.fixture
def official(fake: FakeGateway, monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    """The fake gateway stands in for the official endpoint a profile's identity derives.

    A profile signed with the server's cloud identity takes no ``base_url``: its endpoint is
    Google's or Azure's own, which a test cannot reach, so the derived URL is swapped.
    """
    derived = ai_sdk.base_url

    def stand_in(profile: ProviderProfile) -> str:
        assert profile.base_url is None
        official_url = derived(profile)
        assert official_url.startswith("https://")
        return fake.url + ("/anthropic/" if "anthropic" in official_url else "/")

    monkeypatch.setattr(ai_sdk, "base_url", stand_in)
    return fake


def _endpoint(profile: ProviderProfile, key: str | None = "profile-key") -> Endpoint:
    url = ai_sdk.base_url(profile)
    return Endpoint(profile=profile, base_url=url, key=key, client=ai_sdk.http_client(profile, url))


OPENAI_KINDS = [
    k
    for k in ProviderKind
    if k
    not in {
        ProviderKind.ANTHROPIC,
        ProviderKind.GOOGLE,
        ProviderKind.GOOGLE_VERTEX,
        ProviderKind.LOCAL,
    }
]


@pytest.mark.parametrize("kind", OPENAI_KINDS, ids=[k.value for k in OPENAI_KINDS])
def test_every_openai_api_kind_gets_its_endpoint_and_key_from_the_profile(
    kind: ProviderKind,
) -> None:
    profile = ProviderProfile(
        name="p",
        kind=kind,
        base_url="https://gw.example.com/v1" if kind.needs_base_url else None,
        key=KeySource.ENVIRONMENT,
        api_version="2024-10-21" if kind is ProviderKind.AZURE else None,
    )

    client = _openai_provider(_endpoint(profile)).client

    assert str(client.base_url).startswith(ai_sdk.base_url(profile).rstrip("/"))
    assert "invalid" not in str(client.base_url)
    assert client.api_key == "profile-key"


async def test_a_keyless_gateway_sends_the_placeholder_not_the_hosts_openai_key(
    fake: FakeGateway,
) -> None:
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)

    check = await PydanticAiModels().check(profile, "gpt-4.1-mini", ModelRole.LLM)

    assert check.ok, check.error
    (seen,) = fake.seen
    assert seen.path == "/v1/chat/completions"
    assert seen.headers["authorization"] == "Bearer unused"
    assert "openai-organization" not in seen.headers
    assert "openai-project" not in seen.headers


async def test_an_embedding_check_reports_the_dimensions(fake: FakeGateway) -> None:
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)

    check = await PydanticAiModels().check(profile, "text-embedding-3-small", ModelRole.EMBEDDING)

    assert check.ok, check.error
    assert (check.dimensions, check.served_model) == (DIMENSIONS, "text-embedding-3-small")


async def test_a_reranker_check_speaks_the_cohere_dialect(fake: FakeGateway) -> None:
    profile = ProviderProfile(name="corp", kind=ProviderKind.VLLM, base_url=fake.v1)

    check = await PydanticAiModels().check(profile, "bge-reranker", ModelRole.RERANKER)

    assert check.ok, check.error
    assert fake.seen[0].path == "/v1/rerank"


async def test_a_tei_reranker_check_speaks_the_tei_dialect(fake: FakeGateway) -> None:
    profile = ProviderProfile(name="tei", kind=ProviderKind.TEI, base_url=fake.url)

    check = await PydanticAiModels().check(profile, "bge-reranker-base", ModelRole.RERANKER)

    assert check.ok, check.error
    (seen,) = fake.seen
    assert (seen.path, set(seen.body)) == ("/rerank", {"query", "texts", "truncate"})


async def test_a_reranker_sends_the_profiles_key_and_headers_only_to_its_endpoint(
    fake: FakeGateway,
) -> None:
    profile = ProviderProfile(
        name="cohere",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url=f"{fake.url}/v2",
        key=KeySource.ENVIRONMENT,
        headers=(("X-Team", "docs"),),
    )
    models = PydanticAiModels(keys={"cohere": "cohere-key"})

    reranker = await models.reranker(profile, "rerank-v3.5")
    scores = await reranker.rerank("retry", ["a", "b"])

    assert list(scores) == [0.5, 1.0]
    (seen,) = fake.seen
    assert seen.path == "/v2/rerank"
    assert (seen.headers["authorization"], seen.headers["x-team"]) == ("Bearer cohere-key", "docs")


@pytest.mark.parametrize("kind", [ProviderKind.OPENAI, ProviderKind.ANTHROPIC, ProviderKind.OLLAMA])
async def test_a_kind_without_a_rerank_api_cannot_rerank(kind: ProviderKind) -> None:
    profile = ProviderProfile(
        name="other", kind=kind, base_url="https://llm.example.com/v1", key=KeySource.ENVIRONMENT
    )
    models = PydanticAiModels(keys={"other": "k"})

    with pytest.raises(ProviderUnsupportedError, match="has no rerank API"):
        await models.reranker(profile, "rerank")


async def test_a_tei_profile_serves_neither_chat_nor_embeddings(fake: FakeGateway) -> None:
    profile = ProviderProfile(name="tei", kind=ProviderKind.TEI, base_url=fake.url)
    models = PydanticAiModels()

    with pytest.raises(ProviderUnsupportedError, match="reranker only"):
        await models.chat_model(profile, "m")
    with pytest.raises(ProviderUnsupportedError, match="no embeddings"):
        await models.embedder(profile, "m")
    assert not fake.seen


async def test_claude_gets_the_profiles_key_and_endpoint(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="claude", kind=ProviderKind.ANTHROPIC, base_url=fake.url, key=KeySource.ENVIRONMENT
    )
    models = PydanticAiModels(keys={"claude": "claude-key"})

    check = await models.check(profile, "claude-test", ModelRole.LLM)

    assert check.ok, check.error
    (seen,) = fake.seen
    assert seen.path == "/v1/messages", seen
    sent = {seen.headers.get("x-api-key"), seen.headers.get("authorization")}
    assert sent & {"claude-key", "Bearer claude-key"}, seen.headers
    assert not sent & {POISON["ANTHROPIC_API_KEY"], f"Bearer {POISON['ANTHROPIC_API_KEY']}"}


async def test_azure_with_a_key_sends_the_api_version_and_its_key(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="azure",
        kind=ProviderKind.AZURE,
        base_url=fake.url,
        api_version="2024-10-21",
        key=KeySource.ENVIRONMENT,
    )

    check = await PydanticAiModels(keys={"azure": "azure-key"}).check(
        profile, "my-deployment", ModelRole.LLM
    )

    assert check.ok, check.error
    (seen,) = fake.seen
    assert seen.path.startswith("/openai/")
    assert "api-version=2024-10-21" in seen.path
    assert seen.headers["api-key"] == "azure-key"


async def test_azure_with_entra_sends_a_fresh_token_and_no_key(
    official: FakeGateway, entra: FakeEntra
) -> None:
    profile = ProviderProfile(
        name="azure",
        kind=ProviderKind.AZURE,
        origin=ProfileOrigin.CONFIGURATION,
        resource="acme",
        api_version="2024-10-21",
        auth=AzureAuth.ENTRA,
    )
    models = PydanticAiModels()

    first = await models.check(profile, "my-deployment", ModelRole.LLM)
    second = await models.check(profile, "my-deployment", ModelRole.LLM)

    assert first.ok, first.error
    assert second.ok, second.error
    assert entra.providers == 1  # one credential (and its token cache) per profile
    headers = [seen.headers for seen in official.seen]
    assert [h["authorization"] for h in headers] == ["Bearer entra-token-1", "Bearer entra-token-2"]
    assert POISON["AZURE_OPENAI_API_KEY"] not in str(headers)


async def test_claude_on_foundry_with_entra_signs_every_request_with_a_fresh_token(
    official: FakeGateway, entra: FakeEntra
) -> None:
    profile = ProviderProfile(
        name="foundry",
        kind=ProviderKind.ANTHROPIC,
        origin=ProfileOrigin.CONFIGURATION,
        platform=AnthropicPlatform.FOUNDRY,
        resource="acme",
        auth=AzureAuth.ENTRA,
    )
    models = PydanticAiModels()

    await models.check(profile, "claude-test", ModelRole.LLM)
    check = await models.check(profile, "claude-test", ModelRole.LLM)

    assert check.ok, check.error
    assert entra.providers == 1
    tokens = [seen.headers["authorization"] for seen in official.seen]
    assert tokens == ["Bearer entra-token-1", "Bearer entra-token-2"]
    assert all("x-api-key" not in seen.headers for seen in official.seen)


async def test_claude_on_vertex_gets_project_region_and_endpoint_from_the_profile(
    tmp_path: Path,
) -> None:
    profile = ProviderProfile(
        name="vertex-claude",
        kind=ProviderKind.ANTHROPIC,
        origin=ProfileOrigin.CONFIGURATION,
        platform=AnthropicPlatform.VERTEX,
        project="acme-ml",
        location="us-east5",
        credentials_file=str(_service_account(tmp_path)),
    )

    client = await _anthropic_client(_endpoint(profile, key=None))

    assert isinstance(client, AsyncAnthropicVertex)
    assert (client.project_id, client.region) == ("acme-ml", "us-east5")
    assert str(client.base_url) == "https://us-east5-aiplatform.googleapis.com/v1/"


async def test_vertex_calls_the_profiles_project_and_location(
    official: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def credentials(profile: ProviderProfile) -> Credentials:
        del profile
        return Credentials(token="vertex-token")

    monkeypatch.setattr(ai_sdk, "_google_credentials", credentials)
    profile = ProviderProfile(
        name="vertex",
        kind=ProviderKind.GOOGLE_VERTEX,
        origin=ProfileOrigin.CONFIGURATION,
        project="acme-ml",
        location="europe-west4",
        adc=True,
    )

    await PydanticAiModels().check(profile, "gemini-2.5-flash", ModelRole.LLM)

    (seen,) = official.seen
    assert "/projects/acme-ml/locations/europe-west4/" in seen.path
    assert seen.headers["authorization"] == "Bearer vertex-token"
    assert "x-goog-api-key" not in seen.headers


async def test_the_gemini_api_gets_the_profiles_key(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="gemini", kind=ProviderKind.GOOGLE, base_url=fake.url + "/", key=KeySource.ENVIRONMENT
    )

    await PydanticAiModels(keys={"gemini": "gemini-key"}).check(profile, "gemini", ModelRole.LLM)

    (seen,) = fake.seen
    assert seen.headers["x-goog-api-key"] == "gemini-key"


async def test_extra_headers_are_sent_and_their_values_never_reported(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="corp",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url=fake.url + "/broken/v1",  # answers 404: the check fails and says why
        headers=(("X-Team", "header-secret"),),
    )

    check = await PydanticAiModels().check(profile, "m", ModelRole.LLM)

    assert not check.ok
    assert fake.seen[0].headers["x-team"] == "header-secret"
    assert "header-secret" not in (check.error or "")


async def test_a_key_file_is_read_at_each_call(fake: FakeGateway, tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("first-key\n")
    profile = ProviderProfile(
        name="corp",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url=fake.v1,
        key=KeySource.FILE,
        key_file=str(key_file),
    )
    models = PydanticAiModels()
    await models.check(profile, "m", ModelRole.LLM)

    key_file.write_text("rotated-key\n")
    await models.check(profile, "m", ModelRole.LLM)

    assert [s.headers["authorization"] for s in fake.seen] == [
        "Bearer first-key",
        "Bearer rotated-key",
    ]


async def test_the_profiles_proxy_carries_its_calls(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="corp",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="http://upstream.invalid/v1",  # never resolved here: the proxy is asked
        proxy=fake.url,
    )

    check = await PydanticAiModels().check(profile, "m", ModelRole.LLM)

    assert check.ok, check.error
    assert fake.seen[0].path == "http://upstream.invalid/v1/chat/completions"


async def test_a_call_to_another_host_is_refused_by_the_profiles_client() -> None:
    profile = ProviderProfile(
        name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url="http://127.0.0.1:9/v1"
    )
    client = ai_sdk.http_client(profile, "http://127.0.0.1:9/v1")

    with pytest.raises(ForeignHostError):
        await client.get("https://env-openai.invalid/v1/models")
    await client.aclose()


async def test_the_client_is_rebuilt_when_the_profile_changes(fake: FakeGateway) -> None:
    models = PydanticAiModels()
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)
    first = await models.endpoint(profile)
    same = await models.endpoint(profile)
    changed = await models.endpoint(
        ProviderProfile(
            name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1, request_timeout=5
        )
    )

    assert same.client is first.client
    assert changed.client is not first.client
    assert first.client.is_closed


def test_unsupported_names_what_to_install() -> None:
    models = PydanticAiModels()
    bedrock = ProviderProfile(
        name="b",
        kind=ProviderKind.ANTHROPIC,
        origin=ProfileOrigin.CONFIGURATION,
        platform=AnthropicPlatform.BEDROCK,
        location="x",
    )
    gateway_profile = ProviderProfile(
        name="g", kind=ProviderKind.OPENAI_COMPATIBLE, base_url="https://x"
    )

    assert models.unsupported(ProviderProfile(name="l", kind=ProviderKind.LOCAL)) is not None
    assert "boto3" in (models.unsupported(bedrock) or "")
    assert models.unsupported(gateway_profile) is None


def test_settings_become_read_only_profiles_with_keys_kept_in_bootstrap(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("k")
    ai = AiSettings.model_validate(
        {
            "providers": {
                "corp": {
                    "kind": "openai-compatible",
                    "base_url": "https://llm.example.com/v1",
                    "api_key": "env-key",
                    "headers": {"X-Team": "docs"},
                },
                "files": {"kind": "openai", "api_key_file": str(key_file)},
            },
            "llm": {"model": "corp:gpt-4.1-mini"},
            "embedding": {"model": "corp:text-embedding-3-small", "dimensions": 1024},
        }
    )

    configured = configured_ai(ai)

    corp, files = sorted(configured.profiles, key=lambda p: p.name)
    assert (corp.key, files.key, files.key_file) == (
        KeySource.ENVIRONMENT,
        KeySource.FILE,
        str(key_file),
    )
    assert all(p.read_only for p in configured.profiles)
    assert dict(configured.keys) == {"corp": "env-key"}
    assert "env-key" not in repr(configured)
    assert str(configured.roles.llm) == "corp:gpt-4.1-mini"


def test_a_missing_key_file_is_refused_at_start(tmp_path: Path) -> None:
    ai = AiSettings.model_validate(
        {"providers": {"corp": {"kind": "openai", "api_key_file": str(tmp_path / "none")}}}
    )

    with pytest.raises(InvalidProviderError, match="api_key_file"):
        configured_ai(ai)


def _service_account(tmp_path: Path) -> Path:
    """A service-account file with a throwaway RSA key (never used: no call is made)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "acme-ml",
                "private_key_id": "1",
                "private_key": pem,
                "client_email": "sa@acme-ml.iam.gserviceaccount.com",
                "client_id": "1",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )
    return path


async def test_the_sdks_header_variables_never_replace_the_profiles_key(
    fake: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENAI_CUSTOM_HEADERS", "ANTHROPIC_CUSTOM_HEADERS"):  # set again: removed once
        monkeypatch.setenv(name, POISON[name])
    openai_profile = ProviderProfile(
        name="corp",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url=fake.v1,
        key=KeySource.ENVIRONMENT,
    )
    azure = ProviderProfile(
        name="azure",
        kind=ProviderKind.AZURE,
        base_url=fake.url,
        api_version="2024-10-21",
        key=KeySource.ENVIRONMENT,
    )
    claude = ProviderProfile(
        name="claude", kind=ProviderKind.ANTHROPIC, base_url=fake.url, key=KeySource.ENVIRONMENT
    )
    models = PydanticAiModels(keys={"corp": "corp-key", "azure": "azure-key", "claude": "c-key"})

    for profile in (openai_profile, azure, claude):
        check = await models.check(profile, "m", ModelRole.LLM)
        assert check.ok, check.error

    corp_seen, azure_seen, claude_seen = (seen.headers for seen in fake.seen)
    assert corp_seen["authorization"] == "Bearer corp-key"
    assert azure_seen["api-key"] == "azure-key"
    assert {claude_seen.get("x-api-key"), claude_seen.get("authorization")} & {
        "c-key",
        "Bearer c-key",
    }
    assert "env-custom" not in json.dumps([seen.headers for seen in fake.seen])


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9/v1/models",  # another scheme
        "https://127.0.0.1:10/v1/models",  # another port
        "https://env-openai.invalid/v1/models",  # another host
    ],
)
async def test_the_guard_compares_scheme_host_and_port(url: str) -> None:
    profile = ProviderProfile(
        name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url="https://127.0.0.1:9/v1"
    )
    client = ai_sdk.http_client(profile, "https://127.0.0.1:9/v1")

    with pytest.raises(ForeignHostError):
        await client.get(url)
    await client.aclose()


async def test_a_released_profile_closes_its_client(fake: FakeGateway) -> None:
    models = PydanticAiModels()
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)
    endpoint = await models.endpoint(profile)

    await models.release("corp")

    assert endpoint.client.is_closed
    assert (await models.endpoint(profile)).client is not endpoint.client


async def test_two_first_calls_build_one_client(fake: FakeGateway) -> None:
    models = PydanticAiModels()
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)

    first, second = await asyncio.gather(models.endpoint(profile), models.endpoint(profile))

    assert first.client is second.client


@pytest.mark.parametrize(
    ("fields", "official"),
    [
        (
            {"kind": ProviderKind.GOOGLE_VERTEX, "project": "p", "location": "europe-west4"},
            "https://europe-west4-aiplatform.googleapis.com/",
        ),
        (
            {"kind": ProviderKind.GOOGLE_VERTEX, "project": "p", "location": "global"},
            "https://aiplatform.googleapis.com/",
        ),
        (
            {
                "kind": ProviderKind.AZURE,
                "resource": "acme",
                "api_version": "v",
                "auth": AzureAuth.ENTRA,
            },
            "https://acme.openai.azure.com",
        ),
        (
            {
                "kind": ProviderKind.ANTHROPIC,
                "platform": AnthropicPlatform.FOUNDRY,
                "resource": "acme",
                "auth": AzureAuth.ENTRA,
            },
            "https://acme.services.ai.azure.com/anthropic/",
        ),
        (
            {
                "kind": ProviderKind.ANTHROPIC,
                "platform": AnthropicPlatform.VERTEX,
                "project": "p",
                "location": "us-east5",
            },
            "https://us-east5-aiplatform.googleapis.com/v1",
        ),
    ],
)
def test_the_servers_cloud_identity_only_reaches_the_official_endpoint(
    fields: dict, official: str
) -> None:
    ambient = {"adc": True} if "auth" not in fields else {}
    profile = ProviderProfile(name="cloud", origin=ProfileOrigin.CONFIGURATION, **fields, **ambient)

    assert ai_sdk.base_url(profile) == official


@pytest.mark.parametrize(
    ("host", "official"),
    [
        ("evil.example/x?.openai.azure.com", AZURE_OPENAI_HOST),
        ("x@evil.services.ai.azure.com", FOUNDRY_HOST),
        ("a.evil.com", AZURE_OPENAI_HOST),
        ("evil.cloudapp.azure.com", AZURE_OPENAI_HOST),  # under azure.com, a customer's name
        ("evil.openai.azure.com", FOUNDRY_HOST),
        ("evil.example#.googleapis.com", VERTEX_HOST),
        ("storage.googleapis.com", VERTEX_HOST),
        ("bedrock-runtime.x%2Fevil.amazonaws.com", BEDROCK_HOST),
        ("evil.s3.amazonaws.com", BEDROCK_HOST),
    ],
)
def test_a_derived_host_that_is_not_the_providers_endpoint_is_refused(
    host: str, official: re.Pattern[str]
) -> None:
    profile = ProviderProfile(name="p", kind=ProviderKind.OPENAI_COMPATIBLE, base_url="https://x")

    with pytest.raises(ProviderUnsupportedError, match="would not be the provider's own"):
        _official_url(profile, host, "/", official)


def test_the_profiles_proxy_goes_only_to_the_credentials_that_call_entra_id() -> None:
    profile = ProviderProfile(
        name="azure",
        kind=ProviderKind.AZURE,
        origin=ProfileOrigin.CONFIGURATION,
        resource="acme",
        api_version="v",
        auth=AzureAuth.ENTRA,
        proxy="http://proxy.example.com:3128",
    )
    proxies = {"proxies": {"http": profile.proxy, "https": profile.proxy}}

    plain = ai_sdk.entra_chain(profile, {})
    federated = ai_sdk.entra_chain(profile, {"AZURE_FEDERATED_TOKEN_FILE": "/var/run/token"})
    user_assigned = ai_sdk.entra_chain(profile, {"AZURE_CLIENT_ID": "1111-2222"})

    assert plain == [(EnvironmentCredential, proxies), (ManagedIdentityCredential, {})]
    assert federated == [
        (EnvironmentCredential, proxies),
        (WorkloadIdentityCredential, proxies),
        (ManagedIdentityCredential, {}),  # IMDS / IDENTITY_ENDPOINT: never through the proxy
    ]
    # A user-assigned managed identity is chosen by AZURE_CLIENT_ID, as DefaultAzureCredential did.
    assert user_assigned[-1] == (ManagedIdentityCredential, {"client_id": "1111-2222"})


async def test_the_factorys_models_are_instrumented_without_content(fake: FakeGateway) -> None:
    # Prompts never reach a span: include_content=False is the first guard (*Telemetry*).
    profile = ProviderProfile(name="corp", kind=ProviderKind.OPENAI_COMPATIBLE, base_url=fake.v1)
    models = PydanticAiModels()

    chat = await models.chat_model(profile, "gpt-4.1-mini")
    embedder = await models.embedder(profile, "text-embedding-3-small")

    assert isinstance(chat, InstrumentedModel)
    assert chat.instrumentation_settings.include_content is False
    assert isinstance(embedder, Embedder)
    assert isinstance(embedder.instrument, InstrumentationSettings)
    assert embedder.instrument.include_content is False


def test_the_reranker_top_n_and_timeout_are_read_with_their_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__RERANKER__MODEL", "rr:rerank-v3.5")
    monkeypatch.setenv("EXACTDOCS_AI__RERANKER__TOP_N", "12")
    monkeypatch.setenv("EXACTDOCS_AI__RERANKER__TIMEOUT", "0.5")

    reranker = Settings().ai.reranker

    assert (reranker.model, reranker.top_n, reranker.timeout) == ("rr:rerank-v3.5", 12, 0.5)
    assert (AiSettings().reranker.top_n, AiSettings().reranker.timeout) == (32, None)


@pytest.mark.parametrize("role", [{"top_n": 0}, {"top_n": 201}, {"timeout": 0}, {"timeout": 61}])
def test_reranker_limits_out_of_bounds_are_refused(role: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        AiSettings.model_validate({"reranker": role})


def test_a_sealed_key_that_no_longer_opens_says_so_without_the_key() -> None:
    profile = ProviderProfile(
        name="corp",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://llm.example.com/v1",
        key=KeySource.SEALED,
        sealed_key="gAAAA-sealed-with-another-key",
    )

    def refuse(sealed: str) -> str:
        del sealed
        raise SealedTextUnreadableError

    with pytest.raises(ProviderUnsupportedError, match="does not open") as error:
        ai_sdk.read_key(profile, None, refuse)

    assert "gAAAA" not in str(error.value)


async def test_the_provider_sdks_load_in_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_in: list[str] = []

    def record(name: str) -> object:
        assert name == AI_SDK_MODULE
        loaded_in.append(threading.current_thread().name)
        return ai_sdk

    monkeypatch.delitem(sys.modules, AI_SDK_MODULE)
    monkeypatch.setattr(ai_models.importlib, "import_module", record)

    await PydanticAiModels().warm()

    assert len(loaded_in) == 1
    assert loaded_in[0] != threading.main_thread().name


async def test_the_first_call_loads_the_provider_sdks_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, fake: FakeGateway
) -> None:
    loaded_in: list[str] = []

    def record(name: str) -> object:
        assert name == AI_SDK_MODULE
        loaded_in.append(threading.current_thread().name)
        return ai_sdk

    monkeypatch.delitem(sys.modules, AI_SDK_MODULE)
    monkeypatch.setattr(ai_models.importlib, "import_module", record)
    profile = ProviderProfile(name="rr", kind=ProviderKind.TEI, base_url=fake.url)

    reranker = await PydanticAiModels().reranker(profile, "bge")

    assert loaded_in
    assert threading.main_thread().name not in loaded_in
    assert reranker is not None


async def test_the_sdks_are_warmed_at_start_when_any_profile_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    warmed: list[bool] = []

    async def record(self: PydanticAiModels) -> None:
        del self
        warmed.append(True)

    monkeypatch.setattr(PydanticAiModels, "warm", record)
    nothing = Container.build(Settings(data_dir=tmp_path / "none"))
    profile_only = Container.build(
        Settings(
            data_dir=tmp_path / "profile",
            ai=AiSettings.model_validate(
                {"providers": {"rr": {"kind": "tei", "base_url": "http://tei.internal:8080"}}}
            ),
        )
    )

    async with nothing.running(jobs=False):
        assert warmed == []
    async with profile_only.running(jobs=False):
        assert warmed == [True]


async def test_a_failed_sdk_load_at_start_is_a_warning_not_a_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(name: str) -> object:
        message = f"cannot import name 'secret' from 'openai' ({name})"
        raise ImportError(message)

    monkeypatch.delitem(sys.modules, AI_SDK_MODULE)
    monkeypatch.setattr(ai_models.importlib, "import_module", broken)
    container = Container.build(
        Settings(
            data_dir=tmp_path,
            ai=AiSettings.model_validate(
                {"providers": {"rr": {"kind": "tei", "base_url": "http://tei.internal:8080"}}}
            ),
        )
    )

    async with container.running(jobs=False):
        pass

    warnings = [r for r in caplog.records if "could not be loaded" in r.getMessage()]
    assert [r.levelname for r in warnings] == ["WARNING"]
    assert "(ImportError)" in warnings[0].getMessage()
    assert "openai" not in caplog.text


def test_the_agentic_limits_refuse_a_snippet_as_long_as_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__SANDBOX_SECONDS", "30")
    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__TIMEOUT", "30")

    with pytest.raises(ValidationError, match="sandbox_seconds must be less than timeout"):
        Settings()


def test_the_agentic_limits_reach_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__MAX_TOOL_CALLS", "7")
    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__SANDBOX_SECONDS", "2")

    agentic = Settings().ai.agentic

    assert (agentic.max_tool_calls, agentic.sandbox_seconds, agentic.timeout) == (7, 2.0, 120.0)


def test_the_loop_threshold_is_3_by_default_and_set_by_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().ai.agentic.max_repeated_calls == 3

    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__MAX_REPEATED_CALLS", "5")

    assert Settings().ai.agentic.max_repeated_calls == 5


def test_one_call_is_never_a_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__AGENTIC__MAX_REPEATED_CALLS", "1")

    with pytest.raises(ValidationError, match="max_repeated_calls"):
        Settings()


# ---------------------------------------------------------------- thinking level (#421)
# Each provider gets the level as its own control, built by pydantic-ai: the request the fake
# gateway records is the one the provider would get (no network).

LOW = ThinkingLevel.LOW


async def _thinking_body(
    fake: FakeGateway, kind: ProviderKind, model: str, suffix: str, level: ThinkingLevel | None
) -> dict[str, Any]:
    profile = ProviderProfile(
        name="p", kind=kind, base_url=fake.url + suffix, key=KeySource.ENVIRONMENT
    )
    await PydanticAiModels(keys={"p": "k"}).check(profile, model, ModelRole.LLM, thinking=level)
    (seen,) = fake.seen
    return seen.body


async def test_vertex_gemini_4_gets_googles_thinking_level(
    official: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def credentials(profile: ProviderProfile) -> Credentials:
        del profile
        return Credentials(token="vertex-token")

    monkeypatch.setattr(ai_sdk, "_google_credentials", credentials)
    profile = ProviderProfile(
        name="gcp",
        kind=ProviderKind.GOOGLE_VERTEX,
        origin=ProfileOrigin.CONFIGURATION,
        project="acme-ml",
        location="global",
        adc=True,
    )

    check = await PydanticAiModels().check(
        profile, "gemini-4-hydrogen", ModelRole.LLM, thinking=LOW
    )

    assert check.ok, check.error
    (seen,) = official.seen
    assert seen.path.endswith("/models/gemini-4-hydrogen:generateContent"), seen.path
    config = seen.body["generationConfig"]["thinkingConfig"]
    assert config["thinking_level"] == "LOW", seen.body
    assert "thinking_budget" not in config


async def test_gemini_2_5_gets_a_thinking_budget(fake: FakeGateway) -> None:
    body = await _thinking_body(fake, ProviderKind.GOOGLE, "gemini-2.5-flash", "/", LOW)

    assert body["generationConfig"]["thinkingConfig"]["thinking_budget"] == 2048, body


async def test_claude_with_adaptive_thinking_gets_its_effort(fake: FakeGateway) -> None:
    body = await _thinking_body(fake, ProviderKind.ANTHROPIC, "claude-sonnet-5-5", "", LOW)

    assert body["thinking"] == {"type": "adaptive"}, body
    assert body["output_config"] == {"effort": "low"}, body


async def test_older_claude_gets_a_budget_with_room_above_the_answers_cap(
    fake: FakeGateway,
) -> None:
    body = await _thinking_body(fake, ProviderKind.ANTHROPIC, "claude-haiku-4-5", "", LOW)

    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2048}, body
    assert body["max_tokens"] == CHECK_MAX_TOKENS + 2048, "the budget counts toward max_tokens"


async def test_openai_reasoning_models_get_their_reasoning_effort(fake: FakeGateway) -> None:
    body = await _thinking_body(fake, ProviderKind.OPENAI, "gpt-5", "/v1", LOW)

    assert body["reasoning"]["effort"] == "low", body


async def test_azure_deployments_get_reasoning_effort(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="az",
        kind=ProviderKind.AZURE,
        base_url=fake.url,
        api_version="2024-10-21",
        key=KeySource.ENVIRONMENT,
    )

    await PydanticAiModels(keys={"az": "k"}).check(
        profile, "corp-reasoner", ModelRole.LLM, thinking=ThinkingLevel.XHIGH
    )

    (seen,) = fake.seen
    assert seen.body["reasoning_effort"] == "xhigh", seen.body


@pytest.mark.parametrize(
    "kind", [ProviderKind.OPENAI_COMPATIBLE, ProviderKind.OLLAMA, ProviderKind.VLLM]
)
async def test_openai_compatible_kinds_get_reasoning_effort(
    fake: FakeGateway, kind: ProviderKind
) -> None:
    body = await _thinking_body(fake, kind, "corp-model", "/v1", ThinkingLevel.MINIMAL)

    assert body["reasoning_effort"] == "minimal", body


async def test_openrouter_gets_its_reasoning_effort(fake: FakeGateway) -> None:
    body = await _thinking_body(fake, ProviderKind.OPENROUTER, "acme/model", "/v1", LOW)

    assert body["reasoning"]["effort"] == "low", body


@pytest.mark.parametrize(
    ("kind", "model", "suffix"),
    [
        (ProviderKind.GOOGLE, "gemini-4-hydrogen", "/"),
        (ProviderKind.ANTHROPIC, "claude-sonnet-5-5", ""),
        (ProviderKind.OPENAI_COMPATIBLE, "corp-model", "/v1"),
    ],
)
async def test_no_level_sends_no_thinking_setting(
    fake: FakeGateway, kind: ProviderKind, model: str, suffix: str
) -> None:
    body = await _thinking_body(fake, kind, model, suffix, None)

    assert not {"thinking", "output_config", "reasoning", "reasoning_effort"} & body.keys()
    assert "thinkingConfig" not in body.get("generationConfig", {}), body


@pytest.mark.parametrize(
    ("kind", "model", "suffix"),
    [(ProviderKind.GOOGLE, "gemini-2.0-flash", "/"), (ProviderKind.OPENAI, "gpt-4.1", "/v1")],
)
async def test_a_model_known_not_to_think_is_named_and_called_without_a_level(
    fake: FakeGateway, kind: ProviderKind, model: str, suffix: str
) -> None:
    profile = ProviderProfile(
        name="p", kind=kind, base_url=fake.url + suffix, key=KeySource.ENVIRONMENT
    )
    models = PydanticAiModels(keys={"p": "k"})

    reason = await models.thinking_unsupported(profile, model)
    body = await _thinking_body(fake, kind, model, suffix, ThinkingLevel.HIGH)

    assert reason == f"{kind.value} serves it without a thinking or reasoning setting"
    assert not {"reasoning", "reasoning_effort"} & body.keys()
    assert "thinkingConfig" not in body.get("generationConfig", {}), body


async def test_thinking_support_is_unknown_behind_an_openai_compatible_endpoint() -> None:
    profile = ProviderProfile(
        name="gw", kind=ProviderKind.VLLM, base_url="https://llm.example.com/v1"
    )

    assert await PydanticAiModels().thinking_unsupported(profile, "any-model") is None


def test_the_thinking_level_is_read_from_the_environment_in_any_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__LLM__MODEL", "gcp:gemini-4-hydrogen")
    monkeypatch.setenv("EXACTDOCS_AI__LLM__THINKING", "Low")
    monkeypatch.setenv("EXACTDOCS_AI__JUDGE__THINKING", "")

    ai = Settings().ai
    roles = configured_ai(ai).roles

    assert (ai.llm.thinking, ai.judge.thinking) == (ThinkingLevel.LOW, None)
    assert (roles.llm_thinking, roles.judge_thinking) == (ThinkingLevel.LOW, None)


def test_an_unknown_thinking_level_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACTDOCS_AI__JUDGE__THINKING", "max")

    with pytest.raises(ValidationError, match=r"judge.thinking"):
        Settings()


def test_the_thinking_level_is_read_from_the_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "exactdocs.toml"
    config.write_text('[ai.judge]\nmodel = "p:m"\nthinking = "minimal"\n', encoding="utf-8")
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(config))

    assert Settings().ai.judge.thinking is ThinkingLevel.MINIMAL
