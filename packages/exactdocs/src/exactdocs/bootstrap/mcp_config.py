"""Ready-to-paste MCP client configuration for an ExactDocs server (``exactdocs config``).

Pure text generation: no I/O, no domain. Formats follow each client's own documentation
(Claude Code ``.mcp.json``, Claude Desktop ``claude_desktop_config.json``, Cursor ``mcp.json``,
VS Code ``.vscode/mcp.json``, Codex ``config.toml``). The token is a placeholder (an environment
variable where the client expands them) unless the caller passes the real one.
"""

import json
from pathlib import Path
from typing import Literal

CLIENTS = ("claude", "claude-desktop", "cursor", "vscode", "codex")
type Client = Literal["claude", "claude-desktop", "cursor", "vscode", "codex"]

SKILL_PATH = Path(__file__).parent / "skill" / "SKILL.md"
NAME = "exactdocs"
STDIO = {"command": "uvx", "args": ["exactdocs", "serve", "--stdio"]}
PLACEHOLDER = "<your-exactdocs-token>"  # for clients that cannot expand environment variables


def render(client: Client, *, mcp_url: str, token: str | None, stdio: bool) -> str:
    """Return the config for ``client``; ``token=None`` writes a placeholder, never a secret."""
    if client == "codex":
        return _codex(mcp_url, token, stdio=stdio)
    return json.dumps(_json(client, mcp_url, token, stdio=stdio), indent=2) + "\n"


def _bearer(token: str | None, placeholder: str) -> str:
    return f"Bearer {token or placeholder}"


def _json(client: Client, url: str, token: str | None, *, stdio: bool) -> dict[str, object]:
    if client == "claude-desktop":  # Desktop's file only knows local commands: mcp-remote bridges
        server = (
            {"command": "uvx", "args": ["exactdocs", "serve", "--stdio"]}
            if stdio
            else {
                "command": "npx",
                "args": [
                    "-y",
                    "mcp-remote@0.16.0",
                    url,
                    "--header",
                    "Authorization:${AUTH_HEADER}",
                ],
                "env": {"AUTH_HEADER": _bearer(token, PLACEHOLDER)},
            }
        )
        return {"mcpServers": {NAME: server}}
    if client == "vscode":
        server = (
            {"type": "stdio", **STDIO}
            if stdio
            else {
                "type": "http",
                "url": url,
                "headers": {"Authorization": _bearer(token, "${input:exactdocs-token}")},
            }
        )
        config: dict[str, object] = {"servers": {NAME: server}}
        if not stdio and token is None:
            config["inputs"] = [
                {
                    "type": "promptString",
                    "id": "exactdocs-token",
                    "description": "ExactDocs API token",
                    "password": True,
                }
            ]
        return config
    if client == "cursor":
        server = (
            dict(STDIO)
            if stdio
            else {
                "url": url,
                "headers": {"Authorization": _bearer(token, "${env:EXACTDOCS_TOKEN}")},
            }
        )
        return {"mcpServers": {NAME: server}}
    server = (  # claude (Claude Code)
        {"type": "stdio", **STDIO}
        if stdio
        else {
            "type": "http",
            "url": url,
            "headers": {"Authorization": _bearer(token, "${EXACTDOCS_TOKEN}")},
        }
    )
    return {"mcpServers": {NAME: server}}


def _codex(url: str, token: str | None, *, stdio: bool) -> str:
    if stdio:
        return f'[mcp_servers.{NAME}]\ncommand = "uvx"\nargs = ["exactdocs", "serve", "--stdio"]\n'
    auth = (
        'bearer_token_env_var = "EXACTDOCS_TOKEN"'
        if token is None
        else f"http_headers = {{ Authorization = {json.dumps(_bearer(token, ''))} }}"
    )
    return f"[mcp_servers.{NAME}]\nurl = {json.dumps(url)}\n{auth}\n"
