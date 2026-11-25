"""A stand-in coding-agent CLI for the harness benchmark's tests: Claude Code's interface, no model.

It takes the command line ``harness_bench.claude_code`` builds (``-p``, ``--mcp-config``) and:

- with an MCP server configured, lists its tools and calls its ``search_docs`` for the version the
  prompt names, over HTTP through the gate's forward (the stand-in documentation server);
- copies the files of ``STAND_IN_SOLUTION`` (a folder), if set, into its working directory;
- answers with the first search result's text, or says it does not know;
- prints a Claude Code stream-JSON transcript: ``init``, each tool call and its result, the answer,
  and the ``result`` with the usage and the cost.

It reaches nothing but the MCP server. Run it with the interpreter of the suite.
"""

import asyncio
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

VERSION = re.compile(r"at version (\S+?)\.(?:\s|$)")
LIBRARY = "/acme/demo"


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def assistant(message_id: str, block: dict[str, Any]) -> None:
    usage = {"input_tokens": 100, "cache_read_input_tokens": 0, "output_tokens": 20}
    emit(
        {
            "type": "assistant",
            "message": {"id": message_id, "role": "assistant", "content": [block], "usage": usage},
            "parent_tool_use_id": None,
        }
    )


def result_of(tool_id: str, content: str, *, error: bool = False) -> None:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": error}
    emit({"type": "user", "message": {"role": "user", "content": [block]}})


async def search(server: str, config: dict[str, Any], ref: str, query: str) -> str:
    transport = StreamableHttpTransport(config["url"], headers=config.get("headers") or {})
    async with Client(transport) as client:
        tools = {t.name for t in await client.list_tools()}
        if "search_docs" not in tools:
            return ""
        tool_id = f"toolu_{uuid.uuid4().hex[:8]}"
        args = {"library": LIBRARY, "ref": ref, "query": query}
        assistant(
            "msg_search",
            {
                "type": "tool_use",
                "id": tool_id,
                "name": f"mcp__{server}__search_docs",
                "input": args,
            },
        )
        found = await client.call_tool("search_docs", args)
        text = json.dumps(found.structured_content or {})
        result_of(tool_id, text)
        hits = (found.structured_content or {}).get("results") or []
        return str(hits[0].get("snippet", "")) if hits else ""


def main() -> int:
    argv = sys.argv[1:]
    prompt = argv[argv.index("-p") + 1]
    config = Path(argv[argv.index("--mcp-config") + 1])
    servers = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
    emit(
        {
            "type": "system",
            "subtype": "init",
            "tools": ["Write", *(f"mcp__{s}__search_docs" for s in servers)],
            "mcp_servers": [{"name": s, "status": "connected"} for s in servers],
            "model": "stand-in",
            "claude_code_version": {"VERSION": "stand-in"},
        }
    )
    version = VERSION.search(prompt)
    ref = version[1] if version else ""
    found = ""
    for server, config in servers.items():
        found = asyncio.run(search(server, config, ref, prompt.rsplit("\n", 1)[-1])) or found
    solution = os.environ.get("STAND_IN_SOLUTION")
    if solution:
        for path in sorted(Path(solution).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                relative = path.relative_to(solution)
                target = Path.cwd() / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                tool_id = f"toolu_{uuid.uuid4().hex[:8]}"
                assistant(
                    "msg_write",
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Write",
                        "input": {"file_path": str(target), "content": "..."},
                    },
                )
                result_of(tool_id, f"File created successfully at: {target}")
    answer = found or "I do not know what that version does."
    assistant("msg_answer", {"type": "text", "text": answer})
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 1200,
            "num_turns": 3,
            "result": answer,
            "total_cost_usd": 0.0123,
            "usage": {
                "input_tokens": 300,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 200,
                "output_tokens": 60,
            },
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
