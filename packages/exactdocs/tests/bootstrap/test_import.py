"""The import over the real catalog, retrieval and SQLite, on the fixture docs repository."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from exactdocs.bootstrap.bridges import (
    CatalogLibrarySources,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.adapters.driven.sqlite import manifests as manifest_rows
from exactdocs.catalog.dtos import (
    ArticleIn,
    CreateLibraryCommand,
    GetActiveManifestQuery,
    HostKind,
    ListArticlesQuery,
    StoreManifestCommand,
)
from exactdocs.catalog.dtos import RefKind as CatalogRefKind
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.adapters.driven.sqlite import SqliteJobRepository
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    PARSER_VERSION,
    ArticleChunk,
    Job,
    JobId,
    ParsedArticle,
)
from exactdocs.ingestion.use_cases import ImportVersionUseCase
from exactdocs.retrieval.adapters.driven.sqlite import (
    chunk_set_rows,
    indexed_manifests,
)
from exactdocs.retrieval.dtos import ArticleChunksIn, ChunkIn, IndexManifestCommand
from exactdocs_kernel import SystemClock
from fixture_repo import DocsRepo, git

LIBRARY = "/fixture/docs-repo"
UNREADABLE = {"docs/legacy/binary.md", "docs/legacy/latin1.md", "docs/legacy/undecodable.md"}


class CountingChunker:
    def __init__(self) -> None:
        self.inner = MarkdownChunker()
        self.config_hash = self.inner.config_hash
        self.chunked: list[str] = []

    def chunk(self, article: ParsedArticle) -> Sequence[ArticleChunk]:
        self.chunked.append(article.path)
        return self.inner.chunk(article)


class Progress:
    async def report(self, *, done: int, total: int) -> None: ...

    async def problem(self, path: str, reason: str) -> None: ...


class CrashError(Exception):
    pass


class FailingActivation(CatalogVersionPublisher):
    """The real catalog, except that the last step fails (a crash right before activation)."""

    async def activate(self, manifest_id: str) -> None:
        raise CrashError(manifest_id)


@dataclass(slots=True)
class World:
    container: Container
    docs_repo: DocsRepo
    chunker: CountingChunker

    def importer(self, *, activation_fails: bool = False) -> ImportVersionUseCase:
        c = self.container
        git_cli = GitCli.locate()
        publisher = (FailingActivation if activation_fails else CatalogVersionPublisher)(
            c.catalog.store_manifest,
            c.catalog.activate_manifest,
            c.catalog.discard_pending_manifests,
        )
        return ImportVersionUseCase(
            gateway=git_cli,
            remote=git_cli,
            chunker=self.chunker,
            sources=CatalogLibrarySources(c.catalog.get_library),
            versions=publisher,
            index=RetrievalChunkIndex(
                c.retrieval.index_manifest,
                c.retrieval.get_chunk_sets,
                c.retrieval.discard_pending_chunks,
            ),
        )

    async def import_ref(self, ref: str, *, activation_fails: bool = False) -> None:
        job = Job.queued(
            job_id=JobId("j"),
            kind="import",  # ty: ignore[invalid-argument-type]
            library=LIBRARY,
            version=ref,
            commit_sha=git("rev-parse", f"{ref}^{{commit}}", cwd=self.docs_repo.path),
            now=SystemClock().now(),
        )
        await self.importer(activation_fails=activation_fails)(job, Progress())

    async def count(self, table) -> int:
        async with self.container.engine.connect() as connection:
            return (await connection.execute(select(func.count()).select_from(table))).scalar_one()

    async def paths(self, ref: str) -> list[str]:
        listed = await self.container.catalog.list_articles(
            ListArticlesQuery(library=LIBRARY, ref=ref, limit=100)
        )
        return [a.path for a in listed.articles]


@pytest.fixture
async def world(docs_repo: DocsRepo) -> AsyncIterator[World]:
    container = Container.build(Settings())
    async with container.running(jobs=False):
        await container.catalog.create_library(
            CreateLibraryCommand(
                id=LIBRARY,
                title="Docs",
                source_url=docs_repo.file_url,
                host=HostKind.GIT,
                default_branch="main",
                include_paths=["docs/"],
            )
        )
        yield World(container, docs_repo, CountingChunker())


async def test_an_unchanged_blob_is_not_chunked_again_in_the_next_version(world: World) -> None:
    await world.import_ref("v1.3.0")
    first = world.chunker.chunked
    world.chunker.chunked = []

    await world.import_ref("v1.4.0")

    assert len(first) > 5
    assert sorted(world.chunker.chunked) == [  # what v1.4.0 adds or changes, nothing else
        "docs/api/client.mdx",
        "docs/guide/install.md",
        "docs/guide/resilience.md",
    ]
    assert "docs/guide/resilience.md" in await world.paths("v1.4.0")
    assert "docs/guide/resilience.md" not in await world.paths("v1.3.0")


async def test_importing_the_same_commit_again_chunks_nothing_and_serves_the_same_version(
    world: World,
) -> None:
    await world.import_ref("v1.3.0")
    before = await world.paths("v1.3.0")
    sets = await world.count(chunk_set_rows)
    world.chunker.chunked = []

    await world.import_ref("v1.3.0")

    assert world.chunker.chunked == []
    assert await world.paths("v1.3.0") == before
    assert await world.count(chunk_set_rows) == sets
    assert UNREADABLE.isdisjoint(before)


async def test_a_failure_right_before_activation_leaves_the_previous_version_and_no_leftovers(
    world: World,
) -> None:
    await world.import_ref("v1.3.0")
    before = await world.paths("v1.3.0")
    served = await world.container.catalog.get_active_manifest(
        GetActiveManifestQuery(library=LIBRARY, ref="v1.3.0")
    )
    sets, indexed = await world.count(chunk_set_rows), await world.count(indexed_manifests)

    with pytest.raises(CrashError):
        await world.import_ref("v1.4.0", activation_fails=True)

    active = await world.container.catalog.get_active_manifest(
        GetActiveManifestQuery(library=LIBRARY, ref="v1.3.0")
    )
    assert active == served
    assert await world.paths("v1.3.0") == before
    assert await world.count(indexed_manifests) == indexed  # the new chunk rows are gone
    assert await world.count(chunk_set_rows) == sets  # so are the chunk sets only they used
    assert await world.count(manifest_rows) == 1  # the pending manifest is gone from the catalog


async def test_a_restart_discards_what_an_interrupted_import_left_and_runs_it_again(
    docs_repo: DocsRepo,
) -> None:
    """A crash after the pending manifest was stored: the next start cleans up, then re-runs."""
    first = Container.build(Settings())
    async with first.running(jobs=False):
        await first.catalog.create_library(
            CreateLibraryCommand(
                id=LIBRARY,
                title="Docs",
                source_url=docs_repo.file_url,
                host=HostKind.GIT,
                default_branch="main",
                include_paths=["docs/"],
            )
        )
        stored = await first.catalog.store_manifest(
            StoreManifestCommand(
                library=LIBRARY,
                ref="v1.3.0",
                kind=CatalogRefKind.TAG,
                commit_sha="b" * 40,
                articles=[
                    ArticleIn(
                        path="docs/a.md",
                        blob_sha="c" * 40,
                        content_version=PARSER_VERSION,
                        title="A",
                        content="a",
                    )
                ],
            )
        )
        await first.retrieval.index_manifest(
            IndexManifestCommand(
                manifest_id=stored.manifest_id,
                library=LIBRARY,
                ref="v1.3.0",
                config_hash="x",
                articles=[
                    ArticleChunksIn(
                        path="docs/a.md",
                        blob_sha="c" * 40,
                        chunks=[
                            ChunkIn(
                                heading_path=["A"],
                                occurrence_index=0,
                                content="a",
                                content_hash="h",
                                anchor="a",
                            )
                        ],
                    )
                ],
            )
        )
        now = datetime.now(UTC)
        running = Job.queued(
            job_id=JobId("j"),
            kind=IMPORT_JOB,
            library=LIBRARY,
            version="v1.3.0",
            commit_sha=git("rev-parse", "v1.3.0^{commit}", cwd=docs_repo.path),
            now=now,
        ).started(now)
        await SqliteJobRepository(first.engine).add(running)
        assert await _count(first, manifest_rows) == 1
        assert await _count(first, chunk_set_rows) == 1

    restarted = Container.build(Settings())  # recovery runs when the worker starts
    async with restarted.running(jobs=False):
        await restarted.ingestion.recover_jobs()
        assert await _count(restarted, manifest_rows) == 0
        assert await _count(restarted, chunk_set_rows) == 0
        assert await _count(restarted, indexed_manifests) == 0
        job = await SqliteJobRepository(restarted.engine).get(JobId("j"))
        assert job is not None
        assert job.state.value == "queued"  # runs again from the beginning


async def _count(container: Container, table) -> int:
    async with container.engine.connect() as connection:
        return (await connection.execute(select(func.count()).select_from(table))).scalar_one()
