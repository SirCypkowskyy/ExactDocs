"""deploy/upgrade_check.py still installs a previous release that PyPI has yanked (#533)."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[4]


@pytest.fixture
def upgrade_check() -> SimpleNamespace:
    path = list(sys.path)
    try:
        return SimpleNamespace(**runpy.run_path(str(ROOT / "deploy" / "upgrade_check.py")))
    finally:
        sys.path[:] = path


def test_the_previous_release_and_its_kernel_are_both_pinned_exactly(
    upgrade_check: SimpleNamespace,
) -> None:
    # uv takes a yanked version only for an exact pin given to it, not for the kernel pin in
    # exactdocs' own metadata: both must be on the command line.
    old, _ = upgrade_check.commands(None, "0.2.0")

    assert old[0] == "uvx"
    assert old[old.index("--from") + 1] == "exactdocs==0.2.0"
    assert old[old.index("--with") + 1] == "exactdocs-kernel==0.2.0"
