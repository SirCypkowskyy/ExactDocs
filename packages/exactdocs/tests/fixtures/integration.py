"""Integration tests (#507): the ones that need a container, a service, the network or a download.

They carry the ``integration`` marker and are **deselected by default**: ``uv run pytest`` runs
the fast suite, needs nothing but this checkout, and says at the end how many it left out. One
switch turns them on, ``--integration`` or ``EXACTDOCS_INTEGRATION=1`` (``just test-integration``);
``-m integration`` then narrows the run to them (CI's integration job). With the switch on, an
integration test whose service is not configured is skipped and the reason names the variable
(CI sets ``EXACTDOCS_REQUIRE_<NAME>=1``, which turns a missing service into an error instead).

Nothing is marked by hand that can be marked from what the test takes:

- a parameter that needs a service carries the marker: ``databases.SQL_BACKENDS`` /
  ``SEARCH_BACKENDS`` (PostgreSQL, ``pg_search``) and every ``index_backends.BackendCase`` with a
  server (``needs``), so the contract suites mark their PostgreSQL and server cases themselves;
- a test that takes a service fixture (``FIXTURES``: ``on_postgres`` ...) gets the marker at
  collection (``mark_by_fixture``).

A test that reaches a service some other way says so with one of the marks below
(``@integration.POSTGRES``, ``pytestmark = integration.REDIS``). CI's fast jobs set every
service variable to an address where nothing listens, so a test that reaches a service without
the marker fails there instead of being skipped. behave has the same switch and an
``@integration`` tag (``features/environment.py``).
"""

import os
from collections.abc import Iterable

import pytest

MARKER = "integration"
OPTION = "--integration"
VARIABLE = "EXACTDOCS_INTEGRATION"
"""``1``: run the integration tests too (``--integration`` sets it, so subprocesses see it)."""
HOW = "`uv run pytest --integration` (or EXACTDOCS_INTEGRATION=1, `just test-integration`)"
"""How to run them: the summary's hint and the skip reasons say it."""

POSTGRES_URL = "EXACTDOCS_TEST_POSTGRES_URL"


def needs(*variables: str) -> pytest.MarkDecorator:
    """The marker of an integration test that needs these environment variables set.

    Args:
        *variables: What the test needs, e.g. ``EXACTDOCS_TEST_REDIS_URL``; none for a test
            that needs no variable (only the switch).

    Returns:
        ``pytest.mark.integration(*variables)``.
    """
    return pytest.mark.integration(*variables)


POSTGRES = needs(POSTGRES_URL)
"""A PostgreSQL server where the test may create databases and roles (``databases.py``)."""
POSTGRES_PG_SEARCH = needs(POSTGRES_URL, "EXACTDOCS_TEST_PG_SEARCH")
"""That server with ParadeDB's ``pg_search`` (``EXACTDOCS_TEST_PG_SEARCH=1``)."""
PGBOUNCER = needs(POSTGRES_URL, "EXACTDOCS_TEST_PGBOUNCER_URL")
"""PgBouncer in transaction mode in front of that server."""
SUPABASE = needs("EXACTDOCS_TEST_SUPABASE_URL")
LIBSQL_DATABASE = needs("EXACTDOCS_TEST_LIBSQL_DATABASE_URL")
"""An empty libSQL server for ExactDocs' own database (#474)."""
QDRANT = needs("EXACTDOCS_TEST_QDRANT_URL")
ELASTICSEARCH = needs("EXACTDOCS_TEST_ELASTICSEARCH_URL")
OPENSEARCH = needs("EXACTDOCS_TEST_OPENSEARCH_URL")
CHROMA = needs("EXACTDOCS_TEST_CHROMA_URL")
REDIS = needs("EXACTDOCS_TEST_REDIS_URL")
MILVUS = needs("EXACTDOCS_TEST_MILVUS_URL")
MONGODB = needs("EXACTDOCS_TEST_MONGODB_URL")
LIBSQL = needs("EXACTDOCS_TEST_LIBSQL_URL")
"""A libSQL server for the libSQL index backend (#358)."""
PINECONE = needs("EXACTDOCS_TEST_PINECONE_URL")
AZURE_SEARCH = needs("EXACTDOCS_TEST_AZURE_SEARCH_URL")
"""A real Azure AI Search service (the manual ``azure-search.yml`` workflow)."""
LOCAL_MODELS = needs("EXACTDOCS_TEST_MODELS_DIR")
"""The default local models, pulled from Hugging Face by ``exactdocs models pull`` (the release)."""

FIXTURES: dict[str, pytest.MarkDecorator] = {
    "on_postgres": POSTGRES,
    "on_postgres_c": POSTGRES,
    "on_pg_search": POSTGRES_PG_SEARCH,
}
"""Fixtures that hand a test a service: a test that takes one, directly or through another
fixture, is an integration test."""


def enabled() -> bool:
    """Whether this run includes the integration tests (``--integration`` sets the variable).

    Returns:
        ``True`` when ``EXACTDOCS_INTEGRATION`` is ``1``.
    """
    return os.environ.get(VARIABLE) == "1"


def mark_by_fixture(items: Iterable[pytest.Item]) -> None:
    """Mark every test that takes a service fixture (``FIXTURES``) with that fixture's marker.

    Args:
        items: The collected tests.
    """
    for item in items:
        for name in getattr(item, "fixturenames", ()):
            if name in FIXTURES:
                item.add_marker(FIXTURES[name])


def missing(item: pytest.Item) -> list[str]:
    """The variables an integration test needs that are unset or empty here.

    Args:
        item: An integration test.

    Returns:
        Their names, sorted, without repeats.
    """
    wanted = {name for mark in item.iter_markers(MARKER) for name in mark.args}
    return sorted(name for name in wanted if not os.environ.get(name))


def select(config: pytest.Config, items: list[pytest.Item]) -> int:
    """Leave the integration tests out unless the switch is on; skip those whose service is unset.

    ``-m`` naming the marker (``-m integration``, ``-m "not integration"``) chooses by itself.

    Args:
        config: The run's configuration, for ``-m``.
        items: The collected tests; the deselected ones are removed in place.

    Returns:
        How many integration tests were deselected.
    """
    mark_by_fixture(items)
    marked = [item for item in items if item.get_closest_marker(MARKER) is not None]
    for item in marked:  # kept, `-m integration` without the switch included
        if names := missing(item):
            item.add_marker(pytest.mark.skip(reason=f"integration test: set {', '.join(names)}"))
    if enabled() or MARKER in (config.option.markexpr or ""):
        return 0
    if marked:
        left_out = set(marked)
        config.hook.pytest_deselected(items=marked)
        items[:] = [item for item in items if item not in left_out]
    return len(marked)


def summary(deselected: int) -> str:
    """The line the run ends with when it left integration tests out.

    Args:
        deselected: How many it left out.

    Returns:
        What to print.
    """
    return (
        f"{deselected} integration tests deselected (they need PostgreSQL, a search or vector"
        f" server, Docker or the network); run them with {HOW}"
    )
