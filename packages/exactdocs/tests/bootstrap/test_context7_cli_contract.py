"""The ``library`` and ``docs`` commands keep the shape of ctx7's (pinned in tests/contracts)."""

import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from exactdocs.bootstrap import cli

PIN = json.loads(
    (Path(__file__).parents[1] / "contracts" / "context7" / "cli" / "ctx7-cli.json").read_text(
        encoding="utf-8"
    )
)
IMPLEMENTED = [name for name, pin in PIN["commands"].items() if pin["exactdocs"] == "implemented"]


def _help(command: str) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        cli.app([command, "--help"], exit_on_error=False, result_action="return_value")
    return out.getvalue()


def test_the_pin_names_the_commands_we_have() -> None:
    assert IMPLEMENTED == ["library", "docs"]


@pytest.mark.parametrize("command", IMPLEMENTED)
def test_every_ctx7_option_exists(command: str) -> None:
    text = _help(command)
    for option in PIN["commands"][command]["options"]:
        assert option in text, f"{command} lacks {option}"


@pytest.mark.parametrize("command", IMPLEMENTED)
def test_every_ctx7_argument_is_described_and_named_in_the_usage(command: str) -> None:
    text = _help(command)
    usage = text.splitlines()[0]
    assert "ARGS" not in usage, usage
    for argument in PIN["commands"][command]["arguments"]:
        name = re.sub(r"(?<!^)(?=[A-Z])", "-", argument["name"]).upper()
        assert name in usage, (name, usage)
        rows = [line for line in text.splitlines() if line.startswith("│")]
        row = next(line for line in rows if f" {name} " in line)
        assert re.search(rf"{name}(?: --[\w-]+)?\s{{2,}}\S", row), f"{command}: {name} has no help"
