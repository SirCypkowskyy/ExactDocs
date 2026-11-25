"""The pydantic-ai side of the ``ModelFactory`` (#241): loaded only once a model is called.

``ai_models.PydanticAiModels`` imports this module the first time a configured role is used (a
check, an embedding, a chat turn), never at start: with nothing configured, nothing of the
``[ai]`` extra is imported (RUN-02).

Every SDK client is built with explicit values only: the endpoint, the key (``unused`` for a
profile without one), the project, location and credentials, the API version. No model is ever
built from a ``"<provider>:<model>"`` string, which would let pydantic-ai infer the provider and
the SDKs read ``OPENAI_API_KEY``, ``*_BASE_URL`` and the like from the environment. Every call
goes through the profile's own ``httpx2`` client: its proxy on the transport (the profile's
own, else the instance's outbound proxy when ``ai.use_instance_proxy`` is on; the environment's
proxy variables are never read by the client), the instance's CA bundle (#538), its extra
headers, one retry layer (the SDK's), an overall timeout, and a guard that refuses any host but
the profile's endpoint.
"""

import asyncio
import importlib
import logging
import os
import re
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import google.auth
import httpx2
from anthropic import AnthropicError, AsyncAnthropic, AsyncAnthropicVertex
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError
from azure.identity import (
    ChainedTokenCredential,
    EnvironmentCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
    get_bearer_token_provider,
)
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.genai.errors import APIError as GoogleAPIError
from google.genai.types import HttpRetryOptions
from google.oauth2 import service_account
from openai import AsyncAzureOpenAI, AsyncOpenAI, OpenAIError
from pydantic_ai import Embedder, RunContext
from pydantic_ai.direct import model_request
from pydantic_ai.embeddings.google import GoogleEmbeddingModel
from pydantic_ai.exceptions import AgentRunError, UserError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.cerebras import CerebrasModel, CerebrasModelSettings
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.instrumented import InstrumentationSettings, instrument_model
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
)
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles.anthropic import ANTHROPIC_THINKING_BUDGET_MAP
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
    AZURE_OPENAI_HOST,
    AZURE_SCOPE,
    BEDROCK_HOST,
    CHECK_MAX_TOKENS,
    CHECK_PROMPT,
    DEFAULT_BASE_URLS,
    FOUNDRY_HOST,
    GOOGLE_SCOPE,
    NAMED_MODEL_KINDS,
    NO_KEY,
    RERANK_DIALECTS,
    SDK_HEADER_VARIABLES,
    VERTEX_HOST,
)
from exactdocs.bootstrap.outbound import RoutedTransport, tls_verify
from exactdocs.retrieval.adapters.driven.http_reranker import HttpReranker, RerankDialect
from exactdocs.retrieval.errors import ProviderUnsupportedError, RerankerError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    KeySource,
    ProviderKind,
    ProviderProfile,
    ThinkingLevel,
)
from exactdocs.retrieval.ports.driven import Reranker
from exactdocs_kernel import OutboundNetwork, SealedTextUnreadableError

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
            profile, express=profile.key is not KeySource.NONE
        )
    if kind is ProviderKind.AZURE and profile.resource:
        return _official_url(profile, f"{profile.resource}.openai.azure.com", "", AZURE_OPENAI_HOST)
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
            return _vertex_base_url(profile, express=False) + "v1"
        case AnthropicPlatform.FOUNDRY:
            if profile.base_url:
                return profile.base_url
            host = f"{profile.resource}.services.ai.azure.com"
            return _official_url(profile, host, "/anthropic/", FOUNDRY_HOST)
        case AnthropicPlatform.BEDROCK:
            host = f"bedrock-runtime.{profile.location}.amazonaws.com"
            return _official_url(profile, host, "", BEDROCK_HOST)


def _vertex_base_url(profile: ProviderProfile, *, express: bool) -> str:
    """Vertex AI's endpoint for a location, as the Google and Anthropic SDKs derive it.

    Args:
        profile: The profile; its ``location`` is ``global``, ``us``, ``eu`` or a region.
        express: Vertex Express mode (a key, no location): the global endpoint.

    Returns:
        The base URL, ending in ``/``.
    """
    location = profile.location
    if (express and not location) or location in {"global", None}:
        host = "aiplatform.googleapis.com"
    elif location in {"us", "eu"}:
        host = f"aiplatform.{location}.rep.googleapis.com"
    else:
        host = f"{location}-aiplatform.googleapis.com"
    return _official_url(profile, host, "/", VERTEX_HOST)


