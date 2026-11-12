"""Steps for the liveness and readiness probes, asked like an orchestrator asks them.

Every wait here is bounded by ``STEP_SECONDS`` (#304): a request, the instance's start or its
stop that takes longer fails the scenario with the stack it is stuck in, instead of hanging the
run. A scenario's stall is released before its instance stops.
"""

import faulthandler
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
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
STDERR = 2
"""The process's standard error descriptor: behave captures ``sys.stderr``, not this."""
STEP_SECONDS = 30.0
"""The longest a step waits for the instance: a start, a request or a stop. Each takes well
under a few seconds, even with a stalled statement (at most 3 s) and the probes' settle (4 s)."""


def _within[T](what: str, call: Callable[[], T]) -> T:
    """Run a blocking call, failing the step if it takes more than ``STEP_SECONDS``.

    The call runs in a daemon thread of its own, so a stuck one is left behind and the run goes
    on to the next scenario rather than waiting for it. An error the call raises is printed by
    ``threading.excepthook`` (into the step's captured output) and fails the step. A start that
    times out may still finish later in its thread; that instance is never stopped, which is
    acceptable because the step has already failed and the run is broken anyway.

    Args:
        what: What the call does, for the failure message.
        call: The call.

    Returns:
        What the call returned.

    Raises:
        AssertionError: The call raised, or did not return in time; then every thread's stack is
            printed to standard error first.
    """
    outcome: list[T] = []
    worker = threading.Thread(
        target=lambda: outcome.append(call()), name=f"health: {what}", daemon=True
    )
    worker.start()
    worker.join(STEP_SECONDS)
    if worker.is_alive():
        faulthandler.dump_traceback(file=STDERR, all_threads=True)
        message = f"{what} did not finish within {STEP_SECONDS} s; the stacks are on stderr"
        raise AssertionError(message)
    assert outcome, f"{what} failed: its traceback is above"
    return outcome[0]


@given("ExactDocs is running on its own database")
def step_running(context: Context) -> None:
    """Start an instance whose database file sits in a folder of its own.

    Args:
        context: The behave context.
    """
    stack = ExitStack()
    context.add_cleanup(_within, "stopping the instance", stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.database_dir = data_dir / DATABASE_DIR
    context.container = Container.build(
        Settings(
            data_dir=data_dir,
            database_url=f"sqlite:///{(context.database_dir / 'exactdocs.db').as_posix()}",
        )
    )
    context.slow_database = SlowDatabase.on(context.container.engine)
    # Added after the stop, so it runs first: the instance stops with its statements running free.
    context.add_cleanup(context.slow_database.release)
    # An orchestrator sends no cookie and no token.
    client = TestClient(create_app(context.container), base_url="http://localhost")
    context.client = _within("starting the instance", lambda: stack.enter_context(client))


@when("the database is unreachable")
def step_database_unreachable(context: Context) -> None:
    """Remove the database and drop the open connections, so no new one can be made.

    Args:
        context: The behave context.
    """
    shutil.rmtree(context.database_dir)
    portal = context.client.portal
    _within("disposing of the engine", lambda: portal.call(context.container.engine.dispose))


@then('"{live}" reports up and "{ready}" reports {state}')
def step_probes(context: Context, live: str, ready: str, state: str) -> None:
    """Check the liveness probe is up and the readiness probe in the expected state.

    Args:
        context: The behave context.
        live: Path of the liveness probe.
        ready: Path of the readiness probe.
        state: ``ready`` or ``not ready``.
    """
    alive = _within(f"GET {live}", lambda: context.client.get(live))
    assert alive.status_code == HTTPStatus.OK, (alive.status_code, alive.text)
    assert alive.json()["status"] == "ok"
    readiness = _within(f"GET {ready}", lambda: context.client.get(ready))
    expected = HTTPStatus.OK if state == "ready" else HTTPStatus.SERVICE_UNAVAILABLE
    assert readiness.status_code == expected, (readiness.status_code, readiness.text)
    assert readiness.json()["status"] == state.replace(" ", "_")


@given("a database statement that takes {seconds:d} seconds is running")
def step_slow_statement(context: Context, seconds: int) -> None:
    """Hold every database statement until ``seconds`` from now.

    The stall ends on its own, or at the latest when the scenario ends (released before the
    instance stops).

    Args:
        context: The behave context.
        seconds: How long the statement runs.
    """
    context.slow_database.stall(seconds)


@when("the liveness probe is called")
def step_call_liveness(context: Context) -> None:
    """Ask the liveness probe, as an orchestrator does, and time it.

    Args:
        context: The behave context.
    """
    started = time.monotonic()
    context.response = _within("the liveness probe", lambda: context.client.get(LIVENESS_PATH))
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
