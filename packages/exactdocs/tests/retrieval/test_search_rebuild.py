"""SQLite only: `exactdocs reindex` builds the new index beside the old one, then swaps it in.

The engine-independent part (same hits after a rebuild, the format state) is in the adapter
contract, ``test_search_index.py``. This is what only a second table can get wrong: searches
while it builds, chunks indexed or deleted meanwhile, a rebuild that died half-way.
"""

import asyncio
from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.retrieval.adapters.driven.memory import InMemoryDefaultVersions, InMemoryLibraries
from exactdocs.retrieval.adapters.driven.sqlite import SqliteChunkRepository
from exactdocs.retrieval.adapters.driven.sqlite_fts import FORMAT, SqliteSearchIndex
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from exactdocs.retrieval.models import DocTarget, SearchableVersion, TagFilter
from exactdocs.retrieval.module import RetrievalModule


def section(heading: str, content: str) -> ChunkIn:
    return ChunkIn(
        heading_path=["Guide", heading],
        occurrence_index=0,
        content=content,
        content_hash=f"h-{heading}",
        anchor=heading.lower(),
    )


V13 = {"guide/retries.md": ("blob-13", [section("Retries", "Calls are retried three times.")])}
V14 = {
    "guide/retries.md": (
        "blob-14",
        [
            section("Retries", "Calls are retried. See also the retry_policy setting."),
            section("retry_policy", "`retry_policy` sets how often a failed call is retried."),
        ],
    ),
    "guide/auth.md": ("blob-auth", [section("Auth", "Tokens expire after an hour.")]),
}


@dataclass(slots=True)
class NoCatalog:
    """The catalog side is not what these tests are about."""

    async def find(self, library: str, ref: str | None) -> SearchableVersion | None:
        del library, ref
        return None

    async def active_id(self, target: DocTarget) -> str | None:
        del target
        return None

    async def statuses(self, manifest_ids: Collection[str]) -> dict:
        del manifest_ids
        return {}


@dataclass(frozen=True, slots=True)
class Db:
    container: Container
    index: SqliteSearchIndex
    retrieval: RetrievalModule

    async def add(self, manifest_id: str, articles: dict) -> None:
        await self.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=manifest_id,
                library="/acme/payments",
                ref=manifest_id,
                config_hash="cfg",
                articles=[
                    ArticleChunksIn(path=path, blob_sha=blob, tags=[], chunks=chunks)
                    for path, (blob, chunks) in articles.items()
                ],
            )
        )

    async def find(self, manifest_id: str, query: str) -> list[str]:
        hits = await self.index.search(manifest_id, query, TagFilter(), 10)
        return [h.chunk_id for h in hits]

    async def scalar(self, sql: str) -> object:
        async with self.container.engine.connect() as connection:
            return await connection.scalar(text(sql))

    async def remove(self, manifest_id: str) -> None:
        await SqliteChunkRepository(engine=self.container.engine).remove([manifest_id])


@pytest.fixture
async def db() -> AsyncIterator[Db]:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        index = SqliteSearchIndex(engine=container.engine, rebuild_batch=1)
        retrieval = RetrievalModule.build(
            defaults=InMemoryDefaultVersions(),
            libraries=InMemoryLibraries(),
            searchable=NoCatalog(),
            manifests=NoCatalog(),
            chunks=SqliteChunkRepository(engine=container.engine),
            search=index,
            maintenance=index,
        )
        yield Db(container, index, retrieval)


async def test_searches_keep_answering_while_the_new_index_is_built(db: Db) -> None:
    await db.add("m13", V13)
    await db.add("m14", V14)
    expected = await db.find("m14", "retry_policy")
    answers: list[list[str]] = []

    async def search_until(done: asyncio.Task) -> None:
        while not done.done():
            answers.append(await db.find("m14", "retry_policy"))
            await asyncio.sleep(0)

    rebuild = asyncio.ensure_future(db.index.rebuild())
    await search_until(rebuild)

    assert (await rebuild).entries == 4
    assert answers
    assert all(a == expected for a in answers)
    assert await db.find("m14", "retry_policy") == expected


async def test_the_old_index_answers_until_the_swap_and_nothing_indexed_meanwhile_is_lost(
    db: Db,
) -> None:
    await db.add("m13", V13)
    await db.index.build_next()
    new = {"guide/new.md": ("blob-new", [section("Backoff", "The backoff_factor grows.")])}
    await db.add("m15", new)  # indexed into the old table while the new one waits

    assert await db.find("m15", "backoff_factor")  # the old index answers
    assert await db.find("m13", "retried")

    rebuilt = await db.index.swap()

    assert rebuilt.entries == 2
    assert await db.find("m15", "backoff_factor")
    assert await db.find("m13", "retried")
    assert await db.scalar("SELECT format FROM retrieval_search_format") == FORMAT


async def test_a_chunk_deleted_while_building_is_not_in_the_new_index(db: Db) -> None:
    await db.add("m13", V13)
    await db.add("m14", V14)
    await db.index.build_next()  # every chunk is in the new table now

    # The newest chunks go, and a new one may get their id (no AUTOINCREMENT): its text must win.
    await db.remove("m14")
    replaced = {"guide/new.md": ("blob-new", [section("Backoff", "The backoff_factor grows.")])}
    await db.add("m15", replaced)
    rebuilt = await db.index.swap()

    assert rebuilt.entries == await db.scalar("SELECT count(*) FROM retrieval_chunks")
    assert await db.find("m15", "backoff_factor")
    assert await db.find("m14", "tokens") == []  # the deleted chunk set's text is gone


async def test_a_rebuild_that_died_half_way_is_started_over(db: Db) -> None:
    await db.add("m14", V14)
    await db.index.build_next()  # then the process died: the table and its trigger stay

    rebuilt = await db.index.rebuild()

    assert rebuilt.entries == 3
    assert (
        await db.scalar(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE 'retrieval_search_next%'"
            " OR name = 'retrieval_chunks_search_next_delete'"
        )
        == 0
    )
    await db.remove("m14")  # the swapped-in index kept the delete trigger
    assert await db.scalar("SELECT count(*) FROM retrieval_search") == 0


async def test_an_empty_database_rebuilds_to_an_empty_index(db: Db) -> None:
    rebuilt = await db.index.rebuild()

    assert (rebuilt.format, rebuilt.entries) == (FORMAT, 0)
