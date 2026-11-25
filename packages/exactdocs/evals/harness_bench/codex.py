"""Codex CLI headless: ``codex exec --json``.

- The run's ``CODEX_HOME`` holds a ``config.toml`` of its own: the model's provider (OpenAI, or
  Ollama through a custom provider on the Responses API, which is the only one Codex speaks), the
  arm's MCP server as the only one (``[mcp_servers.<name>]`` over streamable HTTP, a tool the arm
  must not get in ``disabled_tools``), and ``web_search = "disabled"``: Codex lets its web search
  be turned off. It has no web fetch tool. Update checks and analytics are off.
- Codex's own sandbox and approvals are off (``--dangerously-bypass-approvals-and-sandbox``,
  meant for an environment sandboxed from outside): the run's container is that sandbox.
- ``model_reasoning_effort`` takes the thinking setting. Codex has no turn limit: the run's wall
  limit stops it.

The transcript is one event per line: ``thread.started``, ``turn.started``, ``item.started``,
``item.updated`` and ``item.completed`` (an item is an ``agent_message``, ``reasoning``,
``command_execution``, ``file_change``, ``mcp_tool_call`` with its ``server`` and ``tool``,
``web_search``, ``todo_list`` or ``error``), ``turn.completed`` with the turn's ``usage``
(``input_tokens`` with ``cached_input_tokens`` among them, ``output_tokens`` with the reasoning
included, and ``reasoning_output_tokens`` where reported), ``turn.failed`` and ``error``.
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
    number,
    priced,
    provider_failed,
    shown,
)

RELEASE: Final[CliRelease] = CliRelease(
    package="@openai/codex",
    version="0.171.0",
    integrity=(
        "sha512-1IOFzL2Xg86tLdw6kDo3GoKbkQENgQi7TI6rlEvN132R7ngSw7SNOIQoTcnKzSZZ8kf9N9GynCweSoaFbqk2Eg=="
    ),
    released=date(2026, 11, 20),
    executable="codex",
)
"""The pinned Codex CLI release."""
CODEX_HOME: Final[str] = ".codex"
"""The run's ``CODEX_HOME``, in its home."""
CUSTOM_SUFFIX: Final[str] = "-api"
"""Added to a custom provider's ID: Codex refuses to override a built-in one (``ollama``)."""
TOOL_ITEMS: Final[dict[str, str]] = {
    "command_execution": "shell",
    "file_change": "apply_patch",
    "web_search": "web_search",
}
"""Items that are built-in tool calls, and the tool each stands for."""


