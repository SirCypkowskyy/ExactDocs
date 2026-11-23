"""Behave hooks: build the fixture docs repository once per run and serve it on 127.0.0.1.

A guard bounds each scenario (#304): one that runs, cleanups included, for longer than
``SCENARIO_SECONDS`` makes the run print every thread's stack and exit with status 1, instead of
using up the CI job's timeout without a trace.
"""

import faulthandler
import os
import sys
import tempfile
from contextlib import ExitStack
from importlib import import_module
from pathlib import Path

from behave.model import Feature, Scenario
from behave.runner import Context

# The fixture builder is test support shared with pytest, not part of the package. behave has no
# pythonpath option; import_module keeps ruff (E402) and ty from needing the path at lint time.
sys.path.insert(0, str(Path(__file__).parents[1] / "tests" / "fixtures"))
# The retrieval eval suite (retrieval_eval.feature) is development tooling beside the package.
sys.path.insert(0, str(Path(__file__).parents[1] / "evals"))

STDERR = 2
"""The process's standard error descriptor: behave captures ``sys.stderr``, not this."""
SCENARIO_SECONDS = float(os.environ.get("BEHAVE_SCENARIO_TIMEOUT", "300"))
"""Longest a scenario may run, from its start to the next one's (so its cleanups count). The
slowest whole feature takes about 35 s on CI; a hung scenario fails within this. The process
then exits at once (status 1) after printing every thread's stack, so behave writes no JUnit
report for that run."""

fixture_repo = import_module("fixture_repo")
databases = import_module("databases")  # raises when CI requires PostgreSQL and has none
index_backends = import_module("index_backends")


def before_all(context: Context) -> None:
    # Jobs start at once in scenarios (the default polls once a second); child processes inherit.
    os.environ["EXACTDOCS_JOB_POLL_SECONDS"] = "0.02"
    context.stack = ExitStack()
    base = Path(context.stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-fx-")))
    context.fixture_repo = context.stack.enter_context(fixture_repo.served(base))
    context.fixture_git = fixture_repo.git
    context.fixture_serve_copy = fixture_repo.serve_copy


def after_all(context: Context) -> None:
    faulthandler.cancel_dump_traceback_later()
    context.stack.close()


def after_feature(context: Context, feature: Feature) -> None:
    # The feature's last scenario and its cleanups are done: nothing is guarded until the next.
    del context, feature
    faulthandler.cancel_dump_traceback_later()


def before_scenario(context: Context, scenario: Scenario) -> None:
    # Re-armed for each scenario; it fires only if this one, or its cleanups, hang.
    faulthandler.dump_traceback_later(SCENARIO_SECONDS, exit=True, file=STDERR)
    # PostgreSQL scenarios need a server (EXACTDOCS_TEST_POSTGRES_URL); CI always has one and
    # sets EXACTDOCS_REQUIRE_POSTGRES=1, so there they can never be skipped.
    del context
    if "postgres" in scenario.effective_tags and databases.ADMIN_URL is None:
        scenario.skip("needs a PostgreSQL server: set EXACTDOCS_TEST_POSTGRES_URL")
    # CI's ParadeDB has pg_search and sets EXACTDOCS_TEST_PG_SEARCH=1: never skipped there.
    elif "pg_search" in scenario.effective_tags and not databases.PG_SEARCH:
        scenario.skip("needs a PostgreSQL server with the pg_search extension")
    # Supabase scenarios need the supabase/postgres image (EXACTDOCS_TEST_SUPABASE_URL); CI runs
    # one and sets EXACTDOCS_REQUIRE_SUPABASE=1, so there they can never be skipped.
    elif "supabase" in scenario.effective_tags and databases.SUPABASE_URL is None:
        scenario.skip("needs the supabase/postgres image: set EXACTDOCS_TEST_SUPABASE_URL")
    # ExactDocs' database on libSQL (#474) needs a libSQL server of its own; CI starts one.
    elif "libsql_database" in scenario.effective_tags and databases.LIBSQL_DATABASE_URL is None:
        scenario.skip("needs a libSQL server: set EXACTDOCS_TEST_LIBSQL_DATABASE_URL")
    # Pooler scenarios need PgBouncer in transaction mode (EXACTDOCS_TEST_PGBOUNCER_URL, #279);
    # CI runs one and sets EXACTDOCS_REQUIRE_PGBOUNCER=1, so there they can never be skipped.
    elif "pgbouncer" in scenario.effective_tags and (
        databases.ADMIN_URL is None or databases.PGBOUNCER_URL is None
    ):
        scenario.skip("needs PgBouncer in transaction mode: set EXACTDOCS_TEST_PGBOUNCER_URL")
    # Elasticsearch and OpenSearch scenarios (#354) need a test cluster; CI runs both.
    for cluster in ("elasticsearch", "opensearch"):
        if cluster in scenario.effective_tags and index_backends.cluster_options(cluster) is None:
            scenario.skip(f"needs a test cluster: set EXACTDOCS_TEST_{cluster.upper()}_URL")
