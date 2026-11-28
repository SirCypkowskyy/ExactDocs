"""Behave hooks: build the fixture docs repository once per run and serve it on 127.0.0.1.

A guard bounds each scenario (#304): one that runs, cleanups included, for longer than
``SCENARIO_SECONDS`` makes the run print every thread's stack and exit with status 1, instead of
using up the CI job's timeout without a trace.

Integration scenarios (#507) carry ``@integration`` and a tag naming their service (``SERVICES``:
``@postgres``, ``@qdrant`` ...); a service tag without ``@integration`` is an error. They are
left out unless ``EXACTDOCS_INTEGRATION=1`` (``just bdd-integration``), and the run ends saying
how many; with it, one whose service is not configured is skipped, naming the variable (CI's
integration job sets ``EXACTDOCS_REQUIRE_<NAME>=1``, which turns that into an error).
``--tags=@integration`` runs only them. The same switch and services as pytest's
(``tests/fixtures/integration.py``).
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
integration = import_module("integration")

INTEGRATION_TAG = "integration"
SERVICES: dict[str, tuple[str, ...]] = {
    "postgres": integration.POSTGRES.args,
    "pg_search": integration.POSTGRES_PG_SEARCH.args,
    "pgbouncer": integration.PGBOUNCER.args,
    "supabase": integration.SUPABASE.args,
    "libsql_database": integration.LIBSQL_DATABASE.args,
    "libsql_server": integration.LIBSQL.args,
    "elasticsearch": integration.ELASTICSEARCH.args,
    "opensearch": integration.OPENSEARCH.args,
    "qdrant": integration.QDRANT.args,
    "redis": integration.REDIS.args,
    "mongodb": integration.MONGODB.args,
    "chroma_server": integration.CHROMA.args,
    "milvus_server": integration.MILVUS.args,
    "pinecone": integration.PINECONE.args,
    "weaviate": integration.WEAVIATE.args,
}
"""The tags that name a service, and the variables that configure it: a scenario with one is an
integration scenario."""
LEFT_OUT: list[str] = []
"""The integration scenarios this run left out (their locations)."""


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
    if LEFT_OUT:
        # On the real stdout: behave captures sys.stdout in hooks.
        print(
            f"\n{len(LEFT_OUT)} integration scenarios left out (they need PostgreSQL, a search or"
            " vector server or another service): run them with EXACTDOCS_INTEGRATION=1"
            " uv run behave (just bdd-integration)\n",
            file=sys.__stdout__,
            flush=True,
        )


def after_feature(context: Context, feature: Feature) -> None:
    # The feature's last scenario and its cleanups are done: nothing is guarded until the next.
    del context, feature
    faulthandler.cancel_dump_traceback_later()


def before_scenario(context: Context, scenario: Scenario) -> None:
    # Re-armed for each scenario; it fires only if this one, or its cleanups, hang.
    faulthandler.dump_traceback_later(SCENARIO_SECONDS, exit=True, file=STDERR)
    del context
    tags = set(scenario.effective_tags)
    services = sorted(tags & SERVICES.keys())
    if services and INTEGRATION_TAG not in tags:
        message = f"{scenario.location}: @{services[0]} needs a service, so tag it @integration too"
        raise AssertionError(message)
    if INTEGRATION_TAG not in tags:
        return
    if not integration.enabled():
        LEFT_OUT.append(str(scenario.location))
        scenario.skip("an integration scenario: EXACTDOCS_INTEGRATION=1 runs it")
        return
    # CI's integration job sets EXACTDOCS_REQUIRE_<NAME>=1 for each service it runs (databases.py
    # and index_backends.py raise without its URL), so there these can never be skipped.
    missing = sorted(
        {name for tag in services for name in SERVICES[tag] if not os.environ.get(name)}
    )
    if missing:
        scenario.skip(f"an integration scenario: set {', '.join(missing)}")
