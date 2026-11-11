"""Steps for the liveness and readiness probes, asked like an orchestrator asks them."""

import shutil
import tempfile
import time
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.constants import LIVENESS_PATH
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from slow_database import SlowDatabase

DATABASE_DIR = "database"
"""Folder of the data directory that holds only the database, so it can disappear on its own."""
RECOVERY_SECONDS = 2.0
"""How long the database may take to answer again once a held statement is over."""


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
    context.slow_database = SlowDatabase.on(context.container.engine)
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


@given("a database statement that takes {seconds:d} seconds is running")
def step_slow_statement(context: Context, seconds: int) -> None:
    """Hold every database statement until ``seconds`` from now, then wait for it at the end.

    Args:
        context: The behave context.
        seconds: How long the statement runs.
    """
    context.slow_database.stall(seconds)
    # Registered after the client's cleanup, so it runs first: the instance stops once the
    # statement is over and the check the probe left behind has finished.
    context.add_cleanup(_until_the_database_answers, context)


def _until_the_database_answers(context: Context) -> None:
    """Wait for the held statement to end and liveness to see the database again.

    Args:
        context: The behave context.
    """
    time.sleep(context.slow_database.remaining())
    deadline = time.monotonic() + RECOVERY_SECONDS
    while not context.client.get(LIVENESS_PATH).json()["database_reachable"]:
        assert time.monotonic() < deadline, "the database did not answer again"
        time.sleep(0.05)


@when("the liveness probe is called")
def step_call_liveness(context: Context) -> None:
    """Ask the liveness probe, as an orchestrator does, and time it.

    Args:
        context: The behave context.
    """
    started = time.monotonic()
    context.response = context.client.get(LIVENESS_PATH)
    context.elapsed = time.monotonic() - started


@then("it answers within {seconds:d} second")
def step_answers_within(context: Context, seconds: int) -> None:
    """Check the probe answered, and in time.

    Args:
        context: The behave context.
        seconds: The most it may take.
    """
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.elapsed < seconds, f"it took {context.elapsed:.2f} s"


@then("it reports the database details as unknown")
def step_details_unknown(context: Context) -> None:
    """Check liveness says it is up and knows nothing of the database.

    Args:
        context: The behave context.
    """
    body = context.response.json()
    assert body["status"] == "ok"
    assert body["database_reachable"] is False
    assert body["schema_revision"] is None
    assert body["search_engine"] is None
