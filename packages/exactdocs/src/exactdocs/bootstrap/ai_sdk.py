"""The pydantic-ai side of the ``ModelFactory`` (#241): loaded only once a model is called.

``ai_models.PydanticAiModels`` imports this module the first time a configured role is used (a
check, an embedding, a chat turn), never at start: with nothing configured, nothing of the
``[ai]`` extra is imported (RUN-02).

Every SDK client is built with explicit values only: the endpoint, the key (``unused`` for a
profile without one), the project, location and credentials, the API version. No model is ever
built from a ``"<provider>:<model>"`` string, which would let pydantic-ai infer the provider and
the SDKs read ``OPENAI_API_KEY``, ``*_BASE_URL`` and the like from the environment. Every call
goes through the profile's own ``httpx2`` client: its proxy on the transport (the environment's
proxy variables are not read), its extra headers, one retry layer (the SDK's), an overall
timeout, and a guard that refuses any host but the profile's endpoint.
"""

import asyncio
import importlib
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import google.auth
import httpx2
from anthropic import AnthropicError, AsyncAnthropic, AsyncAnthropicVertex
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.genai.errors import APIError as GoogleAPIError
from google.genai.types import HttpRetryOptions
from google.oauth2 import service_account
from openai import AsyncAzureOpenAI, AsyncOpenAI, OpenAIError
from pydantic_ai import Embedder
from pydantic_ai.direct import model_request
from pydantic_ai.embeddings.google import GoogleEmbeddingModel
from pydantic_ai.exceptions import AgentRunError, UserError
from pydantic_ai.messages import ModelRequest
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.cerebras import CerebrasModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers import Provider
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.cerebras import CerebrasProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.fireworks import FireworksProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.providers.heroku import HerokuProvider
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.providers.moonshotai import MoonshotAIProvider
from pydantic_ai.providers.nebius import NebiusProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.providers.ovhcloud import OVHcloudProvider
from pydantic_ai.providers.sambanova import SambaNovaProvider
from pydantic_ai.providers.together import TogetherProvider
from pydantic_ai.providers.vercel import VercelProvider
from pydantic_ai.providers.vllm import VLLMProvider
from pydantic_ai.settings import ModelSettings

from exactdocs.bootstrap.ai_endpoint import Endpoint
from exactdocs.bootstrap.constants import (
    AMBIENT_HEADERS,
    AZURE_SCOPE,
    CHECK_MAX_TOKENS,
    CHECK_PROMPT,
    DEFAULT_BASE_URLS,
    GOOGLE_SCOPE,
    NO_KEY,
    SDK_HEADER_VARIABLES,
)
from exactdocs.retrieval.errors import ProviderUnsupportedError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    KeySource,
    ProviderKind,
    ProviderProfile,
)

logger = logging.getLogger(__name__)


class ForeignHostError(httpx2.TransportError):
    """A call of a profile tried to reach another host than the profile's endpoint."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Guard:
    """The request hook of a profile's client: its endpoint only, its own headers only.

    It refuses another scheme, host or port (also on every redirect hop: httpx runs request hooks
    for each), drops ``OpenAI-Organization`` / ``OpenAI-Project`` that the SDK filled from the
    environment, and, for Claude on Foundry with Entra ID, signs each request with a fresh token.
    """

    origin: tuple[str, str, int | None]
    """The only scheme, host and port the profile's calls may reach."""
    own_headers: frozenset[str]
    """Header names the profile sets itself (lower case): kept even when ambient."""
    bearer: Callable[[], str] | None = field(default=None, repr=False)
    """Gives an Entra ID token for each request (the sync provider caches and refreshes it)."""

    async def __call__(self, request: httpx2.Request) -> None:
        """Refuse another endpoint; drop headers an SDK filled from the environment.

        Args:
            request: The outgoing request.

        Raises:
            ForeignHostError: The request is not for the profile's endpoint.
        """
        url = request.url
        if (url.scheme, url.host, url.port) != self.origin:
            scheme, host, _ = self.origin
            message = f"refused a call to {url.scheme}://{url.host}: this profile may only reach {scheme}://{host}"
            raise ForeignHostError(message, request=request)
        for name in AMBIENT_HEADERS - self.own_headers:
            request.headers.pop(name, None)
        if self.bearer is not None:
            token = await asyncio.to_thread(self.bearer)
            request.headers.pop("x-api-key", None)
            request.headers["authorization"] = f"Bearer {token}"