def _toml(value: object) -> str:
    """Write a TOML value (a string, a bool, an integer or a list of strings).

    Args:
        value: The value.

    Returns:
        Its TOML form; strings as JSON strings, which TOML reads the same.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(str(value))


def config_toml(run: HarnessRun) -> str:
    """The run's ``config.toml``.

    Args:
        run: The run.

    Returns:
        The configuration: the model and its provider, web search off, the arm's MCP server.
    """
    model = run.model
    custom = model.provider.name != "openai" or model.base_url != model.provider.base_url
    # Codex reserves its built-in providers' IDs (``openai``, ``ollama``, ...): a custom one
    # takes another.
    provider = f"{model.provider.name}{CUSTOM_SUFFIX}" if custom else model.provider.name
    top: dict[str, object] = {
        "model": model.model,
        "model_provider": provider,
        "web_search": "disabled",
        "check_for_update_on_startup": False,
    }
    if model.thinking:
        top["model_reasoning_effort"] = "xhigh" if model.thinking == "max" else model.thinking
    lines = [f"{key} = {_toml(value)}" for key, value in top.items()]
    lines += ["", "[analytics]", "enabled = false"]
    if custom:
        lines += [
            "",
            f"[model_providers.{provider}]",
            f"name = {_toml(model.provider.name)}",
            f"base_url = {_toml(model.base_url)}",
            f"env_key = {_toml(model.provider.key_variable)}",
            'wire_api = "responses"',
        ]
    if run.mcp is not None:
        lines += ["", f"[mcp_servers.{run.mcp.name}]", f"url = {_toml(run.mcp.url)}"]
        lines += ["startup_timeout_sec = 60", "tool_timeout_sec = 120"]
        if run.mcp.excluded:
            lines.append(f"disabled_tools = {_toml(list(run.mcp.excluded))}")
        if run.mcp.headers:
            pairs = ", ".join(f"{_toml(k)} = {_toml(v)}" for k, v in run.mcp.headers.items())
            lines.append(f"http_headers = {{ {pairs} }}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True, kw_only=True)
class Codex:
    """The Codex CLI harness."""

    name: str = "codex"
    """Its name."""
    release: CliRelease = RELEASE
    """The pinned release."""
    providers: frozenset[str] = frozenset({"openai", "ollama"})
    """OpenAI's models, and Ollama's through a custom provider on the Responses API."""
    web_tools: str = 'off: web_search = "disabled" (Codex has no web fetch tool)'
    """How its web tools are turned off."""
    limits: str = "no turn limit (the wall limit); thinking: model_reasoning_effort"
    """How the turn limit and the thinking setting reach it."""

    def configure(self, run: HarnessRun, executable: Path) -> Invocation:
        """Write ``config.toml`` into the run's ``CODEX_HOME`` and give the headless command line.

        Args:
            run: The run.
            executable: The ``codex`` executable.

        Returns:
            The invocation; the provider's key is passed through by name.
        """
        home = run.home / CODEX_HOME
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.toml").write_text(config_toml(run), encoding="utf-8")
        argv = (
            str(executable),
            "exec",
            "--json",
            "--strict-config",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            "--color",
            "never",
            "--cd",
            str(run.workspace),
            run.prompt,
        )
        return Invocation(
            argv=argv,
            env={"CODEX_HOME": str(home), "RUST_LOG": "error"},
            secrets=(run.model.provider.key_variable,),
        )

    def parse(self, output: str, run: HarnessRun) -> Transcript:
        """Parse an ``exec --json`` transcript.

        Args:
            output: What ``codex exec --json`` printed.
            run: The run.

        Returns:
            The transcript; the tokens add up every turn's usage.
        """
        calls: dict[str, HarnessCall] = {}
        fields: dict[str, Any] = {"lines": 0, "unparsed": 0, "thinking_chars": 0}
        spent = dict.fromkeys(("input", "cached", "output", "reasoning", "turns", "reported"), 0)
        answer = ""
        # What ended the turn, what the stream said on the way (reconnecting), and the warnings
        # Codex gives as items (an unknown model's metadata): the first kind that has one.
        errors: dict[str, list[str]] = {"turn.failed": [], "error": [], "item": []}
        for event in events(output):
            fields["lines"] += 1
            kind = event.get("type") if event else None
            if event is None:
                fields["unparsed"] += 1
            elif kind in {"item.started", "item.updated", "item.completed"}:
                item = event.get("item") or {}
                done = kind == "item.completed"
                answer = _item(item, calls, fields, completed=done) or answer
                if item.get("type") == "error" and done:
                    errors["item"].append(str(item.get("message", "")))
            elif kind == "turn.completed":
                _usage(event.get("usage") or {}, spent)
            elif kind in {"turn.failed", "error"}:
                failure = event.get("error") or event
                errors[kind].append(str(failure.get("message", failure)))
            elif kind not in {"thread.started", "turn.started"}:
                fields["unparsed"] += 1
        turns = spent["turns"]
        error = _first(errors)
        if error is None and not answer and not turns:
            error = "the transcript has no turn"
        failed = error is not None and not answer
        # A provider that reports no reasoning tokens (Ollama) gives 0 next to thinking text.
        reported = spent["reported"] > 0 and (
            spent["reasoning"] > 0 or not fields["thinking_chars"]
        )
        money, source = priced(run.model.name, spent["input"], spent["output"], None)
        return Transcript(
            answer="" if failed else answer,
            calls=list(calls.values()),
            turns=turns or None,
            input_tokens=spent["input"] if turns else None,
            cached_input_tokens=spent["cached"] if turns else None,
            output_tokens=spent["output"] if turns else None,
            thinking_tokens=spent["reasoning"] if reported else None,
            thinking="reported" if reported else "not reported",
            usd=money,
            usd_source=source,
            error=error if failed else None,
            provider_failure=failed and provider_failed(error),
            **fields,
        )


def _first(errors: dict[str, list[str]]) -> str | None:
    """The error that says best why a run ended.

    Args:
        errors: The messages of ``turn.failed``, of ``error`` events and of ``error`` items, in
            that order of precedence.

    Returns:
        The first kind's messages that has one, joined; ``None`` for none.
    """
    said = next((found for found in errors.values() if any(found)), [])
    return "; ".join(e for e in said if e) or None


def _usage(usage: dict[str, Any], spent: dict[str, int]) -> None:
    """Add one turn's usage.

    Args:
        usage: The ``turn.completed`` event's usage.
        spent: The totals so far.
    """
    spent["turns"] += 1
    spent["input"] += number(usage.get("input_tokens"))
    spent["cached"] += number(usage.get("cached_input_tokens"))
    spent["output"] += number(usage.get("output_tokens"))
    if "reasoning_output_tokens" in usage:
        spent["reported"] += 1
        spent["reasoning"] += number(usage.get("reasoning_output_tokens"))


def _failure(item: dict[str, Any]) -> str | None:
    """What a tool item says went wrong.

    Args:
        item: A ``mcp_tool_call`` or a built-in tool's item.

    Returns:
        Its error, ``exit status <n>`` for a command that failed, or ``None``.
    """
    failure = item.get("error")
    if failure:
        return str(failure.get("message", failure) if isinstance(failure, dict) else failure)
    exit_code = item.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return f"exit status {exit_code}"
    return "failed" if item.get("status") == "failed" else None


def _item(
    item: dict[str, Any],
    calls: dict[str, HarnessCall],
    fields: dict[str, Any],
    *,
    completed: bool,
) -> str | None:
    """Read one item: a tool call, the reasoning or a message.

    Args:
        item: The item.
        calls: The calls so far, by item ID, in order.
        fields: The transcript's counters.
        completed: It is the item's ``item.completed`` event.

    Returns:
        The text of a completed ``agent_message``, else ``None``.
    """
    kind = str(item.get("type", ""))
    if kind == "agent_message" and completed:
        return str(item.get("text", ""))
    if kind == "reasoning" and completed:
        fields["thinking_chars"] += len(str(item.get("text", "")))
        return None
    if kind == "mcp_tool_call":
        server, tool = str(item.get("server", "")), str(item.get("tool", ""))
        name, args = f"{server}.{tool}", item.get("arguments", {})
    elif kind in TOOL_ITEMS:
        server, tool = None, TOOL_ITEMS[kind]
        name = tool
        args = {
            "command_execution": {"command": item.get("command", "")},
            "file_change": {"changes": item.get("changes", [])},
            "web_search": {"query": item.get("query", "")},
        }[kind]
    else:
        return None
    calls[str(item.get("id", len(calls)))] = HarnessCall(
        name=name,
        server=server,
        tool=tool,
        args=shown(args),
        error=_failure(item),
        web=kind == "web_search",
    )
    return None
