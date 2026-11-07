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
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import ModuleType

from exactdocs.bootstrap.ai_endpoint import Endpoint
from exactdocs.bootstrap.constants import CHECK_TEXT
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.constants import MASK, MAX_CHECK_ERROR
from exactdocs.retrieval.errors import InvalidProviderError, ProviderUnsupportedError
from exactdocs.retrieval.models import (
    AnthropicPlatform,
    AzureAuth,
    InstanceRoles,
    KeySource,
    ModelCheck,
    ModelRef,
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
)
from exactdocs.retrieval.ports.driven import SecretBox

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
            return "local models arrive with the exactdocs[local] extra (#245)"
        return next((why for module, why in _needs(profile) if not _installed(module)), None)

    def _sdk(self, profile: ProviderProfile) -> ModuleType:
        """Load the SDK side, once the profile is known to be callable.

        Args:
            profile: The profile.

        Returns:
            ``exactdocs.bootstrap.ai_sdk``.

        Raises:
            ProviderUnsupportedError: Something it needs is not installed.
        """
        if (reason := self.unsupported(profile)) is not None:
            raise ProviderUnsupportedError(profile.name, reason)
        return importlib.import_module("exactdocs.bootstrap.ai_sdk")

    async def endpoint(self, profile: ProviderProfile) -> Endpoint:
        """The profile's endpoint: its key, now, and its one client, rebuilt when it changed.

        One build at a time per profile, so two first calls never make two clients.

        Args:
            profile: The profile, as it is now.

        Returns:
            The endpoint.
        """
        sdk = self._sdk(profile)
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
        tokens = sdk.entra_token_provider(profile) if profile.auth is AzureAuth.ENTRA else None
        # Claude on Foundry with Entra ID: the client signs each request with a fresh token.
        bearer = tokens if profile.kind is ProviderKind.ANTHROPIC else None
        return Endpoint(
            profile=profile,
            base_url=url,
            key=key,
            client=sdk.http_client(profile, url, bearer=bearer),
            token_provider=tokens,
        )

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

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        """Build a pydantic-ai chat model.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The model.
        """
        return await self._sdk(profile).chat_model(await self.endpoint(profile), model)

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Build a pydantic-ai embedder.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The embedder.
        """
        return await self._sdk(profile).embedder(await self.endpoint(profile), model)

    async def reranker(self, profile: ProviderProfile, model: str) -> object:
        """Build a Cohere-compatible HTTP reranker.

        Args:
            profile: The profile.
            model: The model name.

        Returns:
            The reranker.
        """
        return self._sdk(profile).reranker(await self.endpoint(profile), model)

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        """Make one minimal call as ``role`` uses the model, and time it.

        Args:
            profile: The profile.
            model: The model name.
            role: A chat turn (``llm``, ``judge``), an embedding or a rerank.

        Returns:
            The outcome; a failure says why, with any key masked.
        """
        started = time.perf_counter()
        try:
            sdk = self._sdk(profile)
        except ProviderUnsupportedError as error:
            return self._failed(profile, model, role, started, str(error))
        try:
            served, dimensions = await self._call(sdk, profile, model, role)
        except sdk.call_errors() as error:  # a check reports a failed call, it never raises
            return self._failed(profile, model, role, started, f"{type(error).__name__}: {error}")
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
        self, sdk: ModuleType, profile: ProviderProfile, model: str, role: ModelRole
    ) -> tuple[str, int | None]:
        """Make the one call a role's check makes.

        Args:
            sdk: ``exactdocs.bootstrap.ai_sdk``.
            profile: The profile.
            model: The model name.
            role: The role.

        Returns:
            The model that answered, and an embedding's vector size.
        """
        match role:
            case ModelRole.EMBEDDING:
                embedder = await self.embedder(profile, model)
                return await sdk.check_embedding(embedder, CHECK_TEXT)
            case ModelRole.RERANKER:
                return await sdk.check_rerank(await self.reranker(profile, model), CHECK_TEXT), None
            case ModelRole.LLM | ModelRole.JUDGE:
                return await sdk.check_chat(await self.chat_model(profile, model)), None

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
class ConfiguredAi:
    """The AI configuration of the environment and the TOML file, in retrieval's terms."""

    profiles: tuple[ProviderProfile, ...] = ()
    """The configured profiles (read-only over the REST API)."""
    keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    """The keys given in the environment, by profile name: they never leave bootstrap."""
    roles: InstanceRoles = field(default_factory=InstanceRoles)
    """The instance's roles."""


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
        ),
    )


def _role(text: str | None) -> ModelRef | None:
    """Read a role's ``<profile>:<model>``; blank is unset.

    Args:
        text: The setting.

    Returns:
        The reference, or ``None``.
    """
    return ModelRef.parse(text) if text and text.strip() else None
