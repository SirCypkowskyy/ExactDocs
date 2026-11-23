"""Steps for libSQL as the search and vector backend (#358).

The instance is built from the settings an operator writes (``EXACTDOCS_SEARCH_BACKEND`` /
``EXACTDOCS_VECTOR_BACKEND`` = ``libsql`` and ``[index_backends.libsql]``), through the registry
and the adapter's factories, against a libSQL server (``EXACTDOCS_TEST_LIBSQL_URL``) or a local
file. The steps look into libSQL through a backend of their own; a scenario's tables (server) or
file are removed after it.
"""

import asyncio
import secrets
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient

import libsql_backends
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.libsql_index import vector_backend
from exactdocs.retrieval.dtos import ExternalIndexScope, RebuiltVersionsOut
from fake_llm import gateway
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.hybrid_search_steps import step_embedded
from steps.search_steps import LIBRARY

SEARCH = f"/api/v1/libraries{LIBRARY}/search"
QUERIES = ("connection_pool", "how do I retry failed calls")
REF = "v1.4.0"  # the version the scenario embeds
VERSIONS = 2  # the fixture versions imported
TOP = 3  # the best hits, in the same order as the database's own index
FTS_PER_VERSION = (
    "SELECT e.manifest_id, count(*) FROM {prefix}_search s "
    "JOIN {prefix}_search_entries e ON e.id = s.rowid GROUP BY e.manifest_id"
)
SPACES = "SELECT space_id FROM {prefix}_spaces"
VECTOR_INDEXES = "SELECT sql FROM sqlite_master WHERE type = 'index' AND name LIKE ?"
VECTORS_PER_VERSION = (
    "SELECT manifest_id, count(*) FROM {prefix}_space_{space} "
    "WHERE typeof(embedding) = 'blob' GROUP BY manifest_id"
)


def _searched(context: Context, ref: str, query: str, mode: str) -> list[dict]:
    response = context.client.get(
        SEARCH, params={"q": query, "ref": ref, "mode": mode, "limit": 10}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == (mode, None), body
    assert body["version"] == ref, body
    return body["results"]


async def _rebuild(settings: Settings) -> RebuiltVersionsOut:
    """What `exactdocs index rebuild` does: write every version to the configured backends."""
    container = Container.build(settings)
    async with container.running(jobs=False):
        return await container.retrieval.rebuild_external_indexes(ExternalIndexScope())


@given('the libSQL scenario notes what the database\'s own index finds in "{ref}"')
def step_libsql_note_database(context: Context, ref: str) -> None:
    context.libsql_before = {
        q: [r["chunk_id"] for r in _searched(context, ref, q, "bm25")] for q in QUERIES
    }
    assert all(context.libsql_before.values()), context.libsql_before


def _libsql_options(context: Context, stack: ExitStack, place: str) -> dict[str, object] | None:
    """The ``[index_backends.libsql]`` options of the place, or ``None`` (the scenario skips)."""
    if place == "libSQL server":
        if libsql_backends.server_url() is None:
            context.scenario.skip("needs a libSQL server: set EXACTDOCS_TEST_LIBSQL_URL")
            return None
        prefix = f"behave_{secrets.token_hex(6)}"
        context.add_cleanup(lambda: asyncio.run(libsql_backends.drop_tables(prefix)))
        return libsql_backends.server_options(prefix)
    if not libsql_backends.HAS_DRIVER:
        context.scenario.skip("needs the libsql package (exactdocs[libsql])")
        return None
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="exactdocs-")))
    return {"url": f"file:{folder / 'index.db'}", "prefix": "docs"}


@when("the operator names a {place} as the libSQL search and vector backend and rebuilds")
def step_libsql_instance(context: Context, place: str) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    options = _libsql_options(context, stack, place)
    if options is None:
        return
    context.libsql_options = options
    context.endpoint = stack.enter_context(gateway(by_terms=True))
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1}},
            "embedding": {"model": "corp:terms"},
        }
    )
    settings = context.settings.model_copy(
        update={
            "ai": ai,
            "search_backend": "libsql",
            "vector_backend": "libsql",
            "index_backends": {"libsql": options},
        }
    )
    context.client.__exit__(None, None, None)  # one job worker per process
    rebuilt = asyncio.run(_rebuild(settings))
    assert rebuilt.versions == VERSIONS, rebuilt
    context.container = Container.build(settings)
    context.client = stack.enter_context(
        TestClient(
            create_app(context.container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@when('every chunk of "{ref}" is embedded into libSQL')
def step_libsql_embedded(context: Context, ref: str) -> None:
    step_embedded(context, ref)


async def _look(options: dict[str, object]) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Entries per version in FTS5, vectors per version, and the vector indexes' SQL."""
    backend = vector_backend(options)
    await backend.open()
    prefix = backend.prefix
    try:
        searched, spaces, indexes = await backend.engine.run(
            [
                (FTS_PER_VERSION.format(prefix=prefix), ()),
                (SPACES.format(prefix=prefix), ()),
                (VECTOR_INDEXES, [f"{prefix}_space_%_ann"]),
            ],
            atomic=False,
        )
        assert len(spaces) == 1, spaces  # one embedding model: one space
        (vectors,) = await backend.engine.run(
            [(VECTORS_PER_VERSION.format(prefix=prefix, space=spaces[0][0]), ())], atomic=False
        )
    finally:
        await backend.close()
    return dict(searched), dict(vectors), [sql for (sql,) in indexes]


@then('libSQL holds each version\'s chunks in FTS5 and the vectors of "{ref}" in its vector index')
def step_libsql_holds(context: Context, ref: str) -> None:
    searched, vectors, indexes = asyncio.run(_look(context.libsql_options))
    assert len(searched) == VERSIONS, searched
    assert all(searched.values()), searched
    assert vectors, f"no vector of {ref} in libSQL"
    assert set(vectors) <= set(searched), (vectors, searched)
    assert len(indexes) == 1, indexes
    assert "libsql_vector_idx(embedding, 'metric=cosine'" in indexes[0], indexes


@then("libSQL searches answer as on SQLite, filtered to the asked version")
def step_libsql_answers(context: Context) -> None:
    # The same chunks, best first. BM25's statistics are over libSQL's entries (one per chunk of
    # each version) instead of the database's chunks (one per distinct section), so two hits
    # whose scores are close may swap places further down.
    for query, before in context.libsql_before.items():
        after = [r["chunk_id"] for r in _searched(context, REF, query, "bm25")]
        assert (set(after), after[:TOP]) == (set(before), before[:TOP]), (query, after, before)
    for mode in ("vector", "hybrid"):
        results = _searched(context, REF, QUERIES[1], mode)
        assert results, mode
        assert {r["commit_sha"] for r in results} == {context.commits[REF]}, results
    older = _searched(context, "v1.3.0", QUERIES[0], "bm25")
    assert older, "v1.3.0 is searched in libSQL too"
    assert {r["commit_sha"] for r in older} == {context.commits["v1.3.0"]}, older
