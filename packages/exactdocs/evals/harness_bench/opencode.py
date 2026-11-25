"""OpenCode headless: ``opencode run --format json``.

- The run's configuration (``OPENCODE_CONFIG``, in its home) names the model and its provider
  (Anthropic, OpenAI and Google as OpenCode ships them; Ollama as an OpenAI-compatible provider),
  the arm's MCP server as the only one (``mcp``, a ``remote`` server), its tools named
  ``<server>_<tool>``; a tool the arm must not get is turned off by name (``tools``).
- ``webfetch`` and ``websearch`` are off (``tools`` and ``permission``): OpenCode lets both be
  turned off. Updates, sharing, the models catalog fetch and LSP downloads are off.
- Edits and commands are allowed without asking (``permission``, ``--auto``): the run is sandboxed
  by its container.
- The build agent's ``steps`` limits the turns; the thinking setting is the model's
  ``reasoningEffort`` (an OpenAI-compatible provider) or ``--variant``.

The transcript is one event per line, each with a ``part``: ``step_start``, ``text`` (a finished
text part), ``reasoning`` (with ``--thinking``), ``tool_use`` (a tool part whose ``state`` is
``completed`` or ``error``, with its input and output), ``step_finish`` (the step's ``tokens``:
``input`` without the cache, ``output`` without the reasoning, ``reasoning``, ``cache.read`` and
``cache.write``, and its ``cost``) and ``error``. A step is one model request.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from harness_bench.harness import CliRelease, HarnessRun, Invocation
from harness_bench.transcript import (
    HarnessCall,
    Transcript,
    events,
    mcp_tool,
    number,
    priced,
    provider_failed,
    shown,
)

RELEASE: Final[CliRelease] = CliRelease(
    package="opencode-ai",
    version="1.19.6",
    integrity=(
        "sha512-x0yTvlq3Cyhp3z1IhsNlktLa9M/FSbpMWiDlcGljKMTlBKdHM/um/03JedJa71N2yNlHkOvOPI0H4tbyXuuGwA=="
    ),
    released=date(2026, 11, 17),
    executable="opencode",
)
"""The pinned OpenCode release."""
WEB_TOOLS: Final[tuple[str, ...]] = ("webfetch", "websearch")
"""OpenCode's built-in web tools."""
CONFIG_FILE: Final[str] = "opencode.json"
"""The run's configuration, in its home."""
BUILT_IN: Final[frozenset[str]] = frozenset({"anthropic", "openai", "google"})
"""Providers OpenCode ships; the others are configured as OpenAI-compatible."""
QUIET: Final[dict[str, str]] = {
    "OPENCODE_DISABLE_AUTOUPDATE": "true",
    "OPENCODE_DISABLE_MODELS_FETCH": "true",
    "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
    "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
    "OPENCODE_DISABLE_CLAUDE_CODE": "true",
    "OPENCODE_DISABLE_TERMINAL_TITLE": "true",
}
"""Its variables for a quiet, offline-but-the-model run."""
UNSAFE: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9_-]")
"""What OpenCode replaces in an MCP server's and tool's name."""


def prefix(server: str) -> str:
    """How OpenCode names a server's tools.

    Args:
        server: The server's name.

    Returns:
        ``<server>_``, with what OpenCode replaces replaced.
    """
    return UNSAFE.sub("_", server) + "_"


