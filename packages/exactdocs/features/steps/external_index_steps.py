"""Steps for external search and vector backends (#352).

In process, every container of a scenario shares one in-memory backend (passed to
``Container.build``), as the processes of a deployment share a real one. The command line runs
in a process of its own, whose in-memory backend starts empty: a backend that was reset.
"""

import asyncio
import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.index_backends import IndexBackends
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.retrieval.adapters.driven.memory_index import (
    InMemorySearchBackend,
    InMemoryVectorBackend,
)
from exactdocs.retrieval.dtos import ExternalIndexScope, IndexDriftOut, RebuiltVersionsOut
from exactdocs.retrieval.models import DriftKind, IndexKind
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE, OfflineGit, store_demo_catalog
from steps.search_steps import LIBRARY, import_versions

CLI = "from exactdocs.bootstrap.cli import main; main()"
SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERY = "how do I retry failed calls"
VERSIONS = 2  # the fixture versions imported
SCORE_TOLERANCE = 1e-5  # float32 vectors: the same distance, give or take rounding


def _client(stack: ExitStack, container: Container) -> TestClient:
    return stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


async def _rebuild(settings: Settings, backends: IndexBackends) -> RebuiltVersionsOut:
    """What `exactdocs index rebuild` does, in this process (it shares the backend)."""
    container = Container.build(settings, index_backends=backends)
    async with container.running(jobs=False):
        return await container.retrieval.rebuild_external_indexes(ExternalIndexScope())


async def _check(settings: Settings, backends: IndexBackends) -> IndexDriftOut:
    """What `exactdocs index check` does, in this process (it shares the backend)."""
    container = Container.build(settings, index_backends=backends)
    async with container.running(jobs=False):
        return await container.retrieval.check_external_indexes(ExternalIndexScope())


def _searched(client: TestClient, ref: str, query: str, mode: str) -> list[tuple[str, float]]:
    response = client.get(SEARCH, params={"q": query, "ref": ref, "mode": mode, "limit": 10})
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["retrieval_mode"] == mode, body
    return [(r["chunk_id"], r["score"]) for r in body["results"]]


# ---------------------------------------------------------------- moving the vector index


@when("the operator configures an external vector backend and runs a rebuild")
def step_move_vectors(context: Context) -> None:
    context.before = _searched(context.client, "v1.4.0", QUERY, "vector")
    assert context.before, "the database's vectors find nothing"
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.client.__exit__(None, None, None)  # one job worker per process
    context.vector_backend = InMemoryVectorBackend()
    backends = IndexBackends(vectors=context.vector_backend)
    settings = context.container.settings
    context.rebuilt = asyncio.run(_rebuild(settings, backends))
    context.client = _client(stack, Container.build(settings, index_backends=backends))


@then("every active version's embeddings are written to the backend")
def step_embeddings_written(context: Context) -> None:
    rebuilt = context.rebuilt
    assert (rebuilt.indexes, rebuilt.versions) == ([IndexKind.VECTORS], VERSIONS), rebuilt
    (space,) = context.vector_backend.spaces.values()
    held = {m: len(entries) for m, entries in space.items()}
    assert len(held) == VERSIONS, held
    assert all(held.values()), held
    assert sum(held.values()) == rebuilt.vector_entries, (held, rebuilt)
    drift = asyncio.run(
        _check(context.container.settings, IndexBackends(vectors=context.vector_backend))
    )
    assert drift.clean, drift


@then("searches use it from then on, with the same results for the same scores")
def step_same_results(context: Context) -> None:
    after = _searched(context.client, "v1.4.0", QUERY, "vector")
    assert [c for c, _ in after] == [c for c, _ in context.before], (after, context.before)
    for (_, there), (_, here) in zip(after, context.before, strict=True):
        assert abs(there - here) < SCORE_TOLERANCE, (after, context.before)
    context.vector_backend.spaces.clear()  # the backend answers, not the database's store
    assert _searched(context.client, "v1.4.0", QUERY, "vector") == []