def without_sdk_header_variables() -> None:
    """Drop ``OPENAI_CUSTOM_HEADERS`` and ``ANTHROPIC_CUSTOM_HEADERS`` from this process.

    The OpenAI and Anthropic SDKs merge them into every client's headers *after* the key, in
    their constructors (also in ``copy``/``with_options``, which call the constructor again), so
    a credential there would replace each profile's own key, on every profile of that family.
    ExactDocs has no use for them, so they are removed before any SDK client is built.
    """
    for variable in SDK_HEADER_VARIABLES:
        if os.environ.pop(variable, None) is not None:
            logger.warning(
                "%s is set: ignored, so it cannot replace an AI provider's own key", variable
            )


def base_url(profile: ProviderProfile) -> str:
    """Spell out the endpoint of a profile, never leaving it to an SDK's environment variable.

    Args:
        profile: The profile.

    Returns:
        The base URL its calls go to.

    Raises:
        ProviderUnsupportedError: For ``local``, which has no endpoint.
    """
    kind = profile.kind
    if kind is ProviderKind.ANTHROPIC:
        return _anthropic_base_url(profile)
    if kind is ProviderKind.GOOGLE_VERTEX:
        return profile.base_url or _vertex_base_url(
            profile.location, express=profile.key is not KeySource.NONE
        )
    if kind is ProviderKind.AZURE and profile.resource:
        return f"https://{profile.resource}.openai.azure.com"
    if profile.base_url:
        return profile.base_url
    if kind.value in DEFAULT_BASE_URLS:
        return DEFAULT_BASE_URLS[kind.value]
    raise ProviderUnsupportedError(profile.name, f"kind {kind.value} has no endpoint")


def _anthropic_base_url(profile: ProviderProfile) -> str:
    """The endpoint of an ``anthropic`` profile on its platform.

    Args:
        profile: The profile.

    Returns:
        The base URL.
    """
    match profile.anthropic_platform:
        case AnthropicPlatform.API:
            return profile.base_url or DEFAULT_BASE_URLS["anthropic"]
        case AnthropicPlatform.VERTEX:
            return _vertex_base_url(profile.location, express=False) + "v1"
        case AnthropicPlatform.FOUNDRY:
            return (
                profile.base_url or f"https://{profile.resource}.services.ai.azure.com/anthropic/"
            )
        case AnthropicPlatform.BEDROCK:
            return f"https://bedrock-runtime.{profile.location}.amazonaws.com"


def _vertex_base_url(location: str | None, *, express: bool) -> str:
    """Vertex AI's endpoint for a location, as the Google and Anthropic SDKs derive it.

    Args:
        location: The location (``global``, ``us``, ``eu`` or a region).
        express: Vertex Express mode (a key, no location): the global endpoint.

    Returns:
        The base URL, ending in ``/``.
    """
    if express and not location:
        return "https://aiplatform.googleapis.com/"
    match location:
        case "global" | None:
            return "https://aiplatform.googleapis.com/"
        case "us" | "eu":
            return f"https://aiplatform.{location}.rep.googleapis.com/"
        case _:
            return f"https://{location}-aiplatform.googleapis.com/"


