"""The ``Harness`` protocol: a coding-agent CLI that runs one task headless and leaves a transcript.

A harness writes its CLI's configuration for one run (the model and its provider, the arm's MCP
server, its built-in web tools off where it allows), gives the command that runs it headless, and
parses what it printed into a ``transcript.Transcript``. Each adapter is pinned to one release of
its CLI (``releases``). What a run needs is a ``HarnessRun``: the workspace, a home of its own, the
prompt, the model and the arm's MCP server as the run reaches it (through the gate, ``gate``).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlsplit

from harness_bench.transcript import Transcript


@dataclass(frozen=True, slots=True, kw_only=True)
class Provider:
    """A model provider a harness can run against, with where its key and base URL come from."""

    name: str
    """Its name in a model name (``anthropic:claude-sonnet-4-5``)."""
    base_url: str
    """Its API's base URL."""
    key_variable: str
    """The environment variable that holds its API key; passed to the CLI's container as is."""
    base_url_variable: str
    """The environment variable that points it at another base URL (a gateway, a stand-in)."""


PROVIDERS: Final[dict[str, Provider]] = {
    p.name: p
    for p in (
        Provider(
            name="anthropic",
            base_url="https://api.anthropic.com",
            key_variable="ANTHROPIC_API_KEY",
            base_url_variable="ANTHROPIC_BASE_URL",
        ),
        Provider(
            name="openai",
            base_url="https://api.openai.com/v1",
            key_variable="OPENAI_API_KEY",
            base_url_variable="OPENAI_BASE_URL",
        ),
        Provider(
            name="google",
            base_url="https://generativelanguage.googleapis.com",
            key_variable="GEMINI_API_KEY",
            base_url_variable="GOOGLE_GEMINI_BASE_URL",
        ),
        Provider(
            name="ollama",
            base_url="https://ollama.com/v1",
            key_variable="OLLAMA_API_KEY",
            base_url_variable="OLLAMA_BASE_URL",
        ),
    )
}
"""The providers, by name. Their keys are API keys: a subscription login is never used."""
THINKING_LEVELS: Final[tuple[str, ...]] = ("minimal", "low", "medium", "high", "xhigh", "max")
"""The thinking settings a run takes (``--thinking``); each harness says how it applies them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HarnessModel:
    """A model a harness runs: its provider, its name there and the thinking setting."""

    name: str
    """``<provider>:<model>``, as the report names it (``ollama:gpt-oss:120b``)."""
    provider: Provider
    """Its provider."""
    model: str
    """Its name at the provider."""
    base_url: str
    """The provider's base URL as the run reaches it."""
    thinking: str | None = None
    """The thinking setting (``THINKING_LEVELS``); the model's default when ``None``."""

    @classmethod
    def parse(
        cls, name: str, *, thinking: str | None = None, env: Mapping[str, str] | None = None
    ) -> HarnessModel:
        """Read ``<provider>:<model>``.

        Args:
            name: E.g. ``anthropic:claude-sonnet-4-5`` or ``ollama:gpt-oss:120b``.
            thinking: The thinking setting.
            env: Where the provider's base URL variable is read (``os.environ`` by default).

        Returns:
            The model, its base URL from the provider's variable when set.

        Raises:
            ValueError: No provider, an unknown one, or an unknown thinking setting.
        """
        provider_name, colon, model = name.partition(":")
        provider = PROVIDERS.get(provider_name)
        if not colon or not model or provider is None:
            message = f"model {name!r}: give <provider>:<model>, the providers are " + ", ".join(
                PROVIDERS
            )
            raise ValueError(message)
        if thinking is not None and thinking not in THINKING_LEVELS:
            message = f"thinking {thinking!r}: one of {', '.join(THINKING_LEVELS)}"
            raise ValueError(message)
        environment = os.environ if env is None else env
        base_url = environment.get(provider.base_url_variable) or provider.base_url
        return cls(name=name, provider=provider, model=model, base_url=base_url, thinking=thinking)

    @property
    def address(self) -> tuple[str, int]:
        """The provider's host and port, which the gate lets the run reach.

        Returns:
            ``(host, port)``; 443 for ``https`` unless the URL names a port.
        """
        parts = urlsplit(self.base_url)
        default = 443 if parts.scheme == "https" else 80
        return parts.hostname or "", parts.port or default


@dataclass(frozen=True, slots=True, kw_only=True)
class McpServer:
    """The arm's MCP server as a run reaches it."""

    name: str
    """Its name in the CLI's configuration (the arm's, ``grounded_docs`` for ``grounded-docs``)."""
    url: str
    """Its streamable HTTP endpoint, as the run reaches it (through the gate)."""
    tools: tuple[str, ...] = ()
    """The tools the arm gets."""
    excluded: tuple[str, ...] = ()
    """Tools the server lists that the arm must not get (Grounded Docs' ``fetch_url``)."""
    headers: Mapping[str, str] = field(default_factory=dict)
    """What every request to it carries (ExactDocs' API token, Context7's key)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HarnessRun:
    """One run of a harness: where it works, what it is asked and with what."""

    workspace: Path
    """The task's workspace: the CLI's working directory, the only project it may change."""
    home: Path
    """The run's own home: the CLI's configuration and state, nothing shared between runs."""
    prompt: str
    """What the CLI is asked."""
    model: HarnessModel
    """The model."""
    mcp: McpServer | None = None
    """The arm's MCP server; ``None`` for ``none``."""
    max_turns: int = 40
    """The most turns (model requests) a run may take, where the CLI can limit them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Invocation:
    """How to run a configured CLI."""

    argv: tuple[str, ...]
    """The command line."""
    env: Mapping[str, str] = field(default_factory=dict)
    """Its environment variables (no secret)."""
    secrets: tuple[str, ...] = ()
    """Variables passed through from this process's environment by name (the provider's key), so
    their values never appear on a command line or in a file."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CliRelease:
    """One pinned release of a CLI on npm."""

    package: str
    """The npm package."""
    version: str
    """The release."""
    integrity: str
    """The registry's integrity hash of its tarball: an install of anything else is refused."""
    released: date
    """When it was published."""
    executable: str
    """Its command, under ``node_modules/.bin``."""


class Harness(Protocol):
    """A coding-agent CLI: configure it for a run, run it headless, parse its transcript."""

    @property
    def name(self) -> str:
        """Its name on the command line and in the report."""
        ...

    @property
    def release(self) -> CliRelease:
        """The pinned release of its CLI."""
        ...

    @property
    def providers(self) -> frozenset[str]:
        """The model providers it runs against (``PROVIDERS``)."""
        ...

    @property
    def web_tools(self) -> str:
        """How its built-in web search and fetch are turned off, or that they cannot be."""
        ...

    @property
    def limits(self) -> str:
        """How the turn limit and the thinking setting reach it."""
        ...

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Write the CLI's configuration for a run into its home, and give its command line.

        Args:
            run: The run.
            executable: The installed CLI.

        Returns:
            The command line, its environment and the secrets it needs.
        """
        ...

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse what the CLI printed.

        Args:
            output: Its standard output.
            run: The run (its model and MCP server name).

        Returns:
            The transcript.
        """
        ...
