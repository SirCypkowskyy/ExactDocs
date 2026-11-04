"""The engine under test: the fixture docs repository, imported for real, behind ``SearchDocs``.

To run the suite on another engine (hybrid retrieval, ParadeDB), add its name to ``ENGINES`` and
build its ``Container`` in ``open_container``: the cases and the assertions do not change.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from exactdocs.bootstrap.bridges import (
    CatalogLibrarySources,
    CatalogVersionPublisher,
    RetrievalChunkIndex,
)
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind
from exactdocs.ingestion.adapters.driven.git_cli import GitCli
from exactdocs.ingestion.adapters.driven.markdown_chunker import MarkdownChunker
from exactdocs.ingestion.models import IMPORT_JOB, Job, JobId, RefKind
from exactdocs.ingestion.use_cases import ImportVersionUseCase
from exactdocs.retrieval.ports.driving import SearchDocs
from exactdocs_kernel import SystemClock
from fixture_repo import DocsRepo, git

LIBRARY = "/fixture/docs-repo"
VERSIONS = {"v1.3.0": RefKind.TAG, "v1.4.0": RefKind.TAG, "next": RefKind.BRANCH}
ENGINES = ["fts5"]


class _Progress:
    async def report(self, *, done: int, total: int) -> None: ...

    async def problem(self, path: str, code: object, reason: str) -> None: ...


def open_container(engine: str, data_dir: Path) -> Container:
    """The app's container for ``engine``; every engine shares the import and the search port."""
    assert engine in ENGINES, engine
    return Container.build(Settings(data_dir=data_dir))


async def _import_all(engine: str, data_dir: Path, docs_repo: DocsRepo) -> None:
    container = open_container(engine, data_dir)
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
        importer = ImportVersionUseCase(
            gateway=GitCli.locate(),
            chunker=MarkdownChunker(),
            sources=CatalogLibrarySources(container.catalog.get_library),
            versions=CatalogVersionPublisher(
                container.catalog.store_manifest,
                container.catalog.activate_manifest,
                container.catalog.discard_pending_manifests,
                container.catalog.apply_readme,
            ),
            index=RetrievalChunkIndex(
                container.retrieval.index_manifest,
                container.retrieval.get_chunk_sets,
                container.retrieval.discard_pending_chunks,
                container.retrieval.remove_chunks,
            ),
        )
        for ref, kind in VERSIONS.items():
            job = Job.queued(
                job_id=JobId(f"import-{ref}"),
                kind=IMPORT_JOB,
                library=LIBRARY,
                version=ref,
                commit_sha=git("rev-parse", f"{ref}^{{commit}}", cwd=docs_repo.path),
                ref_kind=kind,
                now=SystemClock().now(),
            )
            await importer(job, _Progress())


@pytest.fixture(scope="session", params=ENGINES)
def imported(
    request: pytest.FixtureRequest, docs_repo: DocsRepo, tmp_path_factory: pytest.TempPathFactory
) -> tuple[str, Path]:
    """Import the three versions once per engine; tests reopen the same data directory.

    Returns:
        The engine's name and the data directory holding its imported versions.
    """
    data_dir = tmp_path_factory.mktemp("ranking")
    asyncio.run(_import_all(request.param, data_dir, docs_repo))
    return request.param, data_dir


@pytest.fixture
async def search_docs(imported: tuple[str, Path]) -> AsyncIterator[SearchDocs]:
    """Open the engine under test.

    Yields:
        Its ``SearchDocs`` driving port.
    """
    engine, data_dir = imported
    container = open_container(engine, data_dir)
    async with container.running(jobs=False):
        yield container.retrieval.search_docs
