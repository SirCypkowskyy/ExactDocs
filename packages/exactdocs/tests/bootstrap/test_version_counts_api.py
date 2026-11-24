"""The version and library lists carry their counts without a query per row (#513).

The counts are read once per page, whatever its size: the test lists a page of a few versions
(libraries), then a page of many, and the number of SQL statements must not change. Embedding
runs through the offline stand-in, so the embedded-chunk count reads a real vector space too.
"""

from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import event

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.http import create_app
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import SqliteLibraryRepository
from exactdocs.catalog.dtos import ActivateManifestCommand, ArticleIn, StoreManifestCommand
from exactdocs.catalog.models import HostKind, Library, LibraryId, RefKind
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    EmbedBatchCommand,
    EmbedVersionCommand,
    FinishEmbeddingCommand,
    IndexManifestCommand,
)
from offline_embedding import offline_container

LIBRARY = "/acme/many"
FEW, MANY = 2, 25


@dataclass(frozen=True, slots=True)
class World:
    container: Container
    client: httpx.AsyncClient


@pytest.fixture(params=SQL_BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    """The database ``Settings()`` points at; asked for before the demo catalog is stored."""
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    return request.param


@pytest.fixture
async def world(backend: str, demo_catalog: dict[str, str]) -> AsyncIterator[World]:
    del backend
    cookies = demo_catalog
    container = offline_container(Settings())
    async with (
        container.running(jobs=False),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(container)),
            base_url="http://localhost",
            cookies=cookies,
        ) as client,
    ):
        yield World(container=container, client=client)


async def _add_library(container: Container, library: str) -> None:
    await SqliteLibraryRepository(engine=container.engine).save(
        Library(
            id=LibraryId(library),
            title=library,
            source_url=f"https://github.com{library}",
            host=HostKind.GITHUB,
        )
    )


async def _import(container: Container, library: str, ref: str, articles: int) -> None:
    """Store, index (two chunks per article) and activate a version, as an import does."""
    paths = [f"docs/{ref}/{n}.md" for n in range(articles)]
    stored = await container.catalog.store_manifest(
        StoreManifestCommand(
            library=library,
            ref=ref,
            kind=RefKind.TAG,
            commit_sha=f"{len(ref):x}{ref}".encode().hex()[:40].ljust(40, "0"),
            articles=[
                ArticleIn(
                    path=path,
                    blob_sha=f"{n:040x}",
                    content_version=1,
                    title=path,
                    content=f"# {path}",
                )
                for n, path in enumerate(paths, start=hash(ref) % 10_000 * 100)
            ],
        )
    )
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id=stored.manifest_id,
            library=library,
            ref=ref,
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=path,
                    blob_sha=f"{ref}:{path}",
                    chunks=[
                        ChunkIn(
                            heading_path=[path, part],
                            occurrence_index=0,
                            content=f"{path} {part} token",
                            content_hash=f"{ref}-{path}-{part}",
                            anchor=part,
                        )
                        for part in ("one", "two")
                    ],
                )
                for path in paths
            ],
        )
    )
    await container.catalog.activate_manifest(
        ActivateManifestCommand(manifest_id=stored.manifest_id)
    )


async def _embed(container: Container, library: str, ref: str) -> None:
    """Run an ``embed`` job of one version as ingestion does."""
    retrieval = container.retrieval
    plan = await retrieval.plan_embedding(EmbedVersionCommand(library=library, ref=ref))
    assert plan.space_id is not None, plan
    assert plan.manifest_id is not None, plan
    command = EmbedBatchCommand(
        library=library, ref=ref, manifest_id=plan.manifest_id, space_id=plan.space_id
    )
    while not (await retrieval.embed_batch(command)).finished:
        pass
    await retrieval.finish_embedding(FinishEmbeddingCommand(space_id=plan.space_id))


@contextmanager
def _statements(container: Container) -> Generator[list[str]]:
    """Record every SQL statement sent while the block runs."""
    sent: list[str] = []

    def record(*args: object) -> None:  # (conn, cursor, statement, parameters, context, many)
        sent.append(str(args[2]))

    event.listen(container.engine.sync_engine, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        event.remove(container.engine.sync_engine, "before_cursor_execute", record)


async def _list(world: World, url: str, *, limit: int) -> tuple[dict, int]:
    """GET a list; return its body and how many SQL statements answering it took."""
    with _statements(world.container) as sent:
        response = await world.client.get(url, params={"limit": limit})
    assert response.status_code == 200, response.text
    return response.json(), len(sent)


async def test_a_page_of_many_versions_takes_as_many_queries_as_a_page_of_few(
    world: World,
) -> None:
    await _add_library(world.container, LIBRARY)
    for n in range(MANY):
        await _import(world.container, LIBRARY, f"v{n:02}", articles=n % 4 + 1)
    await _embed(world.container, LIBRARY, "v00")
    url = f"/api/v1/libraries{LIBRARY}/versions"
    await _list(world, url, limit=1)  # the first request of a process checks the setup once

    few, few_queries = await _list(world, url, limit=FEW)
    many, many_queries = await _list(world, url, limit=MANY)

    assert [v["ref"] for v in few["versions"]] == ["v00", "v01"]
    assert len(many["versions"]) == MANY
    assert many_queries == few_queries, (few_queries, many_queries)
    counts = {
        v["ref"]: (v["articles"], v["chunks"], v["embedded_chunks"]) for v in many["versions"]
    }
    assert counts["v00"] == (1, 2, 2)  # embedded
    assert counts["v01"] == (2, 4, 0)
    assert counts[f"v{MANY - 1:02}"] == ((MANY - 1) % 4 + 1, 2 * ((MANY - 1) % 4 + 1), 0)


async def test_a_page_of_many_libraries_takes_as_many_queries_as_a_page_of_few(
    world: World,
) -> None:
    for n in range(MANY):
        library = f"/count/lib{n:02}"
        await _add_library(world.container, library)
        await _import(world.container, library, "v1", articles=n % 3 + 1)
    url = "/api/v1/libraries"
    await _list(world, url, limit=1)  # the first request of a process checks the setup once

    few, few_queries = await _list(world, url, limit=FEW)
    many, many_queries = await _list(world, url, limit=MANY + 10)

    assert len(few["libraries"]) == FEW
    assert many_queries == few_queries, (few_queries, many_queries)
    counts = {lib["id"]: lib["article_count"] for lib in many["libraries"]}
    assert counts["/count/lib00"] == 1
    assert counts["/count/lib02"] == 3
    assert counts["/acme/payments"] == 0  # the demo catalog's versions have no manifest
