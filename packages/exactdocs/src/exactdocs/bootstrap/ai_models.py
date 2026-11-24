"""Implements retrieval's ``ModelFactory`` port with pydantic-ai, imported only when called.

This module is light: it imports no SDK. ``unsupported`` says, from the installed packages alone,
whether a profile can be called here; the first call loads ``bootstrap/ai_sdk.py`` (pydantic-ai,
the OpenAI, Anthropic and Google SDKs, azure-identity). Keys are produced at each call: a sealed
one is opened with the secret box (its own HKDF purpose), an ``api_key_file`` is read again (so a
rotated secret counts), an environment key is held here and nowhere else. Each profile has one
``httpx2`` client, rebuilt (and the old one closed) when the profile changes.
"""

import asyncio
import importlib
import importlib.util
import logging
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import ModuleType

from exactdocs.bootstrap.ai_endpoint import Endpoint
from exactdocs.bootstrap.constants import AI_SDK_MODULE, CHECK_TEXT, ENTRA_URL
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.bootstrap.outbound import proxy_cause
from exactdocs.bootstrap.settings import AiSettings, BudgetSettings
from exactdocs.retrieval.adapters.driven.ai_embeddings import PydanticAiEmbeddingModels
from exactdocs.retrieval.adapters.driven.local_models import LocalEmbedder, LocalEmbeddingModels
from exactdocs.retrieval.constants import (
    MASK,
    MAX_CHECK_ERROR,
    MICROS_PER_USD,
    SPEND_SCOPE_EMBEDDING,
    SPEND_SCOPE_INSTANCE,
    SPEND_SCOPE_LIBRARY,
    SPEND_SCOPE_USER,
)
from exactdocs.retrieval.errors import InvalidProviderError, ProviderUnsupportedError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    BudgetLimit,
    Budgets,
    InstanceRoles,
    KeySource,
    ModelCheck,
    ModelPrice,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    SpendWindow,
    ThinkingLevel,
)
from exactdocs.retrieval.ports.driven import Embeddings, Reranker, SecretBox
from exactdocs_kernel import OutboundNetwork, SealedTextUnreadableError

logger = logging.getLogger(__name__)


