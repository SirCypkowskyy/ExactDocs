"""Gemini CLI headless: ``gemini -p`` with stream-JSON output.

- The arm's MCP server is the only one (``mcpServers`` in the run's ``~/.gemini/settings.json``,
  ``--allowed-mcp-server-names``), its tools named ``mcp_<server>_<tool>``; a tool the arm must
  not get is in the server's ``excludeTools``.
- ``google_web_search`` and ``web_fetch`` are excluded (``tools.exclude``): Gemini CLI lets both be
  turned off. Usage statistics, telemetry and updates are off.
- Every tool runs without asking (``--approval-mode yolo``), the workspace trusted
  (``--skip-trust``): the run is sandboxed by its container.
- ``model.maxSessionTurns`` limits the turns. Gemini CLI takes no thinking setting on its command
  line: each model thinks as Gemini CLI configures it, which the report records.

The stream-JSON transcript (``JsonStreamEventType``) is one event per line: ``init`` (the session
and the model), ``message`` (the assistant's text in deltas), ``tool_use`` (name, ID, parameters),
``tool_result`` (status, output or error), ``error`` and the final ``result`` (status, ``stats``:
``total_tokens``, ``input_tokens`` (the prompt, cached included), ``output_tokens`` (the
candidates, without the thinking), ``cached``, ``duration_ms``, ``tool_calls``, per model). Gemini
counts the thinking apart from the candidates and the stream's stats leave it out, so it is
derived: ``total_tokens - input_tokens - output_tokens``.
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
    package="@google/gemini-cli",
    version="0.70.0",
    integrity=(
        "sha512-5gilVH8BI2bjSCf+X6zgGpT75bLWzK9UoZS1akjaaBwgWhm1durzKkNC1M3FamcW40YoqV0PDi4hRCIsY3f9Sg=="
    ),
    released=date(2026, 11, 19),
    executable="gemini",
)
"""The pinned Gemini CLI release."""
WEB_TOOLS: Final[tuple[str, ...]] = ("google_web_search", "web_fetch")
"""Gemini CLI's built-in web tools."""
QUIET: Final[dict[str, str]] = {"GEMINI_CLI_NO_RELAUNCH": "true", "NO_BROWSER": "true"}
"""Its variables for a headless run: no relaunch with more memory, no browser."""


def prefix(server: str) -> str:
    """How Gemini CLI names a server's tools.

    Args:
        server: The server's name.

    Returns:
        ``mcp_<server>_``.
    """
    return f"mcp_{server}_"


def _message(event: dict[str, Any], answer: list[str]) -> None:
    """Read a ``message``: the assistant's text, in deltas (the prompt, echoed, is skipped).

    Args:
        event: The event.
        answer: The assistant's text since the last tool call.
    """
    if event.get("role") != "assistant":
        return
    if not event.get("delta"):
        answer.clear()
    answer.append(str(event.get("content", "")))


def _tool_event(
    event: dict[str, Any], prefixes: dict[str, str], calls: dict[str, HarnessCall]
) -> None:
    """Read a ``tool_use`` (a new call) or a ``tool_result`` (its error, if it failed).

    Args:
        event: The event.
        prefixes: The MCP server's tool prefix.
        calls: The calls so far, by tool ID, in order.
    """
    call_id = str(event.get("tool_id", len(calls)))
    if event.get("type") == "tool_use":
        name = str(event.get("tool_name", ""))
        server, tool = mcp_tool(name, prefixes)
        calls[call_id] = HarnessCall(
            name=name,
            server=server,
            tool=tool,
            args=shown(event.get("parameters", {})),
            web=name in WEB_TOOLS,
        )
        return
    call = calls.get(call_id)
    if call is not None and event.get("status") == "error":
        error = event.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else error
        calls[call_id] = call.model_copy(update={"error": str(message or "error")[:500]})


