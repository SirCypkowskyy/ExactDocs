"""Steps that start ``exactdocs serve --stdio`` as a real subprocess."""

import json
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from pathlib import Path

from behave import then, when
from behave.runner import Context

CLI = "from exactdocs.bootstrap.cli import main; main()"
FRAMES = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "behave", "version": "0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "list_libraries", "arguments": {}},
    },
]


def start(data_dir: Path) -> subprocess.Popen[str]:
    env = {**os.environ, "EXACTDOCS_DATA_DIR": str(data_dir)}
    env.pop("EXACTDOCS_DATABASE_URL", None)
    return subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, "serve", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


@when('an agent starts "exactdocs serve --stdio"')
def step_start(context: Context) -> None:
    process = start(context.settings.data_dir)
    assert process.stdin is not None
    assert process.stdout is not None
    for frame in FRAMES:
        process.stdin.write(json.dumps(frame) + "\n")
    process.stdin.flush()
    context.stdio_answers = [json.loads(process.stdout.readline()) for _ in range(2)]
    process.stdin.close()
    process.communicate(timeout=60)


@then('"list_libraries" lists "{library}" without any token')
def step_lists(context: Context, library: str) -> None:
    listed = context.stdio_answers[1]["result"]["structuredContent"]["libraries"]
    assert library in [item["id"] for item in listed], listed


@when('an agent starts "exactdocs serve --stdio" on an empty data directory')
def step_start_empty(context: Context) -> None:
    context.empty_dir = Path(tempfile.mkdtemp(prefix="exactdocs-empty-")) / "data"
    context.add_cleanup(context.empty_dir.parent.rmdir)
    process = start(context.empty_dir)
    assert process.stdin is not None
    process.stdin.close()
    context.stdio_out, context.stdio_err = process.communicate(timeout=60)
    context.stdio_code = process.returncode


@then("it exits with an error on stderr naming the missing database")
def step_missing(context: Context) -> None:
    assert context.stdio_code != 0
    assert not context.stdio_out
    assert str(context.empty_dir / "exactdocs.db") in context.stdio_err, context.stdio_err
    assert not context.empty_dir.exists(), "stdio must not create the data directory"
