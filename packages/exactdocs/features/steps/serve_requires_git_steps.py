"""Steps that start ``exactdocs serve`` as a real subprocess on a PATH without git."""

import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from pathlib import Path

from behave import given, then, when
from behave.runner import Context

CLI = "from exactdocs.bootstrap.cli import main; main()"


@given('a machine without "git" on its PATH')
def step_no_git(context: Context) -> None:
    context.empty_path = tempfile.mkdtemp(prefix="exactdocs-nogit-")
    context.add_cleanup(Path(context.empty_path).rmdir)


def run(context: Context, *args: str, data_dir: Path) -> None:
    env = {**os.environ, "PATH": context.empty_path, "EXACTDOCS_DATA_DIR": str(data_dir)}
    env.pop("EXACTDOCS_DATABASE_URL", None)
    done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter
        [sys.executable, "-c", CLI, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    context.start_code, context.start_err = done.returncode, done.stderr


@when('the user runs "exactdocs serve"')
def step_serve(context: Context) -> None:
    data = Path(tempfile.mkdtemp(prefix="exactdocs-data-")) / "data"
    context.add_cleanup(shutil.rmtree, data.parent, ignore_errors=True)
    run(context, "serve", data_dir=data)


@when('the user runs "exactdocs serve --stdio" on an empty data directory')
def step_serve_stdio(context: Context) -> None:
    empty = Path(tempfile.mkdtemp(prefix="exactdocs-empty-")) / "data"
    context.add_cleanup(empty.parent.rmdir)
    run(context, "serve", "--stdio", data_dir=empty)


@then("start fails with a message saying that git is required")
def step_git_required(context: Context) -> None:
    assert context.start_code != 0
    assert "git is not installed" in context.start_err, context.start_err


@then("start fails only because the database is missing")
def step_only_database(context: Context) -> None:
    assert context.start_code != 0
    assert "git" not in context.start_err, context.start_err
    assert "exactdocs.db" in context.start_err, context.start_err