def _official_url(profile: ProviderProfile, host: str, path: str, official: re.Pattern[str]) -> str:
    """Build a derived endpoint with a URL constructor, then check it is the provider's own.

    ``resource`` and ``location`` are single DNS labels already (``ProviderProfile``); this is
    the second guard: the constructor percent-encodes anything that could end the host, and the
    whole host must then match the provider's endpoint form exactly
    (``<resource>.openai.azure.com``, ``<resource>.services.ai.azure.com``,
    ``bedrock-runtime.<region>.amazonaws.com``, Vertex AI's ``aiplatform`` hosts), not just its
    domain, where customers own names too.

    Args:
        profile: The profile.
        host: The host, built from the profile's fields.
        path: The path (``/`` or ``""``).
        official: The provider's host form (``AZURE_OPENAI_HOST``, ``FOUNDRY_HOST``, ...).

    Returns:
        The URL.

    Raises:
        ProviderUnsupportedError: The host is not the provider's endpoint.
    """
    url = httpx2.URL(scheme="https", host=host, path=path or "/")
    if not official.fullmatch(url.host):
        reason = f"its endpoint {url.host} would not be the provider's own"
        raise ProviderUnsupportedError(profile.name, reason)
    text = str(url)
    return text if path else text.rstrip("/")


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
            try:
                return open_sealed(profile.sealed_key)
            except SealedTextUnreadableError:
                reason = (
                    "its stored key does not open with this secret key (it was changed); "
                    "store the key again"
                )
                raise ProviderUnsupportedError(profile.name, reason) from None


def http_client(
    profile: ProviderProfile,
    url: str,
    *,
    bearer: Callable[[], str] | None = None,
    instance_proxy: str | None = None,
    network: OutboundNetwork | None = None,
) -> httpx2.AsyncClient:
    """Build the profile's one HTTP client.

    Args:
        profile: The profile.
        url: Its endpoint; the client reaches nothing else.
        bearer: Signs every request with an Entra ID token (Claude on Foundry with Entra ID).
        instance_proxy: The instance's outbound proxy for the endpoint, given only when
            ``ai.use_instance_proxy`` is on and ``NO_PROXY`` does not list it; the profile's own
            ``proxy`` wins over it.
        network: The outbound settings: the CA bundle every connection trusts, and what a
            failure through the proxy is redacted with.

    Returns:
        A client with the proxy on its transport, the extra headers, no retries of its own (the
        SDK's are the one retry layer), an overall timeout and the host guard.
    """
    network = network or OutboundNetwork()
    proxy = profile.proxy or instance_proxy
    transport = RoutedTransport(
        route=lambda _: proxy, verify=tls_verify(network), retries=0, redact=network.redact
    )
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


def entra_chain(
    profile: ProviderProfile, environ: Mapping[str, str], *, instance_proxy: str | None = None
) -> list[tuple[type[TokenCredential], dict[str, Any]]]:
    """The Entra ID credentials to try, in order, each with its arguments.

    A client secret or certificate (``AZURE_CLIENT_SECRET`` / ``AZURE_CLIENT_CERTIFICATE_PATH``),
    workload identity when its token file is configured, then managed identity: the identity
    the operator chose with ``auth = "entra"``. The developer tools (Azure CLI, PowerShell,
    VS Code) are not tried: a server never signs in as a person. The profile's ``proxy`` goes
    only to the credentials that call ``login.microsoftonline.com``; managed identity talks to a
    link-local or local endpoint (IMDS, ``IDENTITY_ENDPOINT``) that a proxy cannot reach.
    Without a ``proxy`` of the profile's own, the instance's outbound proxy goes there when
    ``ai.use_instance_proxy`` is on (``instance_proxy``).

    Args:
        profile: The profile.
        environ: The process environment (the Entra ID variables).
        instance_proxy: The instance's proxy for Entra ID, when profiles use it.

    Returns:
        ``(credential class, keyword arguments)`` pairs.
    """
    proxy = profile.proxy or instance_proxy
    via_proxy: dict[str, Any] = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
    chain: list[tuple[type[TokenCredential], dict[str, Any]]] = [(EnvironmentCredential, via_proxy)]
    if environ.get("AZURE_FEDERATED_TOKEN_FILE"):
        chain.append((WorkloadIdentityCredential, via_proxy))
    # A user-assigned identity is chosen by AZURE_CLIENT_ID, as DefaultAzureCredential does;
    # a bare ManagedIdentityCredential would ask IMDS for the system-assigned one instead.
    client_id = environ.get("AZURE_CLIENT_ID")
    chain.append((ManagedIdentityCredential, {"client_id": client_id} if client_id else {}))
    return chain


