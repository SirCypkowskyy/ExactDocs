"""What a CLI's transcript says about a run: its tool calls, its answer, its tokens and its cost.

Each harness parses its own output format into a ``Transcript`` (``Harness.parse``). The fields are
the same for every harness, so the report compares them; where a CLI does not report something,
the field says so instead of guessing:

- ``input_tokens`` count every input token, cached ones included (``cached_input_tokens`` of them);
- ``output_tokens`` count the output with the thinking included, whatever the CLI calls output;
- ``thinking_tokens`` is the thinking on its own, with ``thinking`` saying where it comes from:
  ``reported`` by the CLI, ``derived`` from totals it reports, or ``not reported`` (``None``);
- ``usd`` is the CLI's own cost when it reports one, else the bundled price list's
  (``agent_bench.harness.usd``), else ``None`` (unpriced, never 0).
"""

import json
import re
from collections.abc import Iterator, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_bench.harness import ARGS_SHOWN, usd

type ThinkingSource = Literal["reported", "derived", "not reported"]
"""Where a transcript's thinking tokens come from."""
type UsdSource = Literal["reported", "price list", "unpriced"]
"""Where a run's USD comes from."""

PROVIDER_FAILURE: Final[re.Pattern[str]] = re.compile(
    r"\b(429|500|502|503|504|529)\b|rate.?limit|too many requests|overloaded|quota|"
    r"service unavailable|internal server error|bad gateway|gateway time-?out|"
    r"ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|socket hang up|fetch failed|"
    r"connection (?:reset|refused|closed|error)|stream disconnected|"
    r"usage limit|session limit",
    re.IGNORECASE,
)
"""What a CLI's error says when the model provider failed (rate limited, a server error, a lost
connection): the run is not graded and ``--resume`` asks it again."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class HarnessCall(_Model):
    """One tool call a CLI made."""

    name: str
    """The tool as the CLI names it (``mcp__exactdocs__search_docs``, ``bash``, ``write``)."""
    server: str | None = None
    """The MCP server it belongs to; ``None`` for a built-in tool."""
    tool: str
    """The tool's own name (the MCP tool, without the CLI's prefix)."""
    args: str = ""
    """Its arguments as JSON, cut to ``ARGS_SHOWN`` characters."""
    error: str | None = None
    """What it returned when it failed."""
    web: bool = False
    """A built-in web search or fetch tool (the arms must not have one)."""


class Transcript(_Model):
    """A CLI's transcript, parsed."""

    answer: str = ""
    """The final message."""
    calls: list[HarnessCall] = Field(default_factory=list)
    """Every tool call, in order."""
    tools_offered: list[str] = Field(default_factory=list)
    """The tools the CLI says it offered the model, where its transcript lists them."""
    model: str | None = None
    """The model the CLI says it ran."""
    cli_version: str | None = None
    """The CLI's version, where its transcript says it."""
    turns: int | None = None
    """Model requests (turns or steps), where the transcript counts them."""
    input_tokens: int | None = None
    """Input tokens over the run, cached ones included; ``None`` when not reported."""
    cached_input_tokens: int | None = None
    """Of ``input_tokens``, those read from the provider's cache."""
    output_tokens: int | None = None
    """Output tokens over the run, the thinking included; ``None`` when not reported."""
    thinking_tokens: int | None = None
    """Thinking tokens on their own; ``None`` when the CLI does not report them."""
    thinking: ThinkingSource = "not reported"
    """Where ``thinking_tokens`` comes from."""
    thinking_chars: int = 0
    """Characters of thinking text the transcript holds."""
    usd: float | None = None
    """What the run cost; ``None`` when unpriced."""
    usd_source: UsdSource = "unpriced"
    """Where ``usd`` comes from."""
    reported_seconds: float | None = None
    """The run's duration as the CLI reports it."""
    error: str | None = None
    """Why the run ended without an answer, as the CLI says it."""
    provider_failure: bool = False
    """``error`` is the model provider's (rate limited, a server error, a lost connection)."""
    lines: int = 0
    """Lines of output read."""
    unparsed: int = 0
    """Lines that were not one of the format's events (a CLI's log line, a truncated line)."""

    def docs_calls(self, server: str | None) -> int:
        """Count the calls to one MCP server.

        Args:
            server: The arm's server name; ``None`` for no server.

        Returns:
            The calls to its tools.
        """
        return 0 if server is None else sum(c.server == server for c in self.calls)


def events(text: str) -> Iterator[dict[str, Any] | None]:
    """Read JSON lines.

    Args:
        text: The CLI's standard output.

    Yields:
        Each non-empty line's object, or ``None`` for a line that is not a JSON object.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            yield None
            continue
        yield value if isinstance(value, dict) else None


def shown(args: object) -> str:
    """Show a call's arguments as the agent benchmark records them.

    Args:
        args: The arguments (an object, or a string the CLI already encoded).

    Returns:
        JSON, keys sorted, cut to ``ARGS_SHOWN`` characters.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args[:ARGS_SHOWN]
    return json.dumps(args, ensure_ascii=False, sort_keys=True)[:ARGS_SHOWN]


def number(value: object) -> int:
    """Read a token count.

    Args:
        value: A JSON value.

    Returns:
        The integer, 0 for anything else.
    """
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def priced(
    model: str, input_tokens: int | None, output_tokens: int | None, reported: float | None
) -> tuple[float | None, UsdSource]:
    """Price a run: the CLI's own cost when it reports one, else the bundled price list's.

    Args:
        model: The pydantic-ai style model name (``anthropic:claude-sonnet-4-5``).
        input_tokens: Input tokens.
        output_tokens: Output tokens, the thinking included.
        reported: The CLI's own cost, if it reports one (0 is taken as not priced: a CLI reports 0
            for a model it has no price for).

    Returns:
        The USD and where it comes from.
    """
    if reported:
        return round(reported, 6), "reported"
    if input_tokens is None or output_tokens is None:
        return None, "unpriced"
    found = usd(model, input_tokens, output_tokens)
    return (None, "unpriced") if found is None else (round(found, 6), "price list")


def provider_failed(*texts: str | None) -> bool:
    """Tell whether an error is the model provider's.

    Args:
        texts: What the CLI said about the failure.

    Returns:
        True when one of them names a rate limit, a server error or a lost connection.
    """
    return any(text and PROVIDER_FAILURE.search(text) for text in texts)


def mcp_tool(name: str, prefixes: Mapping[str, str]) -> tuple[str | None, str]:
    """Split a tool name into its MCP server and the server's tool name.

    Args:
        name: The tool as the CLI names it.
        prefixes: Each MCP server's prefix as the CLI writes it (``mcp__exactdocs__``), by server.

    Returns:
        The server (``None`` for a built-in tool) and the tool's own name.
    """
    for server, prefix in prefixes.items():
        if name.startswith(prefix):
            return server, name.removeprefix(prefix)
    return None, name
