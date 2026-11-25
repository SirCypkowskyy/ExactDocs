"""The agent and judge models: stand-ins, Ollama with retries, and the time lost to retries.

A model name is a pydantic-ai name (``openai:gpt-5-mini``), a stand-in (``offline:read``), or an
Ollama model (``ollama:gpt-oss:120b``) served at ``OLLAMA_BASE_URL`` (Ollama Cloud is
``https://ollama.com/v1``) with ``OLLAMA_API_KEY``. pydantic-ai's Ollama provider reads the
thinking from the response's ``reasoning`` field as ``ThinkingPart``s.

An Ollama model gets its own HTTP client so that rate limits are survived and measured: the OpenAI
client retries a 408, 409, 429, 5xx or a lost connection with backoff (``Retry-After`` honoured) up
to ``max_retries`` times, and the client's event hooks add up, per agent run, the requests that
failed and the time from each failed request to its retry (``retries.RetryLog``). The report takes
that time out of the wall time, so a rate limit does not make an arm look slow.
"""

import os
from typing import Final, get_args

from openai import AsyncOpenAI
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, create_async_httpx2_client
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings, ThinkingEffort, ThinkingLevel

from agent_bench.offline import OFFLINE_AGENTS, OFFLINE_JUDGE, offline_agent, offline_judge
from agent_bench.redact import safe_url
from agent_bench.retries import HOOKS

OLLAMA: Final[str] = "ollama"
"""The provider prefix of an Ollama model."""
BASE_URL_VARIABLE: Final[str] = "OLLAMA_BASE_URL"
"""Where the Ollama server is (``https://ollama.com/v1`` for Ollama Cloud)."""
KEY_VARIABLE: Final[str] = "OLLAMA_API_KEY"
"""The Ollama API key's variable; its value is never recorded."""
DEFAULT_RETRIES: Final[int] = 6
"""Retries of a failed provider request (429, 5xx, a lost connection) by default."""
REQUEST_TIMEOUT: Final[float] = 300.0
"""Seconds one model request may take (a long thinking answer included)."""


def ollama_model(name: str, *, max_retries: int = DEFAULT_RETRIES) -> OpenAIChatModel:
    """An Ollama model through pydantic-ai's Ollama provider, with retries and their log.

    Args:
        name: The model as Ollama names it (``gpt-oss:120b``).
        max_retries: Retries of a failed request.

    Returns:
        The model.

    Raises:
        UserError: ``OLLAMA_BASE_URL`` is not set.
    """
    base_url = os.environ.get(BASE_URL_VARIABLE)
    if not base_url:
        message = f"set {BASE_URL_VARIABLE} (https://ollama.com/v1 for Ollama Cloud)"
        raise UserError(message)
    http = create_async_httpx2_client(timeout=REQUEST_TIMEOUT)  # pydantic-ai's defaults
    http.event_hooks = HOOKS
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get(KEY_VARIABLE) or "api-key-not-set",
        max_retries=max_retries,
        http_client=http,
    )
    return OpenAIChatModel(name, provider=OllamaProvider(openai_client=client))


def chat_model(name: str, *, max_retries: int = DEFAULT_RETRIES) -> Model | str:
    """Resolve an agent or judge model name.

    Args:
        name: A pydantic-ai model name (``openai:gpt-5-mini``), an Ollama model
            (``ollama:gpt-oss:120b``), or a stand-in (``offline:search``, ``offline:read``,
            ``offline`` for the judge).
        max_retries: Retries of a failed Ollama request.

    Returns:
        The stand-in or Ollama model, or the name for pydantic-ai to resolve.
    """
    if name in OFFLINE_AGENTS:
        return offline_agent(name)
    if name == OFFLINE_JUDGE:
        return offline_judge()
    provider, colon, model = name.partition(":")
    if provider == OLLAMA and colon and model:
        return ollama_model(model, max_retries=max_retries)
    return name


def thinking_setting(text: str | None) -> ThinkingLevel | None:
    """Read the ``--thinking`` option.

    Args:
        text: ``on``, ``off``, an effort (``low`` ... ``max``), or nothing.

    Returns:
        pydantic-ai's ``thinking`` value; ``None`` leaves each model at its default.

    Raises:
        ValueError: Another value.
    """
    if text is None or not text.strip():
        return None
    value = text.strip().lower()
    for level in get_args(ThinkingEffort):
        if value == level:
            return level
    if value in {"on", "off"}:
        return value == "on"
    message = f"thinking {text!r} is not on, off or one of {', '.join(get_args(ThinkingEffort))}"
    raise ValueError(message)


def model_settings(thinking: ThinkingLevel | None) -> ModelSettings | None:
    """The agent's model settings.

    Args:
        thinking: pydantic-ai's ``thinking`` value, or ``None`` for the model's default.

    Returns:
        The settings, or ``None`` for none.
    """
    return None if thinking is None else ModelSettings(thinking=thinking)


def providers_used(names: list[str]) -> dict[str, str]:
    """Where the run's models are served, for the report: base URLs only, never a key.

    Args:
        names: The agent and judge models.

    Returns:
        Provider to base URL, for the providers that take one from the environment.
    """
    used = {}
    if any(n.startswith(f"{OLLAMA}:") for n in names) and (
        url := os.environ.get(BASE_URL_VARIABLE)
    ):
        used[OLLAMA] = safe_url(url)
    if any(n.startswith("openai:") for n in names) and (url := os.environ.get("OPENAI_BASE_URL")):
        used["openai"] = safe_url(url)
    return used
