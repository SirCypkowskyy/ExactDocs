"""Steps for the vector store. Vectors are made up from each chunk's text (no model runs): the
scenarios check where vectors live and which ones a search compares, not how good they are."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from http import HTTPStatus

from behave import given, then, when
from behave.runner import Context
from fastapi.testclient import TestClient
from sqlalchemy import text

from exactdocs.bootstrap.container import Container, vector_index
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.adapters.driven.memory import StaticModelRoles
from exactdocs.retrieval.dtos import OpenEmbeddingSpaceCommand
from exactdocs.retrieval.errors import VectorDimensionError
from exactdocs.retrieval.models import (
    ChunkKey,
    EmbeddingSpaceId,
    ModelRole,
    RetrievalMode,
    TagFilter,
    VectorHit,
)
from steps.http_steps import DEMO_COOKIE, SESSION_COOKIE
from steps.retrieval_mode_steps import StandInHybrid

LIBRARY = "/fixture/docs-repo"
TOLERANCE = 1e-6
MAX_COSINE_DISTANCE = 2
_CHUNKS = text(
    """
    SELECT mc.chunk_id, c.blob_sha, c.config_hash, c.position, c.content
    FROM retrieval_manifest_chunks mc
    JOIN retrieval_manifests m ON m.manifest_id = mc.manifest_id
    JOIN retrieval_chunks c
      ON c.blob_sha = mc.blob_sha AND c.config_hash = mc.config_hash AND c.position = mc.position
    WHERE m.version_id = :version
    """
)


def made_up_vector(content: str, dimensions: int) -> list[float]:
    """A deterministic stand-in for an embedding: the text's hash, spread over the dimensions."""
    seed = hashlib.sha256(content.encode()).digest()
    return [seed[i % len(seed)] - 127.5 + i / dimensions for i in range(dimensions)]


async def _chunks(container: Container, ref: str) -> list[tuple[str, ChunkKey, str]]:
    """Every chunk row of the version: its chunk ID, its key in the store, its text."""
    async with container.engine.connect() as connection:
        rows = await connection.execute(_CHUNKS, {"version": f"{LIBRARY}/{ref}"})
        return [(r.chunk_id, (r.blob_sha, r.config_hash, r.position), r.content) for r in rows]


async def _fill(
    container: Container, space: EmbeddingSpaceId, refs: list[str], dimensions: int
) -> None:
    vectors = vector_index(container.engine)
    for ref in refs:
        rows = await _chunks(container, ref)
        await vectors.upsert(space, {k: made_up_vector(c, dimensions) for _, k, c in rows})


def _open(context: Context, model: str, dimensions: int, fill: list[str]) -> EmbeddingSpaceId:
    async def go() -> EmbeddingSpaceId:
        container = Container.build(context.settings)
        async with container.running(jobs=False):
            space = await container.retrieval.open_embedding_space(
                OpenEmbeddingSpaceCommand(profile_kind="openai", model=model, dimensions=dimensions)
            )
            space_id = EmbeddingSpaceId(space.id)
            await _fill(container, space_id, fill, dimensions)
            context.created = space.created
            return space_id

    return asyncio.run(go())


def _nearest(
    context: Context, space: EmbeddingSpaceId, ref: str, query: list[float], limit: int
) -> tuple[list[VectorHit], set[str]]:
    """Search one version; also return the chunk IDs that version has."""

    async def go() -> tuple[list[VectorHit], set[str]]:
        container = Container.build(context.settings)
        async with container.running(jobs=False):
            async with container.engine.connect() as connection:
                manifest = await connection.scalar(
                    text("SELECT manifest_id FROM retrieval_manifests WHERE version_id = :v"),
                    {"v": f"{LIBRARY}/{ref}"},
                )
            vectors = vector_index(container.engine)
            hits = await vectors.nearest(space, manifest, query, TagFilter(), limit)
            return list(hits), {i for i, _, _ in await _chunks(container, ref)}

    return asyncio.run(go())


@given('embedding space "{name}" holds vectors for the chunks of "{first}" and "{second}"')
def step_space_with_vectors(context: Context, name: str, first: str, second: str) -> None:
    context.spaces = {name: _open(context, "a", 8, [first, second])}