def read_key(
    profile: ProviderProfile, environment_key: str | None, open_sealed: Callable[[str], str] | None
) -> str | None:
    """Produce the profile's key from where it lives.

    Args:
        profile: The profile.
        environment_key: The key bootstrap holds for an environment profile.
        open_sealed: Opens a sealed key (the secret box); ``None`` when there is none.

    Returns:
        The key, or ``None`` for a profile without one.

    Raises:
        ProviderUnsupportedError: The key cannot be produced (no secret box, no file).
    """
    match profile.key:
        case KeySource.NONE:
            return None
        case KeySource.ENVIRONMENT:
            return environment_key
        case KeySource.FILE:
            try:
                return Path(profile.key_file or "").read_text("utf-8").strip()
            except OSError:
                reason = "its api_key_file cannot be read"
                raise ProviderUnsupportedError(profile.name, reason) from None
        case KeySource.SEALED:
            if open_sealed is None or profile.sealed_key is None:
                reason = "its key is sealed and this process has no secret key to open it"
                raise ProviderUnsupportedError(profile.name, reason)
            return open_sealed(profile.sealed_key)


def http_client(
    profile: ProviderProfile, url: str, *, bearer: Callable[[], str] | None = None
) -> httpx2.AsyncClient:
    """Build the profile's one HTTP client.

    Args:
        profile: The profile.
        url: Its endpoint; the client reaches nothing else.
        bearer: Signs every request with an Entra ID token (Claude on Foundry with Entra ID).

    Returns:
        A client with the proxy on its transport, the extra headers, no retries of its own (the
        SDK's are the one retry layer), an overall timeout and the host guard.
    """
    transport = httpx2.AsyncHTTPTransport(proxy=profile.proxy, retries=0, trust_env=False)
    parts = httpx2.URL(url)
    guard = _Guard(
        origin=(parts.scheme, parts.host, parts.port),
        own_headers=frozenset(name.lower() for name in profile.header_names),
        bearer=bearer,
    )
    return httpx2.AsyncClient(
        transport=transport,
        headers=dict(profile.headers),
        timeout=httpx2.Timeout(profile.request_timeout),
        trust_env=False,
        event_hooks={"request": [guard]},
    )


def _openai_client(endpoint: Endpoint) -> AsyncOpenAI:
    """An OpenAI SDK client on the endpoint, with every value explicit.

    Args:
        endpoint: The profile's endpoint.

    Returns:
        The client.
    """
    without_sdk_header_variables()
    profile = endpoint.profile
    return AsyncOpenAI(
        base_url=endpoint.base_url,
        api_key=endpoint.key or NO_KEY,
        http_client=endpoint.client,
        max_retries=profile.max_retries,
        timeout=profile.request_timeout,
    )


def entra_token_provider(profile: ProviderProfile) -> Callable[[], str]:
    """Entra ID tokens through the sync credential (``azure.identity.aio`` would need aiohttp).

    Built once per profile (``ai_models`` keeps it on the endpoint), so its token cache lives
    as long as the profile: the credential asks Entra ID or the managed-identity endpoint again
    only when the token is about to expire, about once an hour. Managed identity, workload
    identity or a client secret from the environment: the Entra ID variables are the identity
    the operator chose with ``auth = "entra"``. The developer tools (Azure CLI, PowerShell,
    VS Code) are left out: a server never signs in as a person. The profile's proxy carries the
    token requests too.

    Args:
        profile: The profile.

    Returns:
        A callable returning a bearer token.
    """
    proxies = {"http": profile.proxy, "https": profile.proxy} if profile.proxy else None
    credential = DefaultAzureCredential(
        exclude_cli_credential=True,
        exclude_developer_cli_credential=True,
        exclude_powershell_credential=True,
        exclude_visual_studio_code_credential=True,
        exclude_shared_token_cache_credential=True,
        exclude_interactive_browser_credential=True,
        exclude_broker_credential=True,
        proxies=proxies,
    )
    return get_bearer_token_provider(credential, AZURE_SCOPE)


def _azure_client(endpoint: Endpoint) -> AsyncAzureOpenAI:
    """Azure OpenAI with an explicit endpoint, API version, and a key or an Entra ID token.

    Args:
        endpoint: The profile's endpoint.

    Returns:
        The client.
    """
    without_sdk_header_variables()
    profile = endpoint.profile
    if endpoint.token_provider is not None:
        return AsyncAzureOpenAI(
            azure_endpoint=endpoint.base_url,
            api_version=profile.api_version,
            azure_ad_token_provider=endpoint.token_provider,
            http_client=endpoint.client,
            max_retries=profile.max_retries,
            timeout=profile.request_timeout,
        )
    return AsyncAzureOpenAI(
        azure_endpoint=endpoint.base_url,
        api_version=profile.api_version,
        api_key=endpoint.key or NO_KEY,
        http_client=endpoint.client,
        max_retries=profile.max_retries,
        timeout=profile.request_timeout,
    )