# ---------------------------------------------------------------- drift


@given(
    "ExactDocs is running with an external search backend and the fixture docs repository "
    'imported at "{first}" and "{second}"'
)
def step_running_external(context: Context, first: str, second: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    context.settings = Settings(data_dir=data_dir)
    context.search_backend = InMemorySearchBackend()
    context.backends = IndexBackends(search=context.search_backend)
    asyncio.run(store_demo_catalog(context.settings))
    asyncio.run(import_versions(context, [first, second], index_backends=context.backends))
    container = Container.build(
        context.settings, remote=OfflineGit(GitCli.locate()), index_backends=context.backends
    )
    context.client = _client(stack, container)


@given('the external index lost version "{ref}"')
def step_lost(context: Context, ref: str) -> None:
    assert _searched(context.client, ref, "connection_pool", "bm25"), "the backend answers"
    lost = [
        manifest_id
        for manifest_id, entries in context.search_backend.entries.items()
        if next(iter(entries.values())).version_id == f"{LIBRARY}/{ref}"
    ]
    assert len(lost) == 1, lost
    asyncio.run(context.search_backend.delete(lost))


@when("the operator asks for a check")
def step_check(context: Context) -> None:
    context.drift = asyncio.run(_check(context.settings, context.backends))


@then('the check reports "{ref}" missing from the search index')
def step_reported(context: Context, ref: str) -> None:
    rows = [(v.index, v.drift, v.version_id) for v in context.drift.versions]
    assert rows == [(IndexKind.SEARCH, DriftKind.MISSING, f"{LIBRARY}/{ref}")], rows


@then('a search of "{ref}" finds nothing until it is rebuilt')
def step_lost_search(context: Context, ref: str) -> None:
    assert _searched(context.client, ref, "connection_pool", "bm25") == []


@when("the operator rebuilds the external indexes")
def step_rebuild(context: Context) -> None:
    context.rebuilt = asyncio.run(_rebuild(context.settings, context.backends))
    assert context.rebuilt.versions == VERSIONS, context.rebuilt


@then("the check reports nothing missing")
def step_clean(context: Context) -> None:
    assert asyncio.run(_check(context.settings, context.backends)).clean


@then('a search of "{ref}" finds its sections again')
def step_found_again(context: Context, ref: str) -> None:
    assert _searched(context.client, ref, "connection_pool", "bm25")


# ---------------------------------------------------------------- the command line


def _run_cli(context: Context, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "EXACTDOCS_DATA_DIR": str(context.settings.data_dir),
        "EXACTDOCS_SEARCH_BACKEND": "memory",
    }
    env.pop("EXACTDOCS_DATABASE_URL", None)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # our own interpreter and module
        [sys.executable, "-c", CLI, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


@when('the operator runs "exactdocs index check" against an external search backend that was reset')
def step_cli_check(context: Context) -> None:
    context.ran = _run_cli(context, "index", "check")


@then('the command fails, naming "{first}" and "{second}" as missing')
def step_cli_missing(context: Context, first: str, second: str) -> None:
    ran = context.ran
    assert ran.returncode == 1, (ran.stdout, ran.stderr)
    for ref in (first, second):
        assert f"search: missing  {LIBRARY}/{ref}:" in ran.stdout, ran.stdout
    assert "exactdocs index rebuild" in ran.stdout, ran.stdout


@when('the operator runs "exactdocs index rebuild" against that backend')
def step_cli_rebuild(context: Context) -> None:
    context.ran = _run_cli(context, "index", "rebuild")


@then("the command reports {count:d} versions written to the backend")
def step_cli_rebuilt(context: Context, count: int) -> None:
    ran = context.ran
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
    assert f"Rebuilt {count} versions in the external indexes (search: memory" in ran.stdout, (
        ran.stdout
    )
