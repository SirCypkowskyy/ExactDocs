"""The ``library`` and ``docs`` commands keep the shape of ctx7's (pinned in tests/contracts)."""

import io
import json
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