def _openai_providers() -> dict[ProviderKind, Callable[..., Provider[AsyncOpenAI]]]:
    """pydantic-ai's provider class of each OpenAI-API kind (the rest use ``OpenAIProvider``).

    GitHub Models uses ``OpenAIProvider``: pydantic-ai 2.60 deprecates its own provider.

    Returns:
        The provider class by kind.
    """
    return {
        ProviderKind.OPENROUTER: OpenRouterProvider,
        ProviderKind.OLLAMA: OllamaProvider,
        ProviderKind.VLLM: VLLMProvider,
        ProviderKind.LITELLM: LiteLLMProvider,
        ProviderKind.DEEPSEEK: DeepSeekProvider,
        ProviderKind.TOGETHER: TogetherProvider,
        ProviderKind.FIREWORKS: FireworksProvider,
        ProviderKind.CEREBRAS: CerebrasProvider,
        ProviderKind.VERCEL: VercelProvider,
        ProviderKind.MOONSHOTAI: MoonshotAIProvider,
        ProviderKind.HEROKU: HerokuProvider,
        ProviderKind.NEBIUS: NebiusProvider,
        ProviderKind.OVHCLOUD: OVHcloudProvider,
        ProviderKind.SAMBANOVA: SambaNovaProvider,
        ProviderKind.ALIBABA: AlibabaProvider,
    }


def _openai_provider(endpoint: Endpoint) -> Provider[AsyncOpenAI]:
    """pydantic-ai's provider of the kind, on a client built here.

    Args:
        endpoint: The profile's endpoint.

    Returns:
        The provider.
    """
    kind = endpoint.profile.kind
    if kind is ProviderKind.AZURE:
        return AzureProvider(openai_client=_azure_client(endpoint))
    provider = _openai_providers().get(kind, OpenAIProvider)
    return provider(openai_client=_openai_client(endpoint))


async def _google_credentials(profile: ProviderProfile) -> Credentials | None:
    """Google credentials from the profile's service-account file, or ADC when it says ``adc``.

    Args:
        profile: The profile.

    Returns:
        The credentials; ``None`` for Vertex Express mode (a key).
    """
    if profile.credentials_file:
        path = profile.credentials_file
        return await asyncio.to_thread(
            service_account.Credentials.from_service_account_file, path, scopes=[GOOGLE_SCOPE]
        )
    if profile.adc:
        credentials, _ = await asyncio.to_thread(google.auth.default, scopes=[GOOGLE_SCOPE])
        return credentials
    return None


async def _google_provider(endpoint: Endpoint) -> GoogleProvider | GoogleCloudProvider:
    """pydantic-ai's Google provider with explicit key, or project, location and credentials.

    Args:
        endpoint: The profile's endpoint.

    Returns:
        The provider.
    """
    profile = endpoint.profile
    retries = HttpRetryOptions(attempts=profile.max_retries + 1)
    if profile.kind is ProviderKind.GOOGLE:
        return GoogleProvider(
            api_key=endpoint.key or NO_KEY,
            http_client=endpoint.client,
            base_url=endpoint.base_url,
            retry_options=retries,
        )
    credentials = await _google_credentials(profile)
    if credentials is None:  # Vertex Express mode
        return GoogleCloudProvider(
            api_key=endpoint.key or NO_KEY,
            http_client=endpoint.client,
            base_url=endpoint.base_url,
            retry_options=retries,
        )
    return GoogleCloudProvider(
        credentials=credentials,
        project=profile.project,
        location=profile.location,
        http_client=endpoint.client,
        base_url=endpoint.base_url,
        retry_options=retries,
    )


