"""#241: the ModelFactory builds every SDK client from explicit values, never the environment.

Each test runs with the SDKs' environment variables set to values that must not be used: keys,
base URLs, projects, regions. Real pydantic-ai calls go to a fake gateway on loopback, which
records what each request carried.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from anthropic import AsyncAnthropicVertex
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.oauth2.credentials import Credentials

from exactdocs.bootstrap import ai_sdk
from exactdocs.bootstrap.ai_endpoint import Endpoint
from exactdocs.bootstrap.ai_models import PydanticAiModels, configured_ai
from exactdocs.bootstrap.ai_sdk import ForeignHostError, _anthropic_client, _openai_provider
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.errors import InvalidProviderError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    KeySource,
    ModelRole,
    ProviderKind,
    ProviderProfile,
)
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


@pytest.fixture
def entra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entra ID without Azure: the token provider hands out a fixed token."""

    def provider() -> Callable[[], str]:
        return lambda: "entra-token"

    monkeypatch.setattr(ai_sdk, "_entra_token_provider", provider)


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


@pytest.mark.usefixtures("entra")
async def test_azure_with_entra_sends_a_token_and_no_key(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="azure",
        kind=ProviderKind.AZURE,
        base_url=fake.url,
        api_version="2024-10-21",
        auth=AzureAuth.ENTRA,
    )

    check = await PydanticAiModels().check(profile, "my-deployment", ModelRole.LLM)

    assert check.ok, check.error
    (seen,) = fake.seen
    assert seen.headers["authorization"] == "Bearer entra-token"
    assert seen.headers.get("api-key") != POISON["AZURE_OPENAI_API_KEY"]


@pytest.mark.usefixtures("entra")
async def test_claude_on_foundry_with_entra_reads_no_foundry_variable(fake: FakeGateway) -> None:
    profile = ProviderProfile(
        name="foundry",
        kind=ProviderKind.ANTHROPIC,
        platform=AnthropicPlatform.FOUNDRY,
        base_url=fake.url + "/anthropic/",
        auth=AzureAuth.ENTRA,
    )

    check = await PydanticAiModels().check(profile, "claude-test", ModelRole.LLM)

    assert check.ok, check.error
    (seen,) = fake.seen
    assert seen.headers["authorization"] == "Bearer entra-token"
    assert seen.headers.get("x-api-key") != POISON["ANTHROPIC_FOUNDRY_API_KEY"]


async def test_claude_on_vertex_gets_project_region_and_endpoint_from_the_profile(
    tmp_path: Path,
) -> None:
    profile = ProviderProfile(
        name="vertex-claude",
        kind=ProviderKind.ANTHROPIC,
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
    fake: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def credentials(profile: ProviderProfile) -> Credentials:
        del profile
        return Credentials(token="vertex-token")

    monkeypatch.setattr(ai_sdk, "_google_credentials", credentials)
    profile = ProviderProfile(
        name="vertex",
        kind=ProviderKind.GOOGLE_VERTEX,
        base_url=fake.url + "/",
        project="acme-ml",
        location="europe-west4",
        adc=True,
    )

    await PydanticAiModels().check(profile, "gemini-2.5-flash", ModelRole.LLM)

    (seen,) = fake.seen
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
        headers=(("X-Gateway-Token", "header-secret"),),
    )

    check = await PydanticAiModels().check(profile, "m", ModelRole.LLM)

    assert not check.ok
    assert fake.seen[0].headers["x-gateway-token"] == "header-secret"
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
        name="b", kind=ProviderKind.ANTHROPIC, platform=AnthropicPlatform.BEDROCK, location="x"
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
