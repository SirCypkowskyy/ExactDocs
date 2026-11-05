"""Behave hooks: build the fixture docs repository once per run and serve it on 127.0.0.1."""

import os
import sys
import tempfile
from contextlib import ExitStack
from importlib import import_module
from pathlib import Path

from behave.runner import Context

# The fixture builder is test support shared with pytest, not part of the package. behave has no
# pythonpath option; import_module keeps ruff (E402) and ty from needing the path at lint time.
sys.path.insert(0, str(Path(__file__).parents[1] / "tests" / "fixtures"))
fixture_repo = import_module("fixture_repo")


def before_all(context: Context) -> None:
    # Jobs start at once in scenarios (the default polls once a second); child processes inherit.
    os.environ["EXACTDOCS_JOB_POLL_SECONDS"] = "0.02"
    context.stack = ExitStack()
    base = Path(context.stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-fx-")))
    context.fixture_repo = context.stack.enter_context(fixture_repo.served(base))
    context.fixture_git = fixture_repo.git
    context.fixture_serve_copy = fixture_repo.serve_copy


def after_all(context: Context) -> None:
    context.stack.close()
