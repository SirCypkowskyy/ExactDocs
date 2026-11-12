"""Steps for the start-up probe that warns about a transaction-mode pooler (#279).

A real ``exactdocs serve`` process (``postgres_steps.serve``) on a new database, reached directly
or through PgBouncer in transaction mode (``databases.PGBOUNCER_URL``), and its output.
"""

from contextlib import ExitStack
from http import HTTPStatus

import httpx
import psycopg
from behave import given, then, when
from behave.runner import Context
from sqlalchemy.engine import make_url

from databases import postgres_database, through_pgbouncer
from steps.postgres_steps import serve

WARNING = "lost its session state between two transactions"
"""What the pooler warning says, whatever the URL it names."""


def _new_database(context: Context, *, pooled: bool) -> str:
    """Create a database for the scenario (dropped at its end) and return its URL.

    Args:
        context: The scenario's context.
        pooled: Reach it through PgBouncer rather than directly.

    Returns:
        The URL ExactDocs is given.
    """
    stack = ExitStack()
    context.add_cleanup(stack.close)
    database = stack.enter_context(postgres_database())
    return through_pgbouncer(database) if pooled else database.url


@given("ExactDocs connects to PostgreSQL through PgBouncer in transaction mode")
def step_through_pgbouncer(context: Context) -> None:
    context.database_url = _new_database(context, pooled=True)


@given("session state does not survive from one transaction to the next")
def step_state_is_lost(context: Context) -> None:
    plain = make_url(context.database_url).set(drivername="postgresql")
    with psycopg.connect(plain.render_as_string(hide_password=False), autocommit=True) as db:
        db.execute("SELECT set_config('exactdocs.scenario', 'kept', false)")
        found = db.execute("SELECT current_setting('exactdocs.scenario', true)").fetchone()
    assert found != ("kept",), "this pooler keeps session state: the scenario proves nothing"


@given("ExactDocs connects to PostgreSQL directly")
def step_directly(context: Context) -> None:
    context.database_url = _new_database(context, pooled=False)


@when("ExactDocs starts on that connection")
def step_starts(context: Context) -> None:
    context.base = serve(context, context.database_url, "pooler")  # returns once it is ready


@then(
    "it logs a WARNING that the connection is not a session, naming the session or direct "
    "connection to use instead"
)
def step_warned(context: Context) -> None:
    output = context.serve_log.read_text()
    warnings = [line for line in output.splitlines() if WARNING in line]
    assert len(warnings) == 1, output
    [warning] = warnings
    assert "transaction mode" in warning, warning
    assert "session pooler" in warning, warning
    assert "direct connection" in warning, warning
    assert ":***@" in warning, warning  # the URL is named with its password hidden


@then("it still starts")
def step_still_starts(context: Context) -> None:
    health = httpx.get(f"{context.base}/api/health", timeout=10)
    assert health.status_code == HTTPStatus.OK, health.text


@then("no pooler warning is logged")
def step_not_warned(context: Context) -> None:
    output = context.serve_log.read_text()
    assert WARNING not in output, output
