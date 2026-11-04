"""``exactdocs config``: golden snippets per client, the token rules, the skill."""

import json
import os
import re
import tomllib
from pathlib import Path

import pytest
from fastmcp import Client

from exactdocs.bootstrap import cli
from exactdocs.bootstrap.client import ClientError, resolve_url
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.mcp import build_mcp
from exactdocs.bootstrap.mcp_config import CLIENTS, SKILL_PATH, render
from exactdocs.bootstrap.settings import Settings

SKILL_URI = "skill://exactdocs/SKILL.md"
GOLDEN = Path(__file__).parent / "golden" / "mcp_config"
URL = "https://docs.example.com/mcp"
SECRET = "exd_secret_value"
CASES = [(c, mode) for c in CLIENTS for mode in ("http", "stdio", "http-with-token")]


def run(args: list[str]) -> None:
    cli.app(args, exit_on_error=False, result_action="return_value")


def _extension(client: str) -> str:
    return "toml" if client == "codex" else "json"


@pytest.mark.parametrize(("client", "mode"), CASES)
def test_snippet_matches_its_golden_file(client: str, mode: str) -> None:
    text = render(
        client,  # ty: ignore[invalid-argument-type]
        mcp_url=URL,
        token=SECRET if mode == "http-with-token" else None,
        stdio=mode == "stdio",
    )
    golden = GOLDEN / f"{client}.{mode}.{_extension(client)}"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        golden.write_text(text)
    assert text == golden.read_text(), "run with UPDATE_SNAPSHOTS=1 to update"


@pytest.mark.parametrize(("client", "mode"), CASES)
def test_snippet_is_valid_and_names_the_server(client: str, mode: str) -> None:
    text = (GOLDEN / f"{client}.{mode}.{_extension(client)}").read_text()
    data = tomllib.loads(text) if client == "codex" else json.loads(text)
    servers = data.get("mcp_servers") or data.get("mcpServers") or data["servers"]
    server = servers["exactdocs"]
    if mode == "stdio":
        assert server["command"] == "uvx"
        assert server["args"] == ["exactdocs", "serve", "--stdio"]
    else:
        assert URL in json.dumps(server)


@pytest.mark.parametrize("client", CLIENTS)
def test_the_token_appears_only_when_given(client: str) -> None:
    placeholder = render(client, mcp_url=URL, token=None, stdio=False)  # ty: ignore[invalid-argument-type]
    given = render(client, mcp_url=URL, token=SECRET, stdio=False)  # ty: ignore[invalid-argument-type]
    assert SECRET not in placeholder
    assert SECRET in given


def test_the_command_defaults_to_a_placeholder(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("EXACTDOCS_TOKEN", SECRET)
    run(["config", "--client", "claude", "--url", "https://docs.example.com"])
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "${EXACTDOCS_TOKEN}" in out
    assert "https://docs.example.com/mcp" in out


def test_show_token_prints_the_resolved_token(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("EXACTDOCS_TOKEN", SECRET)
    run(["config", "--client", "cursor", "--url", "https://docs.example.com", "--show-token"])
    assert f"Bearer {SECRET}" in capsys.readouterr().out


def test_stdio_needs_no_server_and_refuses_show_token(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.delenv("EXACTDOCS_URL", raising=False)
    run(["config", "--client", "vscode", "--stdio"])
    assert "--stdio" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="needs no token"):
        run(
            ["config", "--client", "vscode", "--stdio", "--show-token"],
        )


def test_http_without_a_server_says_how_to_configure_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.delenv("EXACTDOCS_URL", raising=False)
    with pytest.raises(ClientError, match="exactdocs login"):
        resolve_url()


def test_the_skill_is_printed_and_served_over_mcp(capsys: pytest.CaptureFixture[str]) -> None:
    run(["skill"])
    assert capsys.readouterr().out == SKILL_PATH.read_text()
    assert SKILL_PATH.read_text().startswith("---\nname: exactdocs\n")


async def test_the_skill_is_an_mcp_resource() -> None:
    container = Container.build(Settings())
    async with container.running(), Client(build_mcp(container)) as mcp:
        resources = await mcp.list_resources()
        assert SKILL_URI in [str(r.uri) for r in resources]
        contents = await mcp.read_resource(SKILL_URI)
        assert contents[0].text == SKILL_PATH.read_text()


async def test_every_tool_the_skill_names_exists() -> None:
    container = Container.build(Settings())
    async with container.running(), Client(build_mcp(container)) as mcp:
        tools = {tool.name for tool in await mcp.list_tools()}
    named = set(re.findall(r"`([a-z]+(?:[_-][a-z]+)+)`", SKILL_PATH.read_text()))
    named -= {"next_cursor", "stale_chunk", "not_found"}  # fields and error codes, not tools
    assert named, "the skill names no tools?"
    assert named <= tools, named - tools


def test_show_token_warns_on_stderr_and_never_prints_the_placeholder(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EXACTDOCS_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("EXACTDOCS_TOKEN", SECRET)
    run(
        [
            "config",
            "--client",
            "claude-desktop",
            "--url",
            "https://docs.example.com",
            "--show-token",
        ]
    )
    captured = capsys.readouterr()
    assert "do not commit" in captured.err
    assert SECRET not in captured.err
    assert "<your-exactdocs-token>" not in captured.out
    run(["config", "--client", "claude-desktop", "--url", "https://docs.example.com"])
    assert "do not commit" not in capsys.readouterr().err


def test_the_remote_bridge_is_pinned() -> None:
    assert "mcp-remote@0.16.0" in render("claude-desktop", mcp_url=URL, token=None, stdio=False)
