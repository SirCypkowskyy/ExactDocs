"""Claude Code headless: ``claude -p`` with ``--mcp-config`` and stream-JSON output.

- The arm's MCP server is the only one (``--mcp-config`` with ``--strict-mcp-config``), its tools
  named ``mcp__<server>__<tool>``; a tool the arm must not get is disallowed by name.
- ``WebSearch`` and ``WebFetch`` are disallowed (``--disallowedTools``): Claude Code lets both be
  turned off. Its other traffic (updates, telemetry, error reports) is off by its variables.
- Every permission is granted (``--permission-mode bypassPermissions``): the run is sandboxed by its
  container. Claude Code refuses that as root unless ``IS_SANDBOX`` is set, which the container is.
- ``--max-turns`` limits the turns; ``--effort`` takes the thinking setting.

The stream-JSON transcript is one event per line: ``system`` (``init``: the tools offered, the MCP
servers and their status, the model, the version), ``assistant`` (one content block per event:
``text``, ``thinking``, ``tool_use``; the message's usage repeats on each block of a message),
``user`` (the ``tool_result`` of each call) and the final ``result`` (the answer, the duration,
the turns, ``total_cost_usd``, the usage over the run). Claude Code counts the thinking in the
output tokens and does not report it on its own.
"""

import json
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
    package="@anthropic-ai/claude-code",
    version="2.1.330",
    integrity=(
        "sha512-KQMl6kixLMGHRCDUhkUPebuBhw13MpxlH3+17QzHQx40FNVd1z3uFKUSqQXB5zF9vLQGcpoC/8wWe5R35lsWvQ=="
    ),
    released=date(2026, 11, 20),
    executable="claude",
)
"""The pinned Claude Code release."""
WEB_TOOLS: Final[tuple[str, ...]] = ("WebSearch", "WebFetch")
"""Claude Code's built-in web tools."""
QUIET: Final[dict[str, str]] = {
    "IS_SANDBOX": "1",
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_BUG_COMMAND": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
}
"""Its variables for a sandboxed, quiet run: no update, no telemetry, no error report."""
MCP_FILE: Final[str] = "claude-mcp.json"
"""The MCP configuration, in the run's home."""