def entra_token_provider(
    profile: ProviderProfile, *, instance_proxy: str | None = None
) -> Callable[[], str]:
    """Entra ID tokens through the sync credentials (``azure.identity.aio`` would need aiohttp).

    Built once per profile (``ai_models`` keeps it on the endpoint), so its token cache lives
    as long as the profile: Entra ID or the managed-identity endpoint is asked again only when
    the token is about to expire, about once an hour.

    Args:
        profile: The profile.
        instance_proxy: The instance's proxy for Entra ID, when profiles use it.

    Returns:
        A callable returning a bearer token.
    """
    chain = entra_chain(profile, os.environ, instance_proxy=instance_proxy)
    credentials = [kind(**arguments) for kind, arguments in chain]
    return get_bearer_token_provider(ChainedTokenCredential(*credentials), AZURE_SCOPE)


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


def _bedrock_model(endpoint: Endpoint, model: str, settings: ModelSettings | None) -> Model:
    """Claude on Bedrock, only with boto3 installed (never in the images; ``unsupported`` checks).

    Args:
        endpoint: The profile's endpoint.
        model: The model.
        settings: The model's settings (its thinking level).

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
    provider = AnthropicProvider(anthropic_client=client)
    return AnthropicModel(model, provider=provider, settings=settings)


def instrumentation() -> InstrumentationSettings:
    """Instrument model and embedding calls without their content (decision record, *Telemetry*).

    Spans and the ``gen_ai.client.token.usage`` and ``operation.cost`` metrics go to the global
    providers ``otel_sdk`` sets up; their labels are the provider, the model, the operation and
    the token type, never a library, a user or the query. No prompt or completion is recorded.

    Returns:
        The settings.
    """
    return InstrumentationSettings(include_content=False)


async def chat_model(endpoint: Endpoint, model: str, thinking: ThinkingLevel | None) -> Model:
    """Build the chat model of the profile's kind with its thinking level, instrumented.

    The level becomes the model's own setting (``thinking_settings``), so every call made with
    it sends the provider's control for the level: HyDE, the judge, the agentic mode and
    ``exactdocs ai check`` alike. A model that cannot take one gets none (``list_roles`` and the
    start say so). Calls are instrumented without content (*Telemetry*).

    Args:
        endpoint: The profile's endpoint.
        model: The model (an Azure deployment for ``azure``).
        thinking: The role's level; ``None``: the provider's default.

    Returns:
        The pydantic-ai model.
    """
    build = await _chat_builder(endpoint, model)
    built = build(None)
    if thinking is not None:
        settings = thinking_settings(endpoint.profile.kind, built, thinking)
        if settings is None:
            logger.debug(
                "AI model %s:%s takes no thinking level: %s is left out",
                endpoint.profile.name,
                model,
                thinking.value,
            )
        else:
            built = build(settings)
            if (room := thinking_room(built, thinking)) > 0:
                built = ThinkingRoom(built, room=room)
    return instrument_model(built, instrumentation())


async def bare_chat_model(endpoint: Endpoint, model: str) -> Model:
    """Build the chat model of the profile's kind without settings or instrumentation.

    Args:
        endpoint: The profile's endpoint.
        model: The model.

    Returns:
        The pydantic-ai model, for its profile (nothing is called).
    """
    return (await _chat_builder(endpoint, model))(None)


async def _chat_builder(endpoint: Endpoint, model: str) -> Callable[[ModelSettings | None], Model]:
    """Prepare the chat model of the profile's kind (decision record, *Provider abstraction*).

    The provider (its client, its credentials) is made once; the model is then built with or
    without settings, which need the model's profile to be chosen.

    Args:
        endpoint: The profile's endpoint.
        model: The model (an Azure deployment for ``azure``).

    Returns:
        Builds the pydantic-ai model with the settings given.

    Raises:
        ProviderUnsupportedError: The profile's kind serves no chat model.
    """
    profile = endpoint.profile
    if not profile.kind.has_chat:
        reason = f"kind {profile.kind.value} serves a reranker only, not a chat model"
        raise ProviderUnsupportedError(profile.name, reason)
    match profile.kind:
        case ProviderKind.ANTHROPIC if profile.anthropic_platform is AnthropicPlatform.BEDROCK:
            return lambda settings: _bedrock_model(endpoint, model, settings)
        case ProviderKind.ANTHROPIC:
            claude = AnthropicProvider(anthropic_client=await _anthropic_client(endpoint))
            return lambda settings: AnthropicModel(model, provider=claude, settings=settings)
        case ProviderKind.GOOGLE | ProviderKind.GOOGLE_VERTEX:
            google = await _google_provider(endpoint)
            return lambda settings: GoogleModel(model, provider=google, settings=settings)
        case ProviderKind.CEREBRAS:
            cerebras = _openai_provider(endpoint)
            return lambda settings: CerebrasModel(
                model,
                provider=cerebras,
                settings=None if settings is None else CerebrasModelSettings(**settings),
            )
        case _:
            model_class = {
                ProviderKind.OPENAI: OpenAIResponsesModel,
                ProviderKind.OPENROUTER: OpenRouterModel,
                ProviderKind.OLLAMA: OllamaModel,
            }.get(profile.kind, OpenAIChatModel)
            openai = _openai_provider(endpoint)
            return lambda settings: model_class(model, provider=openai, settings=settings)


def thinking_settings(
    kind: ProviderKind, model: Model, level: ThinkingLevel
) -> ModelSettings | None:
    """Map a thinking level to the model settings that send the provider's own control.

    A model pydantic-ai knows to think takes the unified ``thinking`` setting, which pydantic-ai
    translates for its provider and model: Google's ``thinking_level`` (Gemini 3 and later) or
    ``thinking_budget`` (Gemini 2.5), Claude's adaptive thinking and effort or its
    ``budget_tokens``, OpenAI's and Azure's ``reasoning_effort``, OpenRouter's ``reasoning``.
    A model behind an OpenAI-compatible endpoint whose name pydantic-ai does not know (a
    gateway's alias, an Azure deployment) gets ``reasoning_effort`` itself, or OpenRouter's
    ``reasoning``: the endpoint takes it, and whether the model behind it does cannot be known
    before a call. Anthropic, Google and OpenAI's own API know their models.

    Args:
        kind: The profile's kind.
        model: The model built without settings (its profile is read).
        level: The level.

    Returns:
        The settings, or ``None`` when the model takes no thinking level.
    """
    profile = model.profile
    if profile.get("supports_thinking", False) or profile.get("thinking_always_enabled", False):
        return ModelSettings(thinking=level.value)
    if kind is ProviderKind.OPENROUTER:
        return OpenRouterModelSettings(openrouter_reasoning={"effort": level.value})
    if kind.value in NAMED_MODEL_KINDS:
        return None
    return OpenAIChatModelSettings(openai_reasoning_effort=level.value)


def thinking_unsupported(kind: ProviderKind, model: Model) -> str | None:
    """Say why a model takes no thinking level, from pydantic-ai's profile of it.

    Args:
        kind: The profile's kind.
        model: The model built without settings.

    Returns:
        A fixed text, or ``None`` when it takes one.
    """
    if thinking_settings(kind, model, ThinkingLevel.LOW) is not None:
        return None
    return f"{kind.value} serves it without a thinking or reasoning setting"


def thinking_room(model: Model, level: ThinkingLevel) -> int:
    """The output tokens a thinking level spends ahead of the answer and needs room for.

    Claude models without adaptive thinking think within ``budget_tokens``, which counts toward
    ``max_tokens`` and must stay below it: an answer capped below the budget (HyDE's, the
    judge's, a check's) would be refused. Other providers bound thinking by the level alone.

    Args:
        model: The model, built with its settings.
        level: The level.

    Returns:
        The budget to add to an explicit ``max_tokens``; 0 when none is needed.
    """
    if not isinstance(model, AnthropicModel):
        return 0
    if model.profile.get("anthropic_supports_adaptive_thinking", False):
        return 0
    return ANTHROPIC_THINKING_BUDGET_MAP[level.value]


class ThinkingRoom(WrapperModel):
    """A model whose explicit ``max_tokens`` is raised by its thinking budget.

    The caps ExactDocs sets (HyDE's answer, the judge's ratings, a check) bound the answer; a
    Claude model that thinks within a token budget spends that budget out of the same
    ``max_tokens``, so the budget is added to the cap.
    """

    room: int
    """Output tokens added to an explicit ``max_tokens``."""

    def __init__(self, wrapped: Model, *, room: int) -> None:
        """Wrap a model.

        Args:
            wrapped: The model, built with its thinking settings.
            room: The tokens to add.
        """
        super().__init__(wrapped)
        self.room = room

    def _roomy(self, settings: ModelSettings | None) -> ModelSettings | None:
        """Raise an explicit ``max_tokens`` by the room.

        Args:
            settings: The request's settings.

        Returns:
            The settings with the larger cap, or unchanged without one.
        """
        if settings is None or "max_tokens" not in settings:
            return settings
        return ModelSettings(**{**settings, "max_tokens": settings["max_tokens"] + self.room})

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Make a request with the cap raised.

        Args:
            messages: The messages.
            model_settings: The request's settings.
            model_request_parameters: The request's parameters.

        Returns:
            The response.
        """
        return await super().request(
            messages, self._roomy(model_settings), model_request_parameters
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        """Stream a request with the cap raised.

        Args:
            messages: The messages.
            model_settings: The request's settings.
            model_request_parameters: The request's parameters.
            run_context: The run's context.

        Yields:
            The streamed response.
        """
        async with super().request_stream(
            messages, self._roomy(model_settings), model_request_parameters, run_context
        ) as stream:
            yield stream


async def embedder(endpoint: Endpoint, model: str) -> Embedder:
    """Build the embedder of the profile's kind.

    Args:
        endpoint: The profile's endpoint.
        model: The embedding model.

    Returns:
        The pydantic-ai embedder.

    Raises:
        ProviderUnsupportedError: The kind has no embedding API (Anthropic, TEI).
    """
    profile = endpoint.profile
    if not profile.kind.has_embeddings:
        raise ProviderUnsupportedError(profile.name, f"kind {profile.kind.value} has no embeddings")
    if profile.kind in {ProviderKind.GOOGLE, ProviderKind.GOOGLE_VERTEX}:
        return Embedder(
            GoogleEmbeddingModel(model, provider=await _google_provider(endpoint)),
            instrument=instrumentation(),
        )
    # Imported here: pydantic-ai's OpenAI embeddings module imports tiktoken at load. Only an
    # OpenAI-API embedding role loads it, and nothing ever calls it (no `count_tokens`), so no
    # encoding is ever fetched from openaipublic.blob.core.windows.net.
    openai_embeddings = importlib.import_module("pydantic_ai.embeddings.openai")
    return Embedder(
        openai_embeddings.OpenAIEmbeddingModel(model, provider=_openai_provider(endpoint)),
        instrument=instrumentation(),
    )


def reranker(endpoint: Endpoint, model: str) -> Reranker:
    """Build the HTTP reranker of a profile: Cohere-compatible ``/rerank``, or TEI's.

    Cohere, Jina, Voyage and Azure AI Foundry are ``openai-compatible`` profiles whose base URL
    carries the version prefix (``https://api.cohere.com/v2``); vLLM and LiteLLM speak the same
    dialect; a ``tei`` profile speaks TEI's.

    Args:
        endpoint: The profile's endpoint.
        model: The rerank model.

    Returns:
        The reranker, on the profile's one HTTP client.

    Raises:
        ProviderUnsupportedError: The kind has no rerank API.
    """
    profile = endpoint.profile
    dialect = RERANK_DIALECTS.get(profile.kind.value)
    if dialect is None:
        reason = (
            f"kind {profile.kind.value} has no rerank API; use an openai-compatible (Cohere, "
            "Jina, Voyage, Azure AI Foundry), vllm, litellm or tei profile (the LLM judge "
            "reranks with any chat model)"
        )
        raise ProviderUnsupportedError(profile.name, reason)
    return HttpReranker(
        client=endpoint.client,
        base_url=endpoint.base_url,
        model=model,
        key=endpoint.key,
        dialect=RerankDialect(dialect),
    )


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


async def check_rerank(reranker: Reranker, model: str, text: str) -> str:
    """Rerank one text against itself.

    Args:
        reranker: The reranker.
        model: The model asked for.
        text: The query and the one candidate.

    Returns:
        The model asked for (the rerank dialects report none).
    """
    await reranker.rerank(text, [text])
    return model


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
        RerankerError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    )