async def _anthropic_client(
    endpoint: Endpoint,
) -> AsyncAnthropic | AsyncAnthropicVertex:
    """The Anthropic SDK client of the profile's platform, every value explicit.

    Args:
        endpoint: The profile's endpoint.

    Returns:
        The client of the Anthropic API (or a key-signed Foundry endpoint, which takes the
        Anthropic API's `x-api-key`), Vertex AI or Azure AI Foundry with Entra ID.
    """
    without_sdk_header_variables()
    profile = endpoint.profile
    match profile.anthropic_platform:
        case AnthropicPlatform.VERTEX:
            return AsyncAnthropicVertex(
                project_id=profile.project or "",
                region=profile.location or "",
                base_url=endpoint.base_url,
                credentials=await _google_credentials(profile),
                http_client=endpoint.client,
                max_retries=profile.max_retries,
                timeout=profile.request_timeout,
            )
        case AnthropicPlatform.FOUNDRY if endpoint.token_provider is not None:
            # Not AsyncAnthropicFoundry: it reads ANTHROPIC_FOUNDRY_RESOURCE and _BASE_URL even
            # when given the other, and then fails or goes elsewhere. The profile's client signs
            # every request with a fresh Entra ID token (`http_client(bearer=...)`); this
            # placeholder only keeps the SDK from looking for a key of its own.
            return AsyncAnthropic(
                auth_token=NO_KEY,
                base_url=endpoint.base_url,
                http_client=endpoint.client,
                max_retries=profile.max_retries,
                timeout=profile.request_timeout,
            )
        case _:
            return AsyncAnthropic(
                api_key=endpoint.key or NO_KEY,
                base_url=endpoint.base_url,
                http_client=endpoint.client,
                max_retries=profile.max_retries,
                timeout=profile.request_timeout,
            )


def _bedrock_model(endpoint: Endpoint, model: str) -> Model:
    """Claude on Bedrock, only with boto3 installed (never in the images; ``unsupported`` checks).

    Args:
        endpoint: The profile's endpoint.
        model: The model.

    Returns:
        The pydantic-ai model.
    """
    profile = endpoint.profile
    bedrock = importlib.import_module("anthropic.lib.bedrock")
    client = bedrock.AsyncAnthropicBedrock(
        aws_region=profile.location,
        base_url=endpoint.base_url,
        http_client=endpoint.client,
        max_retries=profile.max_retries,
        timeout=profile.request_timeout,
    )
    return AnthropicModel(model, provider=AnthropicProvider(anthropic_client=client))


async def chat_model(endpoint: Endpoint, model: str) -> Model:
    """Build the chat model of the profile's kind (decision record, *Provider abstraction*).

    Args:
        endpoint: The profile's endpoint.
        model: The model (an Azure deployment for ``azure``).

    Returns:
        The pydantic-ai model.
    """
    profile = endpoint.profile
    match profile.kind:
        case ProviderKind.ANTHROPIC if profile.anthropic_platform is AnthropicPlatform.BEDROCK:
            return _bedrock_model(endpoint, model)
        case ProviderKind.ANTHROPIC:
            client = await _anthropic_client(endpoint)
            return AnthropicModel(model, provider=AnthropicProvider(anthropic_client=client))
        case ProviderKind.GOOGLE | ProviderKind.GOOGLE_VERTEX:
            return GoogleModel(model, provider=await _google_provider(endpoint))
        case _:
            model_class = {
                ProviderKind.OPENAI: OpenAIResponsesModel,
                ProviderKind.OPENROUTER: OpenRouterModel,
                ProviderKind.OLLAMA: OllamaModel,
                ProviderKind.CEREBRAS: CerebrasModel,
            }.get(profile.kind, OpenAIChatModel)
            return model_class(model, provider=_openai_provider(endpoint))