def config_of(run: HarnessRun) -> dict[str, Any]:
    """The run's ``opencode.json``.

    Args:
        run: The run.

    Returns:
        The configuration.
    """
    model = run.model
    provider = model.provider.name
    providers: dict[str, Any] = {}
    if provider in BUILT_IN:
        if model.base_url != model.provider.base_url:
            providers[provider] = {"options": {"baseURL": model.base_url}}
    else:
        options: dict[str, Any] = {}
        if model.thinking:
            options["reasoningEffort"] = model.thinking
        providers[provider] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider,
            "options": {
                "baseURL": model.base_url,
                "apiKey": f"{{env:{model.provider.key_variable}}}",
            },
            "models": {model.model: {"name": model.model, "options": options}},
        }
    tools = dict.fromkeys(WEB_TOOLS, False)
    mcp: dict[str, Any] = {}
    if run.mcp is not None:
        mcp[run.mcp.name] = {"type": "remote", "url": run.mcp.url, "enabled": True}
        if run.mcp.headers:
            mcp[run.mcp.name]["headers"] = run.mcp.headers
        tools |= {prefix(run.mcp.name) + UNSAFE.sub("_", t): False for t in run.mcp.excluded}
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider}/{model.model}",
        "provider": providers,
        "mcp": mcp,
        "tools": tools,
        "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny"},
        "agent": {"build": {"steps": run.max_turns}},
        "autoupdate": False,
        "share": "disabled",
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenCode:
    """The OpenCode harness."""

    name: str = "opencode"
    """Its name."""
    release: CliRelease = RELEASE
    """The pinned release."""
    providers: frozenset[str] = frozenset({"anthropic", "openai", "google", "ollama"})
    """Anthropic's, OpenAI's and Google's models, and Ollama's as an OpenAI-compatible provider."""
    web_tools: str = "off: tools webfetch, websearch false; permission webfetch deny"
    """How its web tools are turned off."""
    limits: str = (
        "agent build steps; thinking: the model's reasoningEffort (OpenAI-compatible) or --variant"
    )
    """How the turn limit and the thinking setting reach it."""

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Write ``opencode.json`` into the run's home and give the headless command line.

        Args:
            run: The run.
            executable: The ``opencode`` executable.

        Returns:
            The invocation; the provider's key is passed through by name.
        """
        config = run.home / CONFIG_FILE
        config.write_text(json.dumps(config_of(run), indent=2) + "\n", encoding="utf-8")
        argv = [
            str(executable),
            "run",
            "--format",
            "json",
            "--thinking",
            "--auto",
            "--dir",
            str(run.workspace),
        ]
        if run.model.thinking and run.model.provider.name in BUILT_IN:
            argv += ["--variant", run.model.thinking]
        argv.append(run.prompt)
        env = {**QUIET, "OPENCODE_CONFIG": str(config)}
        return Invocation(argv=tuple(argv), env=env, secrets=(run.model.provider.key_variable,))

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse a ``run --format json`` transcript.

        Args:
            output: What ``opencode run --format json --thinking`` printed.
            run: The run.

        Returns:
            The transcript; the tokens add up every step's.
        """
        prefixes = {run.mcp.name: prefix(run.mcp.name)} if run.mcp else {}
        calls: list[HarnessCall] = []
        fields: dict[str, Any] = {"lines": 0, "unparsed": 0, "thinking_chars": 0}
        answer = ""
        spent = {"input": 0, "cached": 0, "output": 0, "reasoning": 0, "steps": 0}
        cost = 0.0
        errors: list[str] = []
        for event in events(output):
            fields["lines"] += 1
            kind = event.get("type") if event else None
            part = (event or {}).get("part") or {}
            if event is None:
                fields["unparsed"] += 1
            elif kind == "text":
                answer = str(part.get("text", ""))
            elif kind == "reasoning":
                fields["thinking_chars"] += len(str(part.get("text", "")))
            elif kind == "tool_use":
                calls.append(self._call(part, prefixes))
                answer = ""
            elif kind == "step_finish":
                tokens = part.get("tokens") or {}
                cache = tokens.get("cache") or {}
                spent["steps"] += 1
                spent["cached"] += number(cache.get("read"))
                spent["input"] += (
                    number(tokens.get("input"))
                    + number(cache.get("read"))
                    + number(cache.get("write"))
                )
                spent["output"] += number(tokens.get("output"))
                spent["reasoning"] += number(tokens.get("reasoning"))
                cost += float(part.get("cost") or 0)
            elif kind == "error":
                failure = event.get("error") or {}
                data = failure.get("data") or {}
                errors.append(str(data.get("message") or failure.get("name") or failure))
            elif kind != "step_start":
                fields["unparsed"] += 1
        return self._finish(calls, answer, spent, cost, errors, fields, run)

    @staticmethod
    def _call(part: dict[str, Any], prefixes: dict[str, str]) -> HarnessCall:
        """Read a finished tool part.

        Args:
            part: The tool part.
            prefixes: The MCP server's tool prefix.

        Returns:
            The call.
        """
        name = str(part.get("tool", ""))
        server, tool = mcp_tool(name, prefixes)
        state = part.get("state") or {}
        error = state.get("error") if state.get("status") == "error" else None
        return HarnessCall(
            name=name,
            server=server,
            tool=tool,
            args=shown(state.get("input", {})),
            error=str(error)[:500] if error else None,
            web=name in WEB_TOOLS,
        )

    @staticmethod
    def _finish(
        calls: list[HarnessCall],
        answer: str,
        spent: dict[str, int],
        cost: float,
        errors: list[str],
        fields: dict[str, Any],
        run: HarnessRun,
    ) -> Transcript:
        """Build the transcript from the steps' totals.

        Args:
            calls: The tool calls.
            answer: The text after the last tool call.
            spent: The steps' tokens and count.
            cost: The steps' cost as OpenCode prices them (0 for a model it has no price for).
            errors: The ``error`` events' messages.
            fields: The counters.
            run: The run.

        Returns:
            The transcript. The thinking is reported where OpenCode counted some; a model that
            returned thinking text with a count of 0 (an OpenAI-compatible provider that reports
            none) is ``not reported``.
        """
        steps = spent["steps"]
        output_tokens = spent["output"] + spent["reasoning"]
        reported = spent["reasoning"] > 0 or (steps > 0 and not fields["thinking_chars"])
        money, source = priced(run.model.name, spent["input"], output_tokens, cost)
        error = "; ".join(errors) or None
        if error is None and not answer and not steps:
            error = "the transcript has no step"
        return Transcript(
            answer=answer if error is None else "",
            calls=calls,
            turns=steps or None,
            input_tokens=spent["input"] if steps else None,
            cached_input_tokens=spent["cached"] if steps else None,
            output_tokens=output_tokens if steps else None,
            thinking_tokens=spent["reasoning"] if reported else None,
            thinking="reported" if reported else "not reported",
            usd=money,
            usd_source=source,
            error=error,
            provider_failure=error is not None and provider_failed(error),
            **fields,
        )