@dataclass(frozen=True, slots=True, kw_only=True)
class GeminiCli:
    """The Gemini CLI harness."""

    name: str = "gemini-cli"
    """Its name."""
    release: CliRelease = RELEASE
    """The pinned release."""
    providers: frozenset[str] = frozenset({"google"})
    """It runs Google's Gemini models with a Gemini API key."""
    web_tools: str = "off: tools.exclude google_web_search, web_fetch"
    """How its web tools are turned off."""
    limits: str = "model.maxSessionTurns; thinking: not settable on its command line (its default)"
    """How the turn limit and the thinking setting reach it."""

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Write ``~/.gemini/settings.json`` and give the headless command line.

        Args:
            run: The run.
            executable: The ``gemini`` executable.

        Returns:
            The invocation; the provider's key is passed through by name.
        """
        servers: dict[str, Any] = {}
        if run.mcp is not None:
            server: dict[str, Any] = {"httpUrl": run.mcp.url, "trust": True, "timeout": 120_000}
            if run.mcp.excluded:
                server["excludeTools"] = list(run.mcp.excluded)
            if run.mcp.headers:
                server["headers"] = dict(run.mcp.headers)
            servers[run.mcp.name] = server
        settings = {
            "security": {
                "auth": {"selectedType": "gemini-api-key"},
                "folderTrust": {"enabled": False},
            },
            "general": {"disableAutoUpdate": True, "disableUpdateNag": True},
            "privacy": {"usageStatisticsEnabled": False},
            "telemetry": {"enabled": False},
            "model": {"maxSessionTurns": run.max_turns},
            "tools": {"exclude": list(WEB_TOOLS)},
            "mcpServers": servers,
        }
        folder = run.home / ".gemini"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        argv = [
            str(executable),
            "--prompt",
            run.prompt,
            "--output-format",
            "stream-json",
            "--model",
            run.model.model,
            "--approval-mode",
            "yolo",
            "--skip-trust",
        ]
        if run.mcp is not None:
            argv += ["--allowed-mcp-server-names", run.mcp.name]
        env = dict(QUIET)
        if run.model.base_url != run.model.provider.base_url:
            env["GOOGLE_GEMINI_BASE_URL"] = run.model.base_url
        return Invocation(argv=tuple(argv), env=env, secrets=(run.model.provider.key_variable,))

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse a stream-JSON transcript.

        Args:
            output: What ``gemini -p ... --output-format stream-json`` printed.
            run: The run.

        Returns:
            The transcript; the tokens are the final ``result``'s stats.
        """
        prefixes = {run.mcp.name: prefix(run.mcp.name)} if run.mcp else {}
        calls: dict[str, HarnessCall] = {}
        answer: list[str] = []
        fields: dict[str, Any] = {"lines": 0, "unparsed": 0}
        result: dict[str, Any] | None = None
        errors: list[str] = []
        for event in events(output):
            fields["lines"] += 1
            kind = event.get("type") if event else None
            if event is None:
                fields["unparsed"] += 1
            elif kind == "init":
                fields["model"] = event.get("model")
            elif kind == "message":
                _message(event, answer)
            elif kind in {"tool_use", "tool_result"}:
                _tool_event(event, prefixes, calls)
                if kind == "tool_use":
                    answer.clear()  # the answer is the text after the last tool call
            elif kind == "error":
                errors.append(str(event.get("message", "")))
            elif kind == "result":
                result = event
            else:
                fields["unparsed"] += 1
        return self._finish(result, list(calls.values()), "".join(answer), errors, fields, run)

    @staticmethod
    def _finish(
        result: dict[str, Any] | None,
        calls: list[HarnessCall],
        answer: str,
        errors: list[str],
        fields: dict[str, Any],
        run: HarnessRun,
    ) -> Transcript:
        """Build the transcript from the final ``result`` event.

        Args:
            result: The ``result`` event; ``None`` when the CLI ended without one.
            calls: The tool calls.
            answer: The assistant's text after the last tool call.
            errors: The ``error`` events' messages.
            fields: The counters and the model.
            run: The run.

        Returns:
            The transcript.
        """
        if result is None:
            error = "; ".join(errors) or "the transcript has no result"
            return Transcript(
                calls=calls,
                answer=answer,
                error=error,
                provider_failure=provider_failed(error),
                **fields,
            )
        stats = result.get("stats") or {}
        input_tokens = number(stats.get("input_tokens"))
        candidates = number(stats.get("output_tokens"))
        thinking = max(number(stats.get("total_tokens")) - input_tokens - candidates, 0)
        output_tokens = candidates + thinking
        money, source = priced(run.model.name, input_tokens, output_tokens, None)
        error = None
        if result.get("status") != "success":
            detail = result.get("error") or {}
            message = detail.get("message") if isinstance(detail, dict) else detail
            error = "; ".join([*errors, str(message or result.get("status"))])
        duration = stats.get("duration_ms")
        return Transcript(
            answer=answer if error is None else "",
            calls=calls,
            input_tokens=input_tokens,
            cached_input_tokens=number(stats.get("cached")),
            output_tokens=output_tokens,
            thinking_tokens=thinking if stats else None,
            thinking="derived" if stats else "not reported",
            usd=money,
            usd_source=source,
            reported_seconds=round(duration / 1000, 3)
            if isinstance(duration, int | float) and duration
            else None,
            error=error,
            provider_failure=error is not None and provider_failed(error),
            **fields,
        )
