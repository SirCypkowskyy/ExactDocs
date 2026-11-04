"""Steps for version-scoped chunks: stored through the catalog and retrieval modules."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.container import Container
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import RefKind
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    ChunkOut,
    GetChunkQuery,
    IndexedManifestOut,
    IndexManifestCommand,
)
from exactdocs_kernel import DomainError

CONFIG_HASH = "default-chunking"


def _run[T](context: Context, action: Callable[[Container], Awaitable[T]]) -> T:
    async def go() -> T:
        container = Container.build(context.settings)
        async with container.running():
            return await action(container)

    return asyncio.run(go())


def _git_blob_sha(content: str) -> str:
    data = content.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _chunks(text: str) -> list[ChunkIn]:
    """Two sections per article, named after its text, as the chunker would cut it."""
    return [
        ChunkIn(
            heading_path=["Doc", f"{text} {part}"],
            occurrence_index=0,
            content=f"{text} {part}",
            content_hash=hashlib.sha256(f"{text} {part}".encode()).hexdigest(),
            anchor=f"{text}-{part}".replace(" ", "-"),
        )
        for part in ("one", "two")
    ]


def _index(context: Context, library: str, ref: str, name: str, commit: str) -> None:
    rows = list(context.table or [])

    async def action(container: Container) -> tuple[str, IndexedManifestOut]:
        stored = await container.catalog.store_manifest(
            StoreManifestCommand(
                library=library,
                ref=ref,
                kind=RefKind.TAG if ref.startswith("v") else RefKind.BRANCH,
                commit_sha=commit.ljust(40, "0"),
                articles=[
                    ArticleIn(
                        path=r["path"],
                        blob_sha=_git_blob_sha(r["text"]),
                        content_version=1,
                        title=r["path"],
                        content=r["text"],
                    )
                    for r in rows
                ],
            )
        )
        command = _index_command(stored.manifest_id, library, ref, rows)
        return stored.manifest_id, await container.retrieval.index_manifest(command)

    manifest_id, indexed = _run(context, action)
    context.manifest_ids = getattr(context, "manifest_ids", {}) | {name: manifest_id}
    context.indexed = getattr(context, "indexed", {}) | {name: indexed}
    context.index_commands = getattr(context, "index_commands", {}) | {
        name: _index_command(manifest_id, library, ref, rows)
    }
    context.last_indexed = indexed


def _index_command(manifest_id: str, library: str, ref: str, rows: list) -> IndexManifestCommand:
    return IndexManifestCommand(
        manifest_id=manifest_id,
        library=library,
        ref=ref,
        config_hash=CONFIG_HASH,
        articles=[
            ArticleChunksIn(
                path=r["path"], blob_sha=_git_blob_sha(r["text"]), chunks=_chunks(r["text"])
            )
            for r in rows
        ],
    )


@given('"{library}" version "{ref}" is indexed as "{name}" at commit "{commit}":')
def step_indexed(context: Context, library: str, ref: str, name: str, commit: str) -> None:
    _index(context, library, ref, name, commit)


@when('"{library}" version "{ref}" is indexed as "{name}" at commit "{commit}":')
def step_index(context: Context, library: str, ref: str, name: str, commit: str) -> None:
    _index(context, library, ref, name, commit)


@when('the manifest "{name}" is indexed again')
def step_index_again(context: Context, name: str) -> None:
    command = context.index_commands[name]
    again = _run(context, lambda container: container.retrieval.index_manifest(command))
    context.indexed[f"{name} again"] = again
    context.last_indexed = again


@when('the manifest "{name}" is activated')
def step_activate(context: Context, name: str) -> None:
    command = ActivateManifestCommand(manifest_id=context.manifest_ids[name])
    _run(context, lambda container: container.catalog.activate_manifest(command))


@when('I read the second chunk of "{path}" in "{name}" as "{library}" version "{ref}"')
def step_read(context: Context, path: str, name: str, library: str, ref: str) -> None:
    chunk_id = context.indexed[name].chunk_ids[path][1]
    query = GetChunkQuery(library=library, version=ref, chunk_id=chunk_id)

    async def action(container: Container) -> ChunkOut | DomainError:
        try:
            return await container.retrieval.get_chunk(query)
        except DomainError as error:
            return error

    context.read = _run(context, action)


@then('every chunk of "{path}" has the same ID in "{first}" and "{second}"')
def step_same_ids(context: Context, path: str, first: str, second: str) -> None:
    a, b = context.indexed[first].chunk_ids[path], context.indexed[second].chunk_ids[path]
    assert a, a
    assert a == b, (a, b)


@then('no chunk of "{path}" has the same ID in "{first}" and "{second}"')
def step_different_ids(context: Context, path: str, first: str, second: str) -> None:
    a, b = context.indexed[first].chunk_ids[path], context.indexed[second].chunk_ids[path]
    assert a, a
    assert b, b
    assert set(a).isdisjoint(b), (a, b)


@then('"{name}" stored no chunk set of its own')
def step_stored_once(context: Context, name: str) -> None:
    assert context.indexed[name].chunk_ids, name
    assert context.indexed[name].chunk_sets_stored == 0, context.indexed[name]


@then("nothing new was stored")
def step_nothing_new(context: Context) -> None:
    assert context.last_indexed.already_indexed, context.last_indexed
    assert context.last_indexed.chunk_sets_stored == 0


@then("the chunk cannot be found")
def step_not_found(context: Context) -> None:
    assert isinstance(context.read, DomainError), context.read


@then('the chunk says "{text}" and its previous chunk is the first one')
def step_chunk(context: Context, text: str) -> None:
    chunk = context.read
    assert isinstance(chunk, ChunkOut), chunk
    assert chunk.content == text, chunk
    assert chunk.prev_chunk_id, chunk
    assert chunk.position == 1, chunk