def _installed(module: str) -> bool:
    """Tell whether a module could be imported, without importing it.

    Args:
        module: The dotted module name.

    Returns:
        True when it is installed.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:  # its parent package is missing
        return False


def _needs(profile: ProviderProfile) -> list[tuple[str, str]]:
    """List the modules a profile's calls import, each with what to install for it.

    Args:
        profile: The profile.

    Returns:
        ``(module, what to install)`` pairs.
    """
    extra = "install exactdocs[ai] (uvx --from 'exactdocs[ai]' exactdocs, or the -ai image)"
    needs = [
        ("pydantic_ai", extra),
        ("openai", extra),
        ("anthropic", extra),
        ("google.genai", extra),
    ]
    if profile.auth is AzureAuth.ENTRA:
        needs.append(("azure.identity", extra))
    if profile.kind is ProviderKind.ANTHROPIC and (
        profile.anthropic_platform is AnthropicPlatform.BEDROCK
    ):
        why = (
            "Claude on Bedrock needs boto3, which the images do not include: "
            "uvx --from 'exactdocs[ai]' --with 'anthropic[bedrock]' exactdocs, or reach it "
            "through a LiteLLM gateway"
        )
        needs.append(("boto3", why))
    return needs


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiModels:
    """Implements ``retrieval.ports.driven.ModelFactory`` with pydantic-ai (lazily) and httpx2."""

    keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    """The keys of profiles configured with ``api_key`` in the environment, by profile name."""
    box: SecretBox | None = field(default=None, repr=False)
    """Opens keys stored over the REST API; ``None`` when this process has no secret key."""
    network: OutboundNetwork = field(default_factory=OutboundNetwork, repr=False)
    """The instance's outbound proxy, NO_PROXY and CA bundle (#538)."""
    use_instance_proxy: bool = False
    """``ai.use_instance_proxy``: a profile without a ``proxy`` of its own goes through the
    instance's outbound proxy (unless ``NO_PROXY`` lists its endpoint) instead of directly."""
    _endpoints: dict[str, Endpoint] = field(default_factory=dict, init=False, repr=False)
    """The current endpoint of each profile called so far, by name."""
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    """One build of an endpoint at a time, per profile name."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say why this installation cannot call the profile, from the installed packages.

        Args:
            profile: The profile.

        Returns:
            What to install, or ``None``.
        """
        if profile.kind is ProviderKind.LOCAL:
            return "a local profile runs in this process (LocalModels), not through an SDK"
        return next((why for module, why in _needs(profile) if not _installed(module)), None)

    async def warm(self) -> None:
        """Load the SDK side in a worker thread, so no request waits for it on the event loop.

        Called at start when a provider profile exists; a no-op once loaded or without the
        ``[ai]`` extra (a profile's call then says what to install). A load that fails (a partly
        installed extra) never stops the start: it is logged as a warning with the error's class
        only, and each later call to a model fails and falls back as usual.
        """
        if AI_SDK_MODULE in sys.modules or not _installed("pydantic_ai"):
            return
        started = time.perf_counter()
        load = asyncio.ensure_future(asyncio.to_thread(importlib.import_module, AI_SDK_MODULE))
        await asyncio.wait({load})  # returns the outcome without raising it
        if (error := load.exception()) is not None:
            logger.warning(
                "AI provider SDKs could not be loaded (%s): calls to a model will fail and "
                "searches fall back to what needs none",
                type(error).__name__,
            )
            return
        logger.info("AI provider SDKs loaded in %.1fs", time.perf_counter() - started)

    async def _sdk(self, profile: ProviderProfile) -> ModuleType:
        """Load the SDK side, once the profile is known to be callable.

        The first load (seconds: pydantic-ai and the SDKs) runs in a worker thread, never on the
        event loop; ``warm`` does it at start when a role is configured.

        Args:
            profile: The profile.

        Returns:
            ``exactdocs.bootstrap.ai_sdk``.

        Raises:
            ProviderUnsupportedError: Something it needs is not installed.
        """
        if (reason := self.unsupported(profile)) is not None:
            raise ProviderUnsupportedError(profile.name, reason)
        loaded = sys.modules.get(AI_SDK_MODULE)
        if loaded is not None:
            return loaded
        return await asyncio.to_thread(importlib.import_module, AI_SDK_MODULE)

    async def endpoint(self, profile: ProviderProfile) -> Endpoint:
        """The profile's endpoint: its key, now, and its one client, rebuilt when it changed.

        One build at a time per profile, so two first calls never make two clients.

        Args:
            profile: The profile, as it is now.

        Returns:
            The endpoint.
        """
        sdk = await self._sdk(profile)
        key = sdk.read_key(
            profile, self.keys.get(profile.name), None if self.box is None else self.box.open
        )
        async with self._locks.setdefault(profile.name, asyncio.Lock()):
            current = self._endpoints.get(profile.name)
            if current is not None and current.profile == profile:
                if current.key == key:
                    return current
                endpoint = replace(current, key=key)
            else:
                endpoint = self._build(sdk, profile, key)
                if current is not None:
                    await current.client.aclose()
                    logger.info("AI provider %s changed: its HTTP client was rebuilt", profile.name)
            self._endpoints[profile.name] = endpoint
            return endpoint

    def _build(self, sdk: ModuleType, profile: ProviderProfile, key: str | None) -> Endpoint:
        """Build a profile's endpoint: its URL, its Entra ID token provider, its client.

        Args:
            sdk: ``exactdocs.bootstrap.ai_sdk``.
            profile: The profile.
            key: Its key, or ``None``.

        Returns:
            The endpoint.
        """
        url = sdk.base_url(profile)
        tokens = (
            sdk.entra_token_provider(profile, instance_proxy=self.instance_proxy(ENTRA_URL))
            if profile.auth is AzureAuth.ENTRA
            else None
        )
        # Claude on Foundry with Entra ID: the client signs each request with a fresh token.
        bearer = tokens if profile.kind is ProviderKind.ANTHROPIC else None
        client = sdk.http_client(
            profile,
            url,
            bearer=bearer,
            instance_proxy=self.instance_proxy(url),
            network=self.network,
        )
        return Endpoint(
            profile=profile, base_url=url, key=key, client=client, token_provider=tokens
        )

    def instance_proxy(self, url: str) -> str | None:
        """The instance's outbound proxy for a URL, when profiles use it.

        Args:
            url: The endpoint (or Entra ID's).

        Returns:
            The proxy, or ``None``: ``ai.use_instance_proxy`` is off, or the URL is reached
            directly (``NO_PROXY``, loopback).
        """
        return self.network.proxy_for(url) if self.use_instance_proxy else None

    async def release(self, name: str) -> None:
        """Close the client of a profile that was deleted (or will be rebuilt).

        Args:
            name: The profile's name.
        """
        async with self._locks.setdefault(name, asyncio.Lock()):
            endpoint = self._endpoints.pop(name, None)
            if endpoint is not None:
                await endpoint.client.aclose()
        self._locks.pop(name, None)

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        """Build a pydantic-ai chat model, with its thinking level as the provider's setting.

        Args:
            profile: The profile.
            model: The model name.
            thinking: The role's level; left out when the model cannot take one.

        Returns:
            The model.
        """
        sdk = await self._sdk(profile)
        return await sdk.chat_model(await self.endpoint(profile), model, thinking)

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        """Say why a chat model cannot take a thinking level, from pydantic-ai's model profile.

        The model is built (no call is made): its profile is the one its calls use. A model that
        cannot be built here (a missing SDK, a key file or credentials it cannot read now) is not
        refused: its calls say why they fail.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            A fixed text, or ``None`` when it can or that cannot be known now.
        """
        try:
            sdk = await self._sdk(profile)
        except ProviderUnsupportedError:
            return None
        try:
            built = await sdk.bare_chat_model(await self.endpoint(profile), model)
        except (ProviderUnsupportedError, SealedTextUnreadableError, *sdk.call_errors()) as error:
            logger.debug(
                "thinking support of %s:%s unknown: %s", profile.name, model, type(error).__name__
            )
            return None
        return sdk.thinking_unsupported(profile.kind, built)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Build a pydantic-ai embedder.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The embedder.
        """
        return await (await self._sdk(profile)).embedder(await self.endpoint(profile), model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        """Build an HTTP reranker in the dialect of the profile's kind (Cohere-compatible, TEI).

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The reranker.
        """
        sdk = await self._sdk(profile)
        built: Reranker = sdk.reranker(await self.endpoint(profile), model)
        return built

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        """Make one minimal call as ``role`` uses the model, and time it.

        Args:
            profile: The profile.
            model: The model name.
            role: A chat turn (``llm``, ``judge``), an embedding or a rerank.
            thinking: A chat role's thinking level, sent as its calls send it, so the latency
                reflects it.

        Returns:
            The outcome; a failure says why, with any key masked.
        """
        started = time.perf_counter()
        try:
            sdk = await self._sdk(profile)
        except ProviderUnsupportedError as error:
            return self._failed(profile, model, role, started, str(error))
        try:
            served, dimensions = await self._call(sdk, profile, model, role, thinking)
        except sdk.call_errors() as error:  # a check reports a failed call, it never raises
            # A failure on the way through a proxy names it and the host (#538): the SDK's own
            # error only says "Connection error."
            reason = f"{type(error).__name__}: {proxy_cause(error) or error}"
            return self._failed(profile, model, role, started, reason)
        except ProviderUnsupportedError as error:
            return self._failed(profile, model, role, started, str(error))
        return ModelCheck(
            role=role,
            profile=profile.name,
            model=model,
            ok=True,
            latency_ms=(time.perf_counter() - started) * 1000,
            served_model=served,
            dimensions=dimensions,
        )

    async def _call(
        self,
        sdk: ModuleType,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        thinking: ThinkingLevel | None,
    ) -> tuple[str, int | None]:
        """Make the one call a role's check makes.

        Args:
            sdk: ``exactdocs.bootstrap.ai_sdk``.
            profile: The profile.
            model: The model name.
            role: The role.
            thinking: A chat role's thinking level.

        Returns:
            The model that answered, and an embedding's vector size.
        """
        match role:
            case ModelRole.EMBEDDING:
                embedder = await self.embedder(profile, model)
                return await sdk.check_embedding(embedder, CHECK_TEXT)
            case ModelRole.RERANKER:
                reranker = await self.reranker(profile, model)
                return await sdk.check_rerank(reranker, model, CHECK_TEXT), None
            case ModelRole.LLM | ModelRole.JUDGE:
                chat = await self.chat_model(profile, model, thinking=thinking)
                return await sdk.check_chat(chat), None

    def _failed(
        self, profile: ProviderProfile, model: str, role: ModelRole, started: float, reason: str
    ) -> ModelCheck:
        """Report a failed check, with secrets masked, and log it.

        Args:
            profile: The profile.
            model: The model name.
            role: The role.
            started: When the check started (``perf_counter``).
            reason: Why it failed.

        Returns:
            The failed check.
        """
        reason = self._scrub(profile, reason)
        logger.warning("AI check of %s:%s failed: %s", profile.name, model, reason)
        return ModelCheck(
            role=role,
            profile=profile.name,
            model=model,
            ok=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=reason,
        )

    def _scrub(self, profile: ProviderProfile, text: str) -> str:
        """Mask the profile's key and header values in an error text, and cut it short.

        Args:
            profile: The profile.
            text: The error text.

        Returns:
            The text without secrets, at most ``MAX_CHECK_ERROR`` characters.
        """
        endpoint = self._endpoints.get(profile.name)
        secrets = [value for _, value in profile.headers]
        if endpoint is not None and endpoint.key:
            secrets.append(endpoint.key)
        if profile.name in self.keys:
            secrets.append(self.keys[profile.name])
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            text = text.replace(secret, MASK)
        return text if len(text) <= MAX_CHECK_ERROR else text[:MAX_CHECK_ERROR] + "..."


@dataclass(frozen=True, slots=True, kw_only=True)
class AiModels:
    """Implements ``retrieval.ports.driven.ModelFactory`` for every profile kind.

    ``local`` profiles run in this process (``LocalModels``, fastembed); every other kind goes
    through pydantic-ai (``PydanticAiModels``).
    """

    remote: PydanticAiModels = field(default_factory=PydanticAiModels)
    """The profiles behind an endpoint."""
    local: LocalModels
    """The ``local`` profiles."""

    def _of(self, profile: ProviderProfile) -> PydanticAiModels | LocalModels:
        """Pick the factory of a profile's kind.

        Args:
            profile: The profile.

        Returns:
            ``local`` for a local profile, else ``remote``.
        """
        return self.local if profile.kind is ProviderKind.LOCAL else self.remote

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say why this installation cannot call the profile.

        Args:
            profile: The profile.

        Returns:
            What to install, or ``None``.
        """
        return self._of(profile).unsupported(profile)

    async def chat_model(
        self, profile: ProviderProfile, model: str, *, thinking: ThinkingLevel | None = None
    ) -> object:
        """Build a chat model.

        Args:
            profile: The profile.
            model: The model name.
            thinking: Its thinking level.

        Returns:
            The model.
        """
        return await self._of(profile).chat_model(profile, model, thinking=thinking)

    async def thinking_unsupported(self, profile: ProviderProfile, model: str) -> str | None:
        """Say why a chat model cannot take a thinking level, when that is known.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            A fixed text, or ``None``.
        """
        return await self._of(profile).thinking_unsupported(profile, model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Build an embedder.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            A pydantic-ai ``Embedder``, or a ``LocalEmbedder``.
        """
        return await self._of(profile).embedder(profile, model)

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        """Build a reranker.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The reranker.
        """
        return await self._of(profile).reranker(profile, model)

    async def release(self, name: str) -> None:
        """Close what was built for a deleted profile.

        Args:
            name: The profile's name.
        """
        await self.remote.release(name)
        await self.local.release(name)

    async def check(
        self,
        profile: ProviderProfile,
        model: str,
        role: ModelRole,
        *,
        thinking: ThinkingLevel | None = None,
    ) -> ModelCheck:
        """Make one minimal call as ``role`` uses the model.

        Args:
            profile: The profile.
            model: The model name.
            role: The role.
            thinking: A chat role's thinking level.

        Returns:
            The outcome.
        """
        return await self._of(profile).check(profile, model, role, thinking=thinking)


@dataclass(frozen=True, slots=True, kw_only=True)
class AiEmbeddingModels:
    """Implements ``retrieval.ports.driven.EmbeddingModels`` for both kinds of embedder."""

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> Embeddings:
        """Wrap what ``AiModels.embedder`` built.

        Args:
            handle: A ``LocalEmbedder``, or a pydantic-ai ``Embedder``.
            name: ``<profile>:<model>``.
            dimensions: The configured dimensions, if any.
            batch_size: The most texts per call.

        Returns:
            The model.
        """
        models = (
            LocalEmbeddingModels()
            if isinstance(handle, LocalEmbedder)
            else PydanticAiEmbeddingModels()
        )
        return models.bind(handle, name=name, dimensions=dimensions, batch_size=batch_size)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguredAi:
    """The AI configuration of the environment and the TOML file, in retrieval's terms."""

    profiles: tuple[ProviderProfile, ...] = ()
    """The configured profiles (read-only over the REST API)."""
    keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    """The keys given in the environment, by profile name: they never leave bootstrap."""
    roles: InstanceRoles = field(default_factory=InstanceRoles)
    """The instance's roles."""
    budgets: Budgets = field(default_factory=Budgets)
    """The spend limits and the LLM search rate limit."""
    prices: Mapping[str, ModelPrice] = field(default_factory=dict)
    """The operator's prices, by ``<profile>:<model>``."""


def configured_ai(ai: AiSettings) -> ConfiguredAi:
    """Turn the ``ai`` settings into profiles, environment keys and roles.

    Args:
        ai: The settings.

    Returns:
        The configuration.

    Raises:
        InvalidProviderError: A profile is not valid for its kind, or its key file is missing.
    """
    profiles: list[ProviderProfile] = []
    keys: dict[str, str] = {}
    for name, entry in sorted(ai.providers.items()):
        if entry.api_key is not None and entry.api_key_file is not None:
            raise InvalidProviderError(name, "give api_key or api_key_file, not both")
        if entry.api_key is not None:
            key = KeySource.ENVIRONMENT
            keys[name] = entry.api_key.get_secret_value().strip()
        elif entry.api_key_file is not None:
            if not entry.api_key_file.is_file():
                raise InvalidProviderError(name, f"api_key_file {entry.api_key_file} is no file")
            key = KeySource.FILE
        else:
            key = KeySource.NONE
        profiles.append(
            ProviderProfile(
                name=name,
                kind=ProviderKind.parse(name, entry.kind),
                origin=ProfileOrigin.CONFIGURATION,
                base_url=entry.base_url,
                key=key,
                key_file=None if entry.api_key_file is None else str(entry.api_key_file),
                headers=tuple(entry.headers.items()),
                proxy=entry.proxy,
                request_timeout=entry.request_timeout,
                max_retries=entry.max_retries,
                api_version=entry.api_version,
                project=entry.project,
                location=entry.location,
                credentials_file=(
                    None if entry.credentials_file is None else str(entry.credentials_file)
                ),
                adc=entry.credentials == "adc",
                platform=entry.platform,
                auth=entry.auth,
                resource=entry.resource,
            )
        )
    return ConfiguredAi(
        profiles=tuple(profiles),
        keys=keys,
        roles=InstanceRoles(
            embedding=_role(ai.embedding.model),
            reranker=_role(ai.reranker.model),
            llm=_role(ai.llm.model),
            judge=_role(ai.judge.model),
            llm_thinking=ai.llm.thinking,
            judge_thinking=ai.judge.thinking,
        ),
        budgets=budgets(ai.budgets),
        prices={
            str(ModelRef.parse(ref)): ModelPrice(
                input_usd_per_million=price.input_usd_per_mtok,
                output_usd_per_million=price.output_usd_per_mtok,
            )
            for ref, price in ai.prices.items()
        },
    )


def budgets(settings: BudgetSettings) -> Budgets:
    """Turn the ``[ai.budgets]`` settings into retrieval's limits.

    Args:
        settings: The settings.

    Returns:
        One limit per scope kind and window that has a ceiling.
    """
    fields = {
        SPEND_SCOPE_INSTANCE: "",
        SPEND_SCOPE_LIBRARY: "per_library_",
        SPEND_SCOPE_USER: "per_user_",
        SPEND_SCOPE_EMBEDDING: "",
    }
    limits: list[BudgetLimit] = []
    for kind, prefix in fields.items():
        suffix = "_embedding" if kind == SPEND_SCOPE_EMBEDDING else ""
        for window, name in ((SpendWindow.DAY, "daily"), (SpendWindow.MONTH, "monthly")):
            usd = getattr(settings, f"{prefix}{name}{suffix}_usd")
            tokens = getattr(settings, f"{prefix}{name}{suffix}_tokens")
            if usd is None and tokens is None:
                continue
            limits.append(
                BudgetLimit(
                    scope_kind=kind,
                    window=window,
                    usd_micros=None if usd is None else max(1, round(usd * MICROS_PER_USD)),
                    tokens=tokens,
                )
            )
    return Budgets(limits=tuple(limits), llm_searches_per_minute=settings.llm_searches_per_minute)


def _role(text: str | None) -> ModelRef | None:
    """Read a role's ``<profile>:<model>``; blank is unset.

    Args:
        text: The setting.

    Returns:
        The reference, or ``None``.
    """
    return ModelRef.parse(text) if text and text.strip() else None
