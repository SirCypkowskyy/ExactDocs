"""Steps for the liveness and readiness probes, asked like an orchestrator asks them."""

import shutil
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings

DATABASE_DIR = "database"
"""Folder of the data directory that holds only the database, so it can disappear on its own."""


@given("ExactDocs is running on its own database")
def step_running(context: Context) -> None:
    """Start an instance whose database file sits in a folder of its own.

    Args:
        context: The behave context.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.database_dir = data_dir / DATABASE_DIR
    context.container = Container.build(
        Settings(
            data_dir=data_dir,
            database_url=f"sqlite:///{(context.database_dir / 'exactdocs.db').as_posix()}",
        )
    )
    # An orchestrator sends no cookie and no token.
    context.client = stack.enter_context(
        TestClient(create_app(context.container), base_url="http://localhost")
    )


@when("the database is unreachable")
def step_database_unreachable(context: Context) -> None:
    """Remove the database and drop the open connections, so no new one can be made.

    Args:
        context: The behave context.
    """
    shutil.rmtree(context.database_dir)
    context.client.portal.call(context.container.engine.dispose)


@then('"{live}" reports up and "{ready}" reports {state}')
def step_probes(context: Context, live: str, ready: str, state: str) -> None:
    """Check the liveness probe is up and the readiness probe in the expected state.

    Args:
        context: The behave context.
        live: Path of the liveness probe.
        ready: Path of the readiness probe.
        state: ``ready`` or ``not ready``.
    """
    alive = context.client.get(live)
    assert alive.status_code == HTTPStatus.OK, (alive.status_code, alive.text)
    assert alive.json()["status"] == "ok"
    readiness = context.client.get(ready)
    expected = HTTPStatus.OK if state == "ready" else HTTPStatus.SERVICE_UNAVAILABLE
    assert readiness.status_code == expected, (readiness.status_code, readiness.text)
    assert readiness.json()["status"] == state.replace(" ", "_")