async def embedder(endpoint: Endpoint, model: str) -> Embedder:
    """Build the embedder of the profile's kind.

    Args:
        endpoint: The profile's endpoint.
        model: The embedding model.

    Returns:
        The pydantic-ai embedder.

    Raises:
        ProviderUnsupportedError: The kind has no embedding API (Anthropic).
    """
    profile = endpoint.profile
    if not profile.kind.has_embeddings:
        raise ProviderUnsupportedError(profile.name, f"kind {profile.kind.value} has no embeddings")
    if profile.kind in {ProviderKind.GOOGLE, ProviderKind.GOOGLE_VERTEX}:
        return Embedder(GoogleEmbeddingModel(model, provider=await _google_provider(endpoint)))
    # Imported here: pydantic-ai's OpenAI embeddings module imports tiktoken at load. Only an
    # OpenAI-API embedding role loads it, and nothing ever calls it (no `count_tokens`), so no
    # encoding is ever fetched from openaipublic.blob.core.windows.net.
    openai_embeddings = importlib.import_module("pydantic_ai.embeddings.openai")
    return Embedder(
        openai_embeddings.OpenAIEmbeddingModel(model, provider=_openai_provider(endpoint))
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HttpReranker:
    """A reranker in the Cohere-compatible ``/rerank`` dialect (vLLM, LiteLLM, gateways).

    The minimal client the ``reranker`` role's check needs; #93 builds the reranker port and the
    TEI dialect on top.
    """

    endpoint: Endpoint
    """The profile's endpoint."""
    model: str
    """The rerank model."""

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Score each document against the query.

        Args:
            query: The query.
            documents: The candidates.

        Returns:
            One relevance score per document, in their order.
        """
        headers = {}
        if self.endpoint.key:
            headers["Authorization"] = f"Bearer {self.endpoint.key}"
        response = await self.endpoint.client.post(
            self.endpoint.base_url.rstrip("/") + "/rerank",
            json={"model": self.model, "query": query, "documents": list(documents)},
            headers=headers,
        )
        response.raise_for_status()
        scores = [0.0] * len(documents)
        for result in response.json()["results"]:
            scores[int(result["index"])] = float(result["relevance_score"])
        return scores


def reranker(endpoint: Endpoint, model: str) -> HttpReranker:
    """Build the reranker of a gateway profile.

    Args:
        endpoint: The profile's endpoint.
        model: The rerank model.

    Returns:
        The reranker.

    Raises:
        ProviderUnsupportedError: The kind has no rerank API.
    """
    profile = endpoint.profile
    if profile.kind not in {
        ProviderKind.OPENAI_COMPATIBLE,
        ProviderKind.VLLM,
        ProviderKind.LITELLM,
    }:
        reason = (
            f"kind {profile.kind.value} has no rerank API; use an openai-compatible, vllm or "
            "litellm profile (the LLM judge reranks with any chat model)"
        )
        raise ProviderUnsupportedError(profile.name, reason)
    return HttpReranker(endpoint=endpoint, model=model)


async def check_chat(model: Model) -> str:
    """Ask a chat model for one short answer.

    Args:
        model: The model.

    Returns:
        The model name the provider reported.
    """
    response = await model_request(
        model,
        [ModelRequest.user_text_prompt(CHECK_PROMPT)],
        model_settings=ModelSettings(max_tokens=CHECK_MAX_TOKENS),
    )
    return response.model_name or model.model_name


async def check_embedding(embedding: Embedder, text: str) -> tuple[str, int]:
    """Embed one text.

    Args:
        embedding: The embedder.
        text: What to embed.

    Returns:
        The model name the provider reported, and the vector size.
    """
    result = await embedding.embed_query(text)
    return result.model_name, len(result.embeddings[0])


async def check_rerank(reranker: HttpReranker, text: str) -> str:
    """Rerank one text against itself.

    Args:
        reranker: The reranker.
        text: The query and the one candidate.

    Returns:
        The model asked for (the rerank dialect reports none).
    """
    await reranker.rerank(text, [text])
    return reranker.model


def call_errors() -> tuple[type[Exception], ...]:
    """Name what a failed model call raises, so a check can report it instead of crashing.

    Returns:
        The SDKs' and the transport's error base classes, and the value errors of a bad answer.
    """
    return (
        httpx2.HTTPError,
        OpenAIError,
        AnthropicError,
        GoogleAPIError,
        GoogleAuthError,
        AzureError,
        AgentRunError,
        UserError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    )