def prefix(server: str) -> str:
    """How Claude Code names a server's tools.

    Args:
        server: The server's name.

    Returns:
        ``mcp__<server>__``.
    """
    return f"mcp__{server}__"


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaudeCode:
    """The Claude Code harness."""

    name: str = "claude-code"
    """Its name."""
    release: CliRelease = RELEASE
    """The pinned release."""
    providers: frozenset[str] = frozenset({"anthropic"})
    """It runs Anthropic's models (or a gateway at ``ANTHROPIC_BASE_URL``)."""
    web_tools: str = "off: --disallowedTools WebSearch WebFetch"
    """How its web tools are turned off."""
    limits: str = "--max-turns; thinking: --effort"
    """How the turn limit and the thinking setting reach it."""

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Write the MCP configuration and give the headless command line.

        Args:
            run: The run.
            executable: The ``claude`` executable.

        Returns:
            The invocation; the provider's key is passed through by name.
        """
        servers: dict[str, Any] = {}
        disallowed = list(WEB_TOOLS)
        if run.mcp is not None:
            servers[run.mcp.name] = {"type": "http", "url": run.mcp.url}
            if run.mcp.headers:
                servers[run.mcp.name]["headers"] = dict(run.mcp.headers)
            disallowed += [prefix(run.mcp.name) + tool for tool in run.mcp.excluded]
        config = run.home / MCP_FILE
        config.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")
        argv = [
            str(executable),
            "-p",
            run.prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            run.model.model,
            "--max-turns",
            str(run.max_turns),
            "--mcp-config",
            str(config),
            "--strict-mcp-config",
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
            "--disallowedTools",
            *disallowed,
        ]
        if run.model.thinking:
            argv += ["--effort", run.model.thinking]
        env = dict(QUIET)
        if run.model.base_url != run.model.provider.base_url:
            env["ANTHROPIC_BASE_URL"] = run.model.base_url
        return Invocation(argv=tuple(argv), env=env, secrets=(run.model.provider.key_variable,))

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse a stream-JSON transcript.

        Args:
            output: What ``claude -p --output-format stream-json --verbose`` printed.
            run: The run.

        Returns:
            The transcript; the usage and the cost are the final ``result``'s.
        """
        prefixes = {run.mcp.name: prefix(run.mcp.name)} if run.mcp else {}
        calls: dict[str, HarnessCall] = {}
        order: list[str] = []
        texts: list[str] = []
        fields: dict[str, Any] = {"lines": 0, "unparsed": 0, "thinking_chars": 0}
        messages: set[str] = set()
        result: dict[str, Any] | None = None
        for event in events(output):
            fields["lines"] += 1
            kind = event.get("type") if event else None
            if event is None or kind not in {"system", "assistant", "user", "result"}:
                fields["unparsed"] += event is None
                continue
            if kind == "system" and event.get("subtype") == "init":
                fields["tools_offered"] = [str(t) for t in event.get("tools", [])]
                fields["model"] = event.get("model")
                version = event.get("claude_code_version")
                fields["cli_version"] = (
                    version.get("VERSION") if isinstance(version, dict) else version
                )
            elif kind == "assistant":
                message = event.get("message") or {}
                if event.get("parent_tool_use_id") is None and message.get("id"):
                    messages.add(str(message["id"]))
                for block in message.get("content") or []:
                    self._block(block, prefixes, calls, order, texts, fields)
            elif kind == "user":
                for block in (event.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        self._result(block, calls)
            else:
                result = event
        return self._finish(result, [calls[i] for i in order], texts, fields, len(messages), run)

    @staticmethod
    def _block(
        block: object,
        prefixes: dict[str, str],
        calls: dict[str, HarnessCall],
        order: list[str],
        texts: list[str],
        fields: dict[str, Any],
    ) -> None:
        """Read one content block of an assistant event.

        Args:
            block: The block.
            prefixes: The MCP server's tool prefix.
            calls: The calls so far, by ID.
            order: Their IDs in order.
            texts: The text blocks so far.
            fields: The transcript's counters.
        """
        if not isinstance(block, dict):
            return
        if block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        elif block.get("type") == "thinking":
            fields["thinking_chars"] += len(str(block.get("thinking", "")))
        elif block.get("type") == "tool_use":
            name = str(block.get("name", ""))
            server, tool = mcp_tool(name, prefixes)
            call_id = str(block.get("id", len(order)))
            if call_id not in calls:
                order.append(call_id)
            calls[call_id] = HarnessCall(
                name=name,
                server=server,
                tool=tool,
                args=shown(block.get("input", {})),
                web=name in WEB_TOOLS,
            )

    @staticmethod
    def _result(block: dict[str, Any], calls: dict[str, HarnessCall]) -> None:
        """Read a tool's result: keep its error.

        Args:
            block: The ``tool_result`` block.
            calls: The calls, by ID.
        """
        call = calls.get(str(block.get("tool_use_id")))
        if call is None or not block.get("is_error"):
            return
        content = block.get("content")
        if isinstance(content, list):
            content = " ".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
        calls[str(block.get("tool_use_id"))] = call.model_copy(
            update={"error": str(content or "error")[:500]}
        )

    @staticmethod
    def _finish(
        result: dict[str, Any] | None,
        calls: list[HarnessCall],
        texts: list[str],
        fields: dict[str, Any],
        turns: int,
        run: HarnessRun,
    ) -> Transcript:
        """Build the transcript from the final ``result`` event.

        Args:
            result: The ``result`` event; ``None`` when the CLI ended without one.
            calls: The tool calls.
            texts: The text blocks.
            fields: The counters and what ``init`` said.
            turns: The distinct assistant messages (model requests) of the main agent.
            run: The run.

        Returns:
            The transcript.
        """
        if result is None:
            return Transcript(
                calls=calls,
                answer=texts[-1] if texts else "",
                turns=turns,
                error="the transcript has no result",
                **fields,
            )
        usage = result.get("usage") or {}
        cached = number(usage.get("cache_read_input_tokens"))
        input_tokens = (
            number(usage.get("input_tokens"))
            + number(usage.get("cache_creation_input_tokens"))
            + cached
        )
        output_tokens = number(usage.get("output_tokens"))
        cost = result.get("total_cost_usd")
        money, source = priced(
            run.model.name,
            input_tokens,
            output_tokens,
            float(cost) if isinstance(cost, int | float) else None,
        )
        error = None
        if result.get("is_error") or result.get("subtype") != "success":
            details = result.get("errors") or [result.get("result") or result.get("subtype")]
            error = f"{result.get('subtype')}: " + "; ".join(str(d) for d in details)
        answer = str(result.get("result") or "") if error is None else ""
        duration = result.get("duration_ms")
        return Transcript(
            answer=answer,
            calls=calls,
            turns=number(result.get("num_turns")) or turns,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output_tokens,
            usd=money,
            usd_source=source,
            reported_seconds=round(duration / 1000, 3)
            if isinstance(duration, int | float)
            else None,
            error=error,
            provider_failure=error is not None and provider_failed(error),
            **fields,
        )