@when(
    'the vector index searches "{ref}" in "{name}" for the {limit:d} nearest chunks to a query '
    "vector"
)
def step_search_vectors(context: Context, ref: str, name: str, limit: int) -> None:
    # The query is the vector of a section only "v1.4.0" has, so that section must come first.
    rows = asyncio.run(_with_container(context, lambda c: _chunks(c, ref)))
    context.expected_first, _, content = next(r for r in rows if "retry_policy" in r[2])
    context.hits, context.version_chunks = _nearest(
        context, context.spaces[name], ref, made_up_vector(content, 8), limit
    )


@then(
    'it returns at most {limit:d} chunk IDs of "{ref}", nearest first, with their cosine distances'
)
def step_nearest(context: Context, limit: int, ref: str) -> None:
    hits = context.hits
    assert len(hits) == limit, hits  # the version has more chunks than that
    assert {h.chunk_id for h in hits} <= context.version_chunks, (ref, hits)
    assert hits[0].chunk_id == context.expected_first, hits
    assert hits[0].distance < TOLERANCE, hits  # the same vector: cosine distance 0
    distances = [h.distance for h in hits]
    assert distances == sorted(distances), distances
    assert all(0 <= d <= MAX_COSINE_DISTANCE for d in distances), distances


@given('space "{name}" was built with model "{model}" at {dimensions:d} dimensions')
def step_built(context: Context, name: str, model: str, dimensions: int) -> None:
    context.spaces = {name: _open(context, model, dimensions, ["v1.4.0"])}
    context.dimensions = {name: dimensions}


@when('the operator switches the embedding model to "{model}" at {dimensions:d} dimensions')
def step_switch(context: Context, model: str, dimensions: int) -> None:
    context.new_space = _open(context, model, dimensions, [])
    context.new_dimensions = dimensions
    context.new_model = model


@then('a new space "{name}" is created for "{model}"')
def step_new_space(context: Context, name: str, model: str) -> None:
    assert context.created, "the switch reused a space"
    assert model == context.new_model
    assert context.new_space not in context.spaces.values(), context.spaces
    context.spaces[name] = context.new_space

    async def spaces(container: Container) -> list[tuple[int, str, str]]:
        found = await vector_index(container.engine).spaces()
        return [(s.id, s.spec.model, s.state.value) for s in found]

    listed = asyncio.run(_with_container(context, spaces))
    assert listed == [
        (context.spaces["s1"], "a", "building"),
        (context.new_space, model, "building"),
    ], listed


@then('vectors of "{old}" are never compared with vectors of "{new}"')
def step_never_compared(context: Context, old: str, new: str) -> None:
    query = made_up_vector("Calls are retried.", context.new_dimensions)
    hits, _ = _nearest(context, context.spaces[new], "v1.4.0", query, 5)
    assert hits == [], hits  # the new space holds nothing yet: the old vectors are not borrowed
    try:
        _nearest(context, context.spaces[old], "v1.4.0", query, 5)
    except VectorDimensionError:
        compared = False
    else:
        compared = True
    assert not compared, "a query of the new model was compared with the old space"
    old_query = made_up_vector("Calls are retried.", context.dimensions[old])
    old_hits, _ = _nearest(context, context.spaces[old], "v1.4.0", old_query, 5)
    assert old_hits, "the old space lost its vectors"


async def _with_container[T](context: Context, work: Callable[[Container], Awaitable[T]]) -> T:
    container = Container.build(context.settings)
    async with container.running(jobs=False):
        return await work(container)


def _broken_extension() -> str:
    return "/nowhere/vec0"


@given('an embedding model is configured, the instance mode is "{mode}" and sqlite-vec cannot load')
def step_no_sqlite_vec(context: Context, mode: str) -> None:
    context.client.__exit__(None, None, None)  # one job worker per process
    stack = ExitStack()
    context.add_cleanup(stack.close)
    settings = context.settings.model_copy(update={"ai": AiSettings(mode=RetrievalMode(mode))})
    container = Container.build(
        settings,
        model_roles=StaticModelRoles(roles=frozenset({ModelRole.EMBEDDING})),
        pipelines={RetrievalMode.HYBRID: StandInHybrid()},
        vector_extension=_broken_extension,
    )
    context.client = stack.enter_context(
        TestClient(
            create_app(container),
            base_url="http://localhost",
            cookies={SESSION_COOKIE: DEMO_COOKIE},
        )
    )


@then('BM25 answers with fallback reason "{reason}"')
def step_fallback(context: Context, reason: str) -> None:
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("bm25", reason), body
    assert body["results"], body  # BM25 keeps answering
